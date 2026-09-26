"""
Manutencao: montar a fila de uma execucao a partir do que o banco sabe.

Caso de uso fino. A regra de quem vem primeiro mora em dominio/frescor.py;
aqui so se traduz Candidato (o que o repositorio devolve) em frescor.Item.
"""

from __future__ import annotations

from ..adaptadores.repositorio import Candidato
from ..dominio import frescor


def como_item(c: Candidato) -> frescor.Item:
    return frescor.Item(
        dominio=c.dominio,
        situacao=c.situacao,
        elegivel=c.elegivel,
        em_leilao=c.em_leilao,
        candidatos=c.candidatos,
        nota=c.nota,
        verificado_em=frescor.epoch(c.verificado_em),
    )


def classes_de(candidatos: list[Candidato],
               rodada_inicio: int | None = None) -> dict[str, frescor.Classe]:
    return frescor.classificar([como_item(c) for c in candidatos],
                               rodada_inicio=rodada_inicio)


def alvos(repo, agora: int, capacidade: int, **opcoes) -> list[str]:
    """A fila desta execucao, do pool inteiro."""
    todos = repo.buscar(limite=1_000_000)
    return frescor.escolher([como_item(c) for c in todos], agora, capacidade,
                            **opcoes)
