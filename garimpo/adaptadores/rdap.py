"""
Cliente RDAP do Registro.br, e o teste de "esse dominio esta vivo?".

O endpoint de disponibilidade responde sobre a RODADA: se o nome esta em
liberacao e quantos candidatos tem. Nao responde sobre o nome ja registrado.
O RDAP responde: quem e o titular, desde quando, ate quando, e em quais
servidores de DNS ele esta delegado.

Foi essa combinacao que abriu a historia do pneus.com.br, o .br mais caro ja
vendido (R$ 220 mil em 2019):

    RDAP  -> titular SUNSET PNEUS DO BRASIL LTDA, expira em 2029,
             delegado para a.auto.dns.br / b.auto.dns.br
    DNS   -> nenhum endereco

Ou seja: pago, renovado por uma decada, e servindo nada. Sozinho, nenhum dos
dois lados diz isso; juntos, dizem.

Duas fontes, duas camadas de rede, e nenhuma dependencia externa:

- RDAP e HTTP com JSON, entao `urllib` resolve;
- a resolucao usa `socket.getaddrinfo`, que ja e o resolvedor do sistema.
  Nao construimos pacote DNS na mao: os servidores autoritativos que
  interessam ja vem no proprio RDAP, no campo `nameservers`.

SOBRE O RITMO: o RDAP e um servico separado do endpoint de disponibilidade e
nao compartilha a contagem dele, mas continua sendo o mesmo Registro.br do
outro lado. `PAUSA_SEGURA` daqui vale o mesmo respeito.
"""

from __future__ import annotations

import json
import socket
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, replace

ENDPOINT = "https://rdap.registro.br/domain/{}"
ENDPOINT_ENTIDADE = "https://rdap.registro.br/entity/{}"

UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120 Safari/537.36")

PAUSA_SEGURA = 2.0
TIMEOUT = 20

# Delegar para ca e o mesmo que nao delegar para lugar nenhum: e o DNS que o
# proprio Registro.br empresta a quem registrou e ainda nao apontou o nome
# para servidor proprio. Zona existe, respostas nao.
DNS_DO_REGISTRO = ("auto.dns.br",)

# O que o proprio Registro.br conclui ao testar cada servidor de DNS. Vem
# na extensao NIC.br do RDAP (ftp.registro.br/pub/doc/br-rdap-extensions-02.txt,
# e github.com/registrobr/rdap, protocol/status.go), como eventos por
# servidor: "delegation check" com um status, e "last correct delegation
# check" com a data da ultima vez em que aquele servidor respondeu com
# autoridade. E o unico dos tres sinais de historias.py que vem com data.
DELEGACAO_OK = "ns aa"                 # responde com autoridade
EVENTO_CONFERENCIA = "delegation check"
EVENTO_ULTIMA_OK = "last correct delegation check"

# Status de dominio que so o NIC.br usa (mesma fonte). Os dois "inactive"
# significam nome tirado do ar por ordem judicial ou por decisao do CGI.br.
SITUACAO_ORDEM_JUDICIAL = "nicbr inactive court order"
SITUACAO_CGI = "nicbr inactive CG"


@dataclass(frozen=True)
class Delegacao:
    """Um servidor de DNS e o que o registro achou dele na ultima conferencia."""

    servidor: str
    situacao: str | None = None        # "ns aa", "ns timeout", "ns udn"...
    conferido_em: str | None = None
    ultima_ok: str | None = None       # quando respondeu certo pela ultima vez

    @property
    def responde(self) -> bool | None:
        """None quando o registro nao informou a conferencia."""
        if self.situacao is None:
            return None
        return self.situacao == DELEGACAO_OK


