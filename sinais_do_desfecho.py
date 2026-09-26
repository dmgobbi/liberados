#!/usr/bin/env python3
"""
O que separa um "0 candidatos" verdadeiro de um com candidato oculto.

    python3 sinais_do_desfecho.py desfecho.csv --antes site/dados.json

Depois que a rodada fecha, `desfecho.py` revela, nome a nome, o que o "0"
escondia: LIVRE era 0 mesmo; REGISTRADO era 1 oculto. Este script cruza
esse veredito com o que sabiamos ANTES (nota, tamanho, dicionario, nicho,
elegibilidade, extensao) e mostra, por faixa, a taxa de candidato oculto.

E o unico dado que de fato melhora a chance de levar um nome por R$ 40 na
rodada seguinte: em vez de "0 significa zero ou um" para todo mundo, passa
a ser "nesta faixa, 8% tinham alguem; naquela, 40%".

Roda no dia 16/09/2026 a noite, com o desfecho.csv que o workflow gera.
Sem rede.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import defaultdict

from garimpo.dominio import extensoes
from garimpo.dominio.relevancia import separar

OCULTO = "tinha 1 candidato oculto"
ZERO = "tinha mesmo 0 candidatos"


def faixa_nota(n: int) -> str:
    if n >= 80:
        return "nota 80+"
    if n >= 65:
        return "nota 65-79"
    if n >= 50:
        return "nota 50-64"
    return "nota <50"


def faixa_tamanho(rotulo: str) -> str:
    n = len(rotulo)
    if n <= 5:
        return "até 5 letras"
    if n <= 8:
        return "6-8 letras"
    if n <= 12:
        return "9-12 letras"
    return "13+ letras"


def sinais(dominio: str, nota: int, elegivel: bool, motivos) -> list[str]:
    """As faixas em que um nome cai. Um nome conta em cada uma delas."""
    rotulo, extensao = separar(dominio)
    m = " ".join(motivos).lower()
    saida = [faixa_nota(nota), faixa_tamanho(rotulo),
             "elegível ao leilão" if elegivel else "não elegível",
             f"extensão {extensoes.categoria(extensao)}"]
    if "português" in m or "portugues" in m:
        saida.append("palavra em português")
    elif "inglês" in m or "ingles" in m:
        saida.append("palavra em inglês")
    else:
        saida.append("não é palavra de dicionário")
    if "nicho" in m or "composto" in m:
        saida.append("nicho comercial")
    if "empresa" in m:
        saida.append("nome usado por empresas")
    if "pessoa" in m:
        saida.append("nome de pessoa")
    return saida


def cruzar(desfecho: list[dict], itens_antes: dict[str, dict]) -> dict[str, dict]:
    """
    Por faixa: quantos resolveram, quantos tinham oculto, e a taxa.

    `desfecho` sao as linhas do CSV (dominio, leitura). `itens_antes` mapeia
    dominio -> {nota, elegivel, motivos} do instantaneo anterior ao
    fechamento. Linhas sem veredito (ainda na rodada) ficam de fora.
    """
    tabela: dict[str, dict] = defaultdict(
        lambda: {"n": 0, "ocultos": 0, "peso": 0.0, "peso_ocultos": 0.0})
    for linha in desfecho:
        veredito = linha.get("leitura")
        if veredito not in (OCULTO, ZERO):
            continue
        antes = itens_antes.get(linha["dominio"])
        if not antes:
            continue
        # peso: quantos nomes da faixa de nota esta linha representa quando
        # o desfecho.py rodou por amostra (sem a coluna, 1)
        peso = float(linha.get("peso") or 1)
        for faixa in ["todos"] + sinais(linha["dominio"], antes["nota"],
                                         antes["elegivel"], antes["motivos"]):
            tabela[faixa]["n"] += 1
            tabela[faixa]["peso"] += peso
            if veredito == OCULTO:
                tabela[faixa]["ocultos"] += 1
                tabela[faixa]["peso_ocultos"] += peso
    for faixa in tabela.values():
        faixa["taxa"] = faixa["peso_ocultos"] / faixa["peso"] if faixa["peso"] else 0.0
    return dict(tabela)


def itens_do_instantaneo(dados: dict) -> dict[str, dict]:
    motivos = dados.get("motivos") or []
    saida = {}
    for it in dados.get("itens") or []:
        saida[it[0]] = {
            "nota": it[3],
            "elegivel": bool(it[4]),
            "motivos": [motivos[i] for i in (it[5] or []) if 0 <= i < len(motivos)],
        }
    return saida


def relatorio(tabela: dict[str, dict]) -> str:
    if "todos" not in tabela:
        return "nenhum nome com veredito ainda: a rodada nao fechou?"
    geral = tabela["todos"]
    linhas = [f"{geral['n']} nomes que apareciam com 0 candidatos e ja resolveram; "
              f"{geral['ocultos']} tinham candidato oculto (taxa ponderada pela "
              f"amostra: {geral['taxa'] * 100:.0f}%).",
              "", "| faixa | nomes | com oculto | taxa |", "|---|---|---|---|"]
    ordem = sorted((f for f in tabela if f != "todos"),
                   key=lambda f: (-tabela[f]["taxa"], -tabela[f]["n"]))
    for faixa in ordem:
        t = tabela[faixa]
        if t["n"] < 5:
            continue          # com menos de 5 a taxa e ruido
        linhas.append(f"| {faixa} | {t['n']} | {t['ocultos']} | {t['taxa'] * 100:.0f}% |")
    linhas.append("")
    linhas.append("Leitura: faixa com taxa baixa e onde um '0' vale mais. Faixa com "
                  "taxa alta e onde o '0' quase sempre esconde alguem.")
    return "\n".join(linhas)


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    p.add_argument("desfecho", help="CSV gerado por desfecho.py")
    p.add_argument("--antes", default="site/dados.json",
                   help="instantaneo anterior ao fechamento (padrao: site/dados.json)")
    args = p.parse_args(argv)

    with open(args.desfecho, encoding="utf-8") as f:
        linhas = list(csv.DictReader(f))
    with open(args.antes, encoding="utf-8") as f:
        dados = json.load(f)
    print(relatorio(cruzar(linhas, itens_do_instantaneo(dados))))
    return 0


if __name__ == "__main__":
    sys.exit(main())
