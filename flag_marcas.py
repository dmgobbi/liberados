#!/usr/bin/env python3
"""
Filtro de risco de marca registrada.

    python3 flag_marcas.py lista.txt --out risco.csv

Marca nomes que parecem marca de terceiro, em tres niveis: OK, ATENCAO,
RISCO. NAO consulta o INPI: a busca deles nao tem API publica e o e-INPI
exige sessao.

E FILTRO DE EXCLUSAO, NUNCA LISTA DE ALVOS. Registrar dominio que reproduz
marca alheia com intencao de revender ao titular e ma-fe caracterizada: ele
aciona o SACI-Adm do CGI.br e recupera o dominio, e voce perde o nome e o
dinheiro. Palavra generica em portugues e o alvo certo por nao ter dono.

Confira os marcados como RISCO em busca.inpi.gov.br e tmsearch.uspto.gov.

A lista de marcas mora em garimpo/dominio/marcas.py.
"""

import argparse
import csv

from garimpo.dominio.marcas import MARCAS, TYPOS, Risco, avaliar

__all__ = ["avaliar", "MARCAS", "TYPOS", "Risco"]


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("arquivo")
    ap.add_argument("--out", default="risco.csv")
    args = ap.parse_args()

    with open(args.arquivo, encoding="utf-8", errors="replace") as f:
        dominios = [l.strip().lower() for l in f
                    if l.strip() and not l.startswith("#")]

    contagem = {r.value: 0 for r in Risco}
    with open(args.out, "w", newline="", encoding="utf-8") as fh:
        escritor = csv.writer(fh)
        escritor.writerow(["dominio", "nivel", "motivo"])
        for dominio in dominios:
            nivel, motivo = avaliar(dominio.split(".")[0])
            contagem[nivel] += 1
            escritor.writerow([dominio, nivel, motivo])

    print(f"OK: {contagem['OK']}  ATENCAO: {contagem['ATENCAO']}  "
          f"RISCO: {contagem['RISCO']}")
    print(f"saida: {args.out}")


if __name__ == "__main__":
    main()
