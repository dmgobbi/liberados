#!/usr/bin/env python3
"""
Consulta o ISAVAIL, o servico oficial de disponibilidade do Registro.br.

    python3 isavail.py vacina.com.br one.com.br
    python3 isavail.py --bruto café.com.br

E o mesmo dado do endpoint web da caixa de busca, por outro canal: UDP na
porta 43 de avail.registro.br, protocolo de texto documentado em
ftp.registro.br/pub/isavail/. Serve para conferir um nome quando o endpoint
web mudar ou bloquear, e para ver a resposta crua.

NAO serve para varrer a lista: o limite de consultas deste canal nao e
publicado, e o projeto nao mede limite batendo nele. A pausa minima e a
mesma do resto (2 s). As datas que o servico devolve nao sao confiaveis
(ver garimpo/adaptadores/isavail.py); o script mostra, mas avisa.
"""

from __future__ import annotations

import argparse
import sys
import time

from garimpo.adaptadores import isavail
from garimpo.dominio.situacao import classificar


def main() -> int:
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("dominios", nargs="+")
    p.add_argument("--bruto", action="store_true", help="mostra o pacote como veio")
    p.add_argument("--delay", type=float, default=isavail.PAUSA_SEGURA,
                   help="segundos entre consultas (piso: %(default)s)")
    args = p.parse_args()

    pausa = max(args.delay, isavail.PAUSA_SEGURA)
    cliente = isavail.Cliente()
    falhas = 0
    for i, dominio in enumerate(args.dominios):
        resposta = cliente.consultar(dominio)
        if resposta.status is None:
            falhas += 1
            print(f"{dominio}: falha: {resposta.mensagem}", file=sys.stderr)
        else:
            leitura = classificar(resposta.payload())
            candidatos = f"{leitura.candidatos} candidatos" if leitura.candidatos else ""
            detalhe = " · ".join(x for x in (candidatos, leitura.detalhe) if x)
            print(f"{dominio:32} {leitura.situacao.value:22} {detalhe}")
            if resposta.datas:
                print(f"{'':32} datas do ISAVAIL (nao confiaveis): "
                      f"{' | '.join(resposta.datas)}")
            if leitura.limitado:
                print("bloqueado por excesso de consultas; parando.",
                      file=sys.stderr)
                return 2
        if args.bruto:
            print(resposta.bruto.rstrip())
            print()
        if i + 1 < len(args.dominios):
            time.sleep(pausa)
    return 1 if falhas else 0


if __name__ == "__main__":
    raise SystemExit(main())
