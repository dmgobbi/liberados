#!/usr/bin/env python3
"""
Descobre o que aconteceu com os dominios depois que a rodada fechou.

    python3 desfecho.py --antes site/dados.json

POR QUE ISTO EXISTE

O Registro.br documenta que "a interface de verificacao de disponibilidade
somente informara que existem tickets caso o dominio possua mais de um
candidato". Ou seja, "0 candidatos" na verdade quer dizer "zero ou um", e nao
da para separar os dois casos enquanto a rodada esta aberta.

Mas quando ela fecha, cada nome denuncia o que era:

    tinha mesmo 0 candidatos  ->  volta ao espaco livre  ->  LIVRE
    tinha 1 candidato oculto  ->  e atribuido a ele      ->  REGISTRADO
    tinha 2 ou mais           ->  trava ou vai a leilao  ->  LIBERACAO_*

Entao basta comparar o instantaneo de antes do fechamento com uma varredura
depois. A proporcao de REGISTRADO mede quantas vezes o 0 era mentira, e nao
custa candidatura nenhuma.

QUANDO RODAR

Algumas horas depois do fim da rodada: a atribuicao nao e instantanea.

AMOSTRA (16/09/2026)

Na rodada de setembro eram 15.736 nomes "sem competicao": 8,7 h a 2 s por
consulta, e a execucao do GitHub morre em 90 min com o CSV ainda por gravar.
Agora `--amostra N` sorteia ate N nomes por faixa de nota (semente fixa; as
faixas pequenas entram inteiras), cada linha leva o `peso` da sua faixa
(populacao / sorteados) para a taxa geral nao pender para a nota alta, o CSV
e gravado linha a linha e `--minutos` para a consulta no prazo. A ordem e
embaralhada, entao parar no meio corta todas as faixas por igual.
"""

import argparse
import csv
import random
import sys
import time
from collections import Counter, defaultdict

from garimpo.adaptadores.registrobr import PAUSA_SEGURA, verificar
from garimpo.casos import instantaneo
from garimpo.contexto import padrao
from garimpo.dominio.situacao import Situacao

RECUO_APOS_BLOQUEIO = 120

# o que cada situacao final revela sobre a contagem que viamos antes
LEITURAS = {
    Situacao.REGISTRADO: "tinha 1 candidato oculto",
    Situacao.LIVRE: "tinha mesmo 0 candidatos",
    Situacao.LIBERACAO_LIVRE: "ainda na rodada ou travado",
    Situacao.LIBERACAO_DISPUTADA: "ainda na rodada ou travado",
    Situacao.COMPETITIVO: "ainda na rodada ou travado",
    # status 5 do ISAVAIL: o nome travou e espera a proxima rodada
    # (conferido em 16/09/2026, 15h15: one, peca e liberado.com.br).
    Situacao.AGUARDANDO_LIBERACAO: "travado: espera a proxima rodada",
    Situacao.INDISPONIVEL: "indisponivel, ver motivo",
    Situacao.LIVRE_COM_TICKET: "fora da rodada, com pedido pendente",
}


