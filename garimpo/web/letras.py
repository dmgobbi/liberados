"""
Uma pagina por letra, de /insights/dominios-de-uma-letra/a-com-br/ a z-com-br/.

POR QUE (15/09/2026). O artigo "O que aconteceu com os 26 dominios .com.br de
uma letra" resume 26 historias numa tabela. Quem chega pela busca de
"x.com.br" quer a historia daquele nome: as datas, as telas guardadas pelo
Internet Archive e quem e o dono hoje.

DE ONDE VEM CADA COISA:
  - as oito letras com historia (b, e, n, s, x existem; h, p, z sumiram) tem
    texto proprio em site_modelo/letras/<letra>.html, com o mesmo comentario
    de metadados dos fragmentos. As capturas de tela ficam em
    site_modelo/imagens/letras/ (exportar_site.py as publica);
  - as outras 18 saem daqui, do quadro abaixo. Dizem pouco porque ha pouco a
    dizer: ficam de pe (o artigo liga para todas) com noindex, fora do
    sitemap e do llms.txt, como os ramos ralos de ramos.py;
  - o dono de hoje dos cinco que existem NAO esta no HTML: letra.js consulta o
    RDAP no navegador de quem olha (regra de 12/09/2026 no CLAUDE.md). O
    texto do build diz so pessoa fisica ou empresa.

Fatos de 14 e 15/09/2026, com o metodo em docs/limitacoes-registrobr.md (R11)
e o relatorio privado em work/umaletra/.
"""

from __future__ import annotations

import html
import os

from . import paginas as pg

LETRAS = "abcdefghijklmnopqrstuvwxyz"
EXISTEM = "bensx"
BASE = "insights/dominios-de-uma-letra"
DATA = "2026-09-15"

# O que o Internet Archive tem da pagina inicial das letras sem historia.
# 2013, ~2,4 KB: pagina de erro do proprio arquivo; 2022, 301 de ~310 bytes:
# artefato do robo num nome que nao existe (limitacao F6).
ARQUIVO = {
    "sem": "O Internet Archive não tem nenhuma cópia da página inicial.",
    "erro": ("O Internet Archive só guardou, em 2013, uma página de erro do próprio "
             "arquivo, sem nada do site."),
    "m": ("O Internet Archive ficou fora do ar nas vezes em que tentamos ler o histórico "
          "de <code>m.com.br</code>, em 14 e 15/09/2026. Não dá para dizer se houve site."),
}
ARQUIVO_DE = {**{l: "erro" for l in "afgorwy"}, "m": "m"}

# Os seis nomes de um caractere que ja existiam no .com, .net e .org antes da
# reserva de dezembro de 1993 (ICANN, 27/02/2008)
MUNDO = {
    "i": "<code>i.net</code>",
    "q": "<code>q.com</code> e <code>q.net</code>",
}

# .com.br de duas letras que passaram pelas listas de 2017 a 2026, pela
# primeira letra, e os congelados no RDAP em 14 e 15/09/2026
DUAS = {
    "a": ("ag ah aj ak ao au ax", ""), "b": ("bj bk bo", ""), "c": ("cm cz", ""),
    "d": ("da db dc dk dp ds dt dx", ""), "e": ("ec ed ee ew", "ed ew"),
    "f": ("fa fo fp fx", "fa"), "g": ("gd gg", ""), "h": ("hh hl ht hv", "ht"),
    "i": ("ij in ip iq iy", ""), "j": ("jf jg jh ju jw jz", "jw"),
    "k": ("kh kp kq ku kv kz", ""), "l": ("lt lu lw", ""), "m": ("mh mu", ""),
    "n": ("na nf nj no nt nv", "na"), "o": ("oa od of oh oo op ox", "ox"),
    "p": ("pd pg pj pk py", ""),
    "q": ("qa qc qg qh qj qk ql qm qo qr qu qx qy qz", "qc qm"), "r": ("rq", ""),
    "s": ("sm sq sr st sw sy", "sq sw sy"), "t": ("tb tg tj tq tu", ""),
    "u": ("ua ub uc ud uf un ur uu", "ub ur"), "v": ("vi vk vo vq vu vy", "vk"),
    "w": ("wa wg wh wn wr ws", "wg wr"), "x": ("xa xc xe xi xv", "xe xi"),
    "y": ("ye yf yj yn yo yq ys yu yv yw", "yf yn ys"), "z": ("za zl zr zy", ""),
}
# rodada provavel de volta (vencimento + 5 meses, e a seguinte), como no
# artigo dos .com.br de duas letras
VOLTA = {
    **{n: "11/11/2026 ou 09/12/2026" for n in "ed ht qc wg wr xi".split()},
    **{n: "09/12/2026 ou 13/01/2027" for n in "ew fa ox".split()},
    **{n: "13/01/2027 ou 10/02/2027" for n in
       "jw na qm sq sw sy ub ur vk xe yf yn ys".split()},
}


EXTENSO = {2: "Dois", 3: "Três", 4: "Quatro"}


def slug(letra: str) -> str:
    return f"{BASE}/{letra}-com-br"


def _codigos(nomes: list[str]) -> str:
    itens = [f"<code>{html.escape(n)}</code>" for n in nomes]
    return itens[0] if len(itens) == 1 else ", ".join(itens[:-1]) + " e " + itens[-1]


