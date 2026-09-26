#!/usr/bin/env python3
"""
Verifica o status de dominios .br no Registro.br.

    python3 check_dominios.py lista.txt --out resultado.csv --delay 2
    python3 check_dominios.py lista.txt --banco   # grava tambem no dados.db

Um dominio por linha; linhas comecando com # sao ignoradas.

Classifica cada nome em:

  LIVRE                - disponivel para registro normal
  LIBERACAO_LIVRE      - em liberacao, SEM CANDIDATO VISIVEL
  LIBERACAO_DISPUTADA  - em liberacao, ja tem candidato (tende a travar)
  COMPETITIVO          - em leilao
  REGISTRADO           - ja tem dono
  LIMITADO             - bloqueado por excesso de consultas
  ERRO                 - falha de rede ou resposta inesperada

ATENCAO ao ler LIBERACAO_LIVRE: o proprio Registro.br documenta que "a
interface de verificacao de disponibilidade somente informara que existem
tickets caso o dominio possua mais de um candidato". Ou seja, a coluna
"candidatos" mostra 0 tanto para zero quanto para um candidato.

O Registro.br limita consultas por IP. O delay minimo de 2 segundos e o piso
usado em todo o projeto; filtre a lista antes em vez de acelerar.

Para a mesma coisa numa interface: python3 app.py
"""

import argparse
import csv
import json
import sys
import time

from garimpo.adaptadores import registrobr
from garimpo.adaptadores.registrobr import PAUSA_SEGURA, consultar, verificar
from garimpo.contexto import padrao
from garimpo.dominio.situacao import Situacao, classificar

RECUO_APOS_BLOQUEIO = 60


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("arquivo", help="arquivo com um dominio por linha")
    ap.add_argument("--out", default="resultado.csv")
    ap.add_argument("--delay", type=float, default=PAUSA_SEGURA)
    ap.add_argument("--limite", type=int, default=0,
                    help="para depois de N dominios (0 = sem limite)")
    ap.add_argument("--raw", action="store_true",
                    help="guarda o json bruto numa coluna extra")
    ap.add_argument("--banco", action="store_true",
                    help="grava tambem no dados.db, que a interface usa")
    args = ap.parse_args()

    with open(args.arquivo, encoding="utf-8", errors="replace") as f:
        dominios = [l.strip().lower() for l in f
                    if l.strip() and not l.startswith("#")]
    if args.limite:
        dominios = dominios[:args.limite]

    pausa = max(PAUSA_SEGURA, args.delay)
    print(f"{len(dominios)} dominios, delay de {pausa}s, tempo estimado "
          f"{len(dominios) * pausa / 60:.1f} min", file=sys.stderr)

    campos = ["dominio", "status", "candidatos", "detalhe"]
    if args.raw:
        campos.append("raw")
    repo = padrao.repo if args.banco else None

    with open(args.out, "w", newline="", encoding="utf-8") as fh:
        escritor = csv.DictWriter(fh, fieldnames=campos)
        escritor.writeheader()

        for i, dominio in enumerate(dominios, 1):
            bruto = ""
            if args.raw:
                try:
                    payload = consultar(dominio)
                    leitura = classificar(payload)
                    bruto = json.dumps(payload, ensure_ascii=False)
                except Exception as e:
                    from garimpo.dominio.situacao import Leitura
                    leitura = Leitura(Situacao.ERRO, detalhe=str(e)[:200])
            else:
                leitura = verificar(dominio)

            linha = {"dominio": dominio, "status": leitura.situacao.value,
                     "candidatos": leitura.candidatos,
                     "detalhe": leitura.detalhe}
            if args.raw:
                linha["raw"] = bruto
            escritor.writerow(linha)
            fh.flush()

            if repo and leitura.situacao.resolvida:
                repo.gravar_leitura(dominio, leitura)

            print(f"[{i}/{len(dominios)}] {dominio:<28} "
                  f"{leitura.situacao.value:<20} cand={leitura.candidatos}",
                  file=sys.stderr)

            if leitura.limitado:
                print(f"  bloqueado, pausando {RECUO_APOS_BLOQUEIO}s",
                      file=sys.stderr)
                time.sleep(RECUO_APOS_BLOQUEIO)

            if i < len(dominios):
                time.sleep(pausa)

    print(f"\npronto: {args.out}", file=sys.stderr)


if __name__ == "__main__":
    main()
