"""
Cliente do Registro.br.

Adaptador: o unico lugar do projeto que fala HTTP com o registro.br. Traduz
resposta crua em `Leitura` chamando a camada de dominio, mas nao decide nada
por conta propria.

SOBRE O RITMO DE CONSULTA, medido em 09/09/2026:

    2,0s, uma conexao   ->  0,46 req/s  ->  limpo
    1,0s, uma conexao   ->  0,87 req/s  ->  ja aparecem falhas
    1,0s, tres conexoes ->  2,70 req/s  ->  DERRUBA o servico

A 2,7 req/s o registro.br passou a responder "Taxa maxima de consultas
excedida" para o navegador do proprio usuario, nao so para o script: o limite
e por IP e afeta a maquina inteira. Por isso `PAUSA_SEGURA` e o piso usado em
todo lugar, e a varredura e sequencial. A lista muda uma vez por mes; nao ha
motivo para apressar.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from dataclasses import dataclass

from ..dominio.situacao import Leitura, Situacao, classificar

ENDPOINT = "https://registro.br/v2/ajax/avail/raw/{}"

# As tres listas oficiais da rodada. A distincao entre a segunda e a terceira
# e sutil e custou um erro de leitura: "processo-competitivo" e quem esta
# HABILITADO a leilao por ter acumulado rodadas travadas, enquanto
# "competicao" e quem esta com leilao ACONTECENDO agora.
LISTA_LIBERACAO = "https://registro.br/dominio/lista-processo-liberacao.txt"
LISTA_ELEGIVEIS = "https://registro.br/dominio/lista-processo-competitivo.txt"
LISTA_EM_LEILAO = "https://registro.br/dominio/lista-competicao.txt"

UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120 Safari/537.36")

PAUSA_SEGURA = 2.0      # segundos entre consultas; nao diminua
TIMEOUT = 15

# os arquivos de lista vem em ISO-8859-1, nao em UTF-8
CODIFICACAO_LISTAS = "latin-1"

# Prefixo sem acento de proposito (18/09/2026): "liberacao" e "periodo" tem
# 'ç' e 'í', que uma mudanca de codificacao (a lista veio sempre em Latin-1,
# mas nada garante isso para sempre) transformaria em outro byte e faria o
# validador rejeitar uma lista boa por causa da acentuacao, nao do conteudo.
PREFIXO_LISTA = "# Processo de libera"
RODAPE_LISTA = "# Fim do arquivo"


class ListaInvalida(RuntimeError):
    """
    O corpo baixado nao tem cara de lista oficial do processo de liberacao.

    Um nome de arquivo que nao existe no registro.br devolve HTTP 200 com o
    HTML do site, nao um erro (conferido com HEAD em 18/09/2026, numa lista
    de outubro inexistente: 200, text/html, 4636 bytes). Se isso tambem
    acontecer no instante em que a lista do mes troca, dia 12/10, sem essa
    checagem ler_lista() leria o HTML como se fosse uma lista de dominios.
    """


def validar_lista(url: str, texto: str, content_type: str | None = None) -> None:
    """
    Recusa uma pagina HTML disfarcada de lista. Nao exige Content-Type: um
    tipo inesperado nao pode derrubar uma lista boa, entao ele so entra na
    mensagem de erro.

    O cabecalho com o periodo nao e sempre a primeira linha: em
    `lista-competicao.txt` a primeira e "# Arquivo gerado em ...", e o
    periodo vem depois (conferido em work/leilao/lista-competicao.txt,
    18/09/2026). Por isso procura nas 6 primeiras linhas, a mesma janela que
    `_janela()` e `gerado_em()` ja usam, em vez de exigir a primeira.
    """
    bruto = texto.lstrip()
    linhas = texto.splitlines()
    linhas_uteis = texto.rstrip().splitlines()
    ultima = linhas_uteis[-1] if linhas_uteis else ""
    tem_cabecalho = any(l.startswith(PREFIXO_LISTA) for l in linhas[:6])
    valido = (not bruto.startswith("<")
             and tem_cabecalho
             and ultima.strip() == RODAPE_LISTA)
    if not valido:
        amostra = texto[:80]
        raise ListaInvalida(
            f"{url} nao parece uma lista do processo de liberacao "
            f"(content-type={content_type!r}, inicio={amostra!r})")


@dataclass(frozen=True)
class Rodada:
    """As tres listas de uma rodada, mais a janela de tempo dela."""

    liberacao: list[str]
    elegiveis: set[str]
    em_leilao: set[str]
    inicio: str | None = None
    fim: str | None = None
    # quando o Registro.br gerou a lista de leiloes; ela e refeita durante a
    # rodada, entao essa data e a idade do fato "esta em leilao"
    em_leilao_em: str | None = None
    # False quando a lista de leiloes veio invalida (HTML ou rede) e
    # `em_leilao` ficou vazio por falta de dado, nao porque a rodada nao tem
    # nenhum leilao aberto. varrer.preparar() usa isto para nao apagar um
    # COMPETITIVO ja lido so porque esta consulta nao conseguiu confirmar.
    em_leilao_lido: bool = True

    @property
    def total(self) -> int:
        return len(self.liberacao)


def _abrir(url: str, timeout: int = TIMEOUT):
    pedido = urllib.request.Request(
        url, headers={"User-Agent": UA, "Accept": "application/json"})
    return urllib.request.urlopen(pedido, timeout=timeout)


def consultar(dominio: str, timeout: int = TIMEOUT) -> dict:
    """Devolve o JSON cru do endpoint de disponibilidade."""
    with _abrir(ENDPOINT.format(dominio), timeout) as resposta:
        return json.loads(resposta.read().decode("utf-8", errors="replace"))


def verificar(dominio: str, timeout: int = TIMEOUT) -> Leitura:
    """Consulta e classifica. Falha de rede vira Leitura(ERRO), nao excecao."""
    try:
        return classificar(consultar(dominio, timeout))
    except urllib.error.HTTPError as e:
        situacao = Situacao.LIMITADO if e.code == 429 else Situacao.ERRO
        return Leitura(situacao, detalhe=f"http {e.code}")
    except Exception as e:                      # rede, timeout, json invalido
        return Leitura(Situacao.ERRO, detalhe=str(e)[:200])


# ---------------------------------------------------------------------------
# Listas da rodada
# ---------------------------------------------------------------------------

def _baixar_texto(url: str, destino: str | None = None, timeout: int = 180,
                  validar=None) -> str:
    with _abrir(url, timeout) as resposta:
        content_type = resposta.headers.get("Content-Type")
        texto = resposta.read().decode(CODIFICACAO_LISTAS)
    if validar:
        validar(url, texto, content_type)
    if destino:
        os.makedirs(os.path.dirname(destino), exist_ok=True)
        with open(destino, "w", encoding="utf-8") as f:
            f.write(texto)
    return texto


def ler_lista(texto: str) -> list[str]:
    return [l.strip().lower() for l in texto.splitlines()
            if l.strip() and not l.startswith("#")]


def _janela(texto: str) -> tuple[str | None, str | None]:
    """Extrai o periodo da rodada do cabecalho comentado do arquivo."""
    import re
    for linha in texto.splitlines()[:6]:
        achado = re.search(r"de (\S+) a (\S+)", linha)
        if achado:
            return achado.group(1), achado.group(2)
    return None, None


def gerado_em(texto: str) -> str | None:
    """Data do cabecalho "# Arquivo gerado em <iso>" de uma lista oficial."""
    import re
    for linha in texto.splitlines()[:6]:
        achado = re.search(r"gerado em (\S+)", linha)
        if achado:
            return achado.group(1)
    return None


def janela_do_cache(diretorio: str) -> tuple[str | None, str | None]:
    """Le o periodo da rodada do arquivo ja baixado, sem ir a rede."""
    caminho = os.path.join(diretorio, "liberacao.txt")
    if not os.path.exists(caminho):
        return None, None
    with open(caminho, encoding="utf-8", errors="replace") as f:
        return _janela("".join(f.readline() for _ in range(6)))


def baixar_rodada(cache: str | None = None, aviso=None) -> Rodada:
    """
    Baixa as tres listas oficiais. `cache` e um diretorio onde guardar os
    arquivos crus, util para depurar sem repetir o download de 2,5 MB.
    """
    def diga(msg):
        if aviso:
            aviso(msg)

    def caminho(nome):
        return os.path.join(cache, nome) if cache else None

    # elegiveis e liberacao: lista invalida levanta ListaInvalida (subclasse
    # de RuntimeError) e para a execucao aqui, sem comitar nem publicar nada
    # (varrer.py nao trata a excecao, e o passo "Varrer" do workflow falha
    # antes dos passos de commit e deploy).
    diga("baixando lista de elegiveis ao leilao")
    elegiveis = ler_lista(_baixar_texto(LISTA_ELEGIVEIS, caminho("elegiveis.txt"),
                                        validar=validar_lista))

    diga("baixando lista de leiloes em andamento")
    em_leilao_em = None
    em_leilao_lido = True
    try:
        cru_leilao = _baixar_texto(LISTA_EM_LEILAO, caminho("em_leilao.txt"),
                                   validar=validar_lista)
        em_leilao = ler_lista(cru_leilao)
        em_leilao_em = gerado_em(cru_leilao)
    except Exception as e:
        # Sem ela a varredura segue, mas perde o sinal mais barato que existe:
        # uma requisicao que diz quem esta em leilao AGORA, contra uma consulta
        # por nome que pode ter dias. ListaInvalida cai aqui tambem, do
        # mesmo jeito que uma falha de rede ja caia antes de 18/09/2026.
        # `em_leilao` fica vazio, mas `em_leilao_lido=False` avisa quem chama
        # que isto e "nao sei", nao "nenhum leilao aberto" (18/09/2026,
        # correcao apos revisao: sem o flag, varrer.preparar() apagava todo
        # COMPETITIVO ja lido).
        diga(f"lista de leiloes indisponivel ({e}), seguindo sem ela")
        em_leilao = []
        em_leilao_lido = False

    diga("baixando lista do processo de liberacao (arquivo grande)")
    cru = _baixar_texto(LISTA_LIBERACAO, caminho("liberacao.txt"),
                        validar=validar_lista)
    liberacao = ler_lista(cru)
    inicio, fim = _janela(cru)

    diga(f"rodada: {len(liberacao)} em liberacao, {len(elegiveis)} elegiveis, "
         f"{len(em_leilao)} em leilao")
    return Rodada(liberacao, set(elegiveis), set(em_leilao), inicio, fim,
                  em_leilao_em, em_leilao_lido)
