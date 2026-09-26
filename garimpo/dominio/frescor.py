"""
Frescor: por quanto tempo cada dado pode valer sem nova consulta, e quem
consultar primeiro.

Camada de dominio: funcoes puras, sem rede e sem banco. Recebe o que se sabe
de cada dominio e a hora atual, devolve a fila.

POR QUE EXISTE (10/09/2026)

A vigia antiga ordenava por "verificado ha mais tempo, depois nota". Como o
banco na nuvem e reconstruido a cada execucao e todos os itens voltavam com
o mesmo carimbo, o primeiro criterio sempre empatava e so a nota decidia.
Cabiam 195 consultas, a fila tinha 246, e os 51 de nota mais baixa nunca
mais foram consultados. Entre eles estavam as 28 joias do site, todas ja em
leilao. O site mostrava dado de 30 horas como se fosse de agora.

A licao tem duas metades:

1. Todo fato carrega a propria idade. Nao existe "o instantaneo e de 20h34";
   existe "este nome foi consultado as 14h02".
2. Cada classe de dado tem uma PROMESSA de idade maxima, e a fila e montada
   para cumprir a promessa, nao por ordem de importancia. Ordem de
   importancia, com orcamento menor que a fila, abandona o fim da fila para
   sempre.

A POLITICA, em faixas, nesta ordem:

  0. LEILAO vencido (passou das 48 h), o mais velho primeiro, ate a cota
     leiloes x intervalo / 48 h (160 x 4 / 48 = 14 por execucao).
  1. QUENTE, o mais velho primeiro. Nunca verificado conta como
     infinitamente velho. Quantos: o maior entre
       - os urgentes: quem passaria do prazo antes da proxima execucao;
       - a cota de rodizio: quentes x intervalo / prazo (200 x 4 h / 8 h =
         100 por execucao), para a carga ficar espalhada.
     Quem ficou de fora so envelhece, entao sobe na fila. Ninguem e
     esquecido.
  2. Fila: nunca verificados, melhor nota primeiro.
  3. O resto, mais antigo primeiro.

POR QUE O LEILAO FOI PARA A FRENTE (16/09/2026): ele ficava no fim, atras
da fila de nunca verificados. Com a rodada fechada, todo nome que entra na
faixa quente chega com leitura de dias, os 200 vencem juntos e comem as ~190
vagas; os 160 leiloes chegaram a 143 h sem consulta, com prazo de 48 h e sem
alarme. Leilao acaba 24 h depois do fechamento e so uma leitura diz que ele
virou REGISTRADO. A cota, sem o termo dos urgentes, evita que 160 leiloes
com o mesmo carimbo levem uma execucao inteira da rodada aberta.

POR QUE A COTA (achado em revisao, antes de publicar): a primeira versao
chamava de "vencido" quem chegaria ao prazo ate a proxima execucao, com
`>=`. Com prazo de 8 h e execucao a cada 4 h, um nome consultado na
execucao anterior ja tinha 4 + 4 >= 8: TODO quente vencia em TODA execucao,
a faixa quente comia as ~190 vagas, e a fila de nunca verificados nunca
andava. Pior: o alarme ficava verde, porque os quentes estavam frescos.
Urgencia estrita (> prazo) conserta isso, mas sozinha deixa a carga em
rajadas: quentes que comecam com o mesmo carimbo vencem todos juntos, e a
cada duas execucoes uma leva inteira passaria do prazo. A cota tira a
rajada.

POR QUE A LEITURA DE ANTES DA ABERTURA NAO CONTA (18/09/2026): entre a
saida da lista (12/10) e a abertura (14/10, 15h), um nome travado deve
responder status 5, AGUARDANDO_LIBERACAO, que e FIXO (medido so depois do
fechamento, S16; a confirmar no dia da lista, 12/10). A regra vale para
qualquer status lido antes da abertura, porque a leitura e de outra fase.
Sem esta regra, os nomes lidos
nessa janela (os elegiveis, que a faixa quente poe na frente) nunca mais
eram relidos: a simulacao deu 0 de 2.500 na fila da rodada inteira. Por
isso `classificar` e `escolher` recebem `rodada_inicio` e tratam a leitura
anterior a ele como se nao existisse: o nome volta a fila dos nunca
verificados, pela nota. O varrer.py tambem deixou de consultar antes da
abertura e apaga essas leituras do banco na primeira execucao depois dela.

Quem esta em LEILAO nao precisa de consulta individual para a situacao: a
lista oficial de leiloes e baixada a cada execucao e ja diz isso. A consulta
so atualiza a contagem de tickets, que e informativa.
"""

