"""
Cliente do ISAVAIL, o servico oficial de disponibilidade do Registro.br.

Achado de 12/09/2026, em ftp.registro.br/pub/isavail/: o Registro.br publica
desde 2007 um protocolo de texto, documentado (Protocolo-ISAVAIL.txt), com
clientes-exemplo em Python, Perl, PHP, Java, C++ e Ruby, e diz no README que
"o usuario tem a opcao de implementar seu proprio cliente". O endpoint web
que a caixa de busca usa (`registro.br/v2/ajax/avail/raw/`) e descrito la
como "o proxy no site do Registro.br" deste servico. Ou seja: a "API que nao
existe" existe, so nao e HTTP.

Consequencia mais importante: o campo `status` e uma ENUMERACAO (0 a 9),
nao o bitmask que este projeto deduziu por sondagem. Os valores coincidem
nos casos vistos ate entao, mas o 5 ("aguardando processo de liberacao")
seria lido como "em liberacao, sem candidato". Ver `dominio/situacao.py`.

O protocolo, resumido (transporte UDP, porta 43, ISO-8859-1):

    pergunta   <versao> <cookie> <idioma> <qid> <fqdn> <sugerir>
    resposta   % Copyright Nic.br
               ST <status> <qid>
               <fqdn>[|<fqdn-ace>]
               [linhas extras, conforme o status]

Sem cookie valido a resposta e `CK <cookie> <qid>`: guarda-se o cookie e
repete-se a pergunta. Um cookie vale para as consultas seguintes.

O QUE ESTE ADAPTADOR NAO FAZ, e por que:

- Nao entra na varredura. O limite de consultas do ISAVAIL nao e publicado,
  e medi-lo e bater nele; a regra do projeto e nao bater. O canal fica como
  contingencia documentada para o dia em que o endpoint web mudar, risco que
  o proprio Registro.br apontou (issue #98 do whmcs-registrobr-epp,
  26/07/2025: "corre risco de alteracao de localizacao e comportamento").
- Nao consome as datas. Em 12/09/2026, para a rodada de 09/09 a 16/09, o
  ISAVAIL devolveu "2026-09-26 15:00:00" nos tres campos de data de
  vacina.com.br (leilao) e nos dois de one.com.br (liberacao), enquanto o
  endpoint web devolvia 09/09 e 16/09. As datas ficam em `Resposta.datas`
  para quem quiser olhar, mas nao entram no payload.
- Tambem corta os tickets em 10: a especificacao diz `ticket1|...|ticket10`.
  E a fonte oficial da limitacao A3. Contagem acima de 10 so pelo RDAP.
"""

from __future__ import annotations

import random
import socket
from dataclasses import dataclass

from ..dominio.situacao import Leitura, Situacao, classificar

SERVIDOR = "avail.registro.br"
PORTA = 43
VERSAO = 2              # a unica que devolve o status 9 (processo competitivo)
IDIOMA_PT = 1
IDIOMA_EN = 0
SUGERIR = 0             # 1 pede sugestoes de outras extensoes; nao precisamos

PAUSA_SEGURA = 2.0      # mesmo Registro.br do outro lado; mesma educacao
TIMEOUT = 5
TENTATIVAS = 3
COOKIE_INICIAL = "0" * 20
CODIFICACAO = "iso-8859-1"
TAMANHO_MAXIMO = 4096


@dataclass(frozen=True)
class Resposta:
    """Um pacote do ISAVAIL ja lido. `status` None e falha de transporte."""

    status: int | None
    qid: str = ""
    fqdn: str = ""
    fqdnace: str = ""
    tickets: tuple[int, ...] = ()
    datas: tuple[str, ...] = ()         # cruas e nao confiaveis; ver o topo
    expira_em: str = ""
    publicacao: str = ""
    servidores: tuple[str, ...] = ()
    sugestoes: tuple[str, ...] = ()
    mensagem: str = ""
    cookie: str = ""                    # so na resposta "CK"
    bruto: str = ""

    @property
    def novo_cookie(self) -> bool:
        return bool(self.cookie)

    def payload(self) -> dict:
        """
        A resposta na forma do JSON do endpoint web.

        Assim `situacao.classificar` serve para os dois canais, e o resto do
        projeto nao precisa saber por onde a consulta entrou.
        """
        p: dict = {"status": self.status, "fqdn": self.fqdn,
                   "fqdnace": self.fqdnace}
        if self.tickets:
            p["tickets"] = list(self.tickets)
        if self.mensagem:
            p["reasons"] = [self.mensagem]
        if self.status == 2:
            if self.expira_em:
                p["expires-at"] = self.expira_em
            if self.publicacao:
                p["publication-status"] = self.publicacao
            p["hosts"] = list(self.servidores)
        return p


def _tickets(linha: str) -> tuple[int, ...]:
    return tuple(int(t) for t in linha.split("|") if t.strip().isdigit())


def _sugestoes(linha: str) -> tuple[str, ...]:
    return tuple(s.strip() + ".br" for s in linha.split("|") if s.strip())


