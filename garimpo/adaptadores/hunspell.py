"""
Expansao de dicionario hunspell (.dic + .aff) em Python puro.

Adaptador. O pt_BR.dic do LibreOffice guarda so o radical com "bandeiras":
"vacinar/akYM" quer dizer vacinar, vacina, vacinas, vacinou... Lido cru, como
o projeto fazia, "vacina" nao existe; so aparece aplicando as regras do .aff.
Era por isso que vacina, uma das suas proprias candidaturas, ficava sem os
pontos de palavra em portugues.

So expande entradas em minuscula. Nome proprio no .dic ("Silva/p") viraria
"palavra" e daria pontos a qualquer sobrenome.

Limitacoes aceitas: sufixo encadeado so em um nivel e sem conferir contra o
`unmunch` oficial. Serve para "essa forma existe no portugues", nao para
revisao ortografica.
"""

from __future__ import annotations

import re
import unicodedata


def _sem_acento(texto: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", texto)
                   if unicodedata.category(c) != "Mn")


def _regras(aff: str) -> dict:
    """bandeira -> (tipo, combina, [(tira, poe, bandeiras_seguintes, condicao)])"""
    regras = {}
    linhas = aff.splitlines()
    i = 0
    while i < len(linhas):
        partes = linhas[i].split()
        if (len(partes) >= 4 and partes[0] in ("SFX", "PFX")
                and partes[2] in ("Y", "N") and partes[3].isdigit()):
            tipo, bandeira, combina, n = (partes[0], partes[1], partes[2] == "Y",
                                          int(partes[3]))
            itens = []
            for linha in linhas[i + 1:i + 1 + n]:
                q = linha.split()
                if len(q) < 4:
                    continue
                tira = "" if q[2] == "0" else q[2]
                poe, _, seguintes = q[3].partition("/")
                poe = "" if poe == "0" else poe
                condicao = q[4] if len(q) > 4 else "."
                padrao = re.compile(condicao + "$" if tipo == "SFX" else "^" + condicao)
                itens.append((tira, poe, seguintes, padrao))
            regras[bandeira] = (tipo, combina, itens)
            i += n + 1
        else:
            i += 1
    return regras


def _aplicar(palavra: str, bandeiras: str, regras: dict, nivel: int = 0) -> list[str]:
    formas = []
    for bandeira in bandeiras:
        if bandeira not in regras:
            continue
        tipo, _, itens = regras[bandeira]
        for tira, poe, seguintes, padrao in itens:
            if not padrao.search(palavra):
                continue
            if tipo == "SFX":
                if tira and not palavra.endswith(tira):
                    continue
                nova = palavra[:len(palavra) - len(tira)] + poe
            else:
                if tira and not palavra.startswith(tira):
                    continue
                nova = poe + palavra[len(tira):]
            formas.append(nova)
            if seguintes and nivel < 1:
                formas += _aplicar(nova, seguintes, regras, nivel + 1)
    return formas


def expandir(dic: str, aff: str) -> set[str]:
    """Todas as formas, sem acento e em ASCII, das entradas em minuscula."""
    regras = _regras(aff)
    formas: set[str] = set()
    for linha in dic.splitlines()[1:]:          # a 1a linha e a contagem
        palavra, _, bandeiras = linha.partition("/")
        bandeiras = bandeiras.split()[0] if bandeiras else ""
        if not palavra or not palavra[0].islower():
            continue
        formas.add(palavra)
        sufixadas = _aplicar(palavra, bandeiras, regras)
        formas.update(sufixadas)
        # prefixo e sufixo juntos, quando as duas regras permitem
        prefixos = [b for b in bandeiras
                    if b in regras and regras[b][0] == "PFX" and regras[b][1]]
        if prefixos:
            sufixos = [b for b in bandeiras
                       if b in regras and regras[b][0] == "SFX" and regras[b][1]]
            for forma in _aplicar(palavra, "".join(sufixos), regras):
                formas.update(_aplicar(forma, "".join(prefixos), regras))
    saida = set()
    for forma in formas:
        ascii_ = _sem_acento(forma.lower())
        if ascii_.isalpha() and ascii_.isascii():
            saida.add(ascii_)
    return saida