@dataclass(frozen=True)
class Ficha:
    """O que o RDAP e o resolvedor sabem sobre um dominio ja registrado."""

    dominio: str
    existe: bool = False
    titular: str | None = None
    documento: str | None = None          # CNPJ ou CPF, quando publico
    registrado_em: str | None = None
    expira_em: str | None = None
    alterado_em: str | None = None
    servidores: tuple[str, ...] = ()
    enderecos: tuple[str, ...] = ()
    erro: str | None = None
    # extensao NIC.br do RDAP (lida desde 12/09/2026)
    delegacoes: tuple[Delegacao, ...] = ()
    situacoes: tuple[str, ...] = ()       # o array "status" do RDAP
    arbitragem: bool | None = None        # aceitou a politica de arbitragem
    # quantos dominios o titular tem, pela consulta a entidade; so quando
    # pedida (`ficha(..., com_titular=True)`) e so para CNPJ
    dominios_do_titular: int | None = None

    @property
    def delegacao_quebrada(self) -> bool:
        """
        Nenhum servidor de DNS responde com autoridade, segundo o registro.

        Diferente de `em_branco`, que e o resolvedor daqui nao achando
        endereco: aqui e o Registro.br dizendo que os servidores declarados
        nao servem a zona. Mas so quando ele informou a conferencia.
        """
        conferidas = [d for d in self.delegacoes if d.responde is not None]
        return bool(conferidas) and not any(d.responde for d in conferidas)

    @property
    def delegacao_ok_em(self) -> str | None:
        """
        A ultima vez em que algum servidor respondeu certo.

        Para um nome quebrado, e a data em que o DNS parou: o "desde quando"
        que antes so o Internet Archive dava, e sem consulta extra.
        """
        datas = [d.ultima_ok for d in self.delegacoes if d.ultima_ok]
        return max(datas) if datas else None

    @property
    def fora_do_ar_por_decisao(self) -> bool:
        """Tirado do DNS por ordem judicial ou pelo CGI.br."""
        return any(s in (SITUACAO_ORDEM_JUDICIAL, SITUACAO_CGI)
                   for s in self.situacoes)

    @property
    def resolve(self) -> bool:
        """Tem endereco IP, isto e, um navegador chega a algum lugar."""
        return bool(self.enderecos)

    @property
    def estacionado(self) -> bool:
        """
        Registrado e delegado ao DNS do proprio Registro.br.

        Nao e sinonimo de abandonado: e o estado de quem pagou pelo nome e
        nunca apontou para lugar nenhum.
        """
        return any(s.endswith(DNS_DO_REGISTRO) for s in self.servidores)

    @property
    def em_branco(self) -> bool:
        """Existe, esta pago, e mesmo assim nao entrega nada."""
        return self.existe and not self.resolve


def _abrir(url: str, timeout: int = TIMEOUT):
    pedido = urllib.request.Request(
        url, headers={"User-Agent": UA, "Accept": "application/rdap+json"})
    return urllib.request.urlopen(pedido, timeout=timeout)


def consultar(dominio: str, timeout: int = TIMEOUT) -> dict:
    """Devolve o JSON cru do RDAP."""
    with _abrir(ENDPOINT.format(dominio), timeout) as resposta:
        return json.loads(resposta.read().decode("utf-8", errors="replace"))


def _vcard(entidade: dict) -> dict:
    """
    Achata o vcardArray do RDAP num dicionario.

    O formato e uma lista de listas — ["fn", {}, "text", "FULANO"] — e ler
    isso na mao em tres lugares diferentes seria pedir para errar o indice.
    """
    try:
        campos = entidade["vcardArray"][1]
    except (KeyError, IndexError, TypeError):
        return {}
    saida = {}
    for campo in campos:
        if isinstance(campo, list) and len(campo) >= 4:
            saida[campo[0]] = campo[3]
    return saida


def _titular(dados: dict) -> tuple[str | None, str | None]:
    for entidade in dados.get("entities") or []:
        if "registrant" in (entidade.get("roles") or []):
            documento = None
            for pid in entidade.get("publicIds") or []:
                if pid.get("identifier"):
                    documento = pid["identifier"]
                    break
            nome = _vcard(entidade).get("fn")
            return (nome if isinstance(nome, str) else None), documento
    return None, None


def _eventos(dados: dict) -> dict:
    return {e.get("eventAction"): e.get("eventDate")
            for e in dados.get("events") or [] if e.get("eventAction")}


def _delegacao(servidor: dict) -> Delegacao:
    nome = (servidor.get("ldhName") or "").lower().rstrip(".")
    situacao = conferido_em = ultima_ok = None
    for evento in servidor.get("events") or []:
        acao = evento.get("eventAction")
        if acao == EVENTO_CONFERENCIA:
            conferido_em = evento.get("eventDate")
            # a especificacao mostra string; o servidor real devolve lista
            s = evento.get("status")
            if isinstance(s, list):
                s = s[0] if s else None
            situacao = s
        elif acao == EVENTO_ULTIMA_OK:
            ultima_ok = evento.get("eventDate")
    return Delegacao(nome, situacao, conferido_em, ultima_ok)


