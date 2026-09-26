"""
Paginas do site publicado: uma URL por assunto.

Ate 11/09/2026 o site era um index.html com cinco abas: a ferramenta e
quatro paineis de texto que o JS mostrava e escondia. Para o Google e para
um agente de IA isso e UMA pagina, e uma pagina nao rankeia para "processo
de liberacao" e "leilao de dominio .br" ao mesmo tempo. Agora cada assunto
e um arquivo em site_modelo/conteudo/, com os metadados num comentario no
topo, e este modulo monta cada um dentro do site_modelo/layout.html.

Funcoes puras recebem texto e devolvem texto; so gerar(), no fim, le e
escreve arquivo. O exportar_site.py chama gerar() a cada execucao, entao os
numeros que as paginas citam (quantos nomes na rodada, os pesos da nota)
sao gravados no HTML na hora do build, em vez de preenchidos por JS: o
Google le, e a pagina nao depende de dados.json para fazer sentido.

BASE_URL alimenta canonical, sitemap, Open Graph e llms.txt. Desde
16/09/2026 o site mora no Cloudflare, em liberados.com.br. Nao ha noindex
no site inteiro nem no _headers: o noindex e sempre por pagina
(`Pagina.indexavel`), com <meta name="robots" content="noindex, follow">,
e so nas paginas ralas: ramo com menos de ramos.MINIMO nomes listaveis
(garimpo/web/ramos.py) e as letras sem historia (garimpo/web/letras.py),
fora do sitemap e do llms.txt. O endereco provisorio *.workers.dev foi
desligado no wrangler.jsonc em 17/09/2026, quando o dominio entrou no ar.
"""

from __future__ import annotations

import html
import json
import os
import re
import unicodedata
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from html.parser import HTMLParser

from ..dominio import calendario
from ..dominio import marcas as marcas_dominio

NOME = "Liberados"
SLOGAN = "domínios .br que voltaram ao mercado"
BASE_URL = "https://liberados.com.br"
# O que e o Liberados, numa frase que se sustenta sozinha. A mesma no rodape de
# toda pagina, no JSON-LD da organizacao e no llms.txt: um nome so ganha
# sentido para buscador e agente quando a definicao se repete igual.
# Quem faz (13/09/2026). Pessoa real por tras de um site que le dado oficial
# e o que da confianca a quem visita, e o que buscador e agente usam para
# decidir se citam: vai para a pagina Sobre, o JSON-LD e o llms.txt.
AUTOR = "Daniel Gobbi"
AUTOR_LINKEDIN = "https://www.linkedin.com/in/daniel-gobbi-022b88270/"
DEFINICAO = ("O Liberados mostra, de graça e sem cadastro, os domínios .br que "
             "o Registro.br devolve ao mercado todo mês: os que estão livres "
             "para registrar, os que estão sem concorrente à vista na rodada e "
             "quando um nome que já tem dono pode voltar.")

# A navegacao, na ordem em que aparece. O slug vazio e a raiz (a ferramenta).
NAVEGACAO = (
    ("", "Domínios"),
    ("quando-volta", "Quando volta"),
    ("perguntas", "Perguntas"),
    ("como-selecionamos", "Como selecionamos"),
    ("regras-do-br", "Regras do .br"),
    ("insights", "Insights"),
    ("dados", "Dados"),
    ("api-registrobr", "Para devs"),
)

# O rodape (18/09/2026): a unica porta fixa, em toda pagina, para /dominios/,
# o ciclo de vida e o glossario, que antes so tinham link no meio do texto.
CAMINHOS_RODAPE = (
    ("/dominios/", "Domínios por ramo"),
    ("/quando-volta/", "Quando volta"),
    ("/ciclo-de-vida-do-dominio-br/", "Ciclo de vida do .br"),
    ("/glossario/", "Glossário"),
    ("/dados/", "Dados para baixar"),
    ("/sobre/", "Sobre e privacidade"),
)

FUSO_BRASILIA = "America/Sao_Paulo"


@dataclass
class Pagina:
    slug: str                    # "" e a raiz; "insights/capsula-do-tempo"
    titulo: str
    descricao: str
    corpo: str                   # o fragmento, sem o comentario de metadados
    tipo: str = "pagina"         # ferramenta | pagina | faq | artigo | indice
    secao: str = ""              # "insights" agrupa no indice e na navegacao
    etiqueta: str = ""           # so artigo: "Descoberta · RDAP + DNS"
    data: str = ""               # ISO (AAAA-MM-DD): ultima conferencia
    ordem: int = 0               # posicao no indice da secao
    scripts: tuple[str, ...] = field(default_factory=tuple)
    # O <title> e o que rankeia; o <h1> pode ser a manchete. "O numero que nao
    # existe" e bom titulo de artigo e nao responde busca nenhuma: quando os
    # dois divergem, titulo_busca vai para <title>, og:title e o JSON-LD.
    titulo_busca: str = ""
    modificado: str = ""         # ISO: ultima revisao do texto, se depois de `data`
    # imagem de compartilhamento propria (caminho relativo a raiz do site, ex.
    # "og/tres-travas-e-leilao.png"); vazio usa a do site inteiro
    imagem: str = ""
    # pagina gerada que pode sair rala num mes (ramo com poucos nomes): fica
    # de pe, com noindex, fora do sitemap e do llms.txt (garimpo/web/ramos.py)
    indexavel: bool = True
    lista: tuple[str, ...] = ()      # os primeiros nomes, para o ItemList

    @property
    def titulo_aba(self) -> str:
        return _sem_tags(self.titulo_busca or self.titulo)

    @property
    def caminho(self) -> str:
        return "/" if not self.slug else f"/{self.slug}/"

    def url(self, base: str = BASE_URL) -> str:
        return base.rstrip("/") + self.caminho


# ---------------------------------------------------------------- fragmentos

_METADADOS = re.compile(r"\A\s*<!--(.*?)-->\s*", re.S)


def ler_fragmento(texto: str, slug: str) -> Pagina:
    """
    Um arquivo de conteudo: comentario de metadados e o HTML.

        <!--
        titulo: As regras do Registro.br
        descricao: ...
        tipo: pagina
        -->
        <p>...</p>

    Os metadados moram no proprio arquivo, e nao num manifesto ao lado,
    para que escrever uma pagina nova seja criar UM arquivo.
    """
    achado = _METADADOS.match(texto)
    if not achado:
        raise ValueError(f"{slug or 'raiz'}: falta o comentario de metadados no topo")
    meta: dict[str, str] = {}
    for linha in achado.group(1).splitlines():
        if ":" not in linha:
            continue
        chave, valor = linha.split(":", 1)
        meta[chave.strip()] = valor.strip()
    for obrigatorio in ("titulo", "descricao"):
        if not meta.get(obrigatorio):
            raise ValueError(f"{slug or 'raiz'}: metadado '{obrigatorio}' vazio")
    if len(meta["descricao"]) > 160:
        raise ValueError(f"{slug or 'raiz'}: descricao com mais de 160 caracteres "
                         "(o Google corta)")
    return Pagina(
        slug=slug,
        titulo=meta["titulo"],
        descricao=meta["descricao"],
        corpo=texto[achado.end():],
        tipo=meta.get("tipo", "pagina"),
        secao=meta.get("secao", slug.split("/")[0] if "/" in slug else ""),
        etiqueta=meta.get("etiqueta", ""),
        data=meta.get("data", ""),
        ordem=int(meta.get("ordem", "0") or 0),
        scripts=tuple(s.strip() for s in meta.get("scripts", "").split(",") if s.strip()),
        titulo_busca=meta.get("titulo_busca", ""),
        modificado=meta.get("modificado", ""),
        imagem=meta.get("imagem", ""),
    )


def slug_do_arquivo(relativo: str) -> str:
    """conteudo/ferramenta.html -> ""; conteudo/insights/x.html -> insights/x."""
    sem_ext = relativo.replace(os.sep, "/").removesuffix(".html")
    return "" if sem_ext == "ferramenta" else sem_ext


# ------------------------------------------------------------------ numeros

def _num(n) -> str:
    return f"{int(n):,}".replace(",", ".")


def _quando_brasilia(iso: str | None) -> datetime | None:
    """O instante ISO convertido para o fuso de Brasilia, ou None se ilegivel."""
    try:
        quando = datetime.fromisoformat(str(iso).replace("Z", "+00:00"))
    except ValueError:
        return None
    if quando.tzinfo is None:
        quando = quando.replace(tzinfo=timezone.utc)
    try:
        from zoneinfo import ZoneInfo
        quando = quando.astimezone(ZoneInfo(FUSO_BRASILIA))
    except Exception:            # sem tzdata: fica no fuso que veio
        pass
    return quando


def _data_brasilia(iso: str | None, com_hora: bool = True) -> str:
    if not iso:
        return "-"
    quando = _quando_brasilia(iso)
    if quando is None:
        return str(iso)
    return quando.strftime("%d/%m/%Y %H:%M" if com_hora else "%d/%m/%Y")


def _dia_brasilia(iso: str | None) -> str:
    """A data (AAAA-MM-DD) em horario de Brasilia: o lastmod da raiz, que nao
    tem `modificado` nem `data` (o carimbo dela e o instantaneo, nao uma
    revisao de texto)."""
    quando = _quando_brasilia(iso) if iso else None
    return quando.date().isoformat() if quando else ""


def _por_id(texto: str, id_: str, conteudo: str) -> str:
    """Troca o conteudo do elemento com esse id, mantendo a tag."""
    padrao = re.compile(
        r'(<(\w+)\b[^>]*\bid="' + re.escape(id_) + r'"[^>]*>)(.*?)(</\2>)', re.S)
    return padrao.sub(lambda m: m.group(1) + conteudo + m.group(4), texto, count=1)