from __future__ import annotations

import dataclasses
import math
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum

from .situacao import Situacao, com_leilao_anunciado


class Classe(str, Enum):
    QUENTE = "quente"
    LEILAO = "leilao"
    FRIO = "frio"
    FIXO = "fixo"


# A ordem define os indices gravados no JSON. Acrescente no fim.
CLASSES = (Classe.QUENTE, Classe.LEILAO, Classe.FRIO, Classe.FIXO)

# Idade maxima prometida, em horas. None e "sem promessa": o dado aparece com
# a idade que tem, mas a ferramenta nao se compromete a renova-lo.
PRAZOS: dict[Classe, float | None] = {
    Classe.QUENTE: 2,       # = RAZAO_PRAZO_INTERVALO x INTERVALO_HORAS; ver configurar()
    Classe.LEILAO: 48,
    Classe.FRIO: None,
    Classe.FIXO: None,
}

ROTULOS = {
    Classe.QUENTE: "nomes em disputa ou no topo da lista",
    Classe.LEILAO: "leilão aberto (a situação vem da lista oficial)",
    Classe.FRIO: "o restante, reconsultado quando sobra tempo",
    Classe.FIXO: "já saiu da rodada (registrado ou livre)",
}

# Casa com o cron do .github/workflows/garimpo.yml. Entra em duas contas da
# faixa quente: o que passaria do prazo antes da PROXIMA execucao ja entra
# nesta, e a cota de rodizio e quentes x intervalo / prazo.
#
# De 4 h para 1 h em 12/09/2026, quando o repositorio publico deu minutos
# ilimitados. O prazo dos quentes acompanhou, de 8 h para 2 h: a razao
# prazo/intervalo continua 2, entao a cota de rodizio segue em metade da
# faixa por execucao e cada quente e reconsultado a cada duas execucoes.
#
# Desde 12/09/2026 (noite) o intervalo e decidido pelo workflow conforme o
# repositorio e publico (1 h) ou privado (4 h, para caber nos 2.000 minutos
# do plano Free), e chega aqui por `configurar()`. O prazo dos quentes segue
# a razao, entao o alarme do conferir_frescor.py continua honesto nos dois.
INTERVALO_HORAS = 1
RAZAO_PRAZO_INTERVALO = 2


def configurar(intervalo_horas: float) -> None:
    """
    Ajusta o intervalo entre execucoes e, com ele, o prazo dos quentes.

    Chamado uma vez, no inicio do varrer.py. Muda estado de modulo de
    proposito: `tabela()` grava a promessa no JSON, e o exportador roda no
    mesmo processo, entao o site e o alarme leem o prazo que valeu.
    """
    global INTERVALO_HORAS
    INTERVALO_HORAS = intervalo_horas
    PRAZOS[Classe.QUENTE] = RAZAO_PRAZO_INTERVALO * intervalo_horas

# Quantos nomes cabem na faixa quente. Uma execucao de 15 min faz ~420
# consultas; 200 nomes com prazo de 2 h e execucao a cada 1 h pedem ~100 por
# execucao, e sobra o resto para a fila e para o frio. Passando disso a
# promessa nao fecha, e o alarme do conferir_frescor.py avisa.
LIMITE_QUENTE = 200

