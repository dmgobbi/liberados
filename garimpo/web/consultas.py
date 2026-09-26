"""
Consultas da interface.

Traduz o vocabulario da tela ("joias", "disputados", "menos candidatos") em
SQL. Fica separado do servidor de proposito: e aqui que mora a definicao de
cada filtro, e isso e regra do produto, nao detalhe de HTTP.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..adaptadores.repositorio import Candidato, Repositorio
from ..dominio.situacao import Situacao

# Cada filtro e uma clausula WHERE. "joias" e o cruzamento que da nome ao
# projeto: elegivel ao leilao (ja provou demanda) e ainda sem candidato
# visivel. Visivel e a palavra importante: o endpoint so informa tickets
# quando ha mais de um candidato, entao zero significa "zero ou um".
#
# `em_leilao = 0` em todo filtro de liberacao: quem esta na lista oficial de
# leiloes nao e "sem competicao", por mais recente que pareca a ultima
# leitura. Ver dominio.situacao.com_leilao_anunciado.
_EM_LIBERACAO = (f"'{Situacao.LIBERACAO_LIVRE.value}', "
                 f"'{Situacao.LIBERACAO_DISPUTADA.value}'")
FILTROS = {
    "todos": "1=1",
    "joias": (f"elegivel = 1 AND em_leilao = 0 "
              f"AND status = '{Situacao.LIBERACAO_LIVRE.value}'"),
    "sem_competicao": (f"em_leilao = 0 "
                       f"AND status = '{Situacao.LIBERACAO_LIVRE.value}'"),
    "disputados": (f"em_leilao = 0 "
                   f"AND status = '{Situacao.LIBERACAO_DISPUTADA.value}'"),
    "leilao": (f"(status = '{Situacao.COMPETITIVO.value}' "
               f"OR (em_leilao = 1 AND status IN ({_EM_LIBERACAO})))"),
    "livres": f"status = '{Situacao.LIVRE.value}'",
    "registrados": f"status = '{Situacao.REGISTRADO.value}'",
    "elegiveis": "elegivel = 1",
    "marcados": "marcado = 1",
    "nao_verificados": "status IS NULL",
    "risco_marca": "nivel_marca = 'RISCO'",
}

# NULLS LAST nao existe em sqlite antigo; o CASE faz o mesmo servico
_NAO_VERIFICADO_POR_ULTIMO = "CASE WHEN candidatos IS NULL THEN 1 ELSE 0 END"

ORDENS = {
    "nota": "nota DESC, LENGTH(dominio) ASC, dominio ASC",
    "menos_candidatos": f"{_NAO_VERIFICADO_POR_ULTIMO}, candidatos ASC, nota DESC",
    "candidatos": f"{_NAO_VERIFICADO_POR_ULTIMO}, candidatos DESC, nota DESC",
    "tamanho": "LENGTH(dominio) ASC, nota DESC",
    "alfabetica": "dominio ASC",
    "alfabetica_desc": "dominio DESC",
    "recentes": "verificado_em DESC, nota DESC",
}

PADRAO_FILTRO = "joias"
PADRAO_ORDEM = "nota"
LIMITE_MAXIMO = 1000


@dataclass
class Pagina:
    total: int
    itens: list[Candidato]


class Consultas:
    def __init__(self, repo: Repositorio):
        self._repo = repo

    @staticmethod
    def _montar_onde(filtro: str, busca: str, esconder_risco: bool):
        clausulas = [FILTROS.get(filtro, FILTROS["todos"])]
        parametros: list = []

        if busca:
            clausulas.append("dominio LIKE ?")
            parametros.append(f"%{busca.strip().lower()}%")

        # quem pediu explicitamente os de risco deve ve-los
        if esconder_risco and filtro != "risco_marca":
            clausulas.append("(nivel_marca IS NULL OR nivel_marca != 'RISCO')")

        return " AND ".join(clausulas), parametros

    def listar(self, *, filtro: str = PADRAO_FILTRO, busca: str = "",
               ordem: str = PADRAO_ORDEM, limite: int = 200,
               deslocamento: int = 0, esconder_risco: bool = True) -> Pagina:
        onde, parametros = self._montar_onde(filtro, busca, esconder_risco)
        return Pagina(
            total=self._repo.contar(onde, parametros),
            itens=self._repo.buscar(onde, parametros,
                                    ORDENS.get(ordem, ORDENS[PADRAO_ORDEM]),
                                    min(limite, LIMITE_MAXIMO), deslocamento),
        )

    def resumo(self) -> dict:
        dados = {nome: self._repo.contar(clausula)
                 for nome, clausula in FILTROS.items()}
        dados["total"] = self._repo.contar()
        dados["verificados"] = self._repo.contar("status IS NOT NULL")
        for chave in ("importado_em", "verificado_em", "total_liberacao",
                      "total_elegiveis", "total_em_leilao",
                      "rodada_inicio", "rodada_fim"):
            dados[chave] = self._repo.meta(chave)
        return dados

    def alvos(self, filtro: str, limite: int,
              apenas_nao_verificados: bool = False) -> list[str]:
        """Dominios de um filtro, para enfileirar numa varredura."""
        onde = FILTROS.get(filtro, FILTROS["todos"])
        if apenas_nao_verificados:
            onde += " AND status IS NULL"
        return self._repo.dominios_de(onde, ORDENS[PADRAO_ORDEM], limite)

    @staticmethod
    def como_dicionario(c: Candidato) -> dict:
        """Serializa um Candidato para a interface."""
        return {
            "dominio": c.dominio,
            "status": c.situacao_atual.value if c.situacao_atual else None,
            "candidatos": c.candidatos,
            "nota": c.nota,
            "elegivel": int(c.elegivel),
            "em_leilao": int(c.em_leilao),
            "motivos": "; ".join(c.motivos),
            "nivel_marca": c.risco.value,
            "motivo_marca": c.motivo_marca,
            "marcado": int(c.marcado),
            "verificado_em": c.verificado_em,
        }
