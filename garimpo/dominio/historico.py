"""
Historico das rodadas: as listas antigas do processo de liberacao, lidas de
novo.

Camada de dominio: funcoes puras, sem rede e sem disco. Recebe o texto de
cada copia das listas e devolve a serie.

POR QUE EXISTE (13/09/2026)

O Registro.br publica so a lista da rodada atual. As anteriores somem. O
Internet Archive guardou copias de `lista-processo-liberacao.txt` desde
setembro de 2017 (e de `lista-processo-competitivo.txt`, os elegiveis ao
leilao), e juntar essas copias responde perguntas que ninguem conseguia
responder com uma lista so: quantos nomes voltam por ano, quanto tempo um
nome fica travado, quando um nome vira elegivel ao leilao, que modas morrem
e quando.

TRES ARMADILHAS, todas encontradas na primeira leitura

1. Copia unica por conteudo nao e copia unica por rodada. A mesma rodada
   capturada em dois dias tem "Arquivo gerado em" diferente e, portanto,
   outro digest. Agrupar SEMPRE pelo cabecalho "no periodo de ... a ...".
2. Copia truncada existe: o arquivo guardou parte do arquivo. So vale a
   copia com a linha "# Fim do arquivo".
3. ISO-8859-1. As copias antigas vem em Latin-1 (limitacao L1); decodificar
   antes de comparar nomes entre anos.

O QUE A SERIE MOSTROU (detalhe em docs/historico-das-rodadas.md)

- Nome que aparece em rodadas de meses seguidos travou: com zero
  candidatos ele volta ao espaco livre, com um e registrado. Os elegiveis
  de uma rodada sao, quase sem excecao, os nomes presentes nas TRES rodadas
  anteriores. Tres travas, elegivel na quarta.
- O tamanho da rodada acompanha o calendario: rodada que vem 5 semanas
  depois da anterior e maior que a que vem 4 semanas depois.

Toda contagem aqui e sobre as rodadas CAPTURADAS. Mes sem copia completa
nao entra, e sequencia so conta meses seguidos que foram capturados.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field
from datetime import date

_PERIODO = re.compile(r"no per\S*odo de (\d{4}-\d{2}-\d{2})\S* a (\d{4}-\d{2}-\d{2})")
_GERADO = re.compile(r"gerado em (\S+)")


@dataclass(frozen=True)
class Copia:
    """Uma copia de lista, ja lida."""

    inicio: date | None
    fim: date | None
    gerado_em: str
    nomes: tuple[str, ...]
    completa: bool


@dataclass
class Rodada:
    inicio: date
    fim: date | None
    gerado_em: str
    nomes: frozenset = field(default_factory=frozenset)
    total_linhas: int = 0


def decodificar(bruto: bytes) -> str:
    """UTF-8 quando for (a copia local ja convertida), senao Latin-1 (L1)."""
    try:
        return bruto.decode("utf-8")
    except UnicodeDecodeError:
        return bruto.decode("latin-1")


def ler_lista(texto: str) -> Copia:
    """Uma lista simples: liberacao ou elegiveis (um nome por linha)."""
    inicio = fim = None
    gerado = ""
    nomes: list[str] = []
    completa = False
    for linha in texto.splitlines():
        if linha.startswith("#"):
            m = _PERIODO.search(linha)
            if m:
                inicio, fim = date.fromisoformat(m.group(1)), date.fromisoformat(m.group(2))
            m = _GERADO.search(linha)
            if m:
                gerado = m.group(1)
            if "Fim do arquivo" in linha:
                completa = True
        elif linha.strip():
            nomes.append(linha.strip().lower())
    return Copia(inicio, fim, gerado, tuple(nomes), completa)


def agrupar_por_rodada(copias) -> dict[date, Rodada]:
    """
    Uma rodada por cabecalho de periodo, com a copia completa gerada por
    ultimo. Copia sem periodo ou sem "Fim do arquivo" e descartada.
    """
    rodadas: dict[date, Rodada] = {}
    for c in copias:
        if c.inicio is None or not c.completa:
            continue
        atual = rodadas.get(c.inicio)
        if atual is None or c.gerado_em > atual.gerado_em:
            rodadas[c.inicio] = Rodada(c.inicio, c.fim, c.gerado_em,
                                       frozenset(c.nomes), len(c.nomes))
    return dict(sorted(rodadas.items()))


def meses_entre(a: date, b: date) -> int:
    return (b.year - a.year) * 12 + b.month - a.month


def rotulo(nome: str) -> str:
    return nome.split(".", 1)[0]


def categoria(nome: str) -> str:
    return nome.split(".", 1)[1] if "." in nome else ""


# ------------------------------------------------------------ tamanho

def serie_de_tamanho(rodadas: dict[date, Rodada]) -> list[dict]:
    """Total, .com.br e o intervalo desde a rodada capturada anterior, se do mes anterior."""
    datas = list(rodadas)
    saida = []
    for i, d in enumerate(datas):
        r = rodadas[d]
        intervalo = None
        if i and meses_entre(datas[i - 1], d) == 1:
            intervalo = (d - datas[i - 1]).days
        saida.append({
            "inicio": d.isoformat(),
            "total": r.total_linhas,
            "com_br": sum(1 for n in r.nomes if n.endswith(".com.br")),
            "intervalo_dias": intervalo,
            "semanas": None if intervalo is None else round(intervalo / 7),
        })
    return saida


def unicos_por_ano(rodadas: dict[date, Rodada]) -> list[dict]:
    anos: dict[int, list[Rodada]] = {}
    for d, r in rodadas.items():
        anos.setdefault(d.year, []).append(r)
    return [{"ano": a, "rodadas": len(rs), "soma": sum(r.total_linhas for r in rs),
             "unicos": len(frozenset().union(*(r.nomes for r in rs)))}
            for a, rs in sorted(anos.items())]


# ------------------------------------------------------------ travas

def repetidos_da_anterior(rodadas: dict[date, Rodada]) -> list[dict]:
    """Quantos nomes de cada rodada ja estavam na rodada do mes anterior (so meses seguidos)."""
    datas = list(rodadas)
    return [{"inicio": d.isoformat(), "repetidos": len(rodadas[d].nomes & rodadas[a].nomes),
             "total": rodadas[d].total_linhas}
            for a, d in zip(datas, datas[1:]) if meses_entre(a, d) == 1]


def sequencias(rodadas: dict[date, Rodada]) -> list[tuple[str, date, int]]:
    """
    (nome, primeira rodada, quantas rodadas seguidas) de cada sequencia que
    TERMINOU dentro da serie. Uma rodada sem copia quebra a sequencia, entao
    so vale para trechos de cobertura completa; a ultima rodada nao fecha nada.
    """
    datas = list(rodadas)
    abertas: dict[str, tuple[date, int]] = {}
    fechadas = []
    anterior = None
    for d in datas:
        seguida = anterior is not None and meses_entre(anterior, d) == 1
        nomes = rodadas[d].nomes
        novas = {}
        for n in nomes:
            if seguida and n in abertas:
                ini, k = abertas[n]
                novas[n] = (ini, k + 1)
            else:
                novas[n] = (d, 1)
        for n, (ini, k) in abertas.items():
            if not seguida or n not in nomes:
                fechadas.append((n, ini, k))
        abertas = novas
        anterior = d
    return fechadas


def origem_dos_elegiveis(rodadas: dict[date, Rodada], elegiveis: dict[date, Rodada]) -> list[dict]:
    """
    Para cada rodada com lista de elegiveis e as 4 rodadas anteriores
    capturadas em meses seguidos: quantos elegiveis estavam na anterior, nas
    3 anteriores e nas 4 anteriores.
    """
    datas = list(rodadas)
    saida = []
    for d, ele in elegiveis.items():
        if d not in rodadas:
            continue
        i = datas.index(d)
        if i < 4 or meses_entre(datas[i - 4], d) != 4:
            continue
        ant = [rodadas[datas[i - j]].nomes for j in (1, 2, 3, 4)]
        e = ele.nomes
        saida.append({
            "inicio": d.isoformat(), "elegiveis": len(e),
            "na_anterior": sum(1 for n in e if n in ant[0]),
            "nas_3_anteriores": sum(1 for n in e if n in ant[0] and n in ant[1] and n in ant[2]),
            "nas_4_anteriores": sum(1 for n in e if all(n in a for a in ant)),
        })
    return saida


# ------------------------------------------------------------ bumerangues

def episodios(rodadas: dict[date, Rodada]) -> Counter:
    """
    Quantas vezes cada nome VOLTOU a lista: um episodio novo comeca quando
    a rodada capturada imediatamente anterior nao tinha o nome. Assim um mes
    sem copia no meio de uma trava nao vira dois episodios.
    """
    contagem: Counter = Counter()
    anterior: frozenset = frozenset()
    for r in rodadas.values():
        for n in r.nomes:
            if n not in anterior:
                contagem[n] += 1
        anterior = r.nomes
    return contagem


def intervalos_entre_episodios(rodadas: dict[date, Rodada], nomes) -> Counter:
    """Meses entre o inicio de um episodio e o do seguinte, para os nomes dados."""
    alvo = set(nomes)
    ultimo: dict[str, date] = {}
    anterior: frozenset = frozenset()
    hist: Counter = Counter()
    for d, r in rodadas.items():
        for n in alvo & r.nomes:
            if n not in anterior:
                if n in ultimo:
                    hist[meses_entre(ultimo[n], d)] += 1
                ultimo[n] = d
        anterior = r.nomes
    return hist


# ------------------------------------------------------------ modas

# Casamento ANCORADO no inicio ou no fim do rotulo, com excecoes explicitas.
# Substring solta conta "ecovida" como covid e "capixaba" como pix: a
# contagem ancorada fica menor, e esse e o lado honesto do erro.
TERMOS: dict[str, tuple[str, str | None]] = {
    "covid": (r"^covid|covid(19)?$|coronavirus", None),
    "delivery": (r"^delivery|delivery$", None),
    "home office": (r"homeoffice", None),
    "black friday": (r"blackfriday", None),
    "LGPD": (r"^lgpd|lgpd$", None),
    "NFT": (r"^nfts?|nfts?$", r"zukunft"),
    "cripto": (r"^cripto|cripto$|^crypto|crypto$|bitcoin", r"criptograf"),
    "metaverso": (r"metavers[oe]", None),
    "GPT": (r"chatgpt|^gpt|gpt$", r"^gpt(tele|tec|tur|err)|telecom"),
    "apostas": (r"^aposta|apostas?$|bet$|^bet\d|^bet(br|online|vip|win|pix|club|sport)", r"alfabet|alphabet"),
    "tiktok": (r"tiktok", None),
    "eleição": (r"^eleic|eleicao$|eleicoes\d*$|^candidato|^vote\d", None),
}


def compilar_termos(termos=TERMOS):
    return {t: (re.compile(p), re.compile(x) if x else None) for t, (p, x) in termos.items()}


def casa(rot: str, regra) -> bool:
    padrao, excecao = regra
    return bool(padrao.search(rot)) and not (excecao and excecao.search(rot))


def serie_de_termos(rodadas: dict[date, Rodada], termos=TERMOS) -> list[dict]:
    regras = compilar_termos(termos)
    saida = []
    for d, r in rodadas.items():
        rots = [rotulo(n) for n in r.nomes]
        linha = {"inicio": d.isoformat(), "total": r.total_linhas}
        for t, regra in regras.items():
            linha[t] = sum(1 for x in rots if casa(x, regra))
        saida.append(linha)
    return saida
