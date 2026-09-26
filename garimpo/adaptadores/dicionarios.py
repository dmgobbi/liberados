"""
Vocabularios e listas de apoio da pontuacao de relevancia.

Adaptador: baixa uma vez, guarda em disco, mantem em memoria. Somam uns 70 MB
e mudam pouco; rebaixar a cada execucao e desperdicio.

Cada fonte fecha um buraco medido nos 125 mil nomes da rodada de setembro de
2026. As tres primeiras sao a base original; as outras entraram depois de
ver o que a nota deixava de fora.

  arquivo em work/        fonte                        resolve
  ----------------------  ---------------------------  -------------------------------
  pt_palavras.txt         pythonprobr/palavras         base de portugues
  pt_br.dic               LibreOffice (so os radicais) base de portugues
  en_words.txt            dwyl/english-words           base de ingles, cheia de lixo
  morphobr.txt            MorphoBr, Apache-2.0         substantivo e adjetivo que
                                                       faltavam: chinelo, imovel
  pt_flexoes.txt          pt_BR.dic + .aff expandidos  forma verbal: aprenda, confiar
  wordfreq_*.msgpack.gz   wordfreq, CC BY-SA 4.0       popularidade; e o ingles vira
                                                       "no dicionario E usado": sai
                                                       teakettle, sai fitbit
  cidades_grandes.txt     IBGE, estimativa 2021        nicho + cidade: imoveisembelem
  pessoas.txt             brasil.io + IBGE Censo 2022  nome de gente nao conta como
                                                       palavra de composto
  tranco.zip              Tranco, 1 milhao de sites    .com popular = provavel marca

Toda fonte nova e opcional. Se falhar, a nota degrada com AVISO em vez de
abortar: com menos vocabulario ela fica mais baixa, e nome bom pode sair do
pool sem ninguem perceber, por isso o aviso nao pode ser mudo.

Os dicionarios publicos continuam imperfeitos. A nota ordena atencao, nao
decide nada.
"""

from __future__ import annotations

import csv
import gzip
import io
import json
import math
import os
import re
import threading
import unicodedata
import urllib.request
import zipfile
from collections.abc import Mapping
from dataclasses import dataclass, field

from . import hunspell, registrobr, wordfreq
from ..dominio.relevancia import LEXICO_VAZIO, Lexico

FONTES = {
    "pt_palavras.txt":
        "https://raw.githubusercontent.com/pythonprobr/palavras/master/palavras.txt",
    "pt_br.dic":
        "https://raw.githubusercontent.com/LibreOffice/dictionaries/master/pt_BR/pt_BR.dic",
    "en_words.txt":
        "https://raw.githubusercontent.com/dwyl/english-words/master/words_alpha.txt",
}

MORPHOBR = ("https://raw.githubusercontent.com/LR-POR/MorphoBr/master/"
            "{classe}/{classe}-{letra}.dict")
HUNSPELL = ("https://raw.githubusercontent.com/LibreOffice/dictionaries/master/"
            "pt_BR/pt_BR.{ext}")
WORDFREQ = ("https://raw.githubusercontent.com/rspeer/wordfreq/master/"
            "wordfreq/data/large_{lingua}.msgpack.gz")
POPULACAO = ("https://servicodados.ibge.gov.br/api/v3/agregados/6579/periodos/"
             "2021/variaveis/9324?localidades=N6%5Ball%5D")
NOMES = "https://data.brasil.io/dataset/genero-nomes/nomes.csv.gz"
SOBRENOMES = ("https://servicodados.ibge.gov.br/api/v3/nomes/2022/localidade/0/"
              "ranking/sobrenome?page={pagina}")
TRANCO = "https://tranco-list.eu/top-1m.csv.zip"

# no formato hunspell a linha e "palavra/FLAGS"
SUFIXO_HUNSPELL = ".dic"

EN_TOP = 80_000          # quasar e 57.884; o corte em 50 mil o perdia
COMUM_PT = 40_000        # palavra "comum" para montar composto
COMUM_EN = 20_000
CIDADE_MINIMA = 200_000  # habitantes
PESSOA_MINIMA = 2_000    # nome proprio usado por 2 mil pessoas ou mais
SOBRENOME_PAGINAS = 10   # a API devolve 30 por pagina: os 300 mais comuns


