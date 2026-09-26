#!/usr/bin/env python3
"""
Servidor local do garimpo de dominios .br.

    python3 app.py                       # abre em http://localhost:8765
    python3 app.py --porta 9000 --sem-navegador

Entrada fina: a logica mora no pacote garimpo/. Ver garimpo/__init__.py para
o desenho das camadas.
"""

import argparse

from garimpo.contexto import padrao
from garimpo.web.servidor import PORTA_PADRAO, servir


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--porta", type=int, default=PORTA_PADRAO)
    ap.add_argument("--sem-navegador", action="store_true")
    args = ap.parse_args()

    servir(padrao, porta=args.porta, abrir_navegador=not args.sem_navegador)


if __name__ == "__main__":
    main()
