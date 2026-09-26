#!/usr/bin/env python3
"""
Manutencao do instantaneo, com orcamento de tempo, para o GitHub Actions.

    python3 varrer.py --minutos 7

Diferente do app.py, este script nao guarda nada em disco entre execucoes: o
banco e reconstruido do zero e os resultados anteriores voltam de
site/dados.json, versionado no git. Quem persiste e o JSON.

CADA EXECUCAO

  1. baixa as tres listas oficiais. A de leiloes e refeita pelo Registro.br
     durante a rodada: quem esta nela vira COMPETITIVO na hora, sem consulta.
  2. monta a fila por frescor (garimpo/dominio/frescor.py): primeiro quem
     vai passar do prazo prometido antes da proxima execucao, o mais
     atrasado na frente; depois os nunca verificados; depois o resto.
  3. consulta ate o orcamento acabar e regera o site. Um bloqueio que
     sobrevive ao recuo de 120 s, ou 10 erros seguidos, encerram a
     varredura na hora (barrada, 19/09/2026); o site sai do mesmo jeito.

Leituras feitas fora do GitHub (leituras/casa.json, no formato do
dados.json) entram depois do instantaneo, e a mais nova de cada nome vence
(19/09/2026). A pasta nao vai ao repositorio publico.

Entre a saida da lista e a abertura da rodada (de 12/10 a 14/10, 15h, em
outubro) o passo 3 so regera o site, sem consultar: o nome travado deve
responder status 5 (medido so depois do fechamento, S16; a confirmar no dia
da lista, 12/10) e, qualquer que seja o status, a leitura nao diz nada da
disputa. Aberta a rodada, as leituras
de antes dela sao apagadas e voltam para a fila (18/09/2026).

Antes eram dois modos, "backlog" e "vigia". A vigia desempatava por nota, o
empate era permanente, e 51 nomes nunca mais foram consultados. `--modo`
ainda aceita os nomes antigos, mas todos fazem a mesma coisa.

Sobre o ritmo, ver a nota em garimpo/adaptadores/registrobr.py. O piso de 2s
e rigido: num runner o IP e compartilhado e acelerar respinga em terceiros.
"""

import argparse
import dataclasses
import json
import os
import time

import exportar_site
from garimpo.adaptadores.registrobr import PAUSA_SEGURA
from garimpo.adaptadores.repositorio import agora
from garimpo.casos import instantaneo, manutencao, pool, todos
from garimpo.casos.varredura import Varredura
from garimpo.contexto import padrao
from garimpo.dominio import frescor


def _reaproveitar_leilao(rodada, anterior: dict | None):
    """
    Quando `rodada.em_leilao_lido` e False, a lista de leiloes nao pode
    dizer quem esta em leilao agora. Reconstroi o conjunto a partir do
    instantaneo anterior, mas so se ele for da mesma rodada (fim igual):
    de uma rodada para outra a lista de leiloes zerada e o dado certo, nao
    uma perda.

    Devolve (rodada, reaproveitado: bool). Sem instantaneo aproveitavel,
    devolve `rodada` como veio (em_leilao vazio) e reaproveitado=False, para
    quem chama saber que nao ha nada para proteger.
    """
    if rodada.em_leilao_lido:
        return rodada, False
    fim_anterior = ((anterior or {}).get("rodada") or {}).get("fim")
    if not (anterior and fim_anterior and rodada.fim and fim_anterior == rodada.fim):
        return rodada, False
    em_leilao = {c.dominio for c in instantaneo.candidatos_de(anterior) if c.em_leilao}
    return dataclasses.replace(rodada, em_leilao=em_leilao,
                               em_leilao_em=anterior.get("em_leilao_em")), True


