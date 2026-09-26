"""
Em que rodadas um nome passou pela lista de liberacao, para a ficha
"quando esse dominio volta?".

Camada de dominio: funcoes puras, sem rede e sem disco.

POR QUE SO QUEM PASSOU DUAS VEZES OU MAIS (14/09/2026)

As 87 listas guardadas desde 2017 tem 9,2 milhoes de nomes distintos: o
indice completo daria 216 MB, grande demais para o git e para o site.
Quem passou duas vezes ou mais sao 1,06 milhao de nomes e 28 MB, e e o dado
que diz algo que o RDAP nao diz: o dono ja deixou esse nome vencer antes.
Uma passagem so, quase sempre, e a propria rodada de agora travando.

POR QUE FATIA POR HASH, E NAO PELA PRIMEIRA LETRA

O navegador baixa so a fatia do nome consultado. Pela primeira letra as
fatias ficam desiguais (muito mais nomes com "a" e "c" que com "y"); o hash
espalha por igual. FNV-1a de 32 bits porque cabe em dez linhas nas duas
linguagens, e o mesmo teste confere os dois lados (test_scripts.py roda
o fnv1a32 de site_modelo/ficha.js no node e compara).

A MARCA DE ELEGIVEL (15/09/2026)

"i" e a posicao da rodada; "ie" diz que, naquela rodada, o nome tambem
estava na lista de elegiveis ao leilao. A ficha conta as rodadas seguidas
para prever se a proxima e rodada normal ou leilao (tres travas, limitacao
S13), e precisa separar "nao era elegivel" de "nao ha copia da lista de
elegiveis": por isso o rodadas.json diz quais rodadas tem essa copia.
Rodada que so tem copia da lista de elegiveis fica de fora do indice.
"""

from __future__ import annotations

from collections import defaultdict

FATIAS = 256
MINIMO = 2


def fnv1a32(texto: str) -> int:
    h = 0x811C9DC5
    for byte in texto.encode("utf-8"):
        h ^= byte
        h = (h * 0x01000193) & 0xFFFFFFFF
    return h


def fatia(dominio: str) -> str:
    """O arquivo onde o nome mora: '00' a 'ff'."""
    return f"{fnv1a32(dominio.strip().lower()) % FATIAS:02x}"


def montar(rodadas: dict, minimo: int = MINIMO,
           elegiveis: dict | None = None) -> tuple[list[str], dict[str, list[str]]]:
    """
    Recebe {data de inicio: Rodada} das listas de liberacao (e, se houver, as
    de elegiveis) e devolve as datas das rodadas, em ordem, e as linhas de
    cada fatia: "nome<TAB>i,je,k", onde i, j, k sao posicoes na lista de
    datas e o "e" marca a rodada em que o nome era elegivel ao leilao.
    Linhas em ordem alfabetica: o arquivo so muda quando o dado muda.
    """
    elegiveis = elegiveis or {}
    datas = sorted(rodadas)
    por_nome: dict[str, list[str]] = defaultdict(list)
    for i, d in enumerate(datas):
        ele = elegiveis[d].nomes if d in elegiveis else frozenset()
        for nome in rodadas[d].nomes:
            por_nome[nome].append(f"{i}e" if nome in ele else str(i))
    fatias: dict[str, list[str]] = defaultdict(list)
    for nome in sorted(por_nome):
        indices = por_nome[nome]
        if len(indices) >= minimo:
            fatias[fatia(nome)].append(nome + "\t" + ",".join(indices))
    return [d.isoformat() for d in datas], dict(fatias)


def com_elegiveis(datas: list[str], elegiveis: dict) -> list[int]:
    """Posicoes, na lista de datas, das rodadas que tem copia da lista de elegiveis."""
    tem = {d.isoformat() for d in elegiveis}
    return [i for i, d in enumerate(datas) if d in tem]
