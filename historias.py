#!/usr/bin/env python3
"""
Descobre o que aconteceu com dominios .br que ja tem dono.

    python3 historias.py                          # usa notaveis.csv
    python3 historias.py lista.csv --out saida.csv
    python3 historias.py --delay 2

O resto do projeto olha para a rodada: quem esta em liberacao e quantos
candidatos tem. Este script olha para depois — os nomes que ja foram levados
por alguem — e responde o que foi feito deles.

Cruza tres fontes que raramente sao cruzadas:

  RDAP    (rdap.registro.br)  quem e o titular, desde quando, ate quando
                              esta pago, e para quais servidores DNS aponta
  DNS     (resolvedor local)  esse nome leva a algum endereco de verdade?
  ARQUIVO (web.archive.org)   esse nome JA levou a algum lugar, e quando
                              parou de levar?

Sozinhas, nenhuma conta a historia. Juntas contam. Foi assim que apareceu o
caso do pneus.com.br: R$ 220 mil em 2019, o .br mais caro ja vendido, hoje
sem entregar nada e pago ate 2029 — mas que de 2019 a 2023 redirecionava
para sunset-tires.com. Sem o arquivo, a conclusao seria "compraram e nunca
usaram", e seria falsa.

Cada dominio vira uma categoria:

  em branco     registrado e pago, mas nao resolve para lugar nenhum
  estacionado   resolve, mas ainda no DNS emprestado do proprio Registro.br
  ativo         resolve em servidor proprio: alguem usa
  livre         nao esta registrado

A entrada e um CSV com as colunas `dominio, valor, ano, fonte`. So `dominio`
e obrigatorio; as outras servem para dar contexto ao que for encontrado, e
`fonte` existe para nenhum valor entrar aqui sem procedencia.

O RDAP e um servico separado do endpoint de disponibilidade, mas e o mesmo
Registro.br do outro lado: o piso de 2 segundos entre consultas vale igual.
"""

import argparse
import os
import sys

from garimpo.casos import historias

PADRAO = os.path.join(os.path.dirname(os.path.abspath(__file__)), "notaveis.csv")


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    p.add_argument("entrada", nargs="?", default=PADRAO,
                   help="CSV com dominio,valor,ano,fonte (padrao: notaveis.csv)")
    p.add_argument("--out", help="grava o resultado detalhado neste CSV")
    p.add_argument("--delay", type=float, default=historias.rdap.PAUSA_SEGURA,
                   help="pausa entre consultas, em segundos (minimo 2)")
    p.add_argument("--titular", action="store_true",
                   help="consulta tambem a entidade do titular (so CNPJ) para "
                        "saber quantos dominios ele tem; uma requisicao a mais")
    args = p.parse_args(argv)

    if not os.path.exists(args.entrada):
        print(f"nao encontrei {args.entrada}", file=sys.stderr)
        return 1

    # o piso nao e negociavel, mesmo com o usuario pedindo menos
    pausa = max(args.delay, historias.rdap.PAUSA_SEGURA)

    alvos = historias.ler_alvos(args.entrada)
    if not alvos:
        print("nenhum dominio na entrada", file=sys.stderr)
        return 1

    achados = historias.investigar(
        alvos, pausa=pausa, titular=args.titular,
        aviso=lambda m: print(m, file=sys.stderr, flush=True))

    print()
    print(historias.resumir(achados))

    if args.out:
        historias.escrever(achados, args.out)
        print(f"\ndetalhe em {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
