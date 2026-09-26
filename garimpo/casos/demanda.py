"""
Demanda por nome: o que as empresas ativas do Brasil usam no nome fantasia.

Caso de uso. Recebe as matrizes (de adaptadores/cnpj.py, ou falsas nos
testes), conta, e guarda uma tabela pequena em work/demanda.json.

Tres contagens, todas por EMPRESA (a matriz), nunca por linha: uma rede com
13 filiais e uma empresa querendo o nome, nao treze.

  palavras   quantas empresas usam a palavra no nome fantasia
  nomes      quantas empresas tem EXATAMENTE aquele nome, colado como
             rotulo de dominio ("Pizzaria Bella" -> "pizzariabella")
  setores    as palavras mais usadas em cada GRUPO do CNAE (3 digitos),
             que e de onde saem as categorias de busca do site. Grupo, e
             nao divisao: a divisao 47 e o varejo inteiro (moda, farmacia,
             mercado, pet, material de construcao); o grupo separa

A tabela nao vai para o git: e derivada de dado CC BY-ND (ver cnpj.py).
"""

from __future__ import annotations

import json
import os
import re
import unicodedata
from collections import Counter, defaultdict
from collections.abc import Iterable
from dataclasses import dataclass, field

VERSAO = 2              # 2: setores por grupo do CNAE (3 digitos)
PALAVRA = re.compile(r"[a-z]{3,}")
# palavra de razao social ou de ligacao: aparece em tudo e nao diz nada
VAZIAS = frozenset({"ltda", "eireli", "epp", "cia", "comercio", "servicos",
                    "servico", "com", "dos", "das", "del", "the", "and", "para"})
MINIMO_PALAVRA = 5      # palavra usada por menos empresas que isso fica fora
MINIMO_NOME = 2         # nome exato de uma empresa so pode ser marca
PALAVRAS_POR_SETOR = 300


def _sem_acento(texto: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", texto)
                   if unicodedata.category(c) != "Mn")


def palavras_do_nome(fantasia: str) -> set[str]:
    texto = _sem_acento(fantasia.lower())
    return {p for p in PALAVRA.findall(texto) if p not in VAZIAS}


def colado(fantasia: str) -> str:
    """O nome fantasia no formato de rotulo de dominio."""
    return "".join(re.findall(r"[a-z0-9]+", _sem_acento(fantasia.lower())))


@dataclass
class Demanda:
    palavras: Counter = field(default_factory=Counter)
    nomes: Counter = field(default_factory=Counter)
    setores: dict = field(default_factory=lambda: defaultdict(Counter))
    empresas: int = 0
    mes: str = ""

    def somar(self, matrizes: Iterable) -> None:
        for m in matrizes:
            self.empresas += 1
            if not m.nome_fantasia.strip():
                continue
            palavras = palavras_do_nome(m.nome_fantasia)
            self.palavras.update(palavras)
            self.setores[m.cnae[:3]].update(palavras)
            rotulo = colado(m.nome_fantasia)
            if 3 <= len(rotulo) <= 30:
                self.nomes[rotulo] += 1

    def como_dicionario(self) -> dict:
        return {
            "versao": VERSAO,
            "mes": self.mes,
            "empresas": self.empresas,
            "palavras": {p: n for p, n in self.palavras.items() if n >= MINIMO_PALAVRA},
            "nomes": {r: n for r, n in self.nomes.items() if n >= MINIMO_NOME},
            "setores": {s: dict(c.most_common(PALAVRAS_POR_SETOR))
                        for s, c in self.setores.items()},
        }


def gravar(demanda: Demanda, caminho: str) -> int:
    os.makedirs(os.path.dirname(caminho) or ".", exist_ok=True)
    parcial = caminho + ".parcial"
    with open(parcial, "w", encoding="utf-8") as f:
        json.dump(demanda.como_dicionario(), f, ensure_ascii=False,
                  separators=(",", ":"))
    os.replace(parcial, caminho)
    return os.path.getsize(caminho)


def ler(caminho: str) -> dict | None:
    if not os.path.exists(caminho):
        return None
    with open(caminho, encoding="utf-8") as f:
        dados = json.load(f)
    return dados if dados.get("versao") == VERSAO else None
