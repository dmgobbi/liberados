"""
Ponto de composicao: onde as dependencias sao ligadas.

Os modulos de dominio e de caso de uso nao sabem onde fica o banco nem qual
diretorio guarda os dicionarios. Quem decide isso e este arquivo, e so ele.
Assim um teste monta um Contexto apontando para um banco temporario sem
precisar mexer em variavel global.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from functools import cached_property

from .adaptadores import dicionarios, registrobr
from .adaptadores.repositorio import Repositorio

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


@dataclass
class Contexto:
    raiz: str = RAIZ

    @property
    def banco(self) -> str:
        return os.path.join(self.raiz, "dados.db")

    @property
    def trabalho(self) -> str:
        """Cache de listas e dicionarios. Descartavel, fora do git."""
        return os.path.join(self.raiz, "work")

    @property
    def site(self) -> str:
        return os.path.join(self.raiz, "site")

    @property
    def instantaneo(self) -> str:
        return os.path.join(self.site, "dados.json")

    @cached_property
    def repo(self) -> Repositorio:
        os.makedirs(self.raiz, exist_ok=True)
        return Repositorio(self.banco)

    @cached_property
    def vocabularios(self) -> dicionarios.Repositorio:
        os.makedirs(self.trabalho, exist_ok=True)
        return dicionarios.Repositorio(self.trabalho)

    @property
    def cliente(self):
        """O cliente e sem estado, entao o proprio modulo serve."""
        return registrobr

    @property
    def contador(self):
        """Conta tickets sem o corte em 10, pelo RDAP (varredura.Varredura)."""
        from .adaptadores import rdap
        return rdap.contar_tickets

    def baixar_rodada(self, aviso=None):
        os.makedirs(self.trabalho, exist_ok=True)
        return registrobr.baixar_rodada(cache=self.trabalho, aviso=aviso)


padrao = Contexto()