_EM_LIBERACAO = (Situacao.LIBERACAO_LIVRE, Situacao.LIBERACAO_DISPUTADA, None)
_FORA_DA_RODADA = (Situacao.REGISTRADO, Situacao.LIVRE, Situacao.INDISPONIVEL,
                   Situacao.AGUARDANDO_LIBERACAO, Situacao.LIVRE_COM_TICKET)


@dataclass(frozen=True)
class Item:
    """O minimo que o frescor precisa saber de um dominio."""

    dominio: str
    situacao: Situacao | None = None
    elegivel: bool = False
    em_leilao: bool = False
    candidatos: int | None = None
    nota: int = 0
    verificado_em: int | None = None     # segundos desde 1970, UTC


# --------------------------------------------------------------------- tempo

def epoch(iso: str | None) -> int | None:
    """
    ISO 8601 com qualquer fuso -> segundos UTC.

    Existe porque o banco guarda texto com fuso local: -03:00 na maquina de
    casa, +00:00 no runner. Ordenar esse texto como string poe
    "22:00-03:00" (01:00 UTC) antes de "00:30+00:00", ao contrario do real.
    Comparar sempre em segundos resolve.
    """
    if not iso:
        return None
    try:
        quando = datetime.fromisoformat(str(iso).replace("Z", "+00:00"))
    except ValueError:
        return None
    if quando.tzinfo is None:
        quando = quando.replace(tzinfo=timezone.utc)
    return int(quando.timestamp())


def iso_utc(segundos: int) -> str:
    return datetime.fromtimestamp(segundos, timezone.utc).isoformat(
        timespec="seconds")


# -------------------------------------------------------------- classificacao

def _prioridade_quente(item: Item) -> tuple:
    """
    Quem disputa as vagas da faixa quente, do mais para o menos urgente.

    Elegivel fora do leilao vem primeiro: e a joia, o que a pagina destaca.
    Depois o disputado, cuja contagem muda. Depois o topo por nota, que e o
    que aparece na primeira pagina de "sem competicao".
    """
    if item.elegivel:
        grupo = 0
    elif (item.candidatos or 0) > 0:
        grupo = 1
    else:
        grupo = 2
    return (grupo, -item.nota, len(item.dominio), item.dominio)


def _sem_leitura_de_antes(itens: list[Item],
                          rodada_inicio: int | None) -> list[Item]:
    """
    A leitura anterior a abertura da rodada nao vale depois dela (ver POR QUE
    A LEITURA DE ANTES DA ABERTURA NAO CONTA, no alto do modulo): o item volta
    como nunca verificado. `em_leilao` fica, porque vem da lista de agora.
    """
    if rodada_inicio is None:
        return itens
    return [dataclasses.replace(i, situacao=None, candidatos=None,
                                verificado_em=None)
            if i.verificado_em is not None and i.verificado_em < rodada_inicio
            else i
            for i in itens]


def classificar(itens: list[Item],
                limite_quente: int = LIMITE_QUENTE, *,
                rodada_inicio: int | None = None) -> dict[str, Classe]:
    itens = _sem_leitura_de_antes(itens, rodada_inicio)
    classes: dict[str, Classe] = {}
    em_liberacao: list[Item] = []
    for item in itens:
        situacao = com_leilao_anunciado(item.situacao, item.em_leilao)
        if situacao in _FORA_DA_RODADA:
            classes[item.dominio] = Classe.FIXO
        elif situacao is Situacao.COMPETITIVO:
            classes[item.dominio] = Classe.LEILAO
        elif situacao in _EM_LIBERACAO:
            em_liberacao.append(item)
        else:
            classes[item.dominio] = Classe.FRIO

    em_liberacao.sort(key=_prioridade_quente)
    for posicao, item in enumerate(em_liberacao):
        classes[item.dominio] = (Classe.QUENTE if posicao < limite_quente
                                 else Classe.FRIO)
    return classes


# ------------------------------------------------------------------- a fila

def idade(item: Item, agora: int) -> float:
    if item.verificado_em is None:
        return math.inf
    return max(0, agora - item.verificado_em)


