"""
Cliente do Internet Archive (Wayback Machine).

O RDAP diz o que um dominio E hoje. Este diz o que ele JA FOI.

A diferenca importa porque "nao resolve" e uma foto, nao um filme. Um nome
que nunca teve nada e um nome que teve um site por vinte anos e morreu ano
passado sao coisas diferentes, e do lado de fora parecem iguais.

Foi essa fonte que corrigiu a historia do `pneus.com.br` neste projeto. Pelo
RDAP e pelo DNS, o `.br` mais caro ja vendido (R$ 220 mil em 2019) nao
entrega nada — e a conclusao facil era "compraram e nunca usaram". O arquivo
mostra o contrario: de maio/2019 a abril/2023 ele redirecionava para
`sunset-tires.com`, e a ultima captura, de dezembro/2023, ja apontava para
`sunset-tires.com/pt/`. Foi usado por quase cinco anos, e depois desligado.

Sem o arquivo, a afirmacao publicada teria sido falsa.

Usa a CDX Server API, que e publica e nao pede chave:

    http://web.archive.org/cdx/search/cdx?url=<dominio>&output=json

`collapse=timestamp:6` reduz para uma captura por mes: o interesse aqui e a
forma da linha do tempo, nao cada visita do robo.
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass

CDX = ("http://web.archive.org/cdx/search/cdx"
       "?url={}&output=json&collapse=timestamp:{}")
INSTANTANEO = "http://web.archive.org/web/{}id_/http://{}/"

# O Internet Archive PEDE identificacao descritiva, ao contrario do
# Registro.br: a pagina "Bots, LLMs, and Automated Access"
# (archive.org/developers/bots.html, lida em 17/09/2026) manda dizer quem e
# o cliente e honrar 429/Retry-After. Ate 17/09/2026 mandavamos um Chrome
# falso daqui, o que contraria a politica e convida bloqueio: quem se
# disfarca de navegador nao pode reclamar de ser tratado como um.
# O UA de navegador do rdap.py e outro caso, outro servico, outra politica.
UA = ("LiberadosBot/1.0 (+https://liberados.com.br; "
      "https://github.com/dmgobbi)")

PAUSA_SEGURA = 2.0
TIMEOUT = 60

# 2xx e 3xx contam como "respondia alguma coisa". Um 301 nao e um site, mas
# tambem nao e abandono: e alguem apontando o nome para outro lugar de
# proposito — que foi exatamente o caso do pneus.com.br.
VIVOS = ("200", "301", "302")


@dataclass(frozen=True)
class Captura:
    quando: str      # AAAAMM
    status: str


@dataclass(frozen=True)
class Historico:
    """A linha do tempo de um dominio no arquivo."""

    dominio: str
    capturas: tuple[Captura, ...] = ()
    erro: str | None = None

    @property
    def existe(self) -> bool:
        return bool(self.capturas)

    @property
    def primeira(self) -> str | None:
        return self.capturas[0].quando if self.capturas else None

    @property
    def ultima(self) -> str | None:
        return self.capturas[-1].quando if self.capturas else None

    @property
    def teve_site(self) -> bool:
        """Alguma vez respondeu 200 — houve conteudo proprio ali."""
        return any(c.status == "200" for c in self.capturas)

    @property
    def ultima_viva(self) -> str | None:
        """Quando respondeu algo pela ultima vez."""
        for c in reversed(self.capturas):
            if c.status in VIVOS:
                return c.quando
        return None

    @property
    def anos_de_site(self) -> int:
        """Quantos anos distintos tiveram captura com 200."""
        return len({c.quando[:4] for c in self.capturas if c.status == "200"})

    def resumo(self) -> str:
        # 14/09/2026: com o arquivo fora do ar, x.com.br saiu "nunca
        # capturado" e o site publicou isso; tinha 100 capturas de 1998 a 2019
        if self.erro:
            return f"arquivo nao respondeu ({self.erro}); nada a concluir"
        if not self.existe:
            return "nunca capturado pelo arquivo"
        partes = [f"{len(self.capturas)} capturas",
                  f"{_mes(self.primeira)} a {_mes(self.ultima)}"]
        if self.teve_site:
            partes.append(f"site proprio em {self.anos_de_site} ano(s)")
        if self.ultima_viva:
            partes.append(f"respondeu por ultimo em {_mes(self.ultima_viva)}")
        return "; ".join(partes)


def _mes(carimbo: str | None) -> str:
    if not carimbo or len(carimbo) < 6:
        return "?"
    return f"{carimbo[4:6]}/{carimbo[:4]}"


def _abrir(url: str, timeout: int = TIMEOUT):
    pedido = urllib.request.Request(url, headers={"User-Agent": UA})
    return urllib.request.urlopen(pedido, timeout=timeout)


def consultar(dominio: str, por_mes: int = 6, timeout: int = TIMEOUT) -> list:
    """Devolve a resposta crua da CDX: primeira linha e o cabecalho."""
    url = CDX.format(urllib.parse.quote(dominio, safe=""), por_mes)
    with _abrir(url, timeout) as resposta:
        texto = resposta.read().decode("utf-8", errors="replace")
    if not texto.strip():
        return []                      # sem captura nenhuma: resposta vazia
    return json.loads(texto)


def interpretar(dominio: str, cru: list) -> Historico:
    """
    Traduz a resposta da CDX em Historico. Sem rede: da para testar direto.

    A ordem das colunas vem no cabecalho e nao e assumida — a CDX ja mudou de
    formato antes, e ler por indice fixo seria confiar em algo que nao esta
    prometido em lugar nenhum.
    """
    if not cru or len(cru) < 2:
        return Historico(dominio=dominio)
    cabecalho = cru[0]
    try:
        i_t = cabecalho.index("timestamp")
        i_s = cabecalho.index("statuscode")
    except ValueError:
        return Historico(dominio=dominio, erro="formato inesperado da CDX")

    capturas = []
    for linha in cru[1:]:
        if len(linha) > max(i_t, i_s):
            capturas.append(Captura(quando=str(linha[i_t])[:6],
                                    status=str(linha[i_s])))
    capturas.sort(key=lambda c: c.quando)
    return Historico(dominio=dominio, capturas=tuple(capturas))


# O arquivo sai do ar por minutos ("Temporarily Offline", HTTP 503) varias
# vezes por dia: tenta de novo antes de desistir.
ESPERAS = (15, 60)


def historico(dominio: str, timeout: int = TIMEOUT, esperas=ESPERAS) -> Historico:
    """
    Consulta a CDX. Falha de rede vira Historico com erro, nao excecao.

    Erro nunca e "sem captura": quem le precisa ver `erro` antes de `existe`.
    """
    dominio = dominio.strip().lower()
    for espera in (*esperas, None):
        try:
            return interpretar(dominio, consultar(dominio, timeout=timeout))
        except urllib.error.HTTPError as e:
            erro = f"http {e.code}"
            if e.code < 500 and e.code != 429:
                break
        except Exception as e:
            erro = str(e)[:200]
        if espera is None:
            break
        time.sleep(espera)
    return Historico(dominio=dominio, erro=erro)


# ------------------------------------------------------------ o sparkline

# `__wb/sparkline` (18/09/2026): a tela do proprio Wayback usa este endpoint
# para desenhar o grafico de capturas. Responde "esse nome ja teve site?" em
# uma requisicao de ~800 B e ~0,4 a 0,9 s; a CDX leva de 5 a 56 s para a
# mesma pergunta. Mas e INTERNO e nao documentado: pode sumir sem aviso, e
# por isso `resumo()` cai para a CDX quando ele falha.
SPARKLINE = ("https://web.archive.org/__wb/sparkline"
             "?output=json&collection=web&url={}")


class Bloqueado(Exception):
    """
    O Internet Archive fechou a porta para este IP.

    Medido em 18/09/2026 (limitacao F9): ele NAO responde 429 quando o IP
    passa do limite -- RECUSA A CONEXAO (Errno 111) ou deixa o handshake TLS
    pendurado. A regra de sempre, "parar no 429", nao pega isso. Quem varre
    precisa parar aqui tambem, e nao insistir: do IP errado, esperar mais
    nao ajuda.
    """


def _e_bloqueio(erro: Exception) -> bool:
    if isinstance(erro, urllib.error.HTTPError):
        return erro.code == 429
    texto = str(erro)
    return ("Connection refused" in texto or "Errno 111" in texto
            or "handshake" in texto)


def sparkline(dominio: str, timeout: int = 30) -> dict:
    """
    O JSON cru do sparkline. Levanta `Bloqueado` quando o IP foi barrado, e a
    excecao original em qualquer outra falha (para `resumo()` cair na CDX).
    """
    url = SPARKLINE.format(urllib.parse.quote(dominio.strip().lower(), safe=""))
    try:
        with _abrir(url, timeout) as r:
            return json.loads(r.read().decode("utf-8", errors="replace"))
    except Exception as e:
        if _e_bloqueio(e):
            raise Bloqueado(str(e)[:120]) from e
        raise


def resumo(dominio: str, consultado: str = ""):
    """
    `arquivo.Resumo` de um nome: sparkline, e a CDX se ele falhar.

    `Bloqueado` NAO cai para a CDX: e o mesmo servidor, e o bloqueio e do IP.
    Cair nele so gastaria a mesma porta fechada, mais devagar.
    """
    from ..dominio import arquivo
    try:
        return arquivo.de_sparkline(dominio, sparkline(dominio), consultado)
    except Bloqueado:
        raise
    except Exception:
        h = historico(dominio, esperas=())
        if h.erro:
            if "refused" in h.erro or "handshake" in h.erro:
                raise Bloqueado(h.erro)
            return None          # falha de verdade: nao gravar "nunca capturado"
        return arquivo.de_capturas(dominio, h.capturas, consultado)


def destino(dominio: str, carimbo: str, timeout: int = TIMEOUT) -> str | None:
    """
    Para onde uma captura redirecionava.

    Custa uma requisicao a mais, entao so vale a pena quando o historico ja
    mostrou 301/302 — e ai responde a pergunta que interessa: o dono apontou
    o nome para onde?

    O sufixo `id_` no caminho pede a resposta ORIGINAL arquivada, sem a
    barra de navegacao que o arquivo injeta. Sem ele nao da para ler o
    cabecalho Location de verdade.
    """
    url = INSTANTANEO.format(carimbo, dominio)
    try:
        pedido = urllib.request.Request(url, headers={"User-Agent": UA})
        # nao seguir o redirecionamento: o alvo E a resposta
        class SemRedirecionar(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, *a, **k):
                return None
        abridor = urllib.request.build_opener(SemRedirecionar)
        with abridor.open(pedido, timeout=timeout) as r:
            local = r.headers.get("Location")
    except urllib.error.HTTPError as e:
        local = e.headers.get("Location") if e.headers else None
    except Exception:
        return None
    if not local:
        return None
    # o arquivo embrulha o destino no proprio dominio dele; desembrulha
    marca = "id_/"
    if marca in local:
        local = local.split(marca, 1)[1]
    return local or None


# ------------------------------------------------ copias de arquivo inteiro

CDX_ARQUIVO = ("http://web.archive.org/cdx/search/cdx"
               "?url={}&output=json&fl=timestamp,original,statuscode,digest"
               "&collapse=digest")
COPIA = "http://web.archive.org/web/{}id_/{}"

# O limite do arquivo e ~60 requisicoes por minuto e o bloqueio dobra a cada
# reincidencia (limitacao F3). Arquivo inteiro e maior que pagina: 4 s.
PAUSA_ARQUIVO = 4.0


def copias_de_arquivo(url: str, timeout: int = TIMEOUT) -> list[tuple[str, str]]:
    """
    (carimbo, url original) de cada copia com conteudo diferente e HTTP 200.

    `collapse=digest` junta copias de bytes identicos, nao de rodadas
    identicas: a mesma rodada capturada em dois dias pode vir duas vezes, e
    quem agrupa por rodada e garimpo.dominio.historico.
    """
    with _abrir(CDX_ARQUIVO.format(urllib.parse.quote(url, safe="")), timeout) as r:
        texto = r.read().decode("utf-8", errors="replace")
    linhas = json.loads(texto) if texto.strip() else []
    return [(l[0], l[1]) for l in linhas[1:] if len(l) >= 3 and l[2] == "200"]


def baixar_copia(carimbo: str, original: str, timeout: int = 120) -> bytes:
    """Os bytes originais arquivados (sufixo id_: sem a barra do arquivo)."""
    with _abrir(COPIA.format(carimbo, original), timeout) as r:
        return r.read()
