"""
A base propria das rodadas: as listas oficiais e quantos candidatos cada
nome disputado teve, guardadas no git a cada rodada, desde set/2026.

POR QUE EXISTE (15/09/2026)

Nenhuma fonte publica guarda o passado de uma disputa (limitacao S15). As
listas .txt trazem so nomes e somem quando a rodada vira; o avail e o RDAP
mostram so a rodada de agora; e nome travado tem os tickets cancelados
(S12). As listas antigas so existem no Internet Archive, e com buracos
justamente onde a ficha mais precisa: mar e mai a jul/2026 (F5). O que a
varredura ve de cada rodada, se ninguem guardar, se perde.

DUAS COISAS, NADA ALEM

1. As listas de liberacao e de elegiveis, como vieram, em
   docs/historico/listas/<inicio>-liberacao.txt.gz e -elegiveis.txt.gz.
   Gravadas uma vez, na primeira copia completa da rodada; gzip sem data no
   cabecalho, entao o mesmo texto da sempre os mesmos bytes.
   historico_listas.py le esta pasta junto com as copias do Internet Archive.
2. docs/historico/disputas.json: por rodada, os nomes com dois ou mais
   candidatos visiveis, com o maior numero visto e a fase (rodada normal,
   elegivel ou leilao). Candidatura nao se cancela (S3), entao a contagem
   so cresce e guardar o maior valor visto e guardar o mais novo.

So a contagem. Numero de ticket, nome e documento de quem pediu nunca
entram aqui (AGENTS.md): "quem disputou" continua sendo consulta no
navegador de quem olha, e so enquanto o RDAP mostrar.

O QUE A CONTAGEM E, E O QUE NAO E

Piso, com tres cortes que a pagina precisa dizer: a varredura confere so os
nomes escolhidos pela nota (o denominador vai em `conferidos`), o candidato
unico e invisivel (A2), e acima de 10 o numero depende da recontagem pelo
RDAP (A3), que tem cota por execucao.
"""

from __future__ import annotations

import gzip
import json
import os

from ..dominio import historico as h

# nome da lista no Internet Archive -> sufixo do arquivo proprio
SUFIXOS = {"lista-processo-liberacao": "liberacao",
           "lista-processo-competitivo": "elegiveis"}
# onde cada lista baixada mora em work/: o varrer.py grava elegiveis.txt, o
# baixar_listas.sh grava competitivo.txt
ORIGENS = {"liberacao": ("liberacao.txt",),
           "elegiveis": ("elegiveis.txt", "competitivo.txt")}

FASES = ("rodada", "elegivel", "leilao")
MINIMO = 2

# posicoes dentro de cada item do instantaneo (garimpo/casos/instantaneo.py)
_I_DOMINIO, _I_SITUACAO, _I_CANDIDATOS, _I_ELEGIVEL, _I_EM_LEILAO = 0, 1, 2, 4, 7

SOBRE = ("Quantos candidatos visiveis cada nome disputado teve em cada rodada de "
         "liberacao, pela varredura do Liberados. Piso: so os nomes conferidos (ver "
         "conferidos), candidato unico nao aparece, e acima de 10 depende da recontagem "
         "pelo RDAP. Nunca guarda numero de ticket nem quem pediu.")


# ------------------------------------------------------------ listas

def gzip_estavel(texto: str) -> bytes:
    """gzip sem data nem nome no cabecalho: mesmo texto, mesmos bytes."""
    import io
    saida = io.BytesIO()
    with gzip.GzipFile(filename="", mode="wb", fileobj=saida, mtime=0, compresslevel=9) as g:
        g.write(texto.encode("utf-8"))
    return saida.getvalue()


def guardar_listas(trabalho: str, pasta: str) -> list[str]:
    """
    Copia as listas baixadas em `trabalho` para `pasta`, uma vez por rodada.
    Lista sem periodo no cabecalho ou sem "# Fim do arquivo" fica para a
    proxima execucao. Devolve os arquivos gravados.
    """
    gravados = []
    for sufixo, nomes in ORIGENS.items():
        origem = next((os.path.join(trabalho, n) for n in nomes
                       if os.path.exists(os.path.join(trabalho, n))), None)
        if not origem:
            continue
        with open(origem, "rb") as f:
            texto = h.decodificar(f.read())
        copia = h.ler_lista(texto)
        if copia.inicio is None or not copia.completa:
            continue
        alvo = os.path.join(pasta, f"{copia.inicio.isoformat()}-{sufixo}.txt.gz")
        if os.path.exists(alvo):
            continue
        os.makedirs(pasta, exist_ok=True)
        with open(alvo, "wb") as f:
            f.write(gzip_estavel(texto))
        gravados.append(alvo)
    return gravados


