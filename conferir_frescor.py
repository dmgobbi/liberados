#!/usr/bin/env python3
"""
Confere se o instantaneo cumpre a promessa de idade de cada classe.

    python3 conferir_frescor.py                 # le site/dados.json
    python3 conferir_frescor.py outro.json

Sai com codigo 1 quando algum nome QUENTE passou do prazo. No GitHub Actions
isso deixa a execucao vermelha, e o GitHub manda e-mail: e o alarme que
faltou em 10/09/2026, quando 51 nomes ficaram 30 horas sem consulta e
ninguem soube ate um visitante reclamar.

Sai com 1 tambem quando a varredura desta execucao foi barrada
(work/varredura.json, gravado pelo varrer.py): houve alvos e nenhuma
consulta deu certo, ou houve bloqueio. Desde 19/09/2026 a varredura se
encerra sozinha num bloqueio que sobrevive ao recuo ou em 10 erros
seguidos ("barrada", com "motivo" "bloqueio" ou "rede"), e o alarme cita
o motivo. Isso vale com a rodada aberta ou
fechada: o varrer.py sai com 0 nos dois casos, e antes de 18/09/2026 um
runner barrado pelo Registro.br deixava a execucao verde. A varredura
pulada de proposito antes da abertura da rodada ("pulada":
"antes_da_abertura") nao acende nada.

Roda DEPOIS de publicar, de proposito: um alarme nao pode impedir que o
instantaneo que o comprova seja comitado.
"""

import argparse
import json
import os
import sys
import time

from garimpo.casos import instantaneo
from garimpo.contexto import padrao
from garimpo.dominio import frescor


def alarme_da_varredura(v: dict) -> str | None:
    """O motivo do alarme, ou None se a varredura andou."""
    if v.get("pulada") == "antes_da_abertura":
        # de proposito: a rodada ainda nao abriu e o varrer.py nao consulta
        return None
    alvos, feitos = v.get("alvos") or 0, v.get("feitos") or 0
    bloqueios = v.get("bloqueios") or 0
    if v.get("barrada"):
        motivo = v.get("motivo") or "desconhecido"
        explica = {"bloqueio": "o Registro.br seguiu bloqueando depois do "
                               "recuo de 120 s",
                   "rede": "10 consultas seguidas falharam"}.get(motivo, "")
        return (f"varredura barrada, motivo: {motivo}"
                + (f" ({explica})" if explica else "")
                + f". {feitos} de {alvos} consultas feitas; a proxima "
                  "execucao retoma pela fila.")
    if bloqueios:
        return (f"{bloqueios} bloqueios na varredura ({feitos} de {alvos} "
                "consultas feitas). Se repetir, aumente o --delay.")
    if alvos and not feitos:
        return (f"{alvos} nomes na fila e nenhuma consulta deu certo "
                f"({v.get('erros') or 0} erros).")
    return None


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("arquivo", nargs="?", default=padrao.instantaneo)
    ap.add_argument("--varredura",
                    default=os.path.join(padrao.trabalho, "varredura.json"),
                    help="o resumo que o varrer.py grava; ausente, so o "
                         "frescor conta")
    args = ap.parse_args()

    dados = instantaneo.ler(args.arquivo)
    if not dados:
        print(f"sem instantaneo em {args.arquivo}")
        return 1

    relatorio = instantaneo.frescor_de(dados, int(time.time()))
    print("## Frescor\n")
    print("| classe | prazo | nomes | vencidos | mais velho |")
    print("|---|---|---|---|---|")
    for linha in relatorio:
        prazo = f"{linha['prazo_horas']} h" if linha["prazo_horas"] else "sem promessa"
        velho = f"{linha['mais_velho_h']:.1f} h" if linha["nomes"] else "-"
        print(f"| {linha['nome']} | {prazo} | {linha['nomes']} "
              f"| {linha['vencidos']} | {velho} |")

    # antes da checagem da rodada: varredura barrada e alarme sempre
    if os.path.exists(args.varredura):
        with open(args.varredura, encoding="utf-8") as f:
            motivo = alarme_da_varredura(json.load(f))
        if motivo:
            print(f"\n**ALARME**: {motivo}")
            return 1

    quentes = next((l for l in relatorio if l["nome"] == "quente"), None)
    rodada = dados.get("rodada") or {}
    if not frescor.rodada_aberta(rodada.get("inicio"), rodada.get("fim"), int(time.time())):
        print(f"\nRodada fora da janela ({rodada.get('inicio')} a {rodada.get('fim')}): "
              "a promessa dos quentes so vale com ela aberta. Sem alarme.")
        return 0
    if quentes and quentes["vencidos"]:
        print(f"\n**ALARME**: {quentes['vencidos']} nomes quentes passaram "
              f"de {quentes['prazo_horas']} h sem consulta. Exemplos: "
              + ", ".join(quentes["exemplos"]))
        return 1
    print("\nTodas as promessas cumpridas.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
