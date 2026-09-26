"""
Graficos dos insights: SVG estatico, gerado em Python, com os numeros ao lado.

Funcoes puras: recebem dados, devolvem texto. Quem grava o resultado nas
paginas e historico_listas.py (subcomando `graficos`).

POR QUE SVG ESTATICO (13/09/2026)

- A CSP do site e `style-src 'self'` e `script-src 'self'`: nada de <style>,
  atributo style ou script inline. SVG com atributos de apresentacao e
  classes passa, e as classes vivem em site_modelo/extra.css, onde pegam os
  mesmos tokens de cor do tema claro e escuro (--azul, --suave, --borda...).
- O Google e os agentes leem o numero, nao o desenho. Todo grafico sai
  dentro de <figure> com legenda, fonte e a TABELA dos dados num <details>.
  O espelho em Markdown ignora o <svg> e fica com a tabela.
- Passar o mouse mostra o valor: cada marca leva um <title>, que o navegador
  exibe como dica sem precisar de script.

Regras de desenho (skill de dataviz): marca fina, ponta arredondada de 4 px
presa na base, grade de 1 px recessiva, rotulo seletivo (so o que a historia
precisa), texto nunca na cor da serie, uma serie por grafico sempre que der.
"""

from __future__ import annotations

import html
import math
from datetime import date

LARGURA = 640
FONTE = 13


def _e(s) -> str:
    return html.escape(str(s), quote=True)


def num(n, casas: int = 0) -> str:
    """1234567 -> 1.234.567 ; 0.994 com casas=1 -> 0,9"""
    if casas:
        return f"{n:,.{casas}f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return f"{int(round(n)):,}".replace(",", ".")


def compacto(n) -> str:
    """120000 -> 120 mil ; 1500000 -> 1,5 mi"""
    if n >= 1_000_000:
        return num(n / 1_000_000, 1).rstrip("0").rstrip(",") + " mi"
    if n >= 1000:
        return num(n / 1000) + " mil"
    return num(n)


def _passo(maximo: float, marcas: int = 4) -> float:
    bruto = maximo / marcas
    mag = 10 ** math.floor(math.log10(bruto)) if bruto > 0 else 1
    for m in (1, 2, 5, 10):
        if bruto <= m * mag:
            return m * mag
    return 10 * mag


def _barra(x: float, y_base: float, largura: float, altura: float, classe: str, dica: str) -> str:
    """Coluna com ponta arredondada no topo e base reta."""
    if altura <= 0:
        return ""
    r = min(4.0, largura / 2, altura)
    x2, y = x + largura, y_base - altura
    d = (f"M{x:.1f},{y_base:.1f}V{y + r:.1f}Q{x:.1f},{y:.1f} {x + r:.1f},{y:.1f}"
         f"H{x2 - r:.1f}Q{x2:.1f},{y:.1f} {x2:.1f},{y + r:.1f}V{y_base:.1f}Z")
    return f'<path class="{classe}" d="{d}"><title>{_e(dica)}</title></path>'


def _svg(altura: int, corpo: str, titulo: str) -> str:
    return (f'<svg viewBox="0 0 {LARGURA} {altura}" role="img" aria-label="{_e(titulo)}" '
            f'font-size="{FONTE}">{corpo}</svg>')


def _grade(esq: int, dir_: int, topo: int, base: int, maximo: float, fmt=compacto) -> tuple[str, float]:
    passo = _passo(maximo)
    teto = math.ceil(maximo / passo) * passo
    linhas = []
    v = 0.0
    while v <= teto + 1e-9:
        y = base - (base - topo) * v / teto
        linhas.append(f'<line class="g-grade" x1="{esq}" x2="{dir_}" y1="{y:.1f}" y2="{y:.1f}"/>'
                      f'<text class="g-eixo" x="{esq - 6}" y="{y + 4:.1f}" text-anchor="end">{_e(fmt(v))}</text>')
        v += passo
    return "".join(linhas), teto


