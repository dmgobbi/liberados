"""
Situacao de um dominio no processo de liberacao.

Camada de dominio: funcoes puras, sem rede e sem banco. Recebe o dicionario
cru que o Registro.br devolve e responde o que aquilo significa.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class Situacao(str, Enum):
    """
    O estado de um dominio. Herda de str para continuar serializavel em JSON
    e comparavel com as strings que as versoes anteriores gravaram no banco.
    """

    LIVRE = "LIVRE"
    LIBERACAO_LIVRE = "LIBERACAO_LIVRE"
    LIBERACAO_DISPUTADA = "LIBERACAO_DISPUTADA"
    COMPETITIVO = "COMPETITIVO"
    REGISTRADO = "REGISTRADO"
    LIMITADO = "LIMITADO"
    ERRO = "ERRO"
    INDESCONHECIDO = "INDESCONHECIDO"
    # Os tres abaixo vieram da especificacao oficial do ISAVAIL (12/09/2026).
    # Ate entao o codigo lia o status como bitmask, e o 5 caia em
    # LIBERACAO_LIVRE: um nome que espera a PROXIMA rodada apareceria como
    # "em liberacao, sem candidato", que e exatamente a mentira que gerou as
    # 28 joias falsas de 10/09.
    AGUARDANDO_LIBERACAO = "AGUARDANDO_LIBERACAO"   # status 5
    INDISPONIVEL = "INDISPONIVEL"                   # status 3
    LIVRE_COM_TICKET = "LIVRE_COM_TICKET"           # status 1

    @property
    def rotulo(self) -> str:
        return _ROTULOS[self]

    @property
    def resolvida(self) -> bool:
        """True quando a resposta e um fato sobre o dominio, nao uma falha."""
        return self not in (Situacao.LIMITADO, Situacao.ERRO,
                            Situacao.INDESCONHECIDO)


_ROTULOS = {
    Situacao.LIVRE: "Livre para registro",
    Situacao.LIBERACAO_LIVRE: "Em liberacao, sem candidato visivel",
    Situacao.LIBERACAO_DISPUTADA: "Em liberacao, disputado",
    Situacao.COMPETITIVO: "Leilao em andamento",
    Situacao.REGISTRADO: "Registrado",
    Situacao.LIMITADO: "Bloqueado por excesso de consultas",
    Situacao.ERRO: "Erro na consulta",
    Situacao.INDESCONHECIDO: "Resposta em formato inesperado",
    Situacao.AGUARDANDO_LIBERACAO: "Aguardando a proxima rodada de liberacao",
    Situacao.INDISPONIVEL: "Indisponivel para registro",
    Situacao.LIVRE_COM_TICKET: "Fora da rodada, mas com pedido pendente",
}


# ---------------------------------------------------------------------------
# O campo "status" e uma ENUMERACAO, nao um bitmask.
#
# Ate 11/09/2026 este modulo lia o status como quatro bits (1 tickets,
# 2 existe, 4 liberacao, 8 competitivo), decodificados por sondagem. Os
# valores observados (0, 2, 3, 6, 7, 8, 9) batiam com essa leitura por
# coincidencia. Em 12/09/2026 a especificacao oficial apareceu no FTP do
# Registro.br (ftp.registro.br/pub/isavail/, Protocolo-ISAVAIL.txt): o
# endpoint web e o proxy do servico ISAVAIL, e a tabela e esta:
#
#   0  disponivel
#   1  disponivel, mas com tickets concorrentes (pedido pendente fora da rodada)
#   2  registrado
#   3  indisponivel (vem o motivo)
#   4  consulta invalida
#   5  aguardando processo de liberacao   <- o bitmask lia como 4|1
#   6  em liberacao
#   7  em liberacao, com tickets
#   8  erro (inclusive "taxa maxima de consultas excedida")
#   9  em processo competitivo
#
# Documentado em docs/api-registrobr.md e docs/fontes-oficiais-registrobr.md.
# ---------------------------------------------------------------------------
STATUS_DISPONIVEL = 0
STATUS_COM_TICKET = 1
STATUS_REGISTRADO = 2
STATUS_INDISPONIVEL = 3
STATUS_CONSULTA_INVALIDA = 4
STATUS_AGUARDANDO = 5
STATUS_LIBERACAO = 6
STATUS_LIBERACAO_COM_TICKETS = 7
STATUS_ERRO = 8
STATUS_COMPETITIVO = 9

_POR_STATUS = {
    STATUS_DISPONIVEL: Situacao.LIVRE,
    STATUS_COM_TICKET: Situacao.LIVRE_COM_TICKET,
    STATUS_REGISTRADO: Situacao.REGISTRADO,
    STATUS_INDISPONIVEL: Situacao.INDISPONIVEL,
    STATUS_AGUARDANDO: Situacao.AGUARDANDO_LIBERACAO,
    STATUS_LIBERACAO: Situacao.LIBERACAO_LIVRE,
    STATUS_LIBERACAO_COM_TICKETS: Situacao.LIBERACAO_DISPUTADA,
    STATUS_COMPETITIVO: Situacao.COMPETITIVO,
}


@dataclass(frozen=True)
class Leitura:
    """O que uma consulta ao Registro.br disse sobre um dominio."""

    situacao: Situacao
    candidatos: int = 0
    detalhe: str = ""
    status_bruto: int | None = None
    # os numeros dos tickets, como vieram (no maximo 10): alimentam o ritmo
    # da rodada (dominio/ritmo.py). Nunca vao para o site.
    tickets: tuple[int, ...] = ()

    @property
    def limitado(self) -> bool:
        return self.situacao is Situacao.LIMITADO

    @property
    def cortado(self) -> bool:
        """O avail devolve no maximo 10 tickets: com 10, pode haver mais."""
        return len(self.tickets) >= CORTE_TICKETS


# o avail (e o ISAVAIL, por especificacao) listam no maximo 10 tickets
CORTE_TICKETS = 10

# campos da resposta que valem guardar como detalhe legivel
_CAMPOS_DETALHE = (
    "ends-at",
    "accepting-new-tickets-until",
    "publication-status",
    "expires-at",
)


def _e_recusa_por_limite(motivos: list) -> bool:
    for m in motivos:
        texto = str(m).lower()
        if ("axa" in texto and "consulta" in texto) or "rate limit" in texto:
            return True
    return False


def classificar(payload) -> Leitura:
    """
    Traduz a resposta crua do endpoint de disponibilidade.

    A ordem das checagens aqui NAO e arbitraria. O bloqueio por excesso de
    consultas volta com HTTP 200 e `status: 8` no corpo. Classificar pelo
    numero antes de descartar respostas de erro transforma cada bloqueio num
    falso "dominio em leilao" (a leitura antiga por bits fazia 8 = leilao):
    foi assim que 370 nomes foram rotulados errado em 09/09/2026.
    """
    if not isinstance(payload, dict):
        return Leitura(Situacao.ERRO, detalhe="resposta nao e json")

    bruto = payload.get("status")
    motivos = payload.get("reasons") or []
    if motivos:
        texto = "; ".join(str(m) for m in motivos)
        if bruto == STATUS_INDISPONIVEL:
            # "ja registrado sob sintaxe similar", "reservado para a
            # transicao EDU.BR"...: e um fato sobre o nome, nao uma falha
            return Leitura(Situacao.INDISPONIVEL, detalhe=texto,
                           status_bruto=bruto)
        alvo = Situacao.LIMITADO if _e_recusa_por_limite(motivos) else Situacao.ERRO
        return Leitura(alvo, detalhe=texto, status_bruto=bruto)

    tickets = tuple(int(t) for t in payload.get("tickets") or []
                    if isinstance(t, int) or str(t).isdigit())
    candidatos = len(tickets)

    if not isinstance(bruto, int):
        return Leitura(Situacao.INDESCONHECIDO, candidatos,
                       f"status={bruto!r}")

    # rede de seguranca: a forma exata do bloqueio, caso um dia venha sem o
    # campo "reasons". Resposta valida sempre traz o fqdn preenchido.
    if bruto == STATUS_ERRO:
        if not payload.get("fqdn") and not candidatos:
            return Leitura(Situacao.LIMITADO, detalhe="sem fqdn, provavel limite",
                           status_bruto=bruto)
        return Leitura(Situacao.ERRO, detalhe="status 8 sem motivo",
                       status_bruto=bruto)
    if bruto == STATUS_CONSULTA_INVALIDA:
        return Leitura(Situacao.ERRO, detalhe="consulta invalida",
                       status_bruto=bruto)

    situacao = _POR_STATUS.get(bruto, Situacao.INDESCONHECIDO)
    detalhe = "; ".join(f"{c}={payload[c]}" for c in _CAMPOS_DETALHE
                        if payload.get(c))
    if situacao is Situacao.INDESCONHECIDO:
        detalhe = f"status={bruto}"

    # O endpoint SO informa tickets quando ha mais de um candidato. Esta
    # documentado pelo proprio Registro.br:
    #
    #   "A interface de verificacao de disponibilidade de dominios
    #    somente informara que existem tickets para um dominio em
    #    processo de liberacao caso este possua mais de um candidato."
    #
    # Logo LIBERACAO_LIVRE quer dizer "zero ou um candidato", nunca
    # "zero" com certeza. Ver docs/processo-de-liberacao.md.
    return Leitura(situacao, candidatos, detalhe, bruto, tickets)


def com_leilao_anunciado(situacao: Situacao | None,
                         em_leilao: bool) -> Situacao | None:
    """
    A situacao que vale, somando a leitura com a lista oficial de leiloes.

    `lista-competicao.txt` e regerada pelo Registro.br durante a rodada, e a
    varredura a baixa inteira a cada execucao. Uma consulta individual pode
    ter dias; a lista tem minutos. Quando as duas discordam, a lista manda:
    nome que esta nela tem leilao acontecendo, seja la o que a ultima
    consulta viu.

    Regressao de 10/09/2026: as 28 "joias" do site ja estavam na lista (a
    coluna em_leilao dizia 1), mas a tela so olhava a leitura de 30 horas
    antes, e mostrava leilao aberto como "sem competicao".
    """
    if em_leilao and situacao in (Situacao.LIBERACAO_LIVRE,
                                  Situacao.LIBERACAO_DISPUTADA):
        return Situacao.COMPETITIVO
    return situacao


def situacao_de(texto: str | None) -> Situacao:
    """Converte o texto gravado no banco de volta para o enum."""
    if not texto:
        return Situacao.INDESCONHECIDO
    try:
        return Situacao(texto)
    except ValueError:
        return Situacao.INDESCONHECIDO