@dataclass(frozen=True)
class Vocabularios:
    pt: frozenset[str]
    en: frozenset[str]
    lexico: Lexico = LEXICO_VAZIO
    sites_populares: Mapping[str, int] = field(default_factory=dict)

    def __iter__(self):
        """Compatibilidade: `pt, en = carregar(...)`."""
        return iter((self.pt, self.en))


def sem_acento(texto: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", texto)
                   if unicodedata.category(c) != "Mn")


def _so_letras(texto: str) -> str:
    """"São José dos Campos" -> "saojosedoscampos", o formato de um rotulo."""
    return re.sub(r"[^a-z]", "", sem_acento(texto.lower()))


def _palavras_de(caminho: str, corta_flag: bool) -> set[str]:
    palavras = set()
    with open(caminho, encoding="utf-8", errors="replace") as f:
        for linha in f:
            palavra = linha.strip().lower()
            if corta_flag:
                palavra = palavra.split("/")[0]
            if not palavra:
                continue
            palavra = sem_acento(palavra)
            if palavra.isalpha() and palavra.isascii():
                palavras.add(palavra)
    return palavras


# --------------------------------------------------------------- disco e rede

def _abrir(url: str, timeout: int = 120):
    pedido = urllib.request.Request(url, headers={"User-Agent": registrobr.UA})
    return urllib.request.urlopen(pedido, timeout=timeout)


def _json(url: str, timeout: int = 120):
    """
    JSON de uma API, descomprimindo se preciso.

    As APIs do IBGE respondem em gzip mesmo sem o pedido pedir, e o urllib
    nao descomprime sozinho. Sem isto, cidades e sobrenomes falhavam com
    "can't decode byte 0x8b" (o 0x1f 0x8b e a assinatura do gzip).
    """
    with _abrir(url, timeout) as resposta:
        bruto = resposta.read()
    if bruto[:2] == b"\x1f\x8b":
        bruto = gzip.decompress(bruto)
    return json.loads(bruto.decode("utf-8"))


def _baixar(url: str, destino: str, timeout: int = 300) -> str:
    """Baixa em binario. O arquivo so aparece no lugar quando esta completo."""
    os.makedirs(os.path.dirname(destino) or ".", exist_ok=True)
    parcial = destino + ".parcial"
    with _abrir(url, timeout) as resposta, open(parcial, "wb") as f:
        while pedaco := resposta.read(1 << 20):
            f.write(pedaco)
    os.replace(parcial, destino)
    return destino


def _gravar_linhas(caminho: str, linhas) -> None:
    parcial = caminho + ".parcial"
    with open(parcial, "w", encoding="utf-8") as f:
        f.write("\n".join(sorted(linhas)))
    os.replace(parcial, caminho)


def _ler_linhas(caminho: str) -> set[str]:
    with open(caminho, encoding="utf-8") as f:
        return {linha.strip() for linha in f if linha.strip()}


def _em_cache(caminho: str, gerar) -> set[str]:
    """Le do disco; se nao existe, gera, grava e devolve."""
    if not os.path.exists(caminho):
        _gravar_linhas(caminho, gerar())
    return _ler_linhas(caminho)


# ------------------------------------------------------------- fontes novas

def _morphobr(diretorio: str) -> set[str]:
    def gerar():
        formas = set()
        for classe in ("nouns", "adjectives"):
            for letra in "abcdefghijklmnopqrstuvwxyz":
                with _abrir(MORPHOBR.format(classe=classe, letra=letra)) as r:
                    # linha: "forma<TAB>lema+N+F+SG"
                    for linha in io.TextIOWrapper(r, encoding="utf-8"):
                        forma = sem_acento(linha.split("\t", 1)[0].strip().lower())
                        if forma.isalpha() and forma.isascii():
                            formas.add(forma)
        return formas
    return _em_cache(os.path.join(diretorio, "morphobr.txt"), gerar)