def interpretar(dominio: str, dados: dict, enderecos=()) -> Ficha:
    """Traduz o JSON do RDAP em Ficha. Sem rede: da para testar direto."""
    eventos = _eventos(dados)
    titular, documento = _titular(dados)
    delegacoes = tuple(_delegacao(n) for n in dados.get("nameservers") or []
                       if n.get("ldhName"))
    arbitragem = dados.get("nicbr_arbitration")
    return Ficha(
        dominio=dominio,
        existe=True,
        titular=titular,
        documento=documento,
        registrado_em=eventos.get("registration"),
        expira_em=eventos.get("expiration"),
        alterado_em=eventos.get("last changed"),
        servidores=tuple(d.servidor for d in delegacoes),
        enderecos=tuple(enderecos),
        delegacoes=delegacoes,
        situacoes=tuple(s for s in dados.get("status") or [] if isinstance(s, str)),
        arbitragem=arbitragem if isinstance(arbitragem, bool) else None,
    )


def contar_tickets(dominio: str, timeout: int = TIMEOUT) -> int:
    """
    Quantos tickets um nome tem, sem o corte em 10 do avail (A3).

    Uma requisicao. 404 e "nao existe no cadastro", isto e, zero. Qualquer
    outra falha sobe como excecao: quem chama (a varredura) para de usar o
    RDAP nesta execucao no primeiro erro, porque o limite dele nao e
    publicado (R4).
    """
    try:
        dados = consultar(dominio.strip().lower(), timeout)
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return 0
        raise
    return sum(1 for p in dados.get("publicIds") or []
               if isinstance(p, dict) and p.get("type") == "ticket")


ENDPOINT_TICKET = "https://rdap.registro.br/ticket/{}"
ENDPOINT_DOMINIO_TICKET = "https://rdap.registro.br/domain/{}?ticket={}"


@dataclass(frozen=True)
class Candidato:
    """
    Quem pediu um ticket, como o Registro.br mostra na propria busca.

    E DADO PESSOAL quando o documento e CPF. Existe so para a ferramenta
    local `tickets.py`, do dono do repositorio, para a mesma pesquisa que o
    site do Registro.br permite a qualquer um. Nunca vai para o site
    publicado, nunca para o git (a saida fica em work/), e o repositorio
    que carrega este codigo nao pode ser publico.
    """

    ticket: int
    dominio: str | None = None
    nome: str | None = None
    documento: str | None = None
    tipo_documento: str | None = None     # "cpf" ou "cnpj", como vier
    papel: str | None = None              # o role da entidade no RDAP
    pedido_em: str | None = None
    situacoes: tuple[str, ...] = ()
    dominios_do_titular: int | None = None
    erro: str | None = None

    @property
    def pessoa_fisica(self) -> bool:
        return (self.tipo_documento or "").lower() == "cpf"


def consultar_ticket(ticket: int, dominio: str | None = None,
                     timeout: int = TIMEOUT) -> dict:
    """
    JSON cru de um ticket. Com `dominio`, usa a forma que o site do
    Registro.br usa (`/domain/<nome>?ticket=<n>`); sem, a consulta por
    ticket da biblioteca oficial (`/ticket/<n>`).
    """
    url = (ENDPOINT_DOMINIO_TICKET.format(dominio, ticket) if dominio
           else ENDPOINT_TICKET.format(ticket))
    with _abrir(url, timeout) as resposta:
        return json.loads(resposta.read().decode("utf-8", errors="replace"))


def _entidade_principal(dados: dict) -> dict | None:
    entidades = [e for e in dados.get("entities") or [] if isinstance(e, dict)]
    for papel in ("registrant", "administrative", "technical"):
        for e in entidades:
            if papel in (e.get("roles") or []):
                return e
    return entidades[0] if entidades else None


def interpretar_ticket(ticket: int, dados: dict) -> Candidato:
    """
    Le o que vier: o formato exato de /ticket/<n> nao foi conferido ao vivo
    (12/09/2026), entao o leitor e tolerante e o `tickets.py --bruto` mostra
    o JSON inteiro para ajustar o que faltar.
    """
    eventos = _eventos(dados)
    entidade = _entidade_principal(dados)
    nome = documento = tipo = papel = None
    if entidade:
        fn = _vcard(entidade).get("fn")
        nome = fn if isinstance(fn, str) else None
        for pid in entidade.get("publicIds") or []:
            if pid.get("identifier"):
                documento = str(pid["identifier"])
                tipo = str(pid.get("type") or "") or None
                break
        papeis = entidade.get("roles") or []
        papel = papeis[0] if papeis else None
    # o ticket tambem pode vir como publicId do proprio dominio
    dominio = dados.get("ldhName") or dados.get("unicodeName") or dados.get("handle")
    return Candidato(
        ticket=ticket,
        dominio=str(dominio).lower() if dominio else None,
        nome=nome, documento=documento, tipo_documento=tipo, papel=papel,
        pedido_em=eventos.get("registration"),
        situacoes=tuple(s for s in dados.get("status") or [] if isinstance(s, str)),
    )