def _tabela(itens: list[dict], cabecalho: str) -> str:
    linhas = [f"<tr><th>{html.escape(cabecalho)}</th><th>Pontos</th></tr>"]
    for i in itens:
        sinal = "+" if i["peso"] > 0 else ""
        linhas.append(f"<tr><td>{html.escape(str(i['rotulo']))}</td>"
                      f"<td><strong>{sinal}{i['peso']}</strong></td></tr>")
    return "".join(linhas)


def proxima_rodada(inicio_iso: str | None) -> str:
    """
    Inicio da rodada seguinte pela regra: segunda quarta-feira do mes seguinte.

    As paginas citam a proxima rodada, a pergunta mais buscada sobre o
    processo. Data escrita a mao envelhece no mes seguinte; esta sai do
    instantaneo a cada build. O Registro.br pode ajustar por feriado, e o
    texto em volta diz isso.
    """
    if not inicio_iso:
        return ""
    try:
        inicio = datetime.fromisoformat(inicio_iso)
    except ValueError:
        return ""
    return calendario.mes_seguinte(inicio).strftime("%d/%m/%Y")


def _proxima_abertura_da_pagina(dados: dict | None) -> str:
    """
    A "proxima rodada" que as paginas citam (p-proxima-rodada). Entre a
    lista e a abertura ela e a do instantaneo, que ainda nao abriu; depois,
    a proxima pela regra a partir do instante do build. Antes de 18/09/2026
    era sempre o mes seguinte ao da rodada do instantaneo, e de 12/10 a 14/10
    a pergunta "quando e a proxima rodada" respondia 11/11.
    """
    datas = _datas_da_rodada(dados)
    if not datas:
        return proxima_rodada(((dados or {}).get("rodada") or {}).get("inicio"))
    ref = _referencia(dados)
    abre = datas[0] if ref < datas[0] else calendario.proxima_abertura(ref)
    return abre.strftime("%d/%m/%Y")


def _referencia(dados: dict | None) -> datetime:
    """O instante do instantaneo; sem ele, agora. Deixa o build reproduzivel."""
    try:
        quando = datetime.fromisoformat(str((dados or {}).get("gerado_em")).replace("Z", "+00:00"))
        return quando if quando.tzinfo else quando.replace(tzinfo=timezone.utc)
    except ValueError:
        return datetime.now(timezone.utc)


def calendario_da_pagina(dados: dict | None) -> dict:
    """
    O que o navegador precisa para falar de datas sem refazer a regra: as
    aberturas de um ano antes a dez anos depois (um dominio pode vencer em
    2036) e as constantes que a ficha e a pagina inicial usam.
    """
    ref = _referencia(dados).astimezone(calendario.BRASILIA).date()
    rodada = (dados or {}).get("rodada") or {}
    return {
        "gerado_em": (dados or {}).get("gerado_em") or "",
        "aberturas": calendario.aberturas(ref, 12, 120),
        "hora_abertura": calendario.HORA_ABERTURA,
        "dias_aberta": calendario.DIAS_ABERTA,
        "dias_lista_antes": calendario.DIAS_LISTA_ANTES,
        "meses_ate_a_lista": calendario.MESES_ATE_A_LISTA,
        "rodada": {"inicio": rodada.get("inicio"), "fim": rodada.get("fim")},
    }


MESES = ("janeiro", "fevereiro", "março", "abril", "maio", "junho", "julho",
         "agosto", "setembro", "outubro", "novembro", "dezembro")
DIAS_DA_SEMANA = ("segunda-feira", "terça-feira", "quarta-feira", "quinta-feira",
                  "sexta-feira", "sábado", "domingo")


def _rodada_do_relogio(dados: dict | None) -> tuple[datetime, bool] | None:
    """
    A abertura da rodada que o relogio conta e se a do instantaneo ja fechou.

    Antes do fim, a do instantaneo (entre a lista e a abertura ela ja e a
    nova); depois, a proxima pela regra.
    """
    rodada = (dados or {}).get("rodada") or {}
    try:
        inicio = datetime.fromisoformat(rodada["inicio"])
        fim = datetime.fromisoformat(rodada["fim"])
    except (KeyError, TypeError, ValueError):
        return None
    ref = _referencia(dados)
    if ref < fim:
        return inicio.astimezone(calendario.BRASILIA), False
    return calendario.proxima_abertura(ref), True


def relogio_da_pagina(dados: dict | None) -> str:
    """
    A contagem regressiva do inicio (16/09/2026), pronta no HTML.

    O build grava as tres datas da rodada que vem (lista, abertura,
    fechamento) e o texto de cada uma, para quem le sem JavaScript (buscador,
    agente de IA) e para a caixa nascer do tamanho certo. O relogio do
    visitante fica com o app.js: os digitos, a barra e a troca de alvo.
    """
    achada = _rodada_do_relogio(dados)
    if not achada:
        return ""
    abre, fechada = achada
    fecha = calendario.fechamento(abre)
    lista = datetime.combine(calendario.saida_da_lista(abre), datetime.min.time(),
                             calendario.BRASILIA)
    desde = calendario.fechamento(calendario.mes_anterior(abre))
    mes = MESES[abre.month - 1]
    ref = _referencia(dados)
    semana = lambda d: DIAS_DA_SEMANA[d.weekday()]
    marcos = [
        ("lista", lista, "Sai a lista", lista.strftime("%d/%m"),
         f"A lista da rodada de {mes} sai em",
         f"{semana(lista)}, {lista:%d/%m/%Y}, ao longo do dia (o Registro.br não diz a hora)"),
        ("abre", abre, "Abre a rodada", abre.strftime("%d/%m, %Hh"),
         f"A rodada de {mes} abre em",
         f"{semana(abre)}, {abre:%d/%m/%Y}, às {abre:%H}h (horário de Brasília)"),
        ("fecha", fecha, "Fecha a rodada", fecha.strftime("%d/%m, %Hh"),
         f"A rodada de {mes} fecha em",
         f"{semana(fecha)}, {fecha:%d/%m/%Y}, às {fecha:%H}h (horário de Brasília)"),
    ]
    # o alvo inicial: a abertura, ou o fechamento se ela ja passou
    alvo = next((m for m in marcos[1:] if m[1] > ref), marcos[2])
    esc = html.escape
    botoes = "".join(
        f'<li><button type="button" class="relogio-marco" data-marco="{nome}" '
        f'data-alvo="{quando.isoformat()}" data-rotulo="{esc(rotulo)}" data-texto="{esc(texto)}" '
        f'aria-pressed="{"true" if nome == alvo[0] else "false"}">'
        f'<span class="relogio-marco-nome">{esc(titulo)}</span> '
        f'<strong>{esc(curto)}</strong></button></li>'
        for nome, quando, titulo, curto, rotulo, texto in marcos)
    unidades = "".join(
        f'<span class="relogio-unidade"><b id="relogio-{u}">--</b> {nome}</span>'
        for u, nome in (("d", "dias"), ("h", "h"), ("m", "min"), ("s", "s")))
    return (
        f'<section class="relogio" id="relogio" aria-labelledby="relogio-rotulo" '
        f'data-desde="{desde.isoformat()}" data-fechada="{int(fechada)}">'
        f'<p class="relogio-rotulo" id="relogio-rotulo">{esc(alvo[4])}</p>'
        f'<p class="relogio-digitos" aria-hidden="true">{unidades}</p>'
        f'<p class="relogio-quando"><time id="relogio-quando" datetime="{alvo[1].isoformat()}">'
        f'{esc(alvo[5])}</time></p>'
        '<div class="relogio-barra" id="relogio-barra" aria-hidden="true"><span></span></div>'
        f'<ol class="relogio-marcos" aria-label="O que contar">{botoes}</ol>'
        '<p class="relogio-nota">Datas pela regra da segunda quarta-feira; '
        'o Registro.br pode mudar uma delas por feriado.</p>'
        '</section>')


def _datas_da_rodada(dados: dict | None) -> tuple[datetime, datetime] | None:
    """Abertura e fechamento da rodada do instantaneo, em horario de Brasilia."""
    rodada = (dados or {}).get("rodada") or {}
    try:
        return (datetime.fromisoformat(rodada["inicio"]).astimezone(calendario.BRASILIA),
                datetime.fromisoformat(rodada["fim"]).astimezone(calendario.BRASILIA))
    except (KeyError, TypeError, ValueError):
        return None


def fase_da_rodada(dados: dict | None) -> str:
    """
    Em que ponto o instantaneo pega a rodada: "lista" (a lista saiu e as
    candidaturas ainda nao abriram), "aberta", "fechada", ou "" sem datas.

    A fase "lista" existe desde 18/09/2026: antes, de 12/10 a 14/10 as 15h
    o site dizia "Rodada aberta" e "candidate-se ate 21/10". O app.js faz a
    mesma conta (faseDaRodada), com o relogio de quem olha.
    """
    datas = _datas_da_rodada(dados)
    if not datas:
        return ""
    ref = _referencia(dados)
    if ref < datas[0]:
        return "lista"
    return "aberta" if ref < datas[1] else "fechada"


def _hora(d: datetime) -> str:
    """15h, 15h30: a hora como o site escreve (a mesma do horaCurta do app.js)."""
    return f"{d.hour}h{d.minute:02d}" if d.minute else f"{d.hour}h"


