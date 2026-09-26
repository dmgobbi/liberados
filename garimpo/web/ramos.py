"""
Uma pagina por ramo, e dois recortes, com os nomes da rodada: /dominios/pet/,
/dominios/curtos/... Geradas a cada build, a partir do instantaneo.

POR QUE (14/09/2026). Quem pergunta a um assistente de IA ou ao Google por
"dominios .br disponiveis de pet" so e atendido por pagina indexada: nenhum
assistente de conversa monta sozinho uma URL com parametro
(docs/ia-e-agentes.md). E "nome para empresa de ..." busca 1,5 vez mais que
"registro.br" (docs/perguntas-do-publico.md). Os 19 ramos ja existiam nos dois
JSON, para o filtro da pagina inicial.

REGRAS, para a pagina nao virar lista gerada em serie (politica de spam do
Google, 28/08/2026):
  - dado proprio e datado: a situacao conferida no Registro.br, com a hora da
    leitura e o denominador (quantos da rodada, quantos conferidos);
  - o texto muda com a fase: rodada aberta convida a se candidatar; rodada
    fechada mostra o que ficou livre e o que volta na proxima;
  - nome com possivel marca de terceiro fica de fora (marca e exclusao);
  - ramo com menos de MINIMO nomes listaveis sai com noindex, fora do
    sitemap e do llms.txt, mas a URL continua de pe (link compartilhado nao
    quebra no mes em que o ramo encolhe).

Os indices dos itens sao os do instantaneo (garimpo/casos/instantaneo.py) e
da rodada inteira (garimpo/casos/todos.py).
"""

from __future__ import annotations

import html
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Callable

from ..dominio import calendario, categorias

MINIMO = 10
NA_PAGINA = 60
SECAO = "dominios"
MESES = ("janeiro fevereiro março abril maio junho julho agosto setembro "
         "outubro novembro dezembro").split()

# como cada ramo entra na frase "Domínios .br ___"
FRASES = {
    "alimentacao": "de alimentação", "moda": "de moda e acessórios",
    "beleza": "de beleza e estética", "saude": "de saúde", "imoveis": "de imóveis",
    "construcao": "de construção e reforma", "automotivo": "do ramo automotivo",
    "pet": "de pet", "educacao": "de educação e cursos",
    "juridico": "de advocacia e contabilidade", "tecnologia": "de tecnologia",
    "turismo": "de turismo e hospedagem", "financas": "de finanças e seguros",
    "esporte": "de esporte e academia", "transporte": "de transporte e entregas",
    "eventos": "de eventos e festas", "marketing": "de marketing e comunicação",
    "casa": "de casa e decoração", "pessoas": "com nome de pessoa",
}
SLUGS = {"pessoas": "nomes-de-pessoas"}

# indices do instantaneo e da rodada inteira
D, SS, C, N, E, M, MK, EL, VF, CL, CT = range(11)
T_ROTULO, T_EXT, T_NOTA, T_MOTIVOS, T_MARCA, T_CAT = range(6)
RISCO = 2


@dataclass
class Recorte:
    slug: str
    frase: str
    nome: str                                   # rotulo curto, para a lista de ramos
    no_pool: Callable[[list, dict], bool]
    na_rodada: Callable[[list, dict], bool]
    filtro_inicio: str = ""                     # parametro ?ramo= da pagina inicial


def _rotulo(dominio: str) -> tuple[str, str]:
    r, _, ext = dominio.partition(".")
    return r, ext