def colunas_no_tempo(pontos: list[tuple[date, float, str, str]], titulo: str,
                     altura: int = 300, fmt=compacto, anotacoes: dict | None = None) -> str:
    """
    Uma coluna por mes, posicionada no calendario: mes sem dado fica vazio,
    e o buraco aparece. pontos = (data, valor, classe, dica).
    anotacoes = {data: texto} escreve um rotulo acima daquela coluna.
    """
    esq, dir_, topo, base = 56, LARGURA - 12, 28, altura - 30
    primeiro, ultimo = pontos[0][0], pontos[-1][0]
    meses = (ultimo.year - primeiro.year) * 12 + ultimo.month - primeiro.month + 1
    faixa = (dir_ - esq) / meses
    larg = max(1.5, min(24.0, faixa - 2))
    grade, teto = _grade(esq, dir_, topo, base, max(v for _, v, _, _ in pontos), fmt)
    marcas = []
    for d, v, classe, dica in pontos:
        i = (d.year - primeiro.year) * 12 + d.month - primeiro.month
        x = esq + i * faixa + (faixa - larg) / 2
        marcas.append(_barra(x, base, larg, (base - topo) * v / teto, classe, dica))
        if anotacoes and d in anotacoes:
            xc = x + larg / 2
            yv = base - (base - topo) * v / teto
            marcas.append(f'<text class="g-rotulo" x="{xc:.1f}" y="{yv - 6:.1f}" text-anchor="middle">{_e(anotacoes[d])}</text>')
    anos = []
    for ano in range(primeiro.year, ultimo.year + 1):
        i = max(0, (ano - primeiro.year) * 12 + 1 - primeiro.month)
        if i < meses and (ano > primeiro.year or primeiro.month <= 9):
            x = esq + i * faixa
            anos.append(f'<line class="g-eixo-linha" x1="{x:.1f}" x2="{x:.1f}" y1="{base}" y2="{base + 5}"/>'
                        f'<text class="g-eixo" x="{x + 3:.1f}" y="{base + 18}">{ano}</text>')
    eixo = f'<line class="g-eixo-linha" x1="{esq}" x2="{dir_}" y1="{base}" y2="{base}"/>'
    return _svg(altura, grade + "".join(marcas) + eixo + "".join(anos), titulo)


def colunas(pontos: list[tuple[str, float, str, str]], titulo: str, altura: int = 260,
            fmt=compacto, rotulos: set | None = None, valor_no_topo: set | None = None) -> str:
    """Colunas categoricas. rotulos = quais x escrever (None: todos). pontos = (x, valor, classe, dica)."""
    esq, dir_, topo, base = 56, LARGURA - 12, 24, altura - 30
    n = len(pontos)
    faixa = (dir_ - esq) / n
    larg = max(2.0, min(24.0, faixa * 0.7))
    grade, teto = _grade(esq, dir_, topo, base, max(v for _, v, _, _ in pontos), fmt)
    partes = []
    for i, (x_rot, v, classe, dica) in enumerate(pontos):
        x = esq + i * faixa + (faixa - larg) / 2
        h = (base - topo) * v / teto
        partes.append(_barra(x, base, larg, h, classe, dica))
        if rotulos is None or x_rot in rotulos:
            partes.append(f'<text class="g-eixo" x="{x + larg / 2:.1f}" y="{base + 18}" text-anchor="middle">{_e(x_rot)}</text>')
        if valor_no_topo and x_rot in valor_no_topo:
            partes.append(f'<text class="g-rotulo" x="{x + larg / 2:.1f}" y="{base - h - 6:.1f}" text-anchor="middle">{_e(fmt(v))}</text>')
    eixo = f'<line class="g-eixo-linha" x1="{esq}" x2="{dir_}" y1="{base}" y2="{base}"/>'
    return _svg(altura, grade + "".join(partes) + eixo, titulo)


def pequenos_multiplos(series: dict[str, list[tuple[date, float]]], titulo: str,
                       colunas_grade: int = 2, altura_painel: int = 110) -> str:
    """
    Um painel por serie, mesmo eixo de tempo, escala propria (o maximo de cada
    painel vem escrito). Uma coluna fina por rodada; a do pico em cor cheia.
    """
    nomes = list(series)
    linhas_grade = math.ceil(len(nomes) / colunas_grade)
    gap_x, gap_y = 24, 18
    larg_p = (LARGURA - gap_x * (colunas_grade - 1)) / colunas_grade
    altura = linhas_grade * (altura_painel + gap_y)
    todas = [d for s in series.values() for d, _ in s]
    t0, t1 = min(todas), max(todas)
    meses = (t1.year - t0.year) * 12 + t1.month - t0.month

    def xm(d):
        return ((d.year - t0.year) * 12 + d.month - t0.month) / meses

    partes = []
    for k, nome in enumerate(nomes):
        c, l = k % colunas_grade, k // colunas_grade
        ox, oy = c * (larg_p + gap_x), l * (altura_painel + gap_y)
        topo, base = oy + 30, oy + altura_painel - 6
        pts = sorted(series[nome])
        maximo = max(v for _, v in pts) or 1
        coords = [(ox + xm(d) * larg_p, base - (base - topo) * v / maximo) for d, v in pts]
        pico_d, pico_v = max(pts, key=lambda p: p[1])
        partes.append(f'<text class="g-rotulo" x="{ox:.1f}" y="{oy + 14}" font-weight="600">{_e(nome)}</text>'
                      f'<text class="g-eixo" x="{ox + larg_p:.1f}" y="{oy + 14}" text-anchor="end">'
                      f'pico: {num(pico_v)} em {pico_d.month:02d}/{pico_d.year}</text>'
                      f'<line class="g-eixo-linha" x1="{ox:.1f}" x2="{ox + larg_p:.1f}" y1="{base}" y2="{base}"/>')
        # uma coluna fina por rodada: mes sem copia fica vazio, sem linha inventada
        faixa = larg_p / (meses + 1)
        larg = max(1.2, faixa * 0.72)
        for (d, v), (x, y) in zip(pts, coords):
            classe = "g-s1" if (d, v) == (pico_d, pico_v) else "g-s1 g-fraco"
            partes.append(_barra(x, base, larg, base - y, classe,
                                 f"{nome}: {num(v)} nomes na rodada de {d.month:02d}/{d.year}"))
        for ano in range(t0.year + 1, t1.year + 1, 2):
            d = date(ano, 1, 1)
            if t0 <= d <= t1:
                x = ox + xm(d) * larg_p
                partes.append(f'<text class="g-eixo" x="{x:.1f}" y="{base + 13}" text-anchor="middle" font-size="11">{ano}</text>')
    return _svg(int(altura), "".join(partes), titulo)


