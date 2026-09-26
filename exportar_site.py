#!/usr/bin/env python3
"""
Gera o site estatico em site/, para publicar.

    python3 exportar_site.py

O site publicado e SOMENTE LEITURA: mesma interface, mesmos filtros, mas
lendo um instantaneo em vez de consultar o Registro.br. A varredura continua
sendo local, porque depende de rodar por horas e de nao compartilhar IP.

Nada de pessoal vai junto: sem tickets, sem ofertas, sem os dominios da conta.
So dado de dominio, que e publico.
"""

import base64
import hashlib
import os
import re
import shutil

from garimpo.adaptadores import registrobr
from garimpo.adaptadores.repositorio import agora
from garimpo.casos import instantaneo, lembretes, pool
from garimpo.contexto import padrao
from garimpo.web import paginas

MODELO = os.path.join(padrao.raiz, "site_modelo")

# IndexNow (17/09/2026): avisa o Bing na hora em vez de esperar o recrawl.
# Importa porque a lista muda todo mes e o dados.json e refeito de 4 em 4 h,
# e porque o ChatGPT navega pelo indice do Bing: frescor la e frescor nele.
# A chave e publica por desenho; o segredo nao existe neste protocolo.
CHAVE_INDEXNOW = "dae3ca0846365e83e669c9ef4d7fb518"

# index.html nao esta aqui: desde 11/09/2026 toda pagina, a ferramenta
# inclusive, sai de site_modelo/conteudo/ + layout.html (garimpo/web/paginas)
ESTATICOS = ("app.js", "tema.js", "sw.js", "_headers", ".assetsignore", "og.png", "compartilhar.js",
             "agenda.js", "ficha.js", "seu-nome.js", "letra.js", "erro404.js",
             "favicon.svg", "favicon-48.png", "favicon.ico", "apple-touch-icon.png",
             # a chave do IndexNow (17/09/2026): o protocolo exige que ela
             # esteja servida em https://<host>/<chave>.txt, com a propria
             # chave dentro, senao o Bing recusa a submissao. Trocar a chave
             # e trocar os dois lugares: este arquivo e CHAVE_INDEXNOW no
             # workflow. Nao e segredo: fica publica por desenho.
             f"{CHAVE_INDEXNOW}.txt")
# pastas do site_modelo copiadas inteiras (a fonte propria e a licenca dela)
PASTAS = ("fontes",)
# scripts que o app local (web/) tambem usa
COMPARTILHADOS = ("disputa.js", "pontocom.js")

SCRIPT_INLINE = re.compile(r"<script>(.*?)</script>", re.S)


def ler_cabecalhos(texto: str) -> list[tuple[str, list[tuple[str, str]]]]:
    """
    Le um arquivo _headers do Cloudflare: [(padrao, [(nome, valor), ...])].

    Linha sem recuo abre uma regra; linha recuada e um cabecalho dela;
    # e comentario.
    """
    regras = []
    for linha in texto.splitlines():
        if not linha.strip() or linha.lstrip().startswith("#"):
            continue
        if not linha[0].isspace():
            regras.append((linha.strip(), []))
        else:
            nome, _, valor = linha.strip().partition(":")
            regras[-1][1].append((nome.strip(), valor.strip()))
    return regras


def fixar_hash_da_csp(diretorio: str) -> str | None:
    """
    Calcula o sha256 do script inline e grava na CSP do _headers.

    O script de tema precisa ser inline: aplicado depois da pintura, o tema
    errado apareceria por um instante. Mas a CSP e `script-src 'self'`, que
    bloqueia inline.

    A saida e o hash, que mantem a politica restrita. Calcular no build, e
    nao a mao, evita o pior caso: alguem edita o script, o hash nao bate, o
    navegador bloqueia em silencio e o tema volta a piscar sem ninguem notar.
    """
    caminho_html = os.path.join(diretorio, "index.html")
    caminho_cab = os.path.join(diretorio, "_headers")
    if not (os.path.exists(caminho_html) and os.path.exists(caminho_cab)):
        return None

    html = open(caminho_html, encoding="utf-8").read()
    achado = SCRIPT_INLINE.search(html)
    if not achado:
        return None

    digest = hashlib.sha256(achado.group(1).encode("utf-8")).digest()
    hash_csp = "sha256-" + base64.b64encode(digest).decode("ascii")

    texto = open(caminho_cab, encoding="utf-8").read()
    # Troca so o hash anterior (se houver): o que vem depois dele no
    # script-src, como a origem do beacon do Web Analytics, fica.
    texto = re.sub(r"(?im)^(\s+content-security-policy:.*?script-src 'self')(?: 'sha256-[^']+')?",
                   lambda m: f"{m.group(1)} '{hash_csp}'", texto)
    with open(caminho_cab, "w", encoding="utf-8") as f:
        f.write(texto)
    return hash_csp


def montar_css(destino: str) -> None:
    """
    Junta o CSS compartilhado com o que so o site usa.

    Antes site_modelo/style.css era uma copia manual de web/style.css mais os
    extras, e bastava esquecer de refazer a copia para o site publicado sair
    com o estilo antigo. Aconteceu com o tema escuro: os seletores novos
    existiam no app local e nao no site.
    """
    base = open(os.path.join(padrao.raiz, "web", "style.css"),
                encoding="utf-8").read()
    extra = ""
    caminho = os.path.join(MODELO, "extra.css")
    if os.path.exists(caminho):
        extra = open(caminho, encoding="utf-8").read()
    with open(os.path.join(destino, "style.css"), "w", encoding="utf-8") as f:
        f.write(base + "\n\n" + extra)