def _recortes(dados: dict, todos: dict) -> list[Recorte]:
    tabela = dados.get("categorias") or categorias.tabela()
    saida = []
    for bit, cat in enumerate(tabela):
        nome = cat["nome"]
        mascara = 1 << bit
        saida.append(Recorte(
            slug=SLUGS.get(nome, nome), frase=FRASES.get(nome, f"de {cat['rotulo'].lower()}"),
            nome=cat["rotulo"],
            no_pool=lambda it, d, m=mascara: bool((it[CT] if len(it) > CT else 0) & m),
            na_rodada=lambda t, tt, m=mascara: bool((t[T_CAT] or 0) & m),
            filtro_inicio=nome))
    motivos = dados.get("motivos") or []
    mot_todos = todos.get("motivos") or []
    ext_todos = todos.get("extensoes") or []
    pt = motivos.index("palavra em português") if "palavra em português" in motivos else -1
    pt_t = mot_todos.index("palavra em português") if "palavra em português" in mot_todos else -1

    def curto_pool(it, d):
        r, ext = _rotulo(it[D])
        return ext == "com.br" and 4 <= len(r) <= 7 and r.isalpha() and pt in it[M]

    def curto_rodada(t, tt):
        return (ext_todos[t[T_EXT]] == "com.br" and 4 <= len(t[T_ROTULO]) <= 7
                and t[T_ROTULO].isalpha() and pt_t in t[T_MOTIVOS])

    saida.append(Recorte("curtos", "curtos em português", "Palavras curtas em português",
                         curto_pool, curto_rodada))
    saida.append(Recorte(
        "tres-letras", "de três letras", "Três letras",
        lambda it, d: (lambda r, e: e == "com.br" and len(r) == 3 and r.isalpha())(*_rotulo(it[D])),
        lambda t, tt: ext_todos[t[T_EXT]] == "com.br" and len(t[T_ROTULO]) == 3 and t[T_ROTULO].isalpha()))
    return saida


# ------------------------------------------------------------------ fases

def _data(iso: str | None) -> datetime | None:
    try:
        return datetime.fromisoformat(str(iso).replace("Z", "+00:00"))
    except ValueError:
        return None


def _dia(d: datetime | None) -> str:
    return d.astimezone(calendario.BRASILIA).strftime("%d/%m/%Y") if d else "-"


def _dia_hora(d: datetime | None) -> str:
    return d.astimezone(calendario.BRASILIA).strftime("%d/%m/%Y às %Hh%M") if d else "-"


def _num(n: int) -> str:
    return f"{n:,}".replace(",", ".")


@dataclass
class Fase:
    fechada: bool
    leiloes_acabaram: bool
    inicio: datetime | None
    fim: datetime | None
    gerado: datetime | None
    proxima: datetime | None
    antes: bool = False          # a lista saiu e a rodada ainda nao abriu (18/09/2026)
    sem_leitura: bool = False    # nenhum nome conferido ainda na rodada desta lista

    @property
    def mes(self) -> str:
        if not self.inicio:
            return ""
        local = self.inicio.astimezone(calendario.BRASILIA)
        return f"{MESES[local.month - 1]} de {local.year}"


def fase_de(dados: dict) -> Fase:
    rodada = dados.get("rodada") or {}
    inicio, fim, gerado = _data(rodada.get("inicio")), _data(rodada.get("fim")), _data(dados.get("gerado_em"))
    fechada = bool(fim and gerado and gerado >= fim)
    antes = bool(inicio and gerado and gerado < inicio)
    # na virada o varrer.py esquece as leituras da rodada anterior e so volta
    # a consultar com a rodada aberta: ate la, o que se sabe e a lista
    sem_leitura = not fechada and (antes or not dados.get("itens"))
    return Fase(fechada=fechada,
                leiloes_acabaram=bool(fechada and gerado >= fim + timedelta(hours=36)),
                inicio=inicio, fim=fim, gerado=gerado,
                proxima=calendario.mes_seguinte(inicio) if inicio else None,
                antes=antes, sem_leitura=sem_leitura)


def _hora(d: datetime | None) -> str:
    """15h, 15h30, em horario de Brasilia."""
    if not d:
        return "-"
    local = d.astimezone(calendario.BRASILIA)
    return f"{local.hour}h{local.minute:02d}" if local.minute else f"{local.hour}h"