def tabela(cabecalho: list[str], linhas: list[list], numericas: set[int] | None = None) -> str:
    numericas = numericas or set()

    def cel(tag, i, v):
        classe = ' class="num"' if i in numericas else ""
        return f"<{tag}{classe}>{_e(v)}</{tag}>"

    th = "".join(cel("th", i, c) for i, c in enumerate(cabecalho))
    corpo = "".join("<tr>" + "".join(cel("td", i, v) for i, v in enumerate(l)) + "</tr>" for l in linhas)
    return f'<table class="tabela-doc"><thead><tr>{th}</tr></thead><tbody>{corpo}</tbody></table>'


def figura(svg: str, legenda: str, fonte: str, tabela_html: str = "", legenda_cores: list[tuple[str, str]] | None = None) -> str:
    """<figure> com o grafico, a chave de cores (se houver), a legenda e os numeros."""
    chave = ""
    if legenda_cores:
        # " · " entre os itens: sem ele o espelho em Markdown cola as legendas.
        # Num span que o CSS esconde: solto, virava um ponto perdido na quebra.
        chave = '<p class="g-chave">' + '<span class="g-sep" aria-hidden="true"> · </span>'.join(
            f'<span><span class="g-amostra {c}" aria-hidden="true"></span>{_e(t)}</span>' for c, t in legenda_cores) + "</p>"
    numeros = (f"<details><summary>Ver os números</summary>{tabela_html}</details>" if tabela_html else "")
    return (f'<figure class="grafico">{chave}<div class="g-quadro">{svg}</div>'
            f'<figcaption>{legenda} <span class="g-fonte">Fonte: {fonte}</span></figcaption>'
            f"{numeros}</figure>")


def figura_candidatos(dados: dict) -> str:
    """
    A pagina Dados: quantas pessoas pediram cada nome disputado da rodada
    aberta. Sai do instantaneo a cada build (paginas.preencher_numeros), entao
    toda frase com numero e escrita aqui, nunca no fragmento.

    So LIBERACAO_DISPUTADA (dois ou mais pedidos nesta rodada). Os nomes
    conferidos sao escolhidos pela nota: a legenda diz isso.
    """
    status = dados.get("status") or []
    if "LIBERACAO_DISPUTADA" not in status:
        return ""
    disputado = status.index("LIBERACAO_DISPUTADA")
    return figura_de_pedidos(
        [it[2] for it in dados.get("itens") or [] if it[1] == disputado],
        "consulta pública do Registro.br; só os nomes com melhor nota que o Liberados conferiu, "
        "não a lista inteira")


def figura_de_pedidos(pedidos: list[int], fonte: str, fechada: bool = False) -> str:
    """
    O histograma de pedidos por nome disputado (2, 3, ..., 10 ou mais). Serve
    a rodada aberta, do instantaneo, e a fechada, de docs/historico/disputas.json:
    muda so o tempo do verbo e a fonte.
    """
    contagem = [0] * 9                      # 2, 3, ..., 9, 10 ou mais
    for n in pedidos:
        if n >= 2:
            contagem[min(n, 10) - 2] += 1
    total = sum(contagem)
    if not total:
        return ""
    rotulos = [str(k) for k in range(2, 10)] + ["10+"]
    pontos = [(r, v, "g-s1", f"{num(v)} nomes com {r} {'ou mais ' if r == '10+' else ''}pedidos")
              for r, v in zip(rotulos, contagem)]
    poucos = contagem[0] + contagem[1]
    return figura(
        colunas(pontos, "Quantas pessoas pediram cada nome disputado", fmt=num,
                valor_no_topo=set(rotulos)),
        f"Dos {num(total)} nomes disputados, {num(round(100 * poucos / total))}% "
        f"{'tiveram' if fechada else 'têm'} só 2 ou 3 pessoas interessadas. Cada coluna "
        "conta os nomes pelo número de pedidos.",
        fonte,
        tabela(["Pedidos", "Nomes"], [[r, num(v)] for r, v in zip(rotulos, contagem)], {1}))
