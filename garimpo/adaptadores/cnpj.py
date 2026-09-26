"""
Cadastro aberto de CNPJ da Receita Federal, lido para uma pergunta so: que
palavras os brasileiros poem no NOME FANTASIA do proprio negocio?

Adaptador: rede e arquivo. Quem conta e casos/demanda.py.

POR QUE ESTA FONTE. A pesquisa de 11/09/2026 procurou "o que as pessoas
querem" em vendas de dominio, e-commerce e buscas. Nenhuma fonte era tao
direta: quem abre empresa precisa de dominio, e o nome fantasia e o nome que
ela escolheu. Na primeira amostra (1/10 do cadastro), a contagem
redescobriu sozinha varias candidaturas feitas a mao (combustiveis, redes,
chama, bichos, tributaria).

ONDE ESTA. A pagina da Receita e um compartilhamento Nextcloud que so lista
com JavaScript. O WebDAV publico do mesmo compartilhamento lista e baixa
sem isso: usuario = token do compartilhamento, senha vazia. Uma pasta por
mes (AAAA-MM), com Estabelecimentos0.zip a Estabelecimentos9.zip (~5,3 GB).

LICENCA: CC BY-ND 3.0 (Atribuicao-SemDerivacoes). Usar como insumo de uma
nota e uma coisa; publicar tabela derivada e outra. Por isso a contagem
fica em work/ e no cache do Actions, e nunca vai para o git.

O QUE NAO LE. E-mail, telefone e endereco sao dado pessoal quando a empresa
e um MEI. O leitor so toca as colunas listadas em COLUNAS.
"""

from __future__ import annotations

import base64
import csv
import io
import os
import re
import urllib.request
import zipfile
from collections.abc import Iterator
from dataclasses import dataclass

WEBDAV = "https://arquivos.receitafederal.gov.br/public.php/webdav/"
TOKEN = "YggdBLfdninEJX9"       # token publico do compartilhamento, nao senha
PARTES = tuple(f"Estabelecimentos{n}.zip" for n in range(10))

# posicoes na tabela Estabelecimentos (cnpj-metadados.pdf da Receita)
COLUNAS = {"cnpj_basico": 0, "matriz_filial": 3, "nome_fantasia": 4,
           "situacao": 5, "inicio": 10, "cnae": 11}
ATIVA = "02"
MATRIZ = "1"

_MES = re.compile(r"/(\d{4}-\d{2})/</d:href>")


@dataclass(frozen=True)
class Matriz:
    """Uma empresa ativa, pela linha da matriz: filial nao conta de novo."""

    nome_fantasia: str
    inicio: str          # AAAAMMDD
    cnae: str            # 7 digitos


def _pedido(url: str, metodo: str = "GET") -> urllib.request.Request:
    credencial = base64.b64encode(f"{TOKEN}:".encode()).decode()
    cabecalhos = {"Authorization": f"Basic {credencial}"}
    if metodo == "PROPFIND":
        cabecalhos["Depth"] = "1"
    return urllib.request.Request(url, method=metodo, headers=cabecalhos)


def meses(timeout: int = 60) -> list[str]:
    """Pastas mensais publicadas, da mais antiga para a mais nova."""
    with urllib.request.urlopen(_pedido(WEBDAV, "PROPFIND"), timeout=timeout) as r:
        return sorted(set(_MES.findall(r.read().decode("utf-8", errors="replace"))))


def baixar(mes: str, parte: str, destino: str, timeout: int = 3600) -> str:
    """Baixa uma parte. So aparece no lugar quando completa."""
    os.makedirs(os.path.dirname(destino) or ".", exist_ok=True)
    parcial = destino + ".parcial"
    with urllib.request.urlopen(_pedido(f"{WEBDAV}{mes}/{parte}"),
                                timeout=timeout) as r, open(parcial, "wb") as f:
        while pedaco := r.read(1 << 22):
            f.write(pedaco)
    os.replace(parcial, destino)
    return destino


def matrizes_ativas(caminho_zip: str) -> Iterator[Matriz]:
    """Le o CSV direto do zip, sem descompactar no disco."""
    csv.field_size_limit(10**7)
    maior = max(COLUNAS.values())
    with zipfile.ZipFile(caminho_zip) as z:
        for nome in z.namelist():
            with z.open(nome) as bruto:
                texto = io.TextIOWrapper(bruto, encoding="latin-1", newline="")
                for linha in csv.reader(texto, delimiter=";"):
                    if (len(linha) <= maior
                            or linha[COLUNAS["situacao"]] != ATIVA
                            or linha[COLUNAS["matriz_filial"]] != MATRIZ):
                        continue
                    yield Matriz(linha[COLUNAS["nome_fantasia"]],
                                 linha[COLUNAS["inicio"]],
                                 linha[COLUNAS["cnae"]])