def antes_da_abertura(inicio: str | None, agora_epoch: int) -> bool:
    """
    A lista da rodada ja saiu e a rodada ainda nao abriu (18/09/2026)?

    Nessa janela (de 12/10 a 14/10, 15h, em outubro) nao se consulta: o nome
    travado deve responder status 5 (medido so depois do fechamento, S16; a
    confirmar no dia da lista, 12/10) e, qualquer que seja o status, a
    leitura nao diz nada sobre a disputa que vai comecar. Inicio desconhecido conta como aberta, para nao parar a
    varredura por falta de dado. Depois do fim a varredura segue: os
    leiloes acabam 24 h depois e o desfecho precisa das leituras.
    """
    comeco = frescor.epoch(inicio)
    return comeco is not None and agora_epoch < comeco


def aplicar_leituras_de_casa(ctx, rodada, diga) -> int:
    """
    Repoe as leituras de leituras/casa.json, se forem desta rodada.

    O arquivo tem o formato do dados.json (v5): so situacao, contagem,
    idade e a estimativa de chegada de cada nome, nunca numero de ticket.
    De outra rodada (rodada.fim diferente) e ignorado com aviso; ausente,
    em silencio (o repositorio publico nunca o tem). Nome a nome, fica a
    leitura mais nova entre ele, o instantaneo e o banco (repo.restaurar).
    """
    casa = instantaneo.ler(os.path.join(ctx.raiz, "leituras", "casa.json"))
    if not casa:
        return 0
    fim_casa = (casa.get("rodada") or {}).get("fim")
    if not (rodada.fim and fim_casa == rodada.fim):
        diga(f"leituras/casa.json e de outra rodada ({fim_casa}, a atual "
             f"termina em {rodada.fim}): ignorado")
        return 0
    repostos = ctx.repo.restaurar(instantaneo.candidatos_de(casa))
    diga(f"leituras/casa.json: {repostos} nomes com leitura "
         "(a mais nova de cada um vence)")
    return repostos