def _datas_da_lista(fase: Fase) -> str:
    """'A lista de outubro saiu; as candidaturas abrem em 14/10 as 15h e vao ate 21/10 as 15h'"""
    mes = fase.mes.split(" de ")[0]
    abre, fecha = (d.astimezone(calendario.BRASILIA) for d in (fase.inicio, fase.fim))
    return (f"A lista de {mes} saiu; as candidaturas abrem em {abre:%d/%m} às {_hora(abre)} "
            f"e vão até {fecha:%d/%m} às {_hora(fecha)}")


def situacao(it: list, dados: dict, fase: Fase) -> tuple[int, str]:
    """(ordem na pagina, texto): o que da para fazer agora vem primeiro."""
    nome = (dados.get("status") or [])[it[SS]] if it[SS] >= 0 else ""
    volta = f"volta na rodada de {_dia(fase.proxima)[:5]}" if fase.proxima else "volta na próxima rodada"
    if nome == "LIVRE":
        return 0, "livre agora"
    if nome == "LIBERACAO_LIVRE":
        return (1, "fechou sem candidato visível") if fase.fechada else (0, "sem candidato visível")
    if nome == "AGUARDANDO_LIBERACAO" or (nome == "LIBERACAO_DISPUTADA" and fase.fechada and not it[E]):
        return 2, f"travou: {volta}"
    if nome == "LIBERACAO_DISPUTADA":
        return 2, f"{it[C]} candidatos" if it[C] >= 2 else "disputado"
    if nome == "COMPETITIVO":
        return 3, "foi a leilão" if fase.leiloes_acabaram else "em leilão"
    return 9, ""                       # registrado, indisponivel: nao entra


# ------------------------------------------------------------------ paginas

def _contagens(listados: list[tuple[int, str, list]]) -> dict[str, int]:
    conta: dict[str, int] = {}
    for _, texto, _ in listados:
        chave = texto.split(":")[0]
        chave = "disputado" if chave.endswith("candidatos") else chave
        conta[chave] = conta.get(chave, 0) + 1
    return conta


def _entrada(r: Recorte, n_rodada: int, total: int, conferidos: int,
             conta: dict[str, int], fase: Fase) -> str:
    quando = _dia_hora(fase.gerado)
    base = (f'<p class="entrada">Na rodada de liberação de {fase.mes} '
            f'(de {_dia(fase.inicio)} a {_dia(fase.fim)}), o Registro.br devolveu ao mercado '
            f'<strong>{_num(n_rodada)}</strong> domínios .br {r.frase}, de {_num(total)} '
            f'da lista. ')
    if fase.sem_leitura:
        # nada conferido ainda: so o que a lista diz, e quando a conferencia comeca
        base = (f'<p class="entrada">A lista da rodada de liberação de {fase.mes} traz '
                f'<strong>{_num(n_rodada)}</strong> domínios .br {r.frase}, de {_num(total)} '
                'da lista. ')
        # a data e da abertura, nao da primeira leitura: vem antes dela na frase
        abertura = f'em {_dia(fase.inicio)[:5]}, às {_hora(fase.inicio)}'
        comeca = (f"começa com a rodada, {abertura}." if fase.antes
                  else f"começou com a rodada, {abertura}, e a primeira leitura chega nas "
                  "próximas horas.")
        return (base + (f'{_datas_da_lista(fase)} (horário de Brasília). ' if fase.antes else
                        f'Candidatar-se é de graça até {_dia_hora(fase.fim)}. ')
                + f'Abaixo, os de melhor nota; a conferência de quem já pediu cada nome {comeca}</p>')
    if not fase.fechada:
        return (base + f'Conferimos no Registro.br os {_num(conferidos)} de melhor nota: '
                f'{_num(conta.get("sem candidato visível", 0))} estavam sem candidato visível, '
                f'{_num(conta.get("disputado", 0))} disputados e '
                f'{_num(conta.get("em leilão", 0))} em leilão (leitura até {quando}). '
                f'Candidatar-se é de graça até {_dia_hora(fase.fim)}.</p>')
    return (base + f'A rodada fechou. Dos {_num(conferidos)} que conferimos, '
            f'{_num(conta.get("livre agora", 0))} já estão livres para registrar na hora, '
            f'{_num(conta.get("travou", 0))} travaram e voltam na próxima rodada, e '
            f'{_num(conta.get("fechou sem candidato visível", 0))} fecharam sem candidato visível '
            f'e esperam nova conferência (leitura até {quando}).</p>')


