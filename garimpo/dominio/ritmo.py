"""
O ritmo do registro, lido nos numeros de ticket.

Os tickets do Registro.br sao um contador global e sequencial: o ticket
90001001 foi emitido antes do 90001002, seja la para que nome. E nao so da
liberacao: a especificacao EPP (brdomain, secao 2.1) define o ticket como o
identificador sequencial de TODO pedido de registro .br, e a resposta de
todo domain:create traz o ticketNumber (secao 3.2.1). Duas consequencias que
ninguem publica:

1. O MAIOR ticket visto ate agora menos o primeiro da rodada e quantos
   tickets o Registro.br emitiu no periodo, de todos os tipos. E um TETO
   para as candidaturas da rodada, nao o numero delas (em 12/09/2026: 24.785
   no contador contra 1.187 tickets visiveis em 15.167 nomes conferidos).
   Observado ao longo dos dias, vira a curva de pedidos do .br; se empinar no
   ultimo dia da rodada, a diferenca e a corrida pelos nomes liberados.
2. Os tickets de UM nome dizem quando os concorrentes chegaram. Menor ticket
   = o primeiro; maior visivel = o ultimo (o avail corta em 10, entao o
   maior de verdade pode estar escondido). Um nome cujos dois candidatos
   chegaram na primeira hora e um nome que ganhou tres no ultimo dia sao
   historias diferentes, e so o numero conta.

A serie de calibracao e uma lista de pontos (epoch, ticket), os dois
crescentes: em tal instante, o maior ticket que ja tinhamos visto era tal.
A varredura acrescenta um ponto toda vez que ve um ticket maior. Cada ponto
e um limite: aquele ticket foi emitido ANTES daquele instante. A estimativa
de quando um ticket foi emitido interpola entre os dois pontos que o
cercam. E uma estimativa por cima (o ticket pode ter sido emitido bem antes
de a gente ve-lo), e melhora com a densidade de observacoes.

Sem I/O, sem banco: recebe a serie e responde.
"""

from __future__ import annotations

Ponto = tuple[int, int]     # (epoch em segundos UTC, ticket)


def registrar(serie: list[Ponto], epoch: int, ticket: int) -> list[Ponto]:
    """
    Devolve a serie com o ponto, se ele acrescenta informacao.

    So entra ticket maior que o ultimo; um ticket menor visto depois nao diz
    nada de novo (ja sabiamos que ele existia). Instante que nao avanca e
    corrigido para nao quebrar a monotonia.
    """
    if not serie:
        return [(epoch, ticket)]
    ultimo_epoch, ultimo_ticket = serie[-1]
    if ticket <= ultimo_ticket:
        return serie
    return serie + [(max(epoch, ultimo_epoch), ticket)]


def estimar(serie: list[Ponto], ticket: int) -> int | None:
    """
    Quando este ticket foi emitido, aproximadamente (epoch).

    None quando a serie nao alcanca o ticket (ainda nao vimos nenhum maior:
    nao da para dizer quando foi) ou quando a serie esta vazia. Ticket
    anterior ao primeiro ponto recebe o instante do primeiro ponto: e o
    melhor limite que temos.
    """
    if not serie:
        return None
    if ticket > serie[-1][1]:
        return None
    if ticket <= serie[0][1]:
        return serie[0][0]
    for (e0, t0), (e1, t1) in zip(serie, serie[1:]):
        if t0 < ticket <= t1:
            if t1 == t0:
                return e1
            return int(e0 + (e1 - e0) * (ticket - t0) / (t1 - t0))
    return serie[-1][0]


def emitidos(serie: list[Ponto], primeiro: int | None) -> int | None:
    """Tickets emitidos desde o primeiro visto, todos os tipos: teto das candidaturas."""
    if not serie or primeiro is None:
        return None
    return max(0, serie[-1][1] - primeiro + 1)


# A taxa so vale entre execucoes separadas por horas. Dentro de uma mesma
# execucao o maior ticket visto sobe porque a varredura DESCOBRE nomes, nao
# porque tickets estao sendo emitidos: na primeira execucao de 12/09/2026 os
# cinco pontos cabiam em 7 minutos e a "taxa" deu 872 mil por hora.
MINIMO_HORAS_OBSERVADAS = 3

# O guarda acima olha so o intervalo total, e nao basta: em 13/09/2026 a
# serie tinha cinco pontos em dois minutos (12/09 17h44 a 17h46, +18,6 mil
# tickets de descoberta) e depois nove horas de pontos reais. A taxa saiu
# 2.289/h; sem o artefato, 267/h. Por isso a taxa usa um ponto por execucao.
FOLGA_EXECUCAO_S = 3600


def por_execucao(serie: list[Ponto], folga_s: int = FOLGA_EXECUCAO_S) -> list[Ponto]:
    """
    Um ponto por execucao: de cada grupo de pontos a menos de `folga_s` um do
    outro, fica o ultimo (o limite mais apertado daquele momento). A subida
    dentro do grupo e a varredura descobrindo nomes, nao emissao.
    """
    saida: list[Ponto] = []
    for p in serie:
        if saida and p[0] - saida[-1][0] < folga_s:
            saida[-1] = p
        else:
            saida.append(p)
    return saida


def por_hora(serie: list[Ponto], agora: int, janela_s: int = 24 * 3600) -> float | None:
    """
    Tickets emitidos por hora (todos os tipos) na janela que termina em `agora`.

    Precisa de pelo menos dois pontos separados por MINIMO_HORAS_OBSERVADAS
    dentro da janela; senao devolve None em vez de inventar.
    """
    serie = por_execucao(serie)
    if len(serie) < 2:
        return None
    inicio = agora - janela_s
    # o ticket "no inicio da janela", interpolado na serie
    pontos = [p for p in serie if p[0] <= agora]
    if len(pontos) < 2:
        return None
    if inicio <= pontos[0][0]:
        e0, t0 = pontos[0]
    else:
        e0, t0 = pontos[0]
        for (ea, ta), (eb, tb) in zip(pontos, pontos[1:]):
            if ea <= inicio <= eb:
                if eb == ea:
                    e0, t0 = eb, tb
                else:
                    e0, t0 = inicio, ta + (tb - ta) * (inicio - ea) / (eb - ea)
                break
        else:
            e0, t0 = pontos[-2]
    e1, t1 = pontos[-1]
    horas = (e1 - e0) / 3600
    if horas < MINIMO_HORAS_OBSERVADAS:
        return None
    return (t1 - t0) / horas


def resumo(serie: list[Ponto], primeiro: int | None, agora: int) -> dict:
    """O que vai para o JSON e para a tela, ja calculado."""
    taxa = por_hora(serie, agora)
    return {
        "pontos": len(serie),
        "primeiro": primeiro,
        "emitidos": emitidos(serie, primeiro),
        "por_hora_24h": round(taxa) if taxa is not None else None,
        "desde": serie[0][0] if serie else None,
        "ate": serie[-1][0] if serie else None,
        "serie": [list(p) for p in serie],
    }
