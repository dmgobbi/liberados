"""
Montagem do pool de candidatos.

Caso de uso: pega as tres listas da rodada, pontua tudo e escolhe o que vale
consultar. Sem este corte a varredura teria 125 mil nomes, o que a 0,46 req/s
levaria 75 horas e provavelmente um bloqueio no meio.

O corte tem um degrau natural: nota 45 e onde ficam os compostos de nicho.
Acima disso sao uns 15 mil nomes (~9h); abaixo salta para 45 mil (~27h) com a
qualidade despencando.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..adaptadores.registrobr import Rodada
from ..adaptadores.repositorio import Candidato
from ..dominio.marcas import Avaliacao, avaliar_dominio
from ..dominio.relevancia import LEXICO_VAZIO, Nota, e_palavra, pontuar

NOTA_MINIMA = 45
TETO_LIBERACAO = 20_000


def nota_de(dominio: str, vocabularios, *, elegivel: bool = False) -> Nota:
    """
    A nota com tudo que os vocabularios sabem.

    `vocabularios` pode ser o objeto completo (dicionarios.Vocabularios) ou
    so o par (pt, en), como nos testes: sem lexico, a nota e a antiga.
    """
    pt, en = vocabularios
    return pontuar(dominio, pt, en, elegivel=elegivel,
                   lexico=getattr(vocabularios, "lexico", None))


def marca_de(dominio: str, vocabularios) -> Avaliacao:
    """O risco de marca, incluindo o .com popular quando a lista existe."""
    pt, en = vocabularios
    lexico = getattr(vocabularios, "lexico", None) or LEXICO_VAZIO
    return avaliar_dominio(
        dominio,
        sites_populares=getattr(vocabularios, "sites_populares", None),
        e_palavra=lambda nome: e_palavra(nome, pt, en, lexico))


@dataclass
class ResumoPool:
    total: int
    elegiveis: int
    da_liberacao: int
    descartados: int


def montar(rodada: Rodada, vocabularios, *, nota_minima: int = NOTA_MINIMA,
           teto: int = TETO_LIBERACAO) -> tuple[list[Candidato], ResumoPool]:
    """
    Devolve os candidatos e um resumo.

    Todo elegivel ao leilao entra, independente de nota: o nome ja provou ter
    demanda ao travar rodadas seguidas, e essa e a evidencia mais forte que
    existe. Da lista grande entram os melhores pontuados.
    """
    candidatos: list[Candidato] = []

    for dominio in sorted(rodada.elegiveis):
        nota = nota_de(dominio, vocabularios, elegivel=True)
        marca = marca_de(dominio, vocabularios)
        candidatos.append(Candidato(
            dominio=dominio, fonte="elegivel", elegivel=True,
            em_leilao=dominio in rodada.em_leilao,
            nota=nota.valor, motivos=nota.motivos,
            risco=marca.risco, motivo_marca=marca.motivo))

    ranking = []
    descartados = 0
    for dominio in rodada.liberacao:
        if dominio in rodada.elegiveis:
            continue
        nota = nota_de(dominio, vocabularios)
        if nota.valor < nota_minima:
            descartados += 1
            continue
        ranking.append((nota, dominio))

    # nota alta primeiro; empate resolve pelo nome mais curto
    ranking.sort(key=lambda par: (-par[0].valor, len(par[1]), par[1]))

    for nota, dominio in ranking[:teto]:
        marca = marca_de(dominio, vocabularios)
        candidatos.append(Candidato(
            dominio=dominio, fonte="liberacao",
            em_leilao=dominio in rodada.em_leilao,
            nota=nota.valor, motivos=nota.motivos,
            risco=marca.risco, motivo_marca=marca.motivo))

    resumo = ResumoPool(
        total=len(candidatos),
        elegiveis=len(rodada.elegiveis),
        da_liberacao=len(candidatos) - len(rodada.elegiveis),
        descartados=descartados,
    )
    return candidatos, resumo