def _tabela(listados: list[tuple[int, str, list]], cabecalho: str = "Situação na última leitura") -> str:
    """
    `rel="nofollow"` nos links por nome (20/09/2026). A ficha e montada no
    navegador e tem canonical para `/quando-volta/`, entao `?d=<nome>` nunca
    e indexada: cada uma que o Googlebot visita e rastreio gasto num site
    novo. No Search Console de 19/09 elas eram 27 das 48 paginas em
    "rastreada/detectada, mas nao indexada". O link continua igual para quem
    le a pagina.
    """
    linhas = []
    for _, texto, it in listados[:NA_PAGINA]:
        nome = html.escape(it[D])
        linhas.append(f'<tr><td><a rel="nofollow" href="/quando-volta/?d={nome}">{nome}</a></td>'

                      f"<td>{html.escape(texto)}</td></tr>")
    return ('<div class="rolagem"><table class="tabela-doc tabela-ramo">'
            f"<thead><tr><th>Domínio</th><th>{html.escape(cabecalho)}</th></tr></thead>"
            f'<tbody>{"".join(linhas)}</tbody></table></div>')


def _como_pedir(fase: Fase) -> str:
    if fase.antes:
        return ('<h2 id="como-pedir">Como pedir um desses domínios</h2>\n'
                f"<p>{_datas_da_lista(fase)} (horário de Brasília). Antes da abertura o "
                "Registro.br não aceita candidatura. Depois, entre no Registro.br e candidate-se "
                "ao nome; é de graça. Se só você pedir, o nome é seu pela anuidade; se mais gente "
                "pedir, ninguém leva e ele volta no mês seguinte. Candidatura não tem botão de "
                'cancelar. <a href="/regras-do-br/">As regras</a> e '
                '<a href="/perguntas/#dois-pedidos">o que acontece com dois pedidos</a>.</p>')
    if not fase.fechada:
        return ('<h2 id="como-pedir">Como pedir um desses domínios</h2>\n'
                "<p>Entre no Registro.br e candidate-se ao nome até o fim da rodada, "
                f"{_dia_hora(fase.fim)}. É de graça. Se só você pedir, o nome é seu pela "
                "anuidade; se mais gente pedir, ninguém leva e ele volta no mês seguinte. "
                'Candidatura não tem botão de cancelar. <a href="/regras-do-br/">As regras</a> e '
                '<a href="/perguntas/#dois-pedidos">o que acontece com dois pedidos</a>.</p>')
    lista = calendario.saida_da_lista(fase.proxima).strftime("%d/%m/%Y") if fase.proxima else "-"
    return ('<h2 id="como-pedir">Como pedir um desses domínios</h2>\n'
            "<p><strong>Livre agora</strong>: registre direto no Registro.br, pela anuidade, "
            "sem rodada; quem chega primeiro leva. <strong>Travou</strong>: o nome volta na "
            f"próxima rodada, com a lista em {lista} e candidaturas de graça a partir de "
            f"{_dia_hora(fase.proxima)}. A página inicial põe essa data na sua agenda.</p>")


