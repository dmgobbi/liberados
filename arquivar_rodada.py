#!/usr/bin/env python3
"""
Guarda o que a rodada deixa: as listas oficiais e quantos candidatos cada
nome disputado teve (garimpo/casos/arquivo_das_rodadas.py).

    python3 arquivar_rodada.py              # depois do varrer.py, no workflow
    python3 arquivar_rodada.py --do-git     # refaz disputas.json com todos os
                                            # instantaneos do historico do git

Grava docs/historico/listas/<inicio>-liberacao.txt.gz e -elegiveis.txt.gz
(uma vez por rodada) e acumula site/dados.json em
docs/historico/disputas.json. Se o site ja foi exportado, copia a base para
site/dados/historico/, para a ficha /quando-volta/ ver a contagem da
execucao atual e nao a da anterior.

Nunca consulta o Registro.br: le so o que a varredura ja gravou.
"""

import argparse
import json
import os
import shutil
import subprocess

from garimpo.casos import arquivo_das_rodadas as arq
from garimpo.contexto import padrao

HISTORICO = os.path.join(padrao.raiz, "docs", "historico")
DISPUTAS = os.path.join(HISTORICO, "disputas.json")


def instantaneos_do_git():
    """Cada versao comitada de site/dados.json, da mais antiga para a mais nova."""
    hashes = subprocess.run(["git", "log", "--reverse", "--format=%H", "--", "site/dados.json"],
                            cwd=padrao.raiz, capture_output=True, text=True, check=True).stdout.split()
    for h in hashes:
        bruto = subprocess.run(["git", "show", f"{h}:site/dados.json"], cwd=padrao.raiz,
                               capture_output=True, check=True).stdout
        try:
            yield json.loads(bruto)
        except json.JSONDecodeError:
            continue


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    ap.add_argument("--do-git", action="store_true",
                    help="acumula todas as versoes de site/dados.json do historico do git")
    a = ap.parse_args()

    for caminho in arq.guardar_listas(padrao.trabalho, os.path.join(HISTORICO, "listas")):
        print("lista guardada:", os.path.relpath(caminho, padrao.raiz))

    fontes = list(instantaneos_do_git()) if a.do_git else []
    if os.path.exists(padrao.instantaneo):
        with open(padrao.instantaneo, encoding="utf-8") as f:
            fontes.append(json.load(f))
    mudou = False
    for dados in fontes:
        mudou = arq.atualizar_disputas(DISPUTAS, dados) or mudou
    if os.path.exists(DISPUTAS):
        with open(DISPUTAS, encoding="utf-8") as f:
            base = json.load(f)
        resumo = ", ".join(f"{inicio}: {len(r['nomes'])} nomes de {r['conferidos']} conferidos"
                           for inicio, r in base["rodadas"].items())
        print(f"disputas.json {'atualizado' if mudou else 'sem mudanca'} ({resumo})")
        publicado = os.path.join(padrao.site, "dados", "historico")
        if os.path.isdir(publicado):
            shutil.copy2(DISPUTAS, os.path.join(publicado, "disputas.json"))


if __name__ == "__main__":
    main()
