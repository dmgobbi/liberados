"""
O calendario do processo de liberacao: quando a rodada abre, quando a lista
sai e quando um dominio vencido deve voltar ao mercado.

Camada de dominio: funcoes puras, sem rede e sem disco.

A REGRA (oficial, docs/processo-de-liberacao.md): a rodada abre na segunda
quarta-feira do mes, as 15h de Brasilia, e dura 7 dias; a lista de nomes sai
2 dias antes. O Registro.br pode mexer numa data por feriado, entao toda
data que o site mostra sai daqui a cada build e o texto em volta diz que e
pela regra.

A PREVISAO DE VOLTA (medida, nao oficial; limitacao S14): nenhuma pagina do
Registro.br diz quanto tempo um dominio vencido leva ate a lista. A serie
historica diz. Entre passagens do mesmo nome pela lista (70.450 intervalos
de nomes que passaram 5 vezes ou mais, 2017 a 2026), o intervalo mais comum
e 5 meses (17 de cada 100), depois 6 (8 de cada 100), e o padrao se repete
um ano depois (17 e 18 meses). Um nome registrado numa rodada e nao pago
vence no proprio registro; por isso "5 meses depois do vencimento" e a
rodada mais provavel, e a seguinte e a segunda chance. A previsao e sempre
uma janela de duas rodadas, nunca uma data.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

BRASILIA = timezone(timedelta(hours=-3))
HORA_ABERTURA = 15
DIAS_ABERTA = 7
DIAS_LISTA_ANTES = 2
MESES_ATE_A_LISTA = 5       # o pico da serie historica (S14)


def _somar_meses(ano: int, mes: int, n: int) -> tuple[int, int]:
    total = ano * 12 + (mes - 1) + n
    return total // 12, total % 12 + 1


def abertura(ano: int, mes: int) -> datetime:
    """Segunda quarta-feira do mes, 15h de Brasilia."""
    primeiro = date(ano, mes, 1)
    quarta = 1 + (2 - primeiro.weekday()) % 7          # weekday 2 = quarta
    return datetime(ano, mes, quarta + 7, HORA_ABERTURA, tzinfo=BRASILIA)


def fechamento(abre: datetime) -> datetime:
    return abre + timedelta(days=DIAS_ABERTA)


def saida_da_lista(abre: datetime) -> date:
    return (abre - timedelta(days=DIAS_LISTA_ANTES)).date()


def proxima_abertura(depois_de: datetime) -> datetime:
    """A primeira abertura estritamente depois do instante dado."""
    if depois_de.tzinfo is None:
        depois_de = depois_de.replace(tzinfo=BRASILIA)
    local = depois_de.astimezone(BRASILIA)
    candidata = abertura(local.year, local.month)
    if candidata > depois_de:
        return candidata
    return abertura(*_somar_meses(local.year, local.month, 1))


def mes_seguinte(inicio: datetime) -> datetime:
    """A abertura do mes seguinte ao de uma rodada."""
    local = inicio.astimezone(BRASILIA) if inicio.tzinfo else inicio
    return abertura(*_somar_meses(local.year, local.month, 1))


def mes_anterior(inicio: datetime) -> datetime:
    """A abertura do mes anterior ao de uma rodada."""
    local = inicio.astimezone(BRASILIA) if inicio.tzinfo else inicio
    return abertura(*_somar_meses(local.year, local.month, -1))


def previsao_de_volta(vencimento: date) -> tuple[datetime, datetime]:
    """
    As duas rodadas em que um dominio que vence nessa data e nao e renovado
    deve aparecer: a mais provavel (5 meses depois) e a seguinte.
    """
    ano, mes = _somar_meses(vencimento.year, vencimento.month, MESES_ATE_A_LISTA)
    return abertura(ano, mes), abertura(*_somar_meses(ano, mes, 1))


def aberturas(referencia: date, meses_antes: int, meses_depois: int) -> list[str]:
    """
    As datas de abertura, AAAA-MM-DD, de `meses_antes` meses antes do mes de
    referencia ate `meses_depois` meses depois. E o que o build entrega ao
    navegador: a regra mora aqui, e o JavaScript so escolhe na lista.
    """
    datas = []
    for n in range(-meses_antes, meses_depois + 1):
        ano, mes = _somar_meses(referencia.year, referencia.month, n)
        datas.append(abertura(ano, mes).date().isoformat())
    return datas