def preparar(ctx, nota_minima, teto):
    def diga(msg):
        print(f"  {msg}", flush=True)

    print("baixando listas oficiais...", flush=True)
    rodada = ctx.baixar_rodada(diga)

    # Lido antes do pool.montar (18/09/2026, correcao apos revisao): e o
    # pool que decide o em_leilao de cada Candidato a partir de
    # `rodada.em_leilao`, e gravar_pool() sobrescreve a coluna do banco
    # inteira a cada execucao. Se a lista de leiloes veio invalida e isto
    # nao corrigir `rodada` antes, todo mundo grava em_leilao=0 e
    # encerrar_leiloes_fora_da_lista() apaga o COMPETITIVO que ja tinha sido
    # lido -- a run fica verde e publica um site sem nenhum leilao aberto.
    anterior = instantaneo.ler(ctx.instantaneo)
    rodada, leilao_reaproveitado = _reaproveitar_leilao(rodada, anterior)
    if leilao_reaproveitado:
        diga(f"lista de leiloes invalida: reaproveitando {len(rodada.em_leilao)} "
             "leiloes do instantaneo anterior (mesma rodada)")
    elif not rodada.em_leilao_lido:
        diga("lista de leiloes invalida e sem instantaneo da mesma rodada "
             "para reaproveitar; seguindo sem dado de leilao")

    print("carregando dicionarios...", flush=True)
    vocabularios = ctx.vocabularios.carregar(diga)

    print("montando o pool...", flush=True)
    candidatos, resumo = pool.montar(rodada, vocabularios,
                                     nota_minima=nota_minima, teto=teto)

    # a rodada inteira, para a busca do site; deterministico, entao so vira
    # commit quando a lista ou a nota mudam
    tamanho = todos.escrever(todos.montar(rodada, vocabularios),
                             os.path.join(ctx.site, "todos.json"))
    print(f"  todos.json: {rodada.total:,} nomes, {tamanho / 1e6:.1f} MB", flush=True)
    repo = ctx.repo
    repo.gravar_pool(candidatos)
    repo.set_meta("importado_em", agora())
    repo.set_meta("total_liberacao", rodada.total)
    repo.set_meta("total_elegiveis", len(rodada.elegiveis))
    # so publica a contagem quando ela vem de dado real: lida agora ou
    # reaproveitada do instantaneo da mesma rodada, nunca de um "zero" que
    # so significa "a lista de leiloes nao pode ser lida"
    if rodada.em_leilao_lido or leilao_reaproveitado:
        repo.set_meta("total_em_leilao", len(rodada.em_leilao))
    if rodada.em_leilao_em:
        repo.set_meta("em_leilao_em", rodada.em_leilao_em)
    if rodada.inicio:
        repo.set_meta("rodada_inicio", rodada.inicio)
        repo.set_meta("rodada_fim", rodada.fim)

    # A rodada e mensal e a lista muda inteira. Sem esta checagem, o
    # instantaneo da rodada de setembro seria restaurado dentro da rodada de
    # outubro e o site mostraria nomes que ja nao estao em disputa, com a
    # situacao congelada no mes anterior. `anterior` ja foi lido acima, antes
    # do pool.montar, para o reaproveitamento da lista de leiloes.
    reaproveitados = 0
    if anterior:
        fim_anterior = (anterior.get("rodada") or {}).get("fim")
        if fim_anterior and rodada.fim and fim_anterior != rodada.fim:
            print(f"  rodada virou ({fim_anterior} -> {rodada.fim}); "
                  f"comecando do zero", flush=True)
            repo.esquecer_leituras()
        else:
            reaproveitados = repo.restaurar(instantaneo.candidatos_de(anterior))
            # a curva da rodada tambem mora no instantaneo (o banco do
            # runner e refeito a cada execucao)
            repo.restaurar_ritmo(*instantaneo.ritmo_de(anterior))

    # Depois do instantaneo, para a leitura de casa concorrer com a dele, e
    # antes do esquecer e da lista de leiloes, que continuam mandando.
    aplicar_leituras_de_casa(ctx, rodada, diga)

    # Leitura de antes da abertura e de outra fase (18/09/2026): entre a
    # saida da lista e a abertura, o nome travado deve responder status 5
    # (medido so depois do fechamento, S16; a confirmar no dia da lista,
    # 12/10), que o frescor trata como fixo e nunca mais relia. Vale para
    # qualquer status lido antes da abertura. Depois do restaurar, que a
    # repoe, e antes da lista de leiloes, que carimba com a hora da lista.
    if not antes_da_abertura(rodada.inicio, int(time.time())):
        esquecidas = ctx.repo.esquecer_leituras_antes(rodada.inicio)
        if esquecidas:
            diga(f"{esquecidas} leituras de antes da abertura "
                 f"({rodada.inicio}) voltam para a fila")

    # Depois do restaurar, e nao antes: o restaurar repoe a leitura antiga, e
    # e justamente ela que a lista de leiloes, mais nova, precisa corrigir.
    viraram = repo.aplicar_lista_de_leiloes(rodada.em_leilao_em)
    # e o outro sentido: quem saiu da lista teve o leilao encerrado, e a
    # leitura "leilao aberto" ficou velha (17/09/2026). So roda com dado de
    # em_leilao confiavel (lido agora ou reaproveitado): sem isso, `em_leilao`
    # vazio por falta de leitura apagaria todo COMPETITIVO legitimo, do jeito
    # que a revisao de 18/09/2026 pegou.
    sairam = 0
    if rodada.em_leilao_lido or leilao_reaproveitado:
        sairam = repo.encerrar_leiloes_fora_da_lista()

    print(f"pool com {resumo.total} dominios, "
          f"{reaproveitados} resultados reaproveitados, "
          f"{viraram} passaram a leilao pela lista oficial, "
          f"{sairam} sairam dela e voltam para a fila", flush=True)
    return rodada


