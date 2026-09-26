#!/usr/bin/env python3
"""
Monta work/demanda.json a partir do cadastro aberto de CNPJ da Receita.

    python3 demanda_cnpj.py                  # mes mais recente publicado
    python3 demanda_cnpj.py --mes 2026-08
    python3 demanda_cnpj.py --zips pasta/    # usa zips ja baixados

Baixa uma parte por vez, conta, e apaga antes de baixar a proxima: sao ~5,3
GB no total, e o runner do GitHub nao precisa guardar tudo junto. Em casa,
a 3,4 MB/s, leva uns 30 minutos.

O resultado NAO vai para o git (licenca CC BY-ND, ver adaptadores/cnpj.py).
No Actions ele mora no cache, regerado uma vez por mes pelo modo `demanda`.
"""

import argparse
import glob
import os
import sys
import time

from garimpo.adaptadores import cnpj
from garimpo.casos import demanda
from garimpo.contexto import padrao


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--mes", help="pasta AAAA-MM; padrao: a mais recente")
    ap.add_argument("--zips", help="diretorio com Estabelecimentos*.zip ja baixados")
    ap.add_argument("--out", default=os.path.join(padrao.trabalho, "demanda.json"))
    args = ap.parse_args()

    contagem = demanda.Demanda()
    inicio = time.time()

    if args.zips:
        arquivos = sorted(glob.glob(os.path.join(args.zips, "Estabelecimentos*.zip")))
        if not arquivos:
            print(f"nenhum Estabelecimentos*.zip em {args.zips}")
            return 1
        contagem.mes = args.mes or "local"
        for caminho in arquivos:
            contagem.somar(cnpj.matrizes_ativas(caminho))
            print(f"  {os.path.basename(caminho)}: {contagem.empresas:,} empresas", flush=True)
    else:
        mes = args.mes or cnpj.meses()[-1]
        contagem.mes = mes
        print(f"cadastro de {mes}", flush=True)
        temporario = os.path.join(padrao.trabalho, "cnpj_tmp")
        for parte in cnpj.PARTES:
            caminho = os.path.join(temporario, parte)
            cnpj.baixar(mes, parte, caminho)
            try:
                contagem.somar(cnpj.matrizes_ativas(caminho))
            finally:
                os.remove(caminho)
            print(f"  {parte}: {contagem.empresas:,} empresas "
                  f"({time.time() - inicio:.0f}s)", flush=True)

    tamanho = demanda.gravar(contagem, args.out)
    print(f"\n{contagem.empresas:,} empresas ativas, "
          f"{len(contagem.palavras):,} palavras, {len(contagem.nomes):,} nomes")
    print(f"gravado {args.out} ({tamanho / 1e6:.1f} MB) em {time.time() - inicio:.0f}s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