def amostrar(alvos, por_faixa: int, semente: int = 16092026):
    """
    Ate `por_faixa` nomes de cada faixa de nota, embaralhados, e o peso de
    cada um (quantos da faixa ele representa). Sem amostra, peso 1.
    """
    if not por_faixa:
        return list(alvos), {c.dominio: 1.0 for c in alvos}
    from sinais_do_desfecho import faixa_nota
    faixas = defaultdict(list)
    for c in sorted(alvos, key=lambda c: c.dominio):
        faixas[faixa_nota(c.nota)].append(c)
    sorteio = random.Random(semente)
    escolhidos, pesos = [], {}
    for nome in sorted(faixas):
        grupo = faixas[nome]
        tirados = grupo if len(grupo) <= por_faixa else sorteio.sample(grupo, por_faixa)
        for c in tirados:
            pesos[c.dominio] = len(grupo) / len(tirados)
        escolhidos += tirados
    sorteio.shuffle(escolhidos)
    return escolhidos, pesos


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--antes", default=padrao.instantaneo,
                    help="instantaneo anterior ao fechamento da rodada")
    ap.add_argument("--out", default="desfecho.csv")
    ap.add_argument("--delay", type=float, default=PAUSA_SEGURA)
    ap.add_argument("--limite", type=int, default=0)
    ap.add_argument("--so-elegiveis", action="store_true")
    ap.add_argument("--amostra", type=int, default=0,
                    help="ate N nomes sorteados por faixa de nota (0 = todos)")
    ap.add_argument("--minutos", type=float, default=0,
                    help="para de consultar depois deste tempo (0 = sem prazo)")
    args = ap.parse_args()

    dados = instantaneo.ler(args.antes)
    if not dados:
        raise SystemExit(f"instantaneo nao encontrado: {args.antes}")

    anteriores = instantaneo.candidatos_de(dados)
    print(f"instantaneo de {dados.get('gerado_em')}: "
          f"{len(anteriores)} dominios", file=sys.stderr)

    alvos = [c for c in anteriores
             if c.situacao is Situacao.LIBERACAO_LIVRE and not c.candidatos
             and (c.elegivel or not args.so_elegiveis)]
    populacao = len(alvos)
    alvos, pesos = amostrar(alvos, args.amostra)
    if args.limite:
        alvos = alvos[:args.limite]

    pausa = max(PAUSA_SEGURA, args.delay)
    print(f"{populacao} estavam 'sem competicao'; {len(alvos)} na amostra; reverificando "
          f"({len(alvos) * pausa / 60:.0f} min)", file=sys.stderr)

    veredito = Counter()
    ponderado = Counter()
    fh = open(args.out, "w", newline="", encoding="utf-8")
    escritor = csv.DictWriter(
        fh, fieldnames=["dominio", "depois", "candidatos", "leitura", "peso"])
    escritor.writeheader()
    prazo = time.monotonic() + args.minutos * 60 if args.minutos else None

    for i, candidato in enumerate(alvos, 1):
        if prazo and time.monotonic() > prazo:
            print(f"  prazo de {args.minutos:.0f} min: parando em {i - 1}/{len(alvos)}",
                  file=sys.stderr)
            break
        leitura = verificar(candidato.dominio)
        if leitura.limitado:
            print(f"  bloqueado, recuando {RECUO_APOS_BLOQUEIO}s",
                  file=sys.stderr)
            time.sleep(RECUO_APOS_BLOQUEIO)
            leitura = verificar(candidato.dominio)

        conclusao = LEITURAS.get(leitura.situacao, "indefinido")
        veredito[conclusao] += 1
        ponderado[conclusao] += pesos[candidato.dominio]
        escritor.writerow({"dominio": candidato.dominio,
                           "depois": leitura.situacao.value,
                           "candidatos": leitura.candidatos,
                           "leitura": conclusao,
                           "peso": f"{pesos[candidato.dominio]:.3f}"})
        fh.flush()

        if i % 25 == 0 or i == len(alvos):
            print(f"  [{i}/{len(alvos)}]", file=sys.stderr)
        time.sleep(pausa)

    fh.close()

    total = sum(veredito.values()) or 1
    print(f"\n=== desfecho de {sum(veredito.values())} dominios que "
          f"apareciam sem competicao ===")
    for conclusao, n in veredito.most_common():
        print(f"  {n:5d}  {conclusao}  ({n / total * 100:.0f}%)")

    ocultos = ponderado["tinha 1 candidato oculto"]
    zerados = ponderado["tinha mesmo 0 candidatos"]
    if ocultos + zerados:
        proporcao = ocultos / (ocultos + zerados) * 100
        print(f"\nEntre os que resolveram, {proporcao:.0f}% do que aparecia "
              f"como 0 candidatos na verdade tinha 1 (ponderado pela amostra).")
        if not ocultos:
            print("Nenhum oculto: o 0 pode ser lido como 0 mesmo.")
    print(f"\ndetalhe por dominio em {args.out}")


if __name__ == "__main__":
    main()