def fase_inicio_da_pagina(dados: dict | None) -> str:
    """
    A linha da fase no inicio quando a lista saiu e a rodada nao abriu. Nas
    outras fases fica a do modelo e o app.js escreve a sua.
    """
    if fase_da_rodada(dados) != "lista":
        return ""
    abre, fecha = _datas_da_rodada(dados)
    return html.escape(
        f"A lista da rodada de {MESES[abre.month - 1]} saiu: as candidaturas abrem em "
        f"{abre:%d/%m}, às {_hora(abre)}, e vão até {fecha:%d/%m}, às {_hora(fecha)} "
        "(horário de Brasília).")


def subtitulo_da_pagina(dados: dict | None) -> str:
    """
    A frase do inicio com a rodada fechada (a mesma que o app.js escreve) ou
    ainda sem leitura (lista saiu, ou abriu e a primeira leitura nao chegou).
    """
    if fase_da_rodada(dados) == "lista":
        # antes da abertura ninguem tem candidato: "sem concorrente a vista"
        # seria verdade vazia
        abre, _ = _datas_da_rodada(dados)
        return ("Todo mês o Registro.br devolve ao mercado os domínios que não foram "
                "renovados, e qualquer pessoa pode se candidatar de graça. A lista de "
                f"{MESES[abre.month - 1]} traz <strong>{_num((dados or {}).get('total_rodada') or 0)}"
                "</strong>; aqui eles aparecem pela nota, e a conferência de quem já pediu "
                f"cada nome começa com a rodada, em {abre:%d/%m}, às {_hora(abre)}.")
    if fase_da_rodada(dados) == "aberta" and not (dados or {}).get("itens"):
        # abriu e a primeira leitura nao chegou (ate o Garimpo seguinte):
        # "sem concorrente a vista", do modelo, ainda seria verdade vazia
        abre, _ = _datas_da_rodada(dados)
        return ("Todo mês o Registro.br devolve ao mercado os domínios que não foram "
                "renovados, e qualquer pessoa pode se candidatar de graça. A lista de "
                f"{MESES[abre.month - 1]} traz <strong>{_num((dados or {}).get('total_rodada') or 0)}"
                "</strong>; aqui eles aparecem pela nota, e a conferência de quem já pediu "
                f"cada nome começou com a rodada, em {abre:%d/%m}, às {_hora(abre)}; a primeira "
                "leitura chega nas próximas horas.")
    achada = _rodada_do_relogio(dados)
    if not achada or not achada[1]:
        return ""
    return ("Todo mês o Registro.br devolve ao mercado os domínios que não foram "
            f"renovados. Na última rodada foram <strong>{_num((dados or {}).get('total_rodada') or 0)}"
            "</strong>; agora você vê os que ficaram livres para registrar na hora e os "
            "que travaram e voltam na próxima.")


def passos_da_pagina(dados: dict | None) -> str:
    """
    Os tres passos do inicio com a rodada fechada ou ainda por abrir. Aberta,
    fica o texto do modelo (conteudo/ferramenta.html), que fala de se
    candidatar agora.
    """
    if fase_da_rodada(dados) == "lista":
        abre, fecha = _datas_da_rodada(dados)
        return (
            '<li><strong>Escolha um nome</strong> na lista abaixo, busque o seu ou veja '
            '<a href="/dominios/">por ramo</a>.</li>'
            f'<li><strong>Candidate-se de {abre:%d/%m}, {_hora(abre)}, a {fecha:%d/%m}, '
            f'{_hora(fecha)}</strong> no Registro.br, sem custo. Antes da abertura o '
            'Registro.br não aceita candidatura.</li>'
            '<li><strong>Se só você pedir, é seu</strong> pela anuidade de R$&nbsp;40. Se mais '
            'gente pedir, ninguém leva e o nome volta no mês seguinte, ou vai a leilão se já '
            'travou em rodadas anteriores.</li>')
    achada = _rodada_do_relogio(dados)
    if not achada or not achada[1]:
        return ""
    abre = achada[0]
    lista = calendario.saida_da_lista(abre)
    return (
        '<li><strong>Veja o que sobrou</strong> na lista abaixo, ou busque '
        '<a href="/dominios/">por ramo</a>: os livres você '
        'registra agora; os que travaram voltam na próxima rodada.</li>'
        '<li><strong>Marque os nomes de que gostou</strong> com a estrela e ponha '
        f'a lista de {lista:%d/%m} na agenda, com o botão acima.</li>'
        f'<li><strong>Candidate-se de {abre:%d/%m} a '
        f'{calendario.fechamento(abre):%d/%m}</strong> no Registro.br, sem custo, a partir '
        f'das {abre:%H}h da abertura. Se só você pedir, é seu pela anuidade de R$&nbsp;40.</li>')


def rodadas_para_lembrete(dados: dict | None, quantas: int = 24) -> list[datetime]:
    """As proximas aberturas, a partir do instantaneo, para os .ics servidos."""
    primeira = calendario.proxima_abertura(_referencia(dados))
    datas = [primeira]
    while len(datas) < quantas:
        datas.append(calendario.mes_seguinte(datas[-1]))
    return datas


def preencher_numeros(texto: str, dados: dict, disputas: dict | None = None) -> str:
    """
    Grava no HTML os numeros que antes o app.js preenchia ao vivo.

    Os ids sao os mesmos de antes (p-*, tab-*), entao o conteudo nao mudou
    de forma: so a hora em que o numero entra. Elemento que nao existe na
    pagina e ignorado, e id sem dado fica como esta.
    """
    if not dados:
        return texto
    # pagina Dados com a rodada fechada: a secao inteira troca antes dos ids
    # de dentro dela (p-disputados, p-fig-candidatos...) serem preenchidos
    if 'id="p-rodada"' in texto:
        fechada = rodada_da_pagina(dados, disputas)
        if fechada:
            texto = _por_id(texto, "p-rodada", fechada)
    c = dados.get("criterios") or {}
    pool = len(dados.get("itens", [])) + (dados.get("nao_verificados") or 0)
    horas = lambda n: f"~{n * 2.15 / 3600:.1f} horas".replace(".", ",")
    quente = next((k for k in (dados.get("frescor") or {}).get("classes", [])
                   if k.get("nome") == "quente"), {})
    rodada = dados.get("rodada") or {}
    valores = {
        "p-gerado": _data_brasilia(dados.get("gerado_em")),
        "rodape-gerado": _data_brasilia(dados.get("gerado_em")),
        "p-prazo-quente": str(quente.get("prazo_horas") or ""),
        "p-total-rodada": _num(dados.get("total_rodada") or 0),
        "p-total-rodada2": _num(dados.get("total_rodada") or 0),
        "p-rodada-inicio": _data_brasilia(rodada.get("inicio")),
        "p-rodada-inicio2": _data_brasilia(rodada.get("inicio"), com_hora=False),
        "p-rodada-fim": _data_brasilia(rodada.get("fim")),
        "p-proxima-rodada": _proxima_abertura_da_pagina(dados),
        "p-pool": _num(pool),
        "p-conta-pool": _num(pool),
        "p-conta-pool-h": horas(pool),
        "p-conta-tudo": _num(dados.get("total_rodada") or 0),
        "p-conta-tudo-h": horas(dados.get("total_rodada") or 0),
        "p-elegiveis": _num(dados.get("total_elegiveis") or 0),
        "p-nota-minima": str(c.get("nota_minima", "")),
        "p-nota-minima2": str(c.get("nota_minima", "")),
        "p-nichos": str(len(c.get("nichos") or [])),
        "p-marcas": str(c.get("total_marcas", "")),
    }
    valores.update(_numeros_da_disputa(dados))
    for id_, valor in valores.items():
        if valor and valor != "-":
            texto = _por_id(texto, id_, html.escape(valor))
    # pagina Dados: grafico e ranking vivos, HTML pronto (ja escapado)
    from . import graficos
    blocos = {"p-fig-candidatos": graficos.figura_candidatos(dados),
              "p-mais-disputados": _mais_disputados(dados),
              # JSON dentro de <script type="application/json">: nao executa
              # (a CSP nao se aplica) e nao passa por html.escape, que
              # quebraria as aspas; so "</" precisa de escape
              "p-relogio": relogio_da_pagina(dados),
              "p-passos": passos_da_pagina(dados),
              "fase-inicio": fase_inicio_da_pagina(dados),
              "p-subtitulo": subtitulo_da_pagina(dados),
              "p-calendario": json.dumps(calendario_da_pagina(dados),
                                         ensure_ascii=False).replace("</", "<\\/")}
    for id_, bloco in blocos.items():
        if bloco:
            texto = _por_id(texto, id_, bloco)
    tabelas = {
        "tab-tamanho": (c.get("tamanho"), "Tamanho do rótulo"),
        "tab-vocabulario": (c.get("vocabulario"), "O nome é..."),
        "tab-bonus": (c.get("bonus"), "Bônus"),
        "tab-penalidades": (c.get("penalidades"), "Penalidade"),
    }
    for id_, (itens, cabecalho) in tabelas.items():
        if itens:
            texto = _por_id(texto, id_, _tabela(itens, cabecalho))
    return texto


def _disputados(dados: dict) -> list:
    """Nomes com 2+ pedidos na rodada aberta, sem risco de marca, do mais pedido ao menos."""
    status = dados.get("status") or []
    if "LIBERACAO_DISPUTADA" not in status:
        return []
    i = status.index("LIBERACAO_DISPUTADA")
    return sorted((it for it in dados.get("itens") or [] if it[1] == i and it[2] >= 2),
                  key=lambda it: (-it[2], it[0]))


def _numeros_da_disputa(dados: dict) -> dict[str, str]:
    """Os numeros vivos da pagina Dados; vazio quando o instantaneo nao tem itens."""
    itens = dados.get("itens") or []
    if not itens:
        return {}
    disputados = _disputados(dados)
    return {"p-verificados": _num(len(itens)),
            "p-disputados": _num(len(disputados))}


