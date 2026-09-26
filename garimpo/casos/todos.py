"""
A rodada inteira, pesquisavel no site: os ~125 mil nomes com a nota de cada um.

Caso de uso. O site mostra, por padrao, os ~17 mil que a varredura consulta.
Mas o corte de 45 e opiniao da ferramenta, e quem procura um nome especifico
(o da propria cidade, o do proprio ramo) quer procurar em tudo. Este arquivo
e isso: cada nome da lista oficial, com nota e motivos, SEM situacao. Quem
quer saber a situacao de um nome de fora do pool clica em "conferir", que
pergunta ao Registro.br do navegador de quem visita.

Formato compacto e DETERMINISTICO de proposito: sem data de geracao, sem
ordem instavel. O workflow roda a cada 4 horas e comita o que mudou; com o
mesmo conteudo o git nao ve diferenca, e um arquivo de ~3 MB nao entra no
historico seis vezes por dia. So muda quando a lista ou a nota mudam.

    {"versao": 1, "rodada": {...}, "extensoes": [...], "motivos": [...],
     "marcas": ["OK", "ATENCAO", "RISCO"], "categorias": [...],
     "itens": [[rotulo, indice_extensao, nota, [indices_de_motivo],
                indice_de_risco, bits_de_categoria], ...]}

O risco de marca vai junto: busca na rodada inteira sem ele levaria gente
direto a nome de terceiro, que e justamente o que o projeto evita.

Os motivos sao so o tipo ("composto", nao "composto: loja + online"): o
detalhe multiplicaria o vocabulario por dezenas de milhares de variantes.
"""

from __future__ import annotations

import json
import os

from ..dominio import categorias
from ..dominio.marcas import Risco
from ..dominio.relevancia import separar
from .pool import marca_de, nota_de

VERSAO = 1
RISCOS = (Risco.OK, Risco.ATENCAO, Risco.RISCO)


def _tipo(motivo: str) -> str:
    return motivo.split(":", 1)[0].strip()


def montar(rodada, vocabularios) -> dict:
    extensoes: dict[str, int] = {}
    motivos: dict[str, int] = {}
    itens = []
    lexico = getattr(vocabularios, "lexico", None)
    pessoas = lexico.pessoas if lexico else frozenset()
    for dominio in sorted(set(rodada.liberacao)):
        rotulo, extensao = separar(dominio)
        if not rotulo:
            continue
        nota = nota_de(dominio, vocabularios, elegivel=dominio in rodada.elegiveis)
        tipos = sorted({motivos.setdefault(_tipo(m), len(motivos))
                        for m in nota.motivos})
        risco = marca_de(dominio, vocabularios).risco
        itens.append([rotulo, extensoes.setdefault(extensao, len(extensoes)),
                      nota.valor, tipos, RISCOS.index(risco),
                      categorias.mascara(rotulo, pessoas)])
    return {
        "versao": VERSAO,
        "rodada": {"inicio": rodada.inicio, "fim": rodada.fim},
        "extensoes": sorted(extensoes, key=extensoes.get),
        "motivos": sorted(motivos, key=motivos.get),
        "marcas": [r.value for r in RISCOS],
        "categorias": categorias.tabela(),
        "itens": itens,
    }


def escrever(dados: dict, caminho: str) -> int:
    os.makedirs(os.path.dirname(caminho) or ".", exist_ok=True)
    parcial = caminho + ".parcial"
    with open(parcial, "w", encoding="utf-8") as f:
        json.dump(dados, f, ensure_ascii=False, separators=(",", ":"))
    os.replace(parcial, caminho)
    return os.path.getsize(caminho)