def _da_lista(r: Recorte, todos: dict, fase: Fase) -> list[tuple[int, str, list]]:
    """
    Os nomes do ramo na lista nova, ainda sem leitura, como linhas do
    instantaneo (so dominio e nota importam aqui). Marca fica de fora, como
    no resto.
    """
    ext = todos.get("extensoes") or []
    marcas = todos.get("marcas") or []
    risco = marcas.index("RISCO") if "RISCO" in marcas else RISCO
    texto = f"a conferir a partir de {_dia(fase.inicio)[:5]}"
    saida = []
    for t in todos.get("itens") or []:
        if t[T_MARCA] == risco or not r.na_rodada(t, todos):
            continue
        dominio = f"{t[T_ROTULO]}.{ext[t[T_EXT]]}" if t[T_EXT] < len(ext) else t[T_ROTULO]
        linha = [dominio, -1, 0, t[T_NOTA] or 0, 0, [], 0, 0, 0, 0, t[T_CAT] or 0]
        saida.append((0, texto, linha))
    return saida


def _pagina(r: Recorte, dados: dict, todos: dict, fase: Fase, outros: str) -> tuple:
    itens = [it for it in dados.get("itens") or []
             if it[SS] >= 0 and it[MK] != RISCO and r.no_pool(it, dados)]
    listados = []
    if fase.sem_leitura:
        # lista nova ainda sem leitura: a pagina fica de pe com o que a lista diz
        listados, itens = _da_lista(r, todos, fase), []
    for it in itens:
        ordem, texto = situacao(it, dados, fase)
        if texto:
            listados.append((ordem, texto, it))
    listados.sort(key=lambda x: (x[0], -x[2][N], len(x[2][D]), x[2][D]))
    n_rodada = sum(1 for t in todos.get("itens") or [] if r.na_rodada(t, todos))
    total = dados.get("total_rodada") or len(todos.get("itens") or [])
    conta = _contagens(listados)
    titulo = f"Domínios .br {r.frase} que voltaram ao mercado"
    descricao = (f"{_num(n_rodada)} domínios .br {r.frase} voltaram ao mercado na rodada de "
                 f"{fase.mes}. "
                 + ("Veja quais ficaram livres e quais voltam na próxima rodada."
                    if fase.fechada else "Veja os de melhor nota e como pedir."
                    if fase.sem_leitura else "Veja quais estão sem candidato e como pedir."))
    if len(descricao) > 160:
        descricao = f"Domínios .br {r.frase} da rodada de {fase.mes}: situação conferida e como pedir."
    corpo = "\n".join([
        _entrada(r, n_rodada, total, len(itens), conta, fase),
        '<h2 id="lista">Os nomes, dos mais relevantes</h2>',
        _tabela(listados, "Situação" if fase.sem_leitura else "Situação na última leitura"),
        (f'<p><a rel="nofollow" href="/?ramo={html.escape(r.filtro_inicio)}">Ver os {_num(len(listados))} na lista, '
         'com filtros</a> · ' if r.filtro_inicio else "<p>")
        + '<a href="/quando-volta/">Consultar outro nome</a>'
        + (' · <a href="/seu-nome/">Seu nome .com.br está livre?</a>' if r.slug == SLUGS["pessoas"] else "")
        + '</p>',
        '<h2 id="como-ler">Como ler esta lista</h2>',
        (f"<p>A lista é a oficial do Registro.br, ordenada pela nota, e nenhum nome foi "
         f"conferido ainda (lista lida até {_dia_hora(fase.gerado)}). Com a rodada aberta, cada "
         "nome ganha a situação conferida no Registro.br: sem candidato visível, disputado ou em "
         "leilão. Os que parecem marca de terceiro ficam de fora. " if fase.sem_leitura else
         "<p>Sem candidato visível quer dizer zero ou um: o Registro.br esconde o candidato "
         'único (<a href="/insights/o-candidato-que-nao-aparece/">por quê</a>). A situação é a '
         f"da última leitura de cada nome, até {_dia_hora(fase.gerado)}; o link de cada domínio "
         "confere de novo, na hora. Só entram os nomes com melhor nota que consultamos, e os que "
         "parecem marca de terceiro ficam de fora. ")
        + 'O ramo é adivinhado por pedaços do nome, então '
        '<a href="/como-selecionamos/">erra às vezes</a>.</p>',
        _como_pedir(fase),
        '<h2 id="outros">Outros ramos</h2>',
        outros,
    ])
    pagina_dados = {
        "slug": f"{SECAO}/{r.slug}", "titulo": titulo, "descricao": descricao, "corpo": corpo,
        "tipo": "lista", "secao": SECAO,
        "titulo_busca": f"Domínios .br {r.frase} disponíveis: a lista de {fase.mes}",
        "data": fase.gerado.astimezone(calendario.BRASILIA).date().isoformat() if fase.gerado else "",
        "indexavel": len(listados) >= MINIMO,
        "lista": tuple(it[D] for _, _, it in listados[:20]),
    }
    return pagina_dados, (r, n_rodada, len(listados), conta)


