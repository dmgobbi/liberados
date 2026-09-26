"""
Leitor das listas de frequencia do wordfreq, sem instalar o pacote.

Adaptador: le um arquivo, devolve um dicionario. O projeto e so biblioteca
padrao, e o wordfreq vem com dependencias (msgpack, regex, ftfy...). O
arquivo de dados, porem, e simples o bastante para ler na mao.

Formato ("cBpack"): msgpack comprimido em gzip, uma lista
[cabecalho, balde0, balde1, ...]. O balde k guarda as palavras com
frequencia ~10^(-k/100). Percorrendo os baldes em ordem, a posicao de cada
palavra e o ranking de popularidade: 0 e a mais usada.

Dados: https://github.com/rspeer/wordfreq, CC BY-SA 4.0. O projeto foi
encerrado em 2021, entao a lista e daquele ano: serve para "palavra comum",
nao para moda do momento.
"""

from __future__ import annotations

import gzip
import struct


def desempacotar(dados: bytes):
    """msgpack -> objetos Python. So o subconjunto que o wordfreq usa, e um pouco mais."""
    pos = 0

    def ler(n: int) -> bytes:
        nonlocal pos
        pedaco = dados[pos:pos + n]
        pos += n
        return pedaco

    def inteiro(n: int, com_sinal: bool = False) -> int:
        return int.from_bytes(ler(n), "big", signed=com_sinal)

    def valor():
        c = ler(1)[0]
        if c <= 0x7F:
            return c
        if c >= 0xE0:
            return c - 0x100
        if 0x80 <= c <= 0x8F:
            return {valor(): valor() for _ in range(c & 0x0F)}
        if 0x90 <= c <= 0x9F:
            return [valor() for _ in range(c & 0x0F)]
        if 0xA0 <= c <= 0xBF:
            return ler(c & 0x1F).decode("utf-8")
        if c == 0xC0:
            return None
        if c in (0xC2, 0xC3):
            return c == 0xC3
        if c in (0xC4, 0xC5, 0xC6):
            return ler(inteiro({0xC4: 1, 0xC5: 2, 0xC6: 4}[c]))
        if c == 0xCA:
            return struct.unpack(">f", ler(4))[0]
        if c == 0xCB:
            return struct.unpack(">d", ler(8))[0]
        if 0xCC <= c <= 0xCF:
            return inteiro(1 << (c - 0xCC))
        if 0xD0 <= c <= 0xD3:
            return inteiro(1 << (c - 0xD0), com_sinal=True)
        if c in (0xD9, 0xDA, 0xDB):
            return ler(inteiro({0xD9: 1, 0xDA: 2, 0xDB: 4}[c])).decode("utf-8")
        if c in (0xDC, 0xDD):
            return [valor() for _ in range(inteiro(2 if c == 0xDC else 4))]
        if c in (0xDE, 0xDF):
            return {valor(): valor() for _ in range(inteiro(2 if c == 0xDE else 4))}
        raise ValueError(f"tipo msgpack nao suportado: {c:#x} na posicao {pos - 1}")

    return valor()


def ranking(caminho: str) -> dict[str, int]:
    """Palavra -> posicao no ranking de uso (0 = a mais usada)."""
    with gzip.open(caminho, "rb") as f:
        pacote = desempacotar(f.read())
    posicoes: dict[str, int] = {}
    n = 0
    for balde in pacote[1:]:
        for palavra in balde:
            posicoes.setdefault(palavra, n)
            n += 1
    return posicoes