def gravar_resumo(ctx, alvos: int, tentados: int = 0, erros: int = 0,
                  bloqueios: int = 0, pulada: str | None = None,
                  barrada: bool = False, motivo: str | None = None) -> None:
    """
    work/varredura.json, para o conferir_frescor.py. Este script sai com 0
    mesmo barrado (o site precisa ser regerado e comitado); quem acende o
    alarme e o conferir, que roda por ultimo.

    `feitos` conta so as consultas que deram leitura: o Progresso.feitos
    conta tentativas, e um runner barrado tenta todas e erra todas.

    `pulada` diz por que nao houve varredura de proposito (hoje so
    "antes_da_abertura"), para o alarme nao confundir com barrada.

    `barrada` e `motivo` ("bloqueio" ou "rede") dizem que a varredura parou
    antes da fila acabar (Varredura, 19/09/2026).
    """
    os.makedirs(ctx.trabalho, exist_ok=True)
    with open(os.path.join(ctx.trabalho, "varredura.json"), "w",
              encoding="utf-8") as f:
        json.dump({"alvos": alvos, "tentados": tentados,
                   "feitos": max(0, tentados - erros), "erros": erros,
                   "bloqueios": bloqueios, "pulada": pulada,
                   "barrada": bool(barrada), "motivo": motivo,
                   "gravado_em": agora()}, f)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--modo", choices=("manter", "backlog", "vigia"),
                    default="manter",
                    help="so existe 'manter'; os outros nomes sao aceitos "
                         "por compatibilidade e fazem o mesmo")
    ap.add_argument("--minutos", type=float, default=7.0,
                    help="orcamento de tempo; para quando estourar")
    ap.add_argument("--intervalo-horas", type=float,
                    default=frescor.INTERVALO_HORAS,
                    help="de quanto em quanto tempo o workflow roda; define "
                         "a urgencia e a cota da faixa quente")
    ap.add_argument("--delay", type=float, default=PAUSA_SEGURA,
                    help="pausa entre consultas; nao diminua")
    ap.add_argument("--nota-minima", type=int, default=pool.NOTA_MINIMA)
    ap.add_argument("--teto", type=int, default=pool.TETO_LIBERACAO)
    args = ap.parse_args()

    ctx = padrao
    pausa = max(PAUSA_SEGURA, args.delay)
    # antes de tudo: o prazo dos quentes e a promessa gravada no JSON
    # dependem do intervalo (ver frescor.configurar)
    frescor.configurar(args.intervalo_horas)
    rodada = preparar(ctx, args.nota_minima, args.teto)

    if antes_da_abertura(rodada.inicio, int(time.time())):
        # a lista nova ja foi aplicada acima; o site sai com ela, sem leitura
        print(f"rodada abre em {rodada.inicio}: nenhuma consulta antes disso",
              flush=True)
        gravar_resumo(ctx, 0, pulada="antes_da_abertura")
        exportar_site.main()
        return

    if args.modo != "manter":
        print(f"(--modo {args.modo} e nome antigo: a fila agora e uma so)")

    # com folga, para nunca estourar o limite do runner
    cabem = int(args.minutos * 60 / (pausa + 0.2)) + 5
    alvos = manutencao.alvos(ctx.repo, int(time.time()), cabem,
                             intervalo=int(args.intervalo_horas * 3600),
                             rodada_inicio=frescor.epoch(rodada.inicio))
    if not alvos:
        # a lista de leiloes ja pode ter mudado alguem: publica mesmo assim
        print("nada para verificar")
        gravar_resumo(ctx, 0)
        exportar_site.main()
        return

    print(f"ate {len(alvos)} dominios em {args.minutos:.0f} min, "
          f"{pausa}s entre consultas", flush=True)

    varredura = Varredura(ctx.cliente, ctx.repo, contador=ctx.contador,
                          relatar=lambda m: print(f"  {m}", flush=True))
    p = varredura.executar(alvos, pausa=pausa, prazo=args.minutos * 60)

    ctx.repo.set_meta("verificado_em", agora())
    print(f"\n{p.feitos} verificados, {len(p.mudancas)} mudancas, "
          f"{p.erros} erros, {p.bloqueios} bloqueios", flush=True)
    gravar_resumo(ctx, len(alvos), p.feitos, p.erros, p.bloqueios,
                  barrada=p.barrada, motivo=p.motivo)

    exportar_site.main()

    if p.barrada:
        print(f"\nvarredura barrada ({p.motivo}): a proxima execucao retoma "
              "pela fila", flush=True)
    elif p.bloqueios:
        print("\nhouve bloqueio: se repetir, aumente o --delay", flush=True)


if __name__ == "__main__":
    main()
