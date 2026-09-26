"""
"Este dominio ja teve site?" -- o passado de um nome, lido no Internet Archive.

Camada de dominio: funcoes puras, sem rede e sem disco.

POR QUE ISTO IMPORTA

A nota diz se um nome e bom; o arquivo diz se ele ja FOI usado. Sao coisas
diferentes, e a segunda e o que os concorrentes pagos vendem como "Authority
Score" (backlinks). Backlink custa API paga; o Wayback responde a pergunta de
fundo -- houve um site de verdade aqui? -- de graca. E foi a pergunta que
corrigiu duas vezes a historia do pneus.com.br: RDAP e DNS mostram o
presente e sugerem conclusao errada sobre o passado.

POR QUE UM INDICE PERMANENTE (18/09/2026)

O passado de um dominio nao muda: consultado uma vez, esta consultado. Do
runner do GitHub Actions o Internet Archive recusa a conexao (limitacao F9),
entao a coleta roda da maquina local e o resultado e comitado. O site serve a
resposta guardada, e o navegador do visitante nunca fala com o Internet
Archive -- o que torna irrelevante a falta de CORS (F8).

Mesmo esquema de fatias das passagens (`passagens.fatia`, FNV-1a em 256
arquivos): o navegador baixa so a fatia do nome consultado, e a funcao de
hash ja existe em JavaScript na ficha, com teste conferindo os dois lados.

COMO LER O SPARKLINE

`years` traz quantas capturas houve em cada mes; `status` traz uma letra por
mes com a classe HTTP. A letra so vale nos meses COM captura: nos meses
vazios ela vem "4" de enchimento, e sem o filtro um 404 real e um mes vazio
ficam indistinguiveis. Conferido no pneus.com.br: 19 meses "2" (serviu
pagina), 8 meses "3" (os redirecionamentos de 2019 a 2023, mes a mes) e 14
meses "4" (404 de verdade, depois que o site morreu).
"""

from __future__ import annotations

from dataclasses import dataclass

from .passagens import fatia

# Tres estados, nao dois. "Nunca capturado" NAO prova "nunca teve site": a
# cobertura do .br no arquivo e desigual. E "so redirecionou" e um caso
# proprio -- nome usado para mandar a outro lugar, como o pneus.com.br de
# 2019 a 2023 --, diferente de nome que nunca foi a lugar nenhum.
NUNCA = "nunca capturado"
REDIRECIONOU = "so redirecionou"
SERVIU = "serviu pagina"


@dataclass(frozen=True)
class Resumo:
    """O passado de um nome, no tamanho que cabe numa linha do indice."""

    dominio: str
    primeira: str = ""          # AAAAMM da primeira captura; "" se nenhuma
    ultima: str = ""            # AAAAMM da ultima
    capturas: int = 0           # total de capturas, todos os meses
    servindo: int = 0           # meses em que serviu pagina (2xx)
    redirecionando: int = 0     # meses em que redirecionou (3xx)
    consultado: str = ""        # AAAAMMDD em que o indice leu o arquivo

    @property
    def estado(self) -> str:
        if not self.capturas:
            return NUNCA
        if self.servindo:
            return SERVIU
        return REDIRECIONOU if self.redirecionando else NUNCA


def de_sparkline(dominio: str, dados: dict, consultado: str = "") -> Resumo:
    """
    Resumo a partir do JSON do `__wb/sparkline`.

    So os meses com captura contam a letra de status: nos outros ela e
    enchimento (ver o cabecalho do modulo).
    """
    anos = dados.get("years") or {}
    status = dados.get("status") or {}
    meses: list[tuple[str, int, str]] = []          # (AAAAMM, capturas, classe)
    for ano in sorted(anos):
        letras = status.get(ano, "")
        for i, quantas in enumerate(anos[ano]):
            if quantas > 0:
                letra = letras[i] if i < len(letras) else ""
                meses.append((f"{ano}{i + 1:02d}", quantas, letra))
    if not meses:
        return Resumo(dominio=dominio, consultado=consultado)
    return Resumo(
        dominio=dominio,
        primeira=meses[0][0],
        ultima=meses[-1][0],
        capturas=sum(q for _, q, _ in meses),
        servindo=sum(1 for _, _, c in meses if c == "2"),
        redirecionando=sum(1 for _, _, c in meses if c == "3"),
        consultado=consultado,
    )


def de_capturas(dominio: str, capturas, consultado: str = "") -> Resumo:
    """
    Resumo a partir das capturas da CDX (`wayback.Historico.capturas`).

    E a queda quando o sparkline, que e interno e nao documentado, falhar.
    A CDX devolve captura a captura; aqui elas viram meses, como no sparkline,
    para os dois caminhos darem o mesmo numero.
    """
    por_mes: dict[str, set[str]] = {}
    for c in capturas:
        por_mes.setdefault(c.quando, set()).add(str(c.status)[:1])
    if not por_mes:
        return Resumo(dominio=dominio, consultado=consultado)
    ordem = sorted(por_mes)
    return Resumo(
        dominio=dominio,
        primeira=ordem[0],
        ultima=ordem[-1],
        capturas=len(capturas),
        servindo=sum(1 for m in ordem if "2" in por_mes[m]),
        redirecionando=sum(1 for m in ordem if "3" in por_mes[m]),
        consultado=consultado,
    )


# -------------------------------------------------------------- o indice

COLUNAS = 7


def linha(r: Resumo) -> str:
    """Uma linha da fatia: separada por TAB, na ordem de `Resumo`."""
    return "\t".join((r.dominio, r.primeira, r.ultima, str(r.capturas),
                      str(r.servindo), str(r.redirecionando), r.consultado))


def ler_linha(texto: str) -> Resumo | None:
    partes = texto.rstrip("\n").split("\t")
    if len(partes) != COLUNAS or not partes[0]:
        return None
    try:
        return Resumo(dominio=partes[0], primeira=partes[1], ultima=partes[2],
                      capturas=int(partes[3]), servindo=int(partes[4]),
                      redirecionando=int(partes[5]), consultado=partes[6])
    except ValueError:
        return None


def agrupar(resumos) -> dict[str, list[str]]:
    """{fatia: linhas ordenadas}. Mesma fatia das passagens, de proposito."""
    fatias: dict[str, list[str]] = {}
    for r in resumos:
        fatias.setdefault(fatia(r.dominio), []).append(linha(r))
    return {f: sorted(ls) for f, ls in fatias.items()}