def copiar_historico(destino: str) -> int:
    """
    Publica as contagens da serie historica (docs/historico/*.json) em
    /dados/historico/, para quem quiser citar ou refazer os graficos. Sao so
    agregados e nomes de dominio; as listas brutas ficam em work/.
    Tambem publica as imagens de compartilhamento dos insights (site_modelo/og/)
    e as telas guardadas das paginas de cada letra (site_modelo/imagens/letras/).
    """
    n = 0
    pares = ((os.path.join(padrao.raiz, "docs", "historico"), os.path.join(destino, "dados", "historico"), ".json"),
             (os.path.join(MODELO, "og"), os.path.join(destino, "og"), ".png"),
             (os.path.join(MODELO, "imagens", "letras"), os.path.join(destino, "imagens", "letras"), ".png"))
    for origem, alvo, ext in pares:
        if not os.path.isdir(origem):
            continue
        os.makedirs(alvo, exist_ok=True)
        for nome in sorted(os.listdir(origem)):
            if nome.endswith(ext):
                shutil.copy2(os.path.join(origem, nome), os.path.join(alvo, nome))
                n += 1
    # o indice da ficha "quando esse dominio volta?": 256 fatias, o navegador
    # baixa so a do nome consultado (garimpo/dominio/passagens.py)
    # o indice "este dominio ja teve site?" (18/09/2026), no mesmo esquema de
    # fatias: montado na maquina local por arquivar_wayback.py (do runner o
    # Internet Archive recusa a conexao, limitacao F9) e so servido aqui
    for pasta in ("passagens", "arquivo"):
        origem = os.path.join(padrao.raiz, "docs", "historico", pasta)
        if os.path.isdir(origem):
            alvo = os.path.join(destino, "dados", "historico", pasta)
            shutil.rmtree(alvo, ignore_errors=True)
            shutil.copytree(origem, alvo)
            n += len(os.listdir(alvo))
    return n


def main():
    ctx = padrao
    repo = ctx.repo
    os.makedirs(ctx.site, exist_ok=True)

    for nome in ESTATICOS:
        origem = os.path.join(MODELO, nome)
        if os.path.exists(origem):
            shutil.copy2(origem, os.path.join(ctx.site, nome))
    for pasta in PASTAS:
        origem = os.path.join(MODELO, pasta)
        if os.path.isdir(origem):
            shutil.copytree(origem, os.path.join(ctx.site, pasta), dirs_exist_ok=True)

    montar_css(ctx.site)
    copiar_historico(ctx.site)
    # o "quem disputa" e o ".com do mesmo nome" sao um so para o site e o app
    # local: moram em web/
    for nome in COMPARTILHADOS:
        shutil.copy2(os.path.join(padrao.raiz, "web", nome), os.path.join(ctx.site, nome))

    # o meta e a fonte, mas nem todo caminho de importacao o preenche;
    # o cabecalho do arquivo ja baixado serve de rede de seguranca
    janela_inicio = repo.meta("rodada_inicio")
    janela_fim = repo.meta("rodada_fim")
    if not janela_inicio:
        janela_inicio, janela_fim = registrobr.janela_do_cache(ctx.trabalho)
        if janela_inicio:
            repo.set_meta("rodada_inicio", janela_inicio)
            repo.set_meta("rodada_fim", janela_fim)
    meta = instantaneo.Metadados(
        gerado_em=agora(),
        total_rodada=int(repo.meta("total_liberacao") or 0),
        total_elegiveis=int(repo.meta("total_elegiveis") or 0),
        nao_verificados=repo.contar("status IS NULL"),
        inicio=janela_inicio,
        fim=janela_fim,
        nota_minima=int(repo.meta("nota_minima") or pool.NOTA_MINIMA),
        em_leilao_em=repo.meta("em_leilao_em"),
    )
    dados = instantaneo.exportar(repo.verificados(), meta,
                                 pessoas=ctx.vocabularios.pessoas(print),
                                 serie=repo.serie_ritmo(),
                                 primeiro=repo.ticket_primeiro())
    tamanho = instantaneo.escrever(dados, ctx.instantaneo)
    # as paginas levam numeros do instantaneo gravados no HTML, por isso
    # vem depois dele; e o hash da CSP le o index.html gerado, por isso
    # vem antes do hash
    escritos = paginas.gerar(MODELO, ctx.site, dados)
    competitivo = dados["status"].index("COMPETITIVO")
    n_lembretes = lembretes.escrever(
        os.path.join(ctx.site, "lembretes"),
        [it[0] for it in dados["itens"] if it[1] == competitivo],
        lembretes.fim_do_leilao(janela_fim))
    # as rodadas dos proximos dois anos: a ficha preve volta ate ~6 meses
    # depois do vencimento, e a pagina inicial oferece a proxima
    n_rodadas = lembretes.escrever_rodadas(
        os.path.join(ctx.site, "lembretes"), paginas.rodadas_para_lembrete(dados))
    hash_csp = fixar_hash_da_csp(ctx.site)

    print("site/ gerado")
    print(f"  {len(dados['itens'])} dominios verificados")
    print(f"  {meta.nao_verificados} ainda nao verificados")
    print(f"  dados.json: {tamanho / 1024:.0f} KB")
    print(f"  lembretes: {n_lembretes} leiloes e {n_rodadas} rodadas com .ics")
    print(f"  paginas: {sum(1 for e in escritos if e.endswith('index.html'))}, "
          f"canonical em {paginas.BASE_URL}")
    print(f"  gerado em: {meta.gerado_em}")
    if hash_csp:
        print(f"  csp: script inline liberado por hash ({hash_csp[:22]}...)")


if __name__ == "__main__":
    main()