def candidato(ticket: int, dominio: str | None = None,
              timeout: int = TIMEOUT) -> Candidato:
    """Consulta um ticket. Falha de rede vira Candidato com erro."""
    try:
        dados = consultar_ticket(ticket, dominio, timeout)
    except urllib.error.HTTPError as e:
        return Candidato(ticket=ticket, dominio=dominio, erro=f"http {e.code}")
    except Exception as e:
        return Candidato(ticket=ticket, dominio=dominio, erro=str(e)[:200])
    return interpretar_ticket(ticket, dados)


def consultar_entidade(handle: str, timeout: int = TIMEOUT) -> dict:
    """JSON cru de rdap.registro.br/entity/<handle>. O handle e o documento."""
    with _abrir(ENDPOINT_ENTIDADE.format(handle), timeout) as resposta:
        return json.loads(resposta.read().decode("utf-8", errors="replace"))


def interpretar_entidade(dados: dict) -> int | None:
    """
    So o que interessa da entidade: quantos dominios ela tem.

    `nicbr_domainCount` e extensao NIC.br (12/09/2026: a titular de
    pneus.com.br tem 166). A entidade traz tambem `legalRepresentative`, o
    nome de uma pessoa: nao e lido, nao e guardado, nao e exibido.
    """
    n = dados.get("nicbr_domainCount")
    return n if isinstance(n, int) else None


def _cnpj(documento: str | None) -> str | None:
    """Digitos do documento se for CNPJ; CPF nunca vai para a consulta."""
    digitos = "".join(c for c in (documento or "") if c.isdigit())
    return digitos if len(digitos) == 14 else None


def com_titular(f: Ficha, consulta=consultar_entidade) -> Ficha:
    """
    Completa a ficha com a contagem de dominios do titular.

    Uma requisicao a mais, so para CNPJ. Falha vira ficha igual, nao erro:
    a contagem e enfeite em cima do que ja se sabe.
    """
    handle = _cnpj(f.documento)
    if not f.existe or not handle:
        return f
    try:
        dominios = interpretar_entidade(consulta(handle))
    except Exception:
        return f
    return replace(f, dominios_do_titular=dominios)


def resolver(dominio: str, timeout: float = 5.0) -> tuple[str, ...]:
    """
    Enderecos IP do dominio, pelo resolvedor do sistema.

    Nome sem endereco nao e erro: e a resposta. Por isso a falha vira tupla
    vazia em vez de excecao — o chamador quer saber "resolve ou nao", nao
    lidar com socket.gaierror.
    """
    anterior = socket.getdefaulttimeout()
    socket.setdefaulttimeout(timeout)
    try:
        infos = socket.getaddrinfo(dominio, None)
        return tuple(sorted({i[4][0] for i in infos}))
    except OSError:
        return ()
    finally:
        socket.setdefaulttimeout(anterior)


def ficha(dominio: str, timeout: int = TIMEOUT, resolvedor=resolver,
          com_titular_: bool = False, pausa: float = PAUSA_SEGURA) -> Ficha:
    """
    Consulta RDAP e resolucao. Falha de rede vira Ficha com erro, nao excecao.

    `resolvedor` entra por parametro para o teste nao tocar na rede.
    `com_titular_` faz a segunda consulta, a entidade, depois de `pausa`.
    """
    dominio = dominio.strip().lower()
    try:
        dados = consultar(dominio, timeout)
    except urllib.error.HTTPError as e:
        if e.code == 404:
            # 404 no RDAP e informacao boa: o nome nao esta registrado
            return Ficha(dominio=dominio, existe=False)
        return Ficha(dominio=dominio, erro=f"http {e.code}")
    except Exception as e:
        return Ficha(dominio=dominio, erro=str(e)[:200])
    f = interpretar(dominio, dados, resolvedor(dominio))
    if com_titular_ and _cnpj(f.documento):
        if pausa:
            time.sleep(pausa)
        f = com_titular(f)
    return f