def interpretar(texto: str) -> Resposta:
    """
    Le um pacote de resposta. Sem rede: testavel com os pacotes gravados.

    A ordem de `fqdn|fqdn-ace` varia: o exemplo da especificacao traz o ACE
    primeiro, a resposta real de 12/09/2026 para café.com.br trouxe
    "café.com.br|xn--caf-dma.com.br". Por isso o ACE e reconhecido pelo
    prefixo, nao pela posicao.
    """
    linhas = [l.strip() for l in texto.splitlines()]
    linhas = [l for l in linhas if l and not l.startswith("%")]
    if not linhas:
        return Resposta(status=None, mensagem="resposta vazia", bruto=texto)

    cabeca = linhas[0].split()
    if cabeca[0] == "CK" and len(cabeca) >= 2:
        return Resposta(status=None, cookie=cabeca[1][:20],
                        qid=cabeca[2] if len(cabeca) > 2 else "", bruto=texto)
    if cabeca[0] != "ST" or len(cabeca) < 2 or not cabeca[1].isdigit():
        return Resposta(status=None, bruto=texto,
                        mensagem=f"cabecalho inesperado: {linhas[0]}")

    status = int(cabeca[1])
    qid = cabeca[2] if len(cabeca) > 2 else ""
    extra = linhas[1:]

    if status == 8:
        return Resposta(status, qid, mensagem=" ".join(extra), bruto=texto)

    partes = (extra[0] if extra else "").split("|")
    fqdnace = next((p for p in partes if p.startswith("xn--")), "")
    fqdn = next((p for p in partes if not p.startswith("xn--")), partes[0])
    resto = extra[1:]

    tickets: tuple[int, ...] = ()
    datas: tuple[str, ...] = ()
    sugestoes: tuple[str, ...] = ()
    servidores: tuple[str, ...] = ()
    expira_em = publicacao = mensagem = ""

    if status == 1:
        tickets = _tickets(resto[0]) if resto else ()
    elif status == 2:
        if resto:
            campos = resto[0].split("|")
            expira_em = campos[0]
            publicacao = campos[1] if len(campos) > 1 else ""
            servidores = tuple(c for c in campos[2:] if c)
        if len(resto) > 1:
            sugestoes = _sugestoes(resto[1])
    elif status in (3, 4):
        mensagem = resto[0] if resto else ""
        if status == 3 and len(resto) > 1:
            sugestoes = _sugestoes(resto[1])
    elif status in (6, 7, 9):
        if resto:
            datas = tuple(d.strip() for d in resto[0].split("|"))
        if len(resto) > 1:
            tickets = _tickets(resto[1])

    return Resposta(status, qid, fqdn, fqdnace, tickets, datas, expira_em,
                    publicacao, servidores, sugestoes, mensagem, bruto=texto)


class Cliente:
    """
    Fala UDP com o ISAVAIL e guarda o cookie entre consultas.

    `enviar` entra por parametro para o teste trocar o transporte por uma
    funcao que devolve pacotes gravados. Nenhum teste toca a rede.
    """

    def __init__(self, servidor: str = SERVIDOR, porta: int = PORTA,
                 timeout: float = TIMEOUT, idioma: int = IDIOMA_PT,
                 enviar=None):
        self.servidor = servidor
        self.porta = porta
        self.timeout = timeout
        self.idioma = idioma
        self.cookie = COOKIE_INICIAL
        self._enviar = enviar or self._enviar_udp

    def _enviar_udp(self, pergunta: str) -> str:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.settimeout(self.timeout)
            s.sendto(pergunta.encode(CODIFICACAO, errors="replace"),
                     (self.servidor, self.porta))
            dados, _ = s.recvfrom(TAMANHO_MAXIMO)
        return dados.decode(CODIFICACAO, errors="replace")

    def pergunta(self, dominio: str) -> str:
        qid = str(random.randint(1, 10**9))
        return f"{VERSAO} {self.cookie} {self.idioma} {qid} {dominio} {SUGERIR}"

    def consultar(self, dominio: str) -> Resposta:
        dominio = dominio.strip().lower()
        ultimo = "sem resposta"
        # +1 porque a primeira resposta pode ser so o cookie
        for _ in range(TENTATIVAS + 1):
            try:
                texto = self._enviar(self.pergunta(dominio))
            except OSError as e:
                ultimo = str(e)[:200]
                continue
            resposta = interpretar(texto)
            if resposta.novo_cookie:
                self.cookie = resposta.cookie
                continue
            return resposta
        return Resposta(status=None, mensagem=ultimo)

    def verificar(self, dominio: str) -> Leitura:
        """Consulta e traduz para a mesma `Leitura` do endpoint web."""
        resposta = self.consultar(dominio)
        if resposta.status is None:
            return Leitura(Situacao.ERRO, detalhe=resposta.mensagem)
        return classificar(resposta.payload())


_padrao: Cliente | None = None


def verificar(dominio: str) -> Leitura:
    """Atalho com um cliente compartilhado, para o cookie durar."""
    global _padrao
    if _padrao is None:
        _padrao = Cliente()
    return _padrao.verificar(dominio)