def _flexoes(diretorio: str, aviso) -> set[str]:
    def gerar():
        # copia propria, em binario: o pt_br.dic da base passa pelo
        # decodificador de listas do registrobr, que e latin-1
        arquivos = {}
        for ext in ("dic", "aff"):
            caminho = os.path.join(diretorio, f"hunspell_pt_BR.{ext}")
            if not os.path.exists(caminho):
                _baixar(HUNSPELL.format(ext=ext), caminho)
            arquivos[ext] = open(caminho, encoding="utf-8", errors="replace").read()
        if aviso:
            aviso("expandindo o dicionario hunspell (uns 30 s, uma vez so)")
        return hunspell.expandir(arquivos["dic"], arquivos["aff"])
    return _em_cache(os.path.join(diretorio, "pt_flexoes.txt"), gerar)


def _ranking(diretorio: str, lingua: str) -> dict[str, int]:
    caminho = os.path.join(diretorio, f"wordfreq_{lingua}.msgpack.gz")
    if not os.path.exists(caminho):
        _baixar(WORDFREQ.format(lingua=lingua), caminho)
    posicoes: dict[str, int] = {}
    for palavra, posicao in wordfreq.ranking(caminho).items():
        chave = sem_acento(palavra.lower())
        if chave.isalpha() and chave.isascii():
            posicoes[chave] = min(posicao, posicoes.get(chave, posicao))
    return posicoes


def _cidades(diretorio: str) -> set[str]:
    def gerar():
        dados = _json(POPULACAO)
        populacao: dict[str, int] = {}
        for serie in dados[0]["resultados"][0]["series"]:
            valor = serie["serie"].get("2021", "")
            if not valor.isdigit():         # "..." quando o IBGE nao estimou
                continue
            nome = _so_letras(serie["localidade"]["nome"].rsplit(" - ", 1)[0])
            populacao[nome] = max(populacao.get(nome, 0), int(valor))
        return {c for c, p in populacao.items() if p >= CIDADE_MINIMA and len(c) >= 4}
    return _em_cache(os.path.join(diretorio, "cidades_grandes.txt"), gerar)


def _pessoas(diretorio: str) -> set[str]:
    def gerar():
        nomes = set()
        arquivo = os.path.join(diretorio, "nomes.csv.gz")
        if not os.path.exists(arquivo):
            _baixar(NOMES, arquivo)
        with gzip.open(arquivo, "rt", encoding="utf-8") as f:
            for linha in csv.DictReader(f):
                if int(linha.get("frequency_total") or 0) >= PESSOA_MINIMA:
                    nomes.add(_so_letras(linha["first_name"]))
        for pagina in range(1, SOBRENOME_PAGINAS + 1):
            for item in _json(SOBRENOMES.format(pagina=pagina)).get("items", []):
                nomes.add(_so_letras(item.get("nome", "")))
        nomes.discard("")
        return nomes
    return _em_cache(os.path.join(diretorio, "pessoas.txt"), gerar)


def _demanda(diretorio: str) -> tuple[dict[str, int], dict[str, int]]:
    """
    (palavras, nomes) do cadastro de CNPJ, gerados por demanda_cnpj.py.

    Nao baixa nada: o arquivo vem do modo `demanda` do workflow (cache do
    Actions) ou de rodar o script em casa. Derivado de dado CC BY-ND 3.0,
    por isso nunca fica no git.
    """
    caminho = os.path.join(diretorio, "demanda.json")
    if not os.path.exists(caminho):
        raise FileNotFoundError("sem work/demanda.json (rode demanda_cnpj.py)")
    with open(caminho, encoding="utf-8") as f:
        dados = json.load(f)
    return dados.get("palavras") or {}, dados.get("nomes") or {}


def _tranco(diretorio: str) -> dict[str, int]:
    """Rotulo -> posicao, so para .com sem subdominio (jetbrains.com)."""
    arquivo = os.path.join(diretorio, "tranco.zip")
    if not os.path.exists(arquivo):
        _baixar(TRANCO, arquivo)
    sites: dict[str, int] = {}
    with zipfile.ZipFile(arquivo) as z, z.open(z.namelist()[0]) as f:
        for linha in io.TextIOWrapper(f, encoding="utf-8"):
            posicao, _, dominio = linha.strip().partition(",")
            if dominio.endswith(".com") and dominio.count(".") == 1:
                sites.setdefault(dominio[:-4], int(posicao))
    return sites