def _codigos_ligados(letras: str) -> str:
    itens = [f'<a href="/{slug(l)}/"><code>{l}.com.br</code></a>' for l in letras]
    return ", ".join(itens[:-1]) + " e " + itens[-1]


def duas_letras(letra: str) -> str:
    todos, congelados = (s.split() for s in DUAS[letra])
    n = len(todos)
    frase = ("1 <code>.com.br</code> de duas letras começando com "
             f"<code>{letra}</code> passou" if n == 1 else
             f"{n} <code>.com.br</code> de duas letras começando com <code>{letra}</code> passaram")
    corpo = (f'<h2 id="duas-letras">E com duas letras?</h2>\n<p>De 2017 a 2026, {frase} '
             f"pelas listas de liberação: {_codigos(todos)}. Em 15/09/2026, "
             f"{'tinha dono' if n == 1 else 'todos tinham dono'}.")
    if congelados:
        um = len(congelados) == 1
        if n == 1:
            quem = "Está congelado e pode"
        elif um:
            quem = "Um deles está congelado e pode"
        else:
            quem = f"{EXTENSO[len(congelados)]} deles estão congelados e podem"
        corpo += (f" {quem} "
                  "voltar se o dono não pagar:</p>\n<ul>" + "".join(
                      f'<li><a rel="nofollow" href="/quando-volta/?d={c}.com.br">'
                      f'<code>{c}.com.br</code></a>: '
                      f"rodada de {VOLTA[c]}</li>" for c in congelados) + "</ul>\n")
    else:
        corpo += "</p>\n"
    return corpo + ('<p>A história dos 139 está em <a href="/insights/dominios-de-duas-letras/">'
                    "Todo .com.br de duas letras que voltou ao mercado já tem dono</a>.</p>\n")


def navegacao(letra: str) -> str:
    atual = ' aria-current="page"'
    links = "".join(f'<a href="/{slug(l)}/"{atual if l == letra else ""}>{l}</a>'
                    for l in LETRAS)
    return (f'<nav class="letras" aria-label="As 26 letras">{links}</nav>\n'
            '<p><a href="/insights/dominios-de-uma-letra/">O que aconteceu com os 26 domínios '
            ".com.br de uma letra</a></p>\n")


def _sem_historia(letra: str) -> dict:
    nome = f"{letra}.com.br"
    arquivo = ARQUIVO[ARQUIVO_DE.get(letra, "sem")]
    ressalva = ("" if letra == "m" else
                " Não ter cópia não prova que o nome nunca existiu: o arquivo começou em 1996 e "
                "guardou pouco dos primeiros sites, e o Registro.br não publica o histórico de "
                "titulares.")
    mundo = (f"<p>Lá fora, {MUNDO[letra]} estão entre os seis nomes de um caractere que já "
             "existiam no <code>.com</code>, <code>.net</code> e <code>.org</code> quando foram "
             "reservados, em dezembro de 1993, segundo a ICANN.</p>\n" if letra in MUNDO else "")
    corpo = (
        f"<p>Não. Em 14/09/2026, a consulta de disponibilidade do Registro.br respondia "
        f'<strong>"Domínio inválido"</strong> para <code>{nome}</code>, e o RDAP não encontrava '
        "o nome. Não é livre: ninguém consegue registrar, nem pagando.</p>\n"
        "<p>Desde a Resolução CGI.br 001/98, o nome de um domínio <code>.br</code> tem de 2 a 26 "
        "caracteres. Só cinco <code>.com.br</code> de uma letra existem, todos registrados antes "
        f"dela: {_codigos_ligados(EXISTEM)}.</p>\n"
        f'<h2 id="arquivo">Já existiu?</h2>\n<p>{arquivo}{ressalva}</p>\n'
        + mundo + duas_letras(letra) + navegacao(letra))
    return dict(
        slug=slug(letra), tipo="pagina", secao="insights", data=DATA,
        titulo=f"<code>{nome}</code> existe?",
        titulo_busca=f"{nome}: dá para registrar esse domínio de uma letra?",
        descricao=(f"{nome} não existe e ninguém pode registrar: o Registro.br responde "
                   "\"Domínio inválido\". Só cinco .com.br de uma letra existem, todos de "
                   "1996 e 1997."),
        corpo=corpo, indexavel=False)


def _com_historia(letra: str, caminho: str) -> dict:
    with open(caminho, encoding="utf-8") as f:
        p = pg.ler_fragmento(f.read(), slug(letra))
    scripts = ("disputa.js", "letra.js") if letra in EXISTEM else ()
    return dict(
        slug=p.slug, tipo="pagina", secao="insights", data=p.data or DATA,
        modificado=p.modificado, titulo=p.titulo, titulo_busca=p.titulo_busca,
        descricao=p.descricao, imagem=p.imagem, scripts=scripts,
        corpo=p.corpo.rstrip() + "\n" + duas_letras(letra) + navegacao(letra))


def paginas(modelo: str) -> list[dict]:
    saida = []
    for letra in LETRAS:
        caminho = os.path.join(modelo, "letras", f"{letra}.html")
        saida.append(_com_historia(letra, caminho) if os.path.exists(caminho)
                     else _sem_historia(letra))
    return saida
