#!/usr/bin/env python3
"""
Rajada em casa: a lista da rodada conferida numa noite, em blocos.

    python3 rajada.py --seco                          # quantos, quais, ate quando
    python3 rajada.py --desde fechamento --ate 07:00  # a de verdade

So roda com o "pode rodar a rajada" do dono, na maquina dele, numa worktree
propria na main (docs/operacao.md, secao 6). Recusa rodar no GitHub Actions
e no checkout principal (codigo 3) e antes da abertura da rodada (codigo 4).

Blocos de 30 min (~700 consultas, 2 s entre elas, uma de cada vez) com 5 min
de descanso. Antes de cada bloco aplica o site/dados.json da origin/main,
para nao reler o que o cron leu; depois de cada bloco comita so
leituras/casa.json e empurra para a main, e o proximo Garimpo o aplica. Dispara
um Garimpo curto (minutos=3) depois do 1o bloco, a cada 4 e no fim, so se
nenhum estiver na fila ou andando. Nunca desliga o workflow.

Para com o alvo esgotado, em --ate, em --maximo, ou no bloqueio: no primeiro
recua 60 min e tenta mais um bloco; no segundo sai com codigo 2, com as
leituras feitas ja comitadas. A regra mora em garimpo/casos/rajada.py.

O banco e proprio (work/rajada/dados.db) e o site e montado em work/rajada/,
nunca em site/: a worktree fica limpa para o pull --rebase, e o dados.db do
checkout principal (antigo, do dono) nao entra.
"""

import argparse
import os
import subprocess
import sys
import time
from dataclasses import dataclass

import varrer
from garimpo.adaptadores.registrobr import PAUSA_SEGURA
from garimpo.casos import pool
from garimpo.casos import rajada as caso
from garimpo.contexto import RAIZ, Contexto


@dataclass
class ContextoDaRajada(Contexto):
    """O de sempre, com banco e site em work/rajada/, fora do git."""

    @property
    def banco(self) -> str:
        return os.path.join(self.trabalho, "rajada", "dados.db")

    @property
    def site(self) -> str:
        return os.path.join(self.trabalho, "rajada")


def executor(programa: str, raiz: str):
    """`programa args` na raiz: (codigo, saida). Sem shell."""
    def rodar(args):
        try:
            p = subprocess.run([programa, *args], cwd=raiz,
                               capture_output=True, text=True)
        except OSError as e:
            return 127, str(e)
        return p.returncode, p.stdout
    return rodar


def argumentos(argv=None):
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--seco", action="store_true",
                    help="so imprime quantos nomes, os 10 primeiros e a hora "
                         "prevista de fim; nao consulta nem comita")
    ap.add_argument("--desde",
                    help="rele quem foi lido antes disto: abertura, "
                         "fechamento, '12 h' ou data ISO (padrao: fechamento "
                         "se a rodada ja fechou, senao abertura)")
    ap.add_argument("--situacao",
                    help="so rele quem tem estas situacoes, separadas por "
                         "virgula (ex.: LIBERACAO_LIVRE); nome sem leitura "
                         "entra sempre")
    ap.add_argument("--ate",
                    help="para nesta hora de Brasilia, HH:MM (a proxima), "
                         "ou numa data ISO")
    ap.add_argument("--maximo", type=int,
                    help="para depois de tantas consultas")
    ap.add_argument("--delay", type=float, default=PAUSA_SEGURA,
                    help="pausa entre consultas; nunca abaixo de "
                         f"{PAUSA_SEGURA}s")
    ap.add_argument("--nota-minima", type=int, default=pool.NOTA_MINIMA)
    ap.add_argument("--teto", type=int, default=pool.TETO_LIBERACAO)
    return ap.parse_args(argv)


def main(argv=None, *, ctx=None, ambiente=None, git=None, gh=None,
         relogio=time.time, dormir=time.sleep, nova_varredura=None) -> int:
    # argparse antes das recusas: o --help roda no Actions (testes.yml)
    args = argumentos(argv)
    ctx = ctx or ContextoDaRajada(raiz=RAIZ)
    ambiente = os.environ if ambiente is None else ambiente
    git = git or executor("git", ctx.raiz)
    gh = gh or executor("gh", ctx.raiz)

    recusa = caso.motivo_para_recusar(ambiente, git)
    if recusa:
        print(f"rajada recusada: {recusa}", file=sys.stderr)
        return caso.RECUSADA

    try:
        situacoes = caso.situacoes_de(args.situacao)
    except ValueError as e:
        print(e, file=sys.stderr)
        return 1

    # o preparar le o instantaneo anterior de ctx.instantaneo: que seja o da
    # origin/main, o mesmo de onde o proximo Garimpo parte
    os.makedirs(ctx.site, exist_ok=True)
    git(["fetch", "-q", "origin", "main"])
    cod, texto = git(["show", "origin/main:site/dados.json"])
    if cod == 0 and texto.strip():
        with open(ctx.instantaneo, "w", encoding="utf-8") as f:
            f.write(texto)

    rodada = varrer.preparar(ctx, args.nota_minima, args.teto)
    agora = int(relogio())
    if varrer.antes_da_abertura(rodada.inicio, agora):
        print(f"a rodada abre em {rodada.inicio}: nenhuma consulta antes disso",
              file=sys.stderr)
        return caso.ANTES_DA_ABERTURA

    try:
        desde = caso.resolver_desde(args.desde, rodada, agora)
        ate = caso.resolver_ate(args.ate, agora)
    except ValueError as e:
        print(e, file=sys.stderr)
        return 1
    if desde is None:
        # sem corte, o alvo seria o pool inteiro, lido ou nao: nunca por acaso
        print("a rodada veio sem data de abertura ou fechamento: passe "
              "--desde com '12h' ou uma data", file=sys.stderr)
        return 1

    if args.seco:
        fila = caso.alvos(ctx.repo.buscar(limite=1_000_000), desde, situacoes)
        if args.maximo is not None:
            fila = fila[:args.maximo]
        if ate is not None and ate <= agora:
            fila = []
        fim = caso.previsao_de_fim(len(fila), args.delay, agora, ate)
        print(f"{len(fila)} nomes sem leitura ou lidos antes de "
              f"{caso.hora_br(desde)}")
        for nome in fila[:10]:
            print(f"  {nome}")
        print(f"fim previsto: {caso.hora_br(fim)} (Brasilia), em blocos de "
              f"{caso.por_bloco(args.delay)} com "
              f"{caso.DESCANSO_SEGUNDOS // 60} min de descanso")
        return caso.OK

    r = caso.Rajada(raiz=ctx.raiz, repo=ctx.repo, cliente=ctx.cliente,
                    rodada=rodada, git=git, gh=gh,
                    relogio=lambda: int(relogio()), dormir=dormir,
                    relatar=lambda m: print(m, flush=True), pausa=args.delay,
                    desde=desde, situacoes=situacoes, ate=ate,
                    maximo=args.maximo, nova_varredura=nova_varredura)
    return r.executar().codigo


if __name__ == "__main__":
    sys.exit(main())