# ------------------------------------------------------------------ montagem

class Repositorio:
    """Cache de vocabularios, seguro para uso por varias threads."""

    def __init__(self, diretorio: str):
        self._diretorio = diretorio
        self._lock = threading.Lock()
        self._carregado: Vocabularios | None = None

    def _base(self, aviso) -> tuple[set[str], set[str]]:
        pt: set[str] = set()
        en: set[str] = set()
        for nome, url in FONTES.items():
            caminho = os.path.join(self._diretorio, nome)
            if not os.path.exists(caminho):
                if aviso:
                    aviso(f"baixando dicionario {nome}")
                try:
                    registrobr._baixar_texto(url, caminho)
                except Exception as e:
                    if aviso:
                        aviso(f"AVISO: {nome} falhou ({e}); "
                              f"as notas ficarao mais baixas")
                    continue
            alvo = en if nome.startswith("en") else pt
            alvo |= _palavras_de(caminho, nome.endswith(SUFIXO_HUNSPELL))
        return pt, en

    def pessoas(self, aviso=None) -> frozenset[str]:
        """
        So a lista de nomes, sem carregar o resto: o exportador do site
        precisa dela para a categoria e nao pode pagar pelo MorphoBr.
        """
        if self._carregado is not None:
            return self._carregado.lexico.pessoas
        # so o cache: quem baixa e a varredura (carregar). Exportar nao vai
        # a rede, e sem o arquivo a categoria sai vazia nos dois JSON.
        caminho = os.path.join(self._diretorio, "pessoas.txt")
        if not os.path.exists(caminho):
            if aviso:
                aviso("AVISO: sem work/pessoas.txt; categoria de nomes vazia")
            return frozenset()
        return frozenset(_ler_linhas(caminho))

    def carregar(self, aviso=None) -> Vocabularios:
        with self._lock:
            if self._carregado is not None:
                return self._carregado

            d = self._diretorio

            def tentar(nome, funcao, vazio):
                try:
                    return funcao()
                except Exception as e:
                    if aviso:
                        aviso(f"AVISO: {nome} falhou ({e}); a nota fica sem "
                              f"esse sinal")
                    return vazio

            pt, en_bruto = self._base(aviso)
            pt |= tentar("MorphoBr", lambda: _morphobr(d), set())
            flexoes = tentar("flexoes do hunspell", lambda: _flexoes(d, aviso), set()) - pt
            rank_pt = tentar("wordfreq pt", lambda: _ranking(d, "pt"), {})
            rank_en = tentar("wordfreq en", lambda: _ranking(d, "en"), {})

            # sem o wordfreq, fica o ingles antigo: pior, mas nao vazio
            en = ({w for w in en_bruto if rank_en.get(w, math.inf) < EN_TOP}
                  if rank_en else en_bruto)
            comuns = ({w for w, r in rank_pt.items()
                       if r < COMUM_PT and (w in pt or w in flexoes)}
                      | {w for w in en if rank_en.get(w, math.inf) < COMUM_EN})

            pessoas = tentar("nomes de pessoa", lambda: _pessoas(d), set())
            # Cidade que tambem e sobrenome comum confunde mais do que ajuda:
            # com Santos na lista, "casaxsantos" e "dsantosimoveis" ganhavam o
            # bonus de nicho + cidade, e eram so o sobrenome do dono.
            cidades = tentar("cidades do IBGE", lambda: _cidades(d), set()) - pessoas

            negocios, nomes_de_empresa = tentar(
                "demanda do CNPJ", lambda: _demanda(d), ({}, {}))

            lexico = Lexico(
                flexoes=frozenset(flexoes),
                popularidade=rank_pt,
                comuns=frozenset(comuns),
                pessoas=frozenset(pessoas),
                cidades=tuple(sorted(cidades)),
                negocios=negocios,
                nomes_de_empresa=nomes_de_empresa,
            )
            sites = tentar("lista Tranco", lambda: _tranco(d), {})

            self._carregado = Vocabularios(frozenset(pt), frozenset(en),
                                           lexico, sites)
            return self._carregado