def vencido(item: Item, classe: Classe, agora: int, horizonte: int = 0) -> bool:
    """
    Vai PASSAR do prazo da classe antes de `agora + horizonte`?

    Estrito de proposito: chegar exatamente no prazo e cumprir a promessa.
    Com `>=`, o que foi consultado na execucao anterior ja contava como
    vencido (ver POR QUE A COTA, no alto do modulo).
    """
    prazo = PRAZOS[classe]
    if prazo is None:
        return False
    return idade(item, agora) + horizonte > prazo * 3600


def rodada_aberta(inicio: str | None, fim: str | None, agora: int) -> bool:
    """
    A promessa dos quentes so vale com a rodada aberta (16/09/2026).

    Fechada a rodada, nenhum nome esta mais em disputa: cada execucao troca
    os quentes que viraram LIVRE ou REGISTRADO por nomes de leitura antiga,
    e o alarme ficaria vermelho ate a rodada seguinte sem nada a consertar.
    Janela desconhecida conta como aberta, para o alarme errar do lado
    barulhento.
    """
    comeco, final = epoch(inicio), epoch(fim)
    if comeco is None or final is None:
        return True
    return comeco <= agora <= final


def escolher(itens: list[Item], agora: int, capacidade: int, *,
             intervalo: int = INTERVALO_HORAS * 3600,
             limite_quente: int = LIMITE_QUENTE,
             rodada_inicio: int | None = None) -> list[str]:
    """
    Os dominios a consultar nesta execucao, em ordem.

    `rodada_inicio` (segundos UTC) e a abertura da rodada da lista atual:
    leitura anterior a ela conta como nenhuma leitura.
    """
    itens = _sem_leitura_de_antes(itens, rodada_inicio)
    classes = classificar(itens, limite_quente)

    todos_leiloes = sorted(
        (i for i in itens if classes[i.dominio] is Classe.LEILAO
         and vencido(i, Classe.LEILAO, agora)),
        key=lambda i: (-idade(i, agora), i.dominio))
    n_leiloes = sum(1 for i in itens if classes[i.dominio] is Classe.LEILAO)
    cota_leiloes = math.ceil(n_leiloes * intervalo / (PRAZOS[Classe.LEILAO] * 3600))
    leiloes = todos_leiloes[:cota_leiloes]
    ja = {i.dominio for i in leiloes}

    # o mais velho primeiro; os urgentes ficam necessariamente na frente
    todos_quentes = sorted(
        (i for i in itens if classes[i.dominio] is Classe.QUENTE),
        key=lambda i: (-idade(i, agora), -i.nota, i.dominio))
    urgentes = sum(1 for i in todos_quentes
                   if vencido(i, Classe.QUENTE, agora, intervalo))
    prazo = PRAZOS[Classe.QUENTE] * 3600
    cota = math.ceil(len(todos_quentes) * intervalo / prazo)
    quentes = todos_quentes[:max(urgentes, cota)]
    ja |= {i.dominio for i in quentes}

    fila = sorted(
        (i for i in itens if i.verificado_em is None and i.dominio not in ja
         and classes[i.dominio] is not Classe.FIXO),
        key=lambda i: (-i.nota, len(i.dominio), i.dominio))
    ja |= {i.dominio for i in fila}

    resto = sorted(
        (i for i in itens if i.dominio not in ja
         and classes[i.dominio] in (Classe.LEILAO, Classe.FRIO)),
        key=lambda i: (-idade(i, agora), i.dominio))

    return [i.dominio for i in (leiloes + quentes + fila + resto)][:max(0, capacidade)]


def tabela() -> dict:
    """As promessas, para o JSON: a pagina explica a partir daqui."""
    return {
        "intervalo_horas": INTERVALO_HORAS,
        "limite_quente": LIMITE_QUENTE,
        "classes": [{"nome": c.value, "prazo_horas": PRAZOS[c],
                     "rotulo": ROTULOS[c]} for c in CLASSES],
    }