def _mais_disputados(dados: dict, n: int = 5) -> str:
    """
    Os <li> do ranking. Nome com possivel marca fica de fora: marca e filtro de
    exclusao no Liberados, nunca vitrine.
    """
    marcas = dados.get("marcas") or []
    ok = marcas.index("OK") if "OK" in marcas else None
    linhas = [f"<li><code>{html.escape(it[0])}</code>: {_num(it[2])}"
              " pedidos</li>"
              for it in _disputados(dados) if ok is None or it[6] == ok][:n]
    return "".join(linhas)


# ------------------------------------------- pagina Dados, rodada fechada

# a base propria das rodadas (arquivar_rodada.py). O repositorio publico nasce
# sem ela: a secao cai no texto curto, sem numero.
DISPUTAS = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
                        "docs", "historico", "disputas.json")


def carregar_disputas(caminho: str = DISPUTAS) -> dict:
    try:
        with open(caminho, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def _rodada_aberta(dados: dict | None) -> bool:
    """Entre a abertura e o fechamento. Antes de abrir, a lista nova ainda nao tem disputa."""
    rodada = (dados or {}).get("rodada") or {}
    try:
        inicio = datetime.fromisoformat(rodada["inicio"])
        fim = datetime.fromisoformat(rodada["fim"])
    except (KeyError, TypeError, ValueError):
        return False
    return inicio <= _referencia(dados) < fim


def _ultima_fechada(disputas: dict, ref: datetime) -> tuple[datetime, dict] | None:
    """A rodada mais recente da base que ja fechou no instante `ref`."""
    achadas = []
    for chave, r in (disputas.get("rodadas") or {}).items():
        try:
            fim = datetime.fromisoformat(r["fim"])
        except (KeyError, TypeError, ValueError):
            continue
        if fim <= ref and r.get("nomes"):
            achadas.append((fim, chave, r))
    if not achadas:
        return None
    _, chave, r = max(achadas, key=lambda a: a[0])
    # a chave e o dia em que a rodada abriu de fato, feriado incluido
    dia = datetime.fromisoformat(chave).date()
    return datetime(dia.year, dia.month, dia.day, calendario.HORA_ABERTURA,
                    tzinfo=calendario.BRASILIA), r


def _cartao(id_: str, numero: str, frase: str) -> str:
    return (f'<div class="cartao" id="{id_}"><p><strong class="cartao-numero">{numero}</strong> '
            f'{frase}</p><button class="compartilhar escondido" type="button" '
            'aria-label="Compartilhar este número"></button></div>')


def rodada_da_pagina(dados: dict | None, disputas: dict | None = None) -> str:
    """
    A secao "A lista deste mes" da pagina Dados com a rodada fechada (18/09/2026).

    Depois do fechamento, o instantaneo so mostra o que sobrou: quem foi
    disputado ja travou ou foi a leilao, e a contagem viva cai para quase
    zero (no ar em 17/09: "4 nomes disputados", eram 311). O retrato certo e o
    da base das rodadas, que guarda o maior numero de candidatos visto em cada
    nome. Com a rodada aberta devolve "" e fica o bloco vivo do modelo.
    Numero nenhum sai do estado atual de cada nome: a releitura depois do
    fechamento leva dias e e parcial.
    """
    if _rodada_aberta(dados):
        return ""
    esc = html.escape
    achada = _ultima_fechada(disputas if disputas is not None else carregar_disputas(),
                             _referencia(dados))
    if not achada:
        return ('<h2 id="este-mes">A lista deste mês</h2>'
                '<p>A rodada está fechada. Quando a próxima abrir, esta seção mostra quantos '
                'nomes estão sendo disputados, e por quantas pessoas.</p>')
    abriu, r = achada
    fechou = datetime.fromisoformat(r["fim"]).astimezone(calendario.BRASILIA)
    volta = calendario.mes_seguinte(abriu)
    mes = f"{MESES[abriu.month - 1]} de {abriu.year}"
    mes_volta = MESES[volta.month - 1]
    nomes = r["nomes"]
    # elegivel com dois ou mais pedidos segue para o leilao: a ultima leitura
    # pode nao ter visto a passagem, e os tres cartoes somam o total
    leilao, travados = ([n for n, v in nomes.items() if v[1] >= 1],
                        [n for n, v in nomes.items() if v[1] == 0])
    conferidos = r.get("conferidos") or 0
    parte = (f": {num_pct(len(nomes), conferidos)} dos {_num(conferidos)} de melhor nota que "
             "conferimos" if conferidos else "")
    destino = {0: f"travou, volta em {mes_volta}", 1: "foi a leilão", 2: "foi a leilão"}

    # marca e filtro de exclusao, nunca vitrine: nome fora do instantaneo nao
    # tem como ser conferido, entao fica de fora tambem
    marcas = (dados or {}).get("marcas") or []
    ok = marcas.index("OK") if "OK" in marcas else None
    marca = {it[0]: it[6] for it in (dados or {}).get("itens") or []}
    # o risco gravado e da ultima varredura; MARCAS pode ter mudado depois
    # (4f880ce/S18), entao reavalia com a lista de hoje por cima, sem
    # esperar a proxima varredura tocar o nome de novo
    def sem_marca(n):
        return (n in marca and (ok is None or marca[n] == ok)
                and not marcas_dominio.parece_marca_dominio(n))
    ranking = sorted(((n, v) for n, v in nomes.items() if sem_marca(n)),
                     key=lambda nv: (-nv[1][0], nv[0]))[:10]
    # o titulo precisa ser verdade sozinho (o index.md e as IAs citam o h3):
    # quantos nomes mais pedidos que o ultimo da lista ficaram de fora
    corte = ranking[-1][1][0] if ranking else 0
    fora = sum(1 for n, v in nomes.items() if v[0] > corte and not sem_marca(n))
    lista = "".join(f"<li><code>{esc(n)}</code>: {_num(v[0])} pedidos ({destino.get(v[1], '')})</li>"
                    for n, v in ranking)
    from . import graficos
    fig = graficos.figura_de_pedidos(
        [v[0] for v in nomes.values()],
        f"consulta pública do Registro.br, a maior contagem vista em cada nome durante a rodada "
        f"de {mes}; só os nomes com melhor nota que o Liberados conferiu, não a lista inteira",
        fechada=True)
    return (
        f'<h2 id="este-mes">Como terminou a rodada de {mes}</h2>'
        f'<p>A rodada ficou aberta de {abriu:%d/%m/%Y} a {fechou:%d/%m/%Y}, às {fechou:%H}h. '
        f'Havia {_num(r.get("na_lista") or 0)} domínios na lista. Quem pediu um nome sozinho '
        'levou pela anuidade; quando duas ou mais pessoas pediram o mesmo, ninguém levou, e o '
        f'nome travou até a rodada seguinte, que abre em {volta:%d/%m/%Y}.</p>'
        '<div class="cartoes">'
        + _cartao("rodada-disputados", _num(len(nomes)),
                  f"nomes tiveram duas ou mais pessoas interessadas{parte}.")
        + _cartao("rodada-leilao", _num(len(leilao)),
                  'foram a leilão, depois de travar nas rodadas anteriores '
                  '(<a href="/insights/tres-travas-e-leilao/">as três travas</a>).')
        + _cartao("rodada-travados", _num(len(travados)),
                  f"travaram: ninguém levou, e eles voltam na lista de {mes_volta}.")
        + '</div>'
        '<h3 id="quantos-querem">Quantas pessoas disputam um domínio .br?</h3>'
        + (fig or "")
        + (f'<h3 id="mais-pedidos">Os domínios .br mais pedidos em {mes}, fora os que parecem '
           f'marca</h3><ol>{lista}</ol>'
           + (f'<p>{_num(fora)} {"nome" if fora == 1 else "nomes"} com mais pedidos que o último '
              'desta lista ficaram de fora por parecerem marca.</p>' if fora else "")
           if lista else "")
        + '<p class="nota">A contagem é a da consulta pública do Registro.br, que não mostra o '
        'candidato sozinho (<a href="/insights/o-candidato-que-nao-aparece/">o candidato que não '
        'aparece</a>). O valor dos lances do leilão o Registro.br não publica. Nomes que parecem '
        'marca ficam de fora da lista. A contagem de cada nome, para baixar: '
        '<a href="/dados/historico/disputas.json">disputas.json</a>.</p>')


def num_pct(parte: int, todo: int) -> str:
    """311 de 16048 -> 1,9%"""
    if not todo:
        return ""
    return f"{100 * parte / todo:.1f}%".replace(".", ",")


# ------------------------------------------------------------------ montagem

def _e(s: str) -> str:
    return html.escape(s, quote=True)


def _sem_tags(s: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", "", s))).strip()


def navegacao(pagina: Pagina) -> str:
    # as paginas de cada letra (tipo pagina, dentro de insights/) acendem Insights
    atual = (pagina.secao if pagina.tipo == "artigo" or pagina.slug.startswith("insights/")
             else "" if pagina.tipo == "lista" else pagina.slug)
    links = []
    for slug, rotulo in NAVEGACAO:
        marca = ' aria-current="page"' if slug == atual else ""
        links.append(f'<a class="aba" href="/{slug + "/" if slug else ""}"{marca}>'
                     f'{_e(rotulo)}</a>')
    return "".join(links)


IMAGEM = "og.png"      # 1200x630, em site_modelo/: a previa no WhatsApp e no X


def _organizacao(base: str) -> dict:
    return {"@type": "Organization", "@id": base.rstrip("/") + "/#org",
            "name": NOME, "url": base.rstrip("/") + "/", "description": DEFINICAO,
            "founder": {"@type": "Person", "name": AUTOR, "url": AUTOR_LINKEDIN,
                        "sameAs": [AUTOR_LINKEDIN]}}


def _migalhas(pagina: Pagina, base: str) -> dict:
    """BreadcrumbList: Inicio > secao > pagina. O Google mostra no lugar da URL."""
    raiz = base.rstrip("/") + "/"
    itens = [("Início", raiz)]
    if pagina.secao and pagina.slug != pagina.secao:
        rotulo = {**dict(NAVEGACAO), "dominios": "Domínios por ramo"}.get(
            pagina.secao, pagina.secao.capitalize())
        itens.append((rotulo, f"{raiz}{pagina.secao}/"))
    itens.append((pagina.titulo_aba, pagina.url(base)))
    return {"@type": "BreadcrumbList", "itemListElement": [
        {"@type": "ListItem", "position": i, "name": nome, "item": url}
        for i, (nome, url) in enumerate(itens, 1)]}


def _perguntas_com_id(corpo: str) -> list[tuple[str, str, str]]:
    """(id, pergunta, resposta): o id e o mesmo que o HTML publica."""
    corpo, _ = ancorar(corpo)
    pares = re.findall(
        r'<h2[^>]*\bid="([^"]+)"[^>]*>(.*?)</h2>\s*<p class="resposta-curta">(.*?)</p>(.*?)</div>',
        corpo, re.S)
    return [(i, _sem_tags(p), _sem_tags(curta + " " + resto)) for i, p, curta, resto in pares]


def termos_do_glossario(corpo: str) -> list[tuple[str, str, str]]:
    """(id, termo, definicao) de cada <dt id=...> seguido do seu <dd>."""
    return [(i, _sem_tags(t), _sem_tags(d)) for i, t, d in re.findall(
        r'<dt id="([^"]+)">(.*?)</dt>\s*<dd>(.*?)</dd>', corpo, re.S)]


def _serie_historica(base: str, org: dict) -> dict:
    """Dataset da pagina Dados: a serie das listas mensais, com os arquivos para baixar."""
    raiz = base.rstrip("/")
    arquivos = ["rodadas", "travas", "bumerangues", "modas", "disputas"]
    return {
        "@type": "Dataset",
        "name": "Série histórica das listas de liberação de domínios .br (2017 em diante)",
        "description": ("Contagens mensais das listas do processo de liberação do Registro.br "
                        "reconstruídas a partir de cópias do Internet Archive: tamanho de cada "
                        "lista, domínios distintos por ano, meses seguidos na lista até o "
                        "leilão, domínios que voltam e termos de moda. Desde a rodada de "
                        "setembro de 2026, também quantos candidatos visíveis teve cada nome "
                        "disputado e se ele travou ou foi a leilão."),
        "url": raiz + "/dados/", "inLanguage": "pt-BR", "isAccessibleForFree": True,
        "creator": {"@id": org["@id"]},
        "temporalCoverage": "2017-09/..",
        "keywords": ["domínios .br", "estatísticas", "processo de liberação",
                     "leilão de domínios", "Registro.br", "domínios expirados"],
        "distribution": [{"@type": "DataDownload", "encodingFormat": "application/json",
                          "contentUrl": f"{raiz}/dados/historico/{a}.json"} for a in arquivos],
    }


def json_ld(pagina: Pagina, base: str = BASE_URL, dados: dict | None = None) -> str:
    """
    Dados estruturados: o que o Google e os agentes leem sem adivinhar.

    Um @graph por pagina. A ferramenta e WebSite + Dataset (o dado e o ativo
    que ninguem mais tem, e o que o Google Dataset Search e um agente citam);
    artigo e Article; FAQ e FAQPage; glossario e DefinedTermSet. Toda pagina
    que nao e a raiz leva BreadcrumbList.
    """
    dados = dados or {}
    org = _organizacao(base)
    url = pagina.url(base)
    grafo: list[dict] = []
    if pagina.tipo == "ferramenta":
        grafo.append({"@type": "WebSite", "@id": url + "#site", "name": NOME,
                      "url": url, "description": pagina.descricao,
                      "inLanguage": "pt-BR", "publisher": {"@id": org["@id"]}})
        grafo.append(org)
        conjunto = {
            "@type": "Dataset",
            "name": "Domínios .br do processo de liberação do Registro.br",
            "description": ("Os nomes da rodada mensal de liberação de domínios .br, "
                            "com situação na consulta pública (livre, disputado, "
                            "leilão), contagem de candidatos visíveis e nota de "
                            "relevância. Atualizado ao longo da rodada."),
            "url": url, "inLanguage": "pt-BR", "isAccessibleForFree": True,
            "creator": {"@id": org["@id"]},
            "keywords": ["processo de liberação", "domínios .br", "Registro.br",
                         "leilão de domínios", "domínios expirados"],
            "distribution": [{"@type": "DataDownload",
                              "encodingFormat": "application/json",
                              "contentUrl": base.rstrip("/") + "/dados.json"}],
            "variableMeasured": ["situação", "candidatos visíveis",
                                 "nota de relevância", "elegível ao leilão"],
        }
        if dados.get("gerado_em"):
            conjunto["dateModified"] = dados["gerado_em"]
        rodada = dados.get("rodada") or {}
        if rodada.get("inicio") and rodada.get("fim"):
            conjunto["temporalCoverage"] = f"{rodada['inicio']}/{rodada['fim']}"
        grafo.append(conjunto)
    elif pagina.tipo == "faq":
        grafo.append({"@type": "FAQPage", "url": url, "inLanguage": "pt-BR",
                      "mainEntity": [
                          {"@type": "Question", "name": p, "url": f"{url}#{i}",
                           "acceptedAnswer": {"@type": "Answer", "text": r}}
                          for i, p, r in _perguntas_com_id(
                              preencher_numeros(pagina.corpo, dados))]})
    elif pagina.tipo == "glossario":
        conjunto_id = url + "#termos"
        grafo.append({"@type": "DefinedTermSet", "@id": conjunto_id,
                      "name": pagina.titulo_aba, "url": url, "inLanguage": "pt-BR",
                      "hasDefinedTerm": [
                          {"@type": "DefinedTerm", "@id": f"{url}#{i}", "name": t,
                           "description": d, "url": f"{url}#{i}",
                           "inDefinedTermSet": conjunto_id}
                          for i, t, d in termos_do_glossario(
                              preencher_numeros(pagina.corpo, dados))]})
    elif pagina.tipo == "lista":
        dado = {"@type": "CollectionPage", "url": url, "inLanguage": "pt-BR",
                "name": pagina.titulo_aba, "description": pagina.descricao,
                "publisher": {"@id": org["@id"]}}
        if dados.get("gerado_em"):
            dado["dateModified"] = dados["gerado_em"]
        if pagina.lista:
            dado["mainEntity"] = {"@type": "ItemList", "numberOfItems": len(pagina.lista),
                                  "itemListElement": [
                                      {"@type": "ListItem", "position": i, "name": nome,
                                       "url": f"{base.rstrip('/')}/quando-volta/?d={nome}"}
                                      for i, nome in enumerate(pagina.lista, 1)]}
        grafo += [dado, org]
    elif pagina.tipo in ("artigo", "pagina", "indice"):
        tipo = "Article" if pagina.tipo == "artigo" else (
            "CollectionPage" if pagina.tipo == "indice" else "WebPage")
        dado = {"@type": tipo, "url": url, "inLanguage": "pt-BR",
                "name": pagina.titulo_aba, "description": pagina.descricao,
                "publisher": {"@id": org["@id"]}}
        if pagina.tipo == "artigo":
            dado["headline"] = _sem_tags(pagina.titulo)
            dado["author"] = {"@id": org["@id"]}
            dado["image"] = base.rstrip("/") + "/" + (pagina.imagem or IMAGEM)
            dado["mainEntityOfPage"] = url
        if pagina.data:
            dado["datePublished"] = pagina.data
            dado["dateModified"] = pagina.modificado or pagina.data
        grafo += [dado, org]
        if pagina.slug == "dados":
            grafo.append(_serie_historica(base, org))
    else:
        return ""
    if pagina.slug:
        grafo.append(_migalhas(pagina, base))
    dado = {"@context": "https://schema.org", "@graph": grafo}
    # o tipo application/ld+json e o que impede o navegador de executar e
    # o que tira este bloco da regex do hash da CSP (exportar_site)
    return ('<script type="application/ld+json">'
            + json.dumps(dado, ensure_ascii=False).replace("</", "<\\/") + "</script>")


# ------------------------------------------------------------------ ancoras

# Todo titulo de secao tem endereco proprio (13/09/2026): quem quer mandar
# "a pergunta do quanto custa" manda /perguntas/#quanto-custa, o Google pode
# levar direto ao trecho e um agente cita a secao, nao a pagina inteira. Tudo
# no build, entao pagina nova ganha o mesmo sem ninguem lembrar.

_TITULO = re.compile(r"<(h2|h3|dt)\b([^>]*)>(.*?)</\1>", re.S)
_COM_ID = re.compile(r'<(\w+)\b[^>]*\bid="[^"]*"[^>]*>.*?</\1>', re.S)


def slug_ancora(texto: str) -> str:
    """'Quanto custa um domínio?' -> 'quanto-custa-um-dominio'; no maximo ~60 letras."""
    sem_acento = "".join(c for c in unicodedata.normalize("NFKD", texto)
                         if not unicodedata.combining(c))
    slug = re.sub(r"[^a-z0-9]+", "-", sem_acento.lower()).strip("-")
    if len(slug) > 60:
        slug = slug[:60].rsplit("-", 1)[0]
    return slug


def ancorar(corpo: str) -> tuple[str, list[tuple[str, str, str]]]:
    """
    Da id a todo h2 e h3 que ainda nao tem e devolve (corpo, [(tag, id, html)]).

    O id sai do texto do titulo SEM os numeros que o build grava (o que tem
    id proprio, como <span id="p-pool">): com eles, o endereco mudaria a cada
    rodada e o link compartilhado quebraria. Quem quer um endereco curto e
    estavel escreve o id na mao; o gerado so cobre o que ficou sem.
    dt entra na lista so se ja tiver id (o glossario).
    """
    usados = set(re.findall(r'\bid="([^"]+)"', corpo))
    titulos: list[tuple[str, str, str]] = []

    def trocar(m):
        tag, attrs, miolo = m.groups()
        achado = re.search(r'\bid="([^"]+)"', attrs)
        if achado:
            id_ = achado.group(1)
        elif tag == "dt":
            return m.group(0)
        else:
            raiz = slug_ancora(_sem_tags(_COM_ID.sub("", miolo))) or "secao"
            id_, n = raiz, 2
            while id_ in usados:
                id_, n = f"{raiz}-{n}", n + 1
            usados.add(id_)
            attrs = f' id="{id_}"' + attrs
        titulos.append((tag, id_, miolo))
        return f"<{tag}{attrs}>{miolo}</{tag}>"

    return _TITULO.sub(trocar, corpo), titulos


def titulos_com_link(corpo: str) -> str:
    """O texto de cada titulo com id vira link para ele mesmo (a.ancora)."""
    def trocar(m):
        tag, attrs, miolo = m.groups()
        achado = re.search(r'\bid="([^"]+)"', attrs)
        if not achado or "<a " in miolo:        # link dentro de link nao existe
            return m.group(0)
        return (f'<{tag}{attrs}><a class="ancora" href="#{achado.group(1)}">'
                f"{miolo}</a></{tag}>")
    return _TITULO.sub(trocar, corpo)


def indice_da_pagina(pagina: Pagina, titulos: list[tuple[str, str, str]]) -> str:
    """
    "Nesta pagina": a lista dos h2, antes do primeiro. So em pagina longa de
    referencia (FAQ sempre); artigo e historia, se le de cima a baixo.
    """
    h2 = [(i, m) for tag, i, m in titulos if tag == "h2"]
    if pagina.tipo == "faq":
        rotulo = f"As {len(h2)} perguntas desta página"
    elif (pagina.tipo == "pagina" and len(h2) >= 4
          and len(_sem_tags(pagina.corpo)) > 5000):
        rotulo = "Nesta página"
    else:
        return ""
    if len(h2) < 2:
        return ""
    itens = "".join(f'<li><a href="#{i}">{_sem_tags(_sem_ids(m))}</a></li>' for i, m in h2)
    return (f'<nav class="indice" aria-label="{rotulo}">'
            f'<p class="indice-titulo">{rotulo}</p><ol>{itens}</ol></nav>\n')


def _sem_ids(miolo: str) -> str:
    """Tira o id dos elementos (o numero fica): id repetido no indice e invalido."""
    return re.sub(r'\s\bid="[^"]*"', "", miolo)


def _corpo_de_texto(pagina: Pagina, dados: dict | None) -> str:
    """Numeros gravados, ids nos titulos, indice e titulos clicaveis."""
    corpo = preencher_numeros(pagina.corpo, dados or {})
    if pagina.tipo == "indice":              # h2 dos cartoes ja sao links
        return corpo
    corpo, titulos = ancorar(corpo)
    indice = indice_da_pagina(pagina, titulos)
    if indice:
        marco = ('<div class="pergunta">' if pagina.tipo == "faq"
                 and '<div class="pergunta">' in corpo else "<h2")
        pos = corpo.find(marco)
        corpo = corpo[:pos] + indice + corpo[pos:] if pos >= 0 else indice + corpo
    return titulos_com_link(corpo)


def _miolo(pagina: Pagina, dados: dict | None = None) -> str:
    if pagina.tipo == "ferramenta":
        # Visivel desde 13/09/2026: era so para leitor de tela, e quem chegava
        # de um link via numeros sem saber do que eram.
        return (f'<h1 class="titulo-inicio">{_e(pagina.titulo)}</h1>\n' + pagina.corpo)
    if pagina.tipo == "artigo":
        etiqueta = (f'<p class="etiqueta">{_e(pagina.etiqueta)}</p>\n'
                    if pagina.etiqueta else "")
        return (f'<article class="insight">\n{etiqueta}<h1>{pagina.titulo}</h1>\n'
                f'<p class="resumo-insight">{pagina.descricao}</p>\n'
                f'{_corpo_de_texto(pagina, dados)}\n</article>')
    return f"<h1>{pagina.titulo}</h1>\n{_corpo_de_texto(pagina, dados)}"


def _rodape(pagina: Pagina) -> str:
    if pagina.tipo == "ferramenta":
        primeiro = 'Instantâneo gerado em <span id="rodape-gerado"></span>'
    elif pagina.data:
        # A ultima revisao do texto, nunca a publicacao (18/09/2026): pagina
        # que so mudou o metadado `modificado` nao devia parecer parada.
        primeiro = (f"Conferido em "
                    f"{_data_brasilia((pagina.modificado or pagina.data) + 'T12:00:00-03:00', False)}")
    else:
        primeiro = f"{NOME}, projeto independente e de código aberto"
    # A frase que diz o que e o site, em toda pagina (13/09/2026): quem chega
    # pelo Google ou por um agente numa pagina de texto nunca viu o inicio.
    nav = ('<nav class="rodape-nav" aria-label="Rodapé">'
           + "".join(f'<a href="{href}">{_e(rotulo)}</a>' for href, rotulo in CAMINHOS_RODAPE)
           + "</nav>")
    return (f'<span class="rodape-sobre">{DEFINICAO} '
            '<a href="/sobre/">Sobre o Liberados</a></span>'
            f"{nav}"
            f"<span>{primeiro}</span>"
            '<span class="espacador"></span>'
            "<span>Sem vínculo com o Registro.br, o NIC.br ou o CGI.br</span>")


def render(pagina: Pagina, layout: str, dados: dict | None = None,
           base: str = BASE_URL) -> str:
    """O HTML completo de uma pagina."""
    titulo_aba = (f"{NOME}: {SLOGAN}" if pagina.tipo == "ferramenta"
                  else f"{pagina.titulo_aba} · {NOME}")
    artigo = pagina.tipo == "artigo"
    og_extra = ""
    if artigo and pagina.data:
        og_extra = (f'<meta property="article:published_time" content="{_e(pagina.data)}">'
                    f'<meta property="article:modified_time" '
                    f'content="{_e(pagina.modificado or pagina.data)}">')
    # compartilhar.js poe o icone de copiar link ao lado de cada titulo: vai
    # em toda pagina de texto, nao so na que o pede
    lista = list(pagina.scripts)
    if pagina.tipo != "ferramenta" and "compartilhar.js" not in lista:
        lista.append("compartilhar.js")
    scripts = "".join(f'<script src="/{s}"></script>' for s in lista)
    campos = {
        "titulo": _e(_sem_tags(titulo_aba)),
        "descricao": _e(pagina.descricao),
        "canonical": _e(pagina.url(base)),
        "nome": _e(NOME),
        "nav": navegacao(pagina),
        "classe_main": "ferramenta" if pagina.tipo == "ferramenta" else "prosa",
        "cabecalho_extra": (CABECALHO_FERRAMENTA if pagina.tipo == "ferramenta"
                            else ""),
        "regua": (REGUA if pagina.tipo == "ferramenta" else ""),
        "miolo": _miolo(pagina, dados),
        "rodape": _rodape(pagina),
        "jsonld": json_ld(pagina, base, dados),
        "og_tipo": "article" if artigo else "website",
        "og_extra": og_extra,
        "imagem": _e(base.rstrip("/") + "/" + (pagina.imagem or IMAGEM)),
        "scripts": scripts,
        "robots": ("" if pagina.indexavel else
                   '<meta name="robots" content="noindex, follow">'),
        "alternativo": ("" if pagina.tipo == "ferramenta" else
                        f'<link rel="alternate" type="text/markdown" '
                        f'href="{_e(pagina.url(base))}index.md">'),
    }
    texto = layout
    for chave, valor in campos.items():
        texto = texto.replace("{{" + chave + "}}", valor)
    sobrou = re.search(r"\{\{[a-z_]+\}\}", texto)
    if sobrou:
        raise ValueError(f"layout com campo sem valor: {sobrou.group(0)}")
    return preencher_numeros(texto, dados or {})


# So a ferramenta tem prazo da rodada, idade do instantaneo e a regua:
# nada os preenche nas outras paginas, e um span vazio e so ruido.
CABECALHO_FERRAMENTA = ('<span id="prazo" class="prazo escondido"></span>\n'
                        '    <span id="carimbo" class="carimbo"></span>')
REGUA = ('<div id="regua" class="regua" role="img" aria-label="Carregando a rodada">'
         "<span></span></div>")


def indice_insights(artigos: list[Pagina], titulo: str, descricao: str) -> Pagina:
    """A pagina /insights/: a lista dos artigos, do primeiro ao ultimo."""
    itens = []
    for a in sorted(artigos, key=lambda p: (p.ordem, p.slug)):
        etiqueta = f'<p class="etiqueta">{_e(a.etiqueta)}</p>' if a.etiqueta else ""
        itens.append(
            f'<li class="insight">{etiqueta}'
            f'<h2><a href="{a.caminho}">{a.titulo}</a></h2>'
            f'<p class="resumo-insight">{a.descricao}</p></li>')
    corpo = (f'<p class="entrada">{descricao}</p>\n'
             '<ol class="lista-insights">' + "\n".join(itens) + "</ol>")
    # "Conferido em" e o lastmod usam a revisao mais recente entre os artigos
    # (18/09/2026); `data` fica com a mais antiga, para o JSON-LD nao dizer
    # que o indice "foi publicado" no dia em que um artigo so foi revisto.
    # Datas ISO comparam certo como texto; sem nenhum artigo datado, vazio.
    publicadas = [a.data for a in artigos if a.data]
    revisadas = [a.modificado or a.data for a in artigos if a.modificado or a.data]
    return Pagina(slug="insights", titulo=titulo, descricao=descricao, corpo=corpo,
                  tipo="indice", data=min(publicadas) if publicadas else "",
                  modificado=max(revisadas) if revisadas else "")


# ------------------------------------------------------------ arquivos anexos

def sitemap(paginas: list[Pagina], base: str = BASE_URL, dados: dict | None = None) -> str:
    # A raiz e a unica sem `data` no arquivo (o carimbo e o instantaneo, nao
    # uma revisao de texto): o lastmod dela vem do dia do build (18/09/2026).
    lastmod_raiz = _dia_brasilia((dados or {}).get("gerado_em"))

    def lastmod(p: Pagina) -> str:
        return p.modificado or p.data or (lastmod_raiz if p.tipo == "ferramenta" else "")

    urls = "".join(
        f"<url><loc>{_e(p.url(base))}</loc>"
        + (f"<lastmod>{lastmod(p)}</lastmod>" if lastmod(p) else "")
        + "</url>"
        for p in paginas if p.indexavel)
    return ('<?xml version="1.0" encoding="UTF-8"?>\n'
            '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
            f"{urls}</urlset>\n")


def robots_txt(base: str = BASE_URL) -> str:
    # Sem Disallow: o site inteiro e para ser indexado.
    return f"User-agent: *\nAllow: /\n\nSitemap: {base.rstrip('/')}/sitemap.xml\n"


def llms_txt(paginas: list[Pagina], base: str = BASE_URL) -> str:
    """
    O indice para agentes de IA (llmstxt.org): titulo, descricao e links.

    Cada pagina de texto tem um espelho em Markdown ao lado (index.md), e e
    ele que o indice aponta: um agente le Markdown melhor que HTML com
    navegacao e botoes. A ferramenta nao tem espelho, e uma aplicacao.
    """
    linhas = [f"# {NOME}", "",
              f"> {DEFINICAO} Ferramenta e documentação sobre o processo de "
              "liberação de domínios .br e o leilão do Registro.br, com os "
              "limites do que a consulta pública mostra. Projeto independente de "
              f"{AUTOR} ({AUTOR_LINKEDIN}), sem vínculo com o Registro.br.",
              "", "## Páginas", ""]
    for p in paginas:
        if not p.indexavel:
            continue
        alvo = p.url(base) if p.tipo == "ferramenta" else p.url(base) + "index.md"
        linhas.append(f"- [{p.titulo_aba}]({alvo}): {p.descricao}")
    linhas += ["", "## Opcional", "",
               f"- [Texto completo]({base.rstrip('/')}/llms-full.txt): todas as "
               "páginas de texto num arquivo só, em Markdown",
               f"- [Dados da rodada]({base.rstrip('/')}/dados.json): o instantâneo "
               "em JSON que a ferramenta usa"]
    return "\n".join(linhas) + "\n"


def llms_full_txt(paginas: list[Pagina], dados: dict | None = None,
                  base: str = BASE_URL) -> str:
    """
    Todo o texto do site num arquivo so (a variante "full" do llmstxt.org).

    Um agente que vai responder "como funciona a liberacao de dominios .br"
    le isto de uma vez, com os numeros ja gravados e a URL de cada trecho
    para citar. A ferramenta entra so com a descricao: ela e uma aplicacao.
    """
    partes = [llms_txt(paginas, base).rstrip()]
    for p in paginas:
        # as listas por ramo sao dado que muda a cada build: o llms.txt aponta
        # o espelho de cada uma, e o texto completo fica com o que e texto
        if p.tipo in ("ferramenta", "lista") or not p.indexavel:
            continue
        partes.append(markdown_da_pagina(p, dados, base).rstrip())
    return "\n\n---\n\n".join(partes) + "\n"


# ------------------------------------------------------------------ markdown

class _Markdown(HTMLParser):
    """
    HTML dos fragmentos -> Markdown. Cobre so o que os fragmentos usam:
    titulos, paragrafos, listas aninhadas, tabelas (com ou sem cabecalho),
    listas de definicao (o glossario),
    citacoes, avisos, details, pre/code, negrito, italico e links.
    """

    _INLINE = {"strong": "**", "b": "**", "em": "*", "i": "*"}
    _VAZIAS = {"br", "img", "hr", "input", "meta", "link", "wbr"}

    def __init__(self, base: str):
        super().__init__(convert_charrefs=True)
        self.base = base.rstrip("/")
        self.blocos: list[str] = []
        self.buf: list[str] = []
        self.listas: list[list] = []          # [marcador, contador]
        self.citacao = 0
        self.pre = False
        self.ignorar = 0
        self.tabela = None
        self.linha = None
        self.celula_th = False
        self.href = None
        self.cartoes = 0        # dentro de <ol class="lista-insights">: nao e lista
        self.pagina_url = ""
        self.titulo_id = None   # id do h2/h3/dt aberto, para o link da secao

    # --- utilidades
    def _texto(self) -> str:
        t = "".join(self.buf)
        self.buf = []
        return re.sub(r"[ \t\r\n]+", " ", t).strip()

    def _emite(self, texto: str) -> None:
        if not texto:
            return
        if self.citacao:
            texto = "\n".join("> " + l for l in texto.splitlines())
        self.blocos.append(texto)

    def _fecha_paragrafo(self) -> None:
        self._emite(self._texto())

    def _fecha_item(self) -> None:
        texto = self._texto()
        if not texto or not self.listas:
            return
        marcador, n = self.listas[-1]
        if marcador == "1.":
            self.listas[-1][1] += 1
            marcador = f"{self.listas[-1][1]}."
        self._emite("  " * (len(self.listas) - 1) + f"{marcador} {texto}")

    # --- tags
    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        classes = (a.get("class") or "").split()
        if self.ignorar or tag in ("script", "style", "button", "nav", "svg", "form") \
                or "sr-apenas" in classes:
            if tag not in self._VAZIAS:
                self.ignorar += 1       # toda tag aberta fecha depois
            return
        if self.pre:
            return
        if tag in ("h2", "h3", "dt"):
            self.titulo_id = a.get("id")
        if tag in ("h1", "h2", "h3", "h4", "p", "div", "article", "section",
                   "details", "summary", "table", "dl", "dt", "dd", "figure", "figcaption"):
            if self.listas and tag == "p":
                self.buf.append(" ")          # <p> dentro de <li>: mesma linha
            elif self.listas:
                pass
            else:
                self._fecha_paragrafo()
        if tag in ("ul", "ol") and "lista-insights" in classes:
            self._fecha_paragrafo()      # cartoes do indice: blocos, nao lista
            self.cartoes += 1
        elif tag in ("ul", "ol"):
            if self.listas:
                self._fecha_item()
            else:
                self._fecha_paragrafo()
            self.listas.append(["-" if tag == "ul" else "1.", 0])
        elif tag == "li" and self.cartoes:
            self._fecha_paragrafo()
        elif tag == "li":
            self._fecha_item()
        elif tag == "p" and "etiqueta" in classes:
            self.buf.append("*")
        elif tag == "blockquote" or (tag == "div" and "aviso" in classes):
            self._fecha_paragrafo()
            self.citacao += 1
        elif tag == "cite":
            self.buf.append(" — ")
        elif tag == "pre":
            self._fecha_paragrafo()
            self.pre = True
            self.buf = []
        elif tag == "code":
            self.buf.append("`")
        elif tag in self._INLINE:
            self.buf.append(self._INLINE[tag])
        elif tag == "a":
            href = a.get("href") or ""
            if href.startswith("/"):
                href = self.base + href
            self.href = href
            self.buf.append("[")
        elif tag == "br":
            self.buf.append(" ")
        elif tag == "table":
            self.tabela = []
        elif tag == "tr":
            self.linha = []
        elif tag in ("td", "th"):
            self.buf = []
            self.celula_th = self.celula_th or tag == "th"
        elif tag == "summary":
            self.buf.append("**")

    def handle_endtag(self, tag):
        if self.ignorar:
            if tag not in self._VAZIAS:
                self.ignorar -= 1
            return
        if self.pre:
            if tag == "pre":
                self.pre = False
                self._emite("```\n" + "".join(self.buf).strip("\n") + "\n```")
                self.buf = []
            return
        if tag in ("h1", "h2", "h3", "h4", "dt"):
            texto = self._texto()
            if self.titulo_id and self.pagina_url and tag != "h1":
                texto = f"[{texto}]({self.pagina_url}#{self.titulo_id})"
            self.titulo_id = None
            nivel = 3 if tag == "dt" else int(tag[1])   # glossario: termo vira subtitulo
            self._emite("#" * nivel + " " + texto)
        elif tag in ("dd", "dl"):
            self._fecha_paragrafo()
        elif tag == "p" and not self.listas:
            if self.buf and self.buf[0] == "*" and self.buf[-1] != "*":
                self.buf.append("*")     # fecha a etiqueta
            self._fecha_paragrafo()
        elif tag == "li" and self.cartoes:
            self._fecha_paragrafo()
        elif tag == "li":
            self._fecha_item()
        elif tag in ("ul", "ol") and self.cartoes:
            self._fecha_paragrafo()
            self.cartoes -= 1
        elif tag in ("ul", "ol"):
            self._fecha_item()
            self.listas.pop()
        elif tag == "blockquote" or (tag == "div" and self.citacao and not self.listas):
            self._fecha_paragrafo()
            if tag == "blockquote":
                self.citacao -= 1
            elif self._div_aviso_aberto:
                self.citacao -= 1
        elif tag == "code":
            self.buf.append("`")
        elif tag in self._INLINE:
            self.buf.append(self._INLINE[tag])
        elif tag == "a":
            self.buf.append(f"]({self.href})" if self.href else "]")
            self.href = None
        elif tag in ("td", "th"):
            self.linha.append(self._texto().replace("|", "\\|"))
        elif tag == "tr":
            self.tabela.append((self.celula_th, self.linha))
            self.celula_th = False
            self.linha = None
        elif tag == "table":
            self._emite(self._tabela_md(self.tabela))
            self.tabela = None
        elif tag == "summary":
            self.buf.append("**")
            self._fecha_paragrafo()
        elif tag in ("div", "article", "section", "details", "figure", "figcaption"):
            self._fecha_paragrafo()

    # <div class="aviso"> so fecha a citacao no </div> correspondente; como
    # os avisos nao se aninham nos fragmentos, um contador simples basta
    @property
    def _div_aviso_aberto(self) -> bool:
        return self.citacao > 0

    def handle_data(self, data):
        if self.ignorar:
            return
        self.buf.append(data)

    @staticmethod
    def _tabela_md(linhas) -> str:
        linhas = [l for l in linhas if l[1]]
        if not linhas:
            return ""
        largura = max(len(l[1]) for l in linhas)
        preencher = lambda cels: cels + [""] * (largura - len(cels))
        if linhas[0][0]:
            cabecalho, corpo = preencher(linhas[0][1]), linhas[1:]
        else:                                   # sem cabecalho: linha vazia
            cabecalho, corpo = [""] * largura, linhas
        saida = ["| " + " | ".join(cabecalho) + " |",
                 "|" + "---|" * largura]
        for _, cels in corpo:
            saida.append("| " + " | ".join(preencher(cels)) + " |")
        return "\n".join(saida)

    def resultado(self) -> str:
        self._fecha_paragrafo()
        return "\n\n".join(b for b in self.blocos if b.strip())


def html_para_markdown(fragmento: str, base: str = BASE_URL, pagina_url: str = "") -> str:
    """Com pagina_url, titulo com id sai como link para a secao (o que um agente cita)."""
    conversor = _Markdown(base)
    conversor.pagina_url = pagina_url
    conversor.feed(fragmento)
    return conversor.resultado()


def markdown_da_pagina(pagina: Pagina, dados: dict | None = None,
                       base: str = BASE_URL) -> str:
    """O espelho em Markdown de uma pagina de texto, com os numeros gravados."""
    corpo_html = preencher_numeros(pagina.corpo, dados or {})
    if pagina.tipo != "indice":
        corpo_html, _ = ancorar(corpo_html)
    corpo = html_para_markdown(corpo_html, base, pagina.url(base))
    cabeca = [f"# {_sem_tags(pagina.titulo)}", ""]
    if pagina.tipo != "indice":          # o indice ja abre com a mesma frase
        cabeca += [f"> {pagina.descricao}", ""]
    if pagina.etiqueta:
        cabeca += [f"*{pagina.etiqueta}*", ""]
    rodape = ["", "---", "",
              f"Fonte: {pagina.url(base)} · {NOME}, projeto independente, sem "
              "vínculo com o Registro.br, o NIC.br ou o CGI.br."
              + (f" Conferido em {pagina.modificado or pagina.data}." if pagina.data else "")]
    return "\n".join(cabeca) + "\n" + corpo + "\n" + "\n".join(rodape) + "\n"


# ------------------------------------------------------------------- arquivo

_EXTENSO = ("zero um dois três quatro cinco seis sete oito nove dez onze doze "
            "treze quatorze quinze dezesseis dezessete dezoito dezenove vinte").split()


def _por_extenso(n: int) -> str:
    return _EXTENSO[n] if 0 <= n < len(_EXTENSO) else str(n)


def carregar(modelo: str) -> list[Pagina]:
    """Le site_modelo/conteudo/ e monta a lista de paginas, com o indice."""
    pasta = os.path.join(modelo, "conteudo")
    paginas: list[Pagina] = []
    for raiz, _, arquivos in os.walk(pasta):
        for nome in sorted(arquivos):
            if not nome.endswith(".html"):
                continue
            caminho = os.path.join(raiz, nome)
            relativo = os.path.relpath(caminho, pasta)
            with open(caminho, encoding="utf-8") as f:
                paginas.append(ler_fragmento(f.read(), slug_do_arquivo(relativo)))
    artigos = [p for p in paginas if p.tipo == "artigo" and p.secao == "insights"]
    if artigos and not any(p.slug == "insights" for p in paginas):
        paginas.append(indice_insights(
            artigos,
            titulo="Insights sobre o mercado de domínios .br",
            descricao=f"{_por_extenso(len(artigos)).capitalize()} achados sobre o "
                      "mercado de domínios .br: preços, leilões, disputas e nove "
                      "anos de listas, de fontes públicas. Cada um se lê sozinho."))
    ordem_nav = {slug: i for i, (slug, _) in enumerate(NAVEGACAO)}
    paginas.sort(key=lambda p: (ordem_nav.get(p.slug.split("/")[0], 99), p.ordem, p.slug))
    return paginas


def pagina_404() -> Pagina:
    """
    A pagina de erro (18/09/2026): sem ela, um endereco que nao existe
    devolvia 404 com corpo vazio, tela branca para quem vem das URLs
    /products/... que o Google ainda conhece da loja Shopify que usou
    liberados.com.br antes. Fora da lista normal de site_modelo/conteudo/
    porque `gerar()` grava direto em destino/404.html (a raiz do site: e la
    que o "not_found_handling": "404-page" do wrangler.jsonc procura),
    nunca em destino/404/index.html como as outras paginas.
    """
    corpo = (
        '<div class="ficha">\n'
        '  <form id="ficha-404-form" class="ficha-busca" role="search">\n'
        '    <label class="sr-apenas" for="ficha-404-nome">Domínio .br</label>\n'
        '    <input id="ficha-404-nome" type="text" inputmode="url" autocomplete="off"\n'
        '           autocapitalize="none" spellcheck="false" placeholder="ex.: padaria.com.br">\n'
        '    <button type="submit">Consultar</button>\n'
        '  </form>\n'
        '</div>\n'
        '<div class="ficha-acoes">\n'
        '  <a class="botao-link" href="/">Domínios</a>\n'
        '  <a class="botao-link" href="/perguntas/">Perguntas</a>\n'
        '  <a class="botao-link" href="/sobre/">Sobre</a>\n'
        '</div>'
    )
    return Pagina(
        slug="404",
        titulo="Esta página não existe",
        descricao=("O endereço não existe no Liberados. Digite um domínio .br "
                   "para ver quando ele volta, ou veja Domínios, Perguntas e Sobre."),
        corpo=corpo,
        tipo="pagina",
        indexavel=False,
        scripts=("erro404.js",),
    )


def gerar(modelo: str, destino: str, dados: dict | None) -> list[str]:
    """Escreve todas as paginas e os anexos em `destino`. Devolve os caminhos."""
    with open(os.path.join(modelo, "layout.html"), encoding="utf-8") as f:
        layout = f.read()
    paginas = carregar(modelo)
    todos = None
    caminho_todos = os.path.join(destino, "todos.json")
    if os.path.exists(caminho_todos):
        with open(caminho_todos, encoding="utf-8") as f:
            todos = json.load(f)
    from . import letras, ramos
    paginas += [Pagina(**campos) for campos in ramos.paginas(dados, todos)]
    paginas += [Pagina(**campos) for campos in letras.paginas(modelo)]
    escritos = []
    for p in paginas:
        pasta = os.path.join(destino, *p.slug.split("/")) if p.slug else destino
        os.makedirs(pasta, exist_ok=True)
        caminho = os.path.join(pasta, "index.html")
        with open(caminho, "w", encoding="utf-8") as f:
            f.write(render(p, layout, dados))
        escritos.append(caminho)
        if p.tipo != "ferramenta":
            espelho = os.path.join(pasta, "index.md")
            with open(espelho, "w", encoding="utf-8") as f:
                f.write(markdown_da_pagina(p, dados))
            escritos.append(espelho)
    anexos = {"sitemap.xml": sitemap(paginas, dados=dados), "robots.txt": robots_txt(),
              "llms.txt": llms_txt(paginas),
              "llms-full.txt": llms_full_txt(paginas, dados)}
    for nome, texto in anexos.items():
        caminho = os.path.join(destino, nome)
        with open(caminho, "w", encoding="utf-8") as f:
            f.write(texto)
        escritos.append(caminho)
    # A pagina de erro (18/09/2026): direto em destino/404.html, nunca via o
    # loop acima (que gravaria destino/404/index.html), e fora da lista
    # `paginas` que alimenta sitemap/llms.txt/llms-full.txt acima.
    erro = pagina_404()
    caminho_erro = os.path.join(destino, "404.html")
    with open(caminho_erro, "w", encoding="utf-8") as f:
        f.write(render(erro, layout, dados))
    escritos.append(caminho_erro)
    pasta_erro = os.path.join(destino, erro.slug)
    os.makedirs(pasta_erro, exist_ok=True)
    caminho_espelho = os.path.join(pasta_erro, "index.md")
    with open(caminho_espelho, "w", encoding="utf-8") as f:
        f.write(markdown_da_pagina(erro, dados))
    escritos.append(caminho_espelho)
    return escritos