def paginas(dados: dict | None, todos: dict | None) -> list[dict]:
    """
    Os campos de cada Pagina (paginas.Pagina(**campos)): uma por ramo e
    recorte, e o indice /dominios/. Vazio sem instantaneo.
    """
    if not dados:
        return []
    todos = todos or {}
    fase = fase_de(dados)
    # sem leitura e sem a lista inteira nao ha o que mostrar; com a lista, a
    # pagina fica de pe na virada da rodada (antes, /dominios/pet/ dava 404
    # de 12/10 ate a primeira leitura)
    if not (dados.get("itens") or (fase.sem_leitura and todos.get("itens"))):
        return []
    recortes = _recortes(dados, todos)
    # primeira passada so para saber quem e indexavel (a lista de "outros")
    rascunho = [_pagina(r, dados, todos, fase, "")[1] for r in recortes]
    bons = [(r, n, k) for r, n, k, _ in rascunho if k >= MINIMO]
    saida = []
    for r in recortes:
        outros = "<ul>" + "".join(
            f'<li><a href="/{SECAO}/{o.slug}/">{html.escape(o.nome)}</a></li>'
            for o, _, _ in bons if o.slug != r.slug) + "</ul>"
        saida.append(_pagina(r, dados, todos, fase, outros)[0])
    itens = "".join(
        f'<li><a href="/{SECAO}/{r.slug}/">{html.escape(r.nome)}</a>: '
        + (f"{_num(n)} na lista</li>" if fase.sem_leitura
           else f"{_num(n)} na rodada, {_num(k)} conferidos</li>") for r, n, k in bons)
    saida.append({
        "slug": SECAO, "titulo": "Domínios .br por ramo que voltaram ao mercado",
        "descricao": (f"Os domínios .br da rodada de liberação de {fase.mes}, separados por ramo: "
                      "pet, saúde, imóveis, alimentação e mais, com a situação de cada um."),
        "corpo": (f'<p class="entrada">Os nomes da rodada de liberação de {fase.mes}, separados '
                  "pelo ramo que o nome sugere. "
                  + (f"{_datas_da_lista(fase)} (horário de Brasília); a conferência de cada nome "
                     "no Registro.br começa com a rodada.</p>\n" if fase.antes else
                     f"Candidatar-se é de graça até {_dia_hora(fase.fim)}; a conferência de cada "
                     "nome no Registro.br começou com a rodada e a primeira leitura chega nas "
                     "próximas horas.</p>\n" if fase.sem_leitura else
                     f"Em cada página, a situação conferida no Registro.br (leitura até "
                     f"{_dia_hora(fase.gerado)}) e o que dá para fazer agora.</p>\n")
                  + f'<ul class="lista-ramos">{itens}</ul>\n'
                  '<p>Não achou o seu ramo? <a href="/">Busque na lista inteira</a> ou '
                  '<a href="/quando-volta/">consulte um nome</a>.</p>'),
        "tipo": "lista", "secao": SECAO,
        "titulo_busca": f"Domínios .br disponíveis por ramo: a lista de {fase.mes}",
        "data": fase.gerado.astimezone(calendario.BRASILIA).date().isoformat() if fase.gerado else "",
        "indexavel": True, "lista": (),
    })
    return saida