# ------------------------------------------------------------ disputas

def fase(situacao: str, elegivel: bool, em_leilao: bool) -> int:
    if em_leilao or situacao == "COMPETITIVO":
        return FASES.index("leilao")
    return FASES.index("elegivel") if elegivel else FASES.index("rodada")


def acumular(base: dict | None, dados: dict) -> dict:
    """
    Junta um instantaneo (site/dados.json) a base. Funcao pura: devolve uma
    base nova. Por nome, fica o maior numero de candidatos e a fase mais
    adiantada ja vistos na rodada.
    """
    base = json.loads(json.dumps(base)) if base else {}
    base["sobre"] = SOBRE
    base["fases"] = list(FASES)
    rodadas = base.setdefault("rodadas", {})
    janela = dados.get("rodada") or {}
    inicio = (janela.get("inicio") or "")[:10]
    if not inicio:
        return base
    status = dados.get("status") or []
    itens = dados.get("itens") or []
    rodada = rodadas.setdefault(inicio, {"fim": janela.get("fim"), "na_lista": 0,
                                         "conferidos": 0, "atualizado_em": None, "nomes": {}})
    nomes = rodada["nomes"]
    mudou = False
    for item in itens:
        n = item[_I_CANDIDATOS] or 0
        if n < MINIMO:
            continue
        situacao = status[item[_I_SITUACAO]] if item[_I_SITUACAO] < len(status) else ""
        # instantaneo de antes da versao 2 nao tem em_leilao
        em_leilao = len(item) > _I_EM_LEILAO and bool(item[_I_EM_LEILAO])
        f = fase(situacao, bool(item[_I_ELEGIVEL]), em_leilao)
        velho = nomes.get(item[_I_DOMINIO])
        novo = [max(n, velho[0]), max(f, velho[1])] if velho else [n, f]
        if novo != velho:
            nomes[item[_I_DOMINIO]] = novo
            mudou = True
    for chave, valor in (("na_lista", dados.get("total_rodada") or 0), ("conferidos", len(itens))):
        if valor > (rodada.get(chave) or 0):
            rodada[chave] = valor
            mudou = True
    if mudou or not rodada.get("atualizado_em"):
        rodada["atualizado_em"] = dados.get("gerado_em")
    rodada["nomes"] = dict(sorted(nomes.items()))
    base["rodadas"] = dict(sorted(rodadas.items()))
    return base


def serializar(base: dict) -> str:
    """JSON com um nome por linha: o diff de uma execucao mostra so quem mudou."""
    linhas = ["{"]
    for chave in ("sobre", "fases"):
        linhas.append(f" {json.dumps(chave)}: {json.dumps(base[chave], ensure_ascii=False)},")
    linhas.append(' "rodadas": {')
    rodadas = list(base["rodadas"].items())
    for i, (inicio, r) in enumerate(rodadas):
        linhas.append(f"  {json.dumps(inicio)}: {{")
        for chave in ("fim", "na_lista", "conferidos", "atualizado_em"):
            linhas.append(f"   {json.dumps(chave)}: {json.dumps(r.get(chave))},")
        itens = list(r["nomes"].items())
        linhas.append('   "nomes": {' + ("" if itens else "}"))
        for j, (nome, v) in enumerate(itens):
            linhas.append(f"    {json.dumps(nome)}: [{v[0]}, {v[1]}]" + ("," if j < len(itens) - 1 else ""))
        if itens:
            linhas.append("   }")
        linhas.append("  }" + ("," if i < len(rodadas) - 1 else ""))
    linhas += [" }", "}", ""]
    return "\n".join(linhas)


def atualizar_disputas(caminho: str, dados: dict) -> bool:
    """Acumula o instantaneo na base em disco. Devolve se o arquivo mudou."""
    antigo = None
    if os.path.exists(caminho):
        with open(caminho, encoding="utf-8") as f:
            antigo = f.read()
    texto = serializar(acumular(json.loads(antigo) if antigo else None, dados))
    if texto == antigo:
        return False
    os.makedirs(os.path.dirname(caminho), exist_ok=True)
    with open(caminho, "w", encoding="utf-8", newline="\n") as f:
        f.write(texto)
    return True
