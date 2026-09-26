#!/usr/bin/env python3
"""
Filtra a lista bruta do processo de liberacao do Registro.br.

A lista de uma rodada tem mais de 100 mil nomes. Consultar todos na API e
inviavel (e voce seria bloqueado por excesso de requisicoes). Este script e
o primeiro passo do fluxo: reduzir a lista a algumas centenas de nomes que
valem uma consulta.

Uso tipico:

    # nomes .com.br curtos, sem numero e sem hifen
    python3 filtrar_lista.py lista_liberacao.txt \\
        --tld com.br --min 3 --max 8 --sem-numero --sem-hifen \\
        --out candidatos.txt

    # so palavras que existem num dicionario de portugues
    python3 filtrar_lista.py lista_liberacao.txt \\
        --tld com.br --dicionario /usr/share/dict/brazilian \\
        --out palavras.txt

    # nomes de um nicho especifico
    python3 filtrar_lista.py lista_liberacao.txt \\
        --contem credito emprestimo financiamento --out fintech.txt

Todos os filtros sao combinados com E (AND). A comparacao com o dicionario
ignora acentos, entao "cafe" no arquivo casa com "cafe" no dominio.

Onde arrumar um dicionario de portugues:

    sudo apt install wbrazilian     # cria /usr/share/dict/brazilian
    sudo dnf install hunspell-pt-BR

Serve qualquer arquivo texto com uma palavra por linha.
"""

import argparse
import re
import sys
import unicodedata

# TLDs .br mais relevantes para garimpo. Usado so como referencia no --help.
TLDS_COMUNS = ["com.br", "app.br", "dev.br", "net.br", "tec.br", "eco.br", "blog.br"]


def sem_acento(s):
    """Remove acentos: 'cafe' -> 'cafe', 'acao' -> 'acao'."""
    nfkd = unicodedata.normalize("NFKD", s)
    return "".join(c for c in nfkd if not unicodedata.combining(c))


def carregar_dicionario(caminho):
    """Le uma palavra por linha e devolve o conjunto normalizado."""
    palavras = set()
    with open(caminho, encoding="utf-8", errors="replace") as f:
        for linha in f:
            p = sem_acento(linha.strip().lower())
            if p.isalpha():
                palavras.add(p)
    return palavras


def separar(dominio):
    """'vacina.com.br' -> ('vacina', 'com.br'). Devolve (None, None) se invalido."""
    partes = dominio.split(".")
    if len(partes) < 2:
        return None, None
    return partes[0], ".".join(partes[1:])


def main():
    ap = argparse.ArgumentParser(
        description="Filtra a lista bruta do processo de liberacao.",
        epilog="TLDs comuns: " + ", ".join(TLDS_COMUNS),
    )
    ap.add_argument("arquivo", help="lista bruta, um dominio por linha")
    ap.add_argument("--out", default="-", help="arquivo de saida (padrao: stdout)")
    ap.add_argument("--tld", action="append", default=[],
                    help="mantem apenas este TLD (pode repetir)")
    ap.add_argument("--min", type=int, default=0, help="tamanho minimo do nome")
    ap.add_argument("--max", type=int, default=0, help="tamanho maximo do nome (0 = sem limite)")
    ap.add_argument("--sem-numero", action="store_true", help="descarta nomes com digito")
    ap.add_argument("--sem-hifen", action="store_true", help="descarta nomes com hifen")
    ap.add_argument("--dicionario", help="arquivo de palavras; mantem so nomes que sao palavra")
    ap.add_argument("--contem", nargs="+", default=[],
                    help="mantem nomes que contenham qualquer um destes trechos")
    ap.add_argument("--regex", help="mantem nomes que casem com esta expressao regular")
    args = ap.parse_args()

    dicionario = carregar_dicionario(args.dicionario) if args.dicionario else None
    padrao = re.compile(args.regex) if args.regex else None
    tlds = set(args.tld)

    total = 0
    mantidos = []

    with open(args.arquivo, encoding="utf-8", errors="replace") as f:
        for linha in f:
            d = linha.strip().lower()
            if not d or d.startswith("#"):
                continue
            total += 1

            nome, tld = separar(d)
            if nome is None:
                continue
            if tlds and tld not in tlds:
                continue
            if args.min and len(nome) < args.min:
                continue
            if args.max and len(nome) > args.max:
                continue
            if args.sem_numero and any(c.isdigit() for c in nome):
                continue
            if args.sem_hifen and "-" in nome:
                continue
            if dicionario is not None and sem_acento(nome) not in dicionario:
                continue
            if args.contem and not any(t in nome for t in args.contem):
                continue
            if padrao and not padrao.search(nome):
                continue

            mantidos.append(d)

    saida = sys.stdout if args.out == "-" else open(args.out, "w", encoding="utf-8")
    try:
        for d in mantidos:
            print(d, file=saida)
    finally:
        if saida is not sys.stdout:
            saida.close()

    print(f"{total} nomes lidos, {len(mantidos)} mantidos", file=sys.stderr)
    if len(mantidos) > 300:
        print("Aviso: ainda sao muitos nomes para consultar na API. "
              "Aperte mais os filtros ou rode em lotes de 100 a 200.", file=sys.stderr)


if __name__ == "__main__":
    main()
