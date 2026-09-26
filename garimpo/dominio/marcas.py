"""
Filtro de risco de marca registrada.

Camada de dominio: funcao pura, nao consulta o INPI (a busca deles nao tem
API publica e o e-INPI exige sessao).

E FILTRO DE EXCLUSAO, NUNCA LISTA DE ALVOS. Registrar dominio que reproduz
marca de terceiro com a intencao de revender ao titular e cybersquatting: o
titular aciona o SACI-Adm do CGI.br, prova ma-fe usando justamente a
intencao de revenda, e recupera o dominio. Voce perde o nome e o dinheiro da
oferta.

Palavra generica em portugues e o alvo certo justamente por nao ter dono.

O filtro erra nos dois sentidos: deixa passar marca que nao esta na lista, e
sinaliza palavra generica que por acaso e nome de empresa. A verificacao que
vale e manual, em busca.inpi.gov.br e tmsearch.uspto.gov.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum


class Risco(str, Enum):
    OK = "OK"
    ATENCAO = "ATENCAO"
    RISCO = "RISCO"


@dataclass(frozen=True)
class Avaliacao:
    risco: Risco
    motivo: str = ""

    def __iter__(self):
        """Compatibilidade: o codigo antigo faz `nivel, motivo = avaliar(x)`."""
        return iter((self.risco.value, self.motivo))


TAMANHO_SIGLA = 3       # abaixo disto quase sempre colide com sigla de empresa
MINIMO_SUBSTRING = 4    # marca curta embutida gera falso positivo demais

MARCAS = {
    "adidas", "airbnb", "alura", "amazon", "ambev", "americanas", "amil",
    "anthropic", "apple", "avon", "azul", "band", "banrisul", "bbb",
    "beyonce", "bndes", "booking", "boticario", "bradesco", "brahma",
    "brasilfoods", "brasiltelecom", "brf", "brfoods", "caixa", "casasbahia",
    "celtics", "chatgpt", "claro", "claude", "cobasi", "coca", "copilot",
    "correios", "coursera", "cvc", "dafiti", "decolar", "detran", "discord",
    "disney", "drogasil", "elastic", "eletrobras", "elo", "embraer",
    "embrapa", "embratel", "eudora", "facebook", "farm", "friboi", "gemini",
    "globo", "gol", "google", "googles",
    "gpt", "grammy", "groupon", "gucci", "hapvida", "heineken",
    "hostgator", "hubspot", "ifood", "ig", "inss", "instagram", "intel",
    "inter", "iphone", "itau", "jbs", "latam", "locaweb", "madonna",
    "magalu", "marisa", "marvel", "mastercard", "mercadolivre",
    "mercadopago", "motorola", "natura", "neon", "nestle", "netflix",
    "netshoes", "nextel", "nike", "nintendo", "nubank", "nvidia", "odoo",
    "oi", "omega", "openai", "oracle", "original", "oscar", "pacheco",
    "pagseguro", "pepsi", "perdigao", "petrobras", "petz", "picpay", "pix",
    "playstation", "portoseguro", "prada", "puma", "raia", "rappi",
    "record", "renner", "riachuelo", "rihanna", "rocketseat", "rolex",
    "sadia", "salesforce", "samsung", "santander", "sap", "sbt", "seara",
    "sebrae", "senac", "senai", "serasa", "sesc", "sesi", "shopee",
    "shopify", "sicoob", "sicredi", "spotify", "steam", "stone",
    "sulamerica", "tam", "terra", "tiktok", "tim", "totvs", "trivago",
    "twitch", "uber", "udemy", "umbler", "unilever", "unimed", "uol",
    "vans", "visa", "vivo", "whatsapp", "wix", "xbox", "xiaomi", "youtube",
    "zendesk",
}

# variacoes obvias de marca: typosquatting
TYPOS = [
    (re.compile(r"^(g[o0]{2,}gle|googl[ea]s?)$"), "google"),
    (re.compile(r"^(fac[e3]b[o0]{2}k)$"), "facebook"),
    (re.compile(r"^(air[bn]{1,2}b|airnb)$"), "airbnb"),
    (re.compile(r"^(0nlyfans|onlyfans)$"), "onlyfans"),
    (re.compile(r"^(what?sap+p?)$"), "whatsapp"),
    (re.compile(r"^(net[fl]+ix)$"), "netflix"),
    (re.compile(r"^(nubanc?k?)$"), "nubank"),
]


def avaliar(rotulo: str, *, sites_populares=None, e_palavra=None) -> Avaliacao:
    """
    Avalia o rotulo (a parte antes do primeiro ponto).

    `sites_populares`: rotulo -> posicao no ranking Tranco (1 milhao de sites
    mais acessados), so .com. `e_palavra`: funcao que diz se o rotulo e
    palavra de dicionario. Os dois sao opcionais; sem eles vale so a lista
    fixa de marcas.
    """
    nome = rotulo.lower()

    if nome in MARCAS:
        return Avaliacao(Risco.RISCO, f"marca conhecida: {nome}")

    for padrao, alvo in TYPOS:
        if padrao.match(nome):
            return Avaliacao(Risco.RISCO, f"possivel typosquat de {alvo}")

    # O .com e um dos sites mais acessados do mundo. Medido em 09/2026: dos
    # 487 nomes da rodada nessa situacao, quase todos eram marca (jetbrains,
    # fitbit, deliveroo, papajohns) e a lista fixa acima pegava 5. Palavra de
    # dicionario (boots, melon, onion) nao tem dono, entao vira so atencao.
    posicao = (sites_populares or {}).get(nome)
    if posicao:
        if e_palavra and e_palavra(nome):
            return Avaliacao(Risco.ATENCAO,
                             f"o .com e site popular (Tranco #{posicao:,}); "
                             f"palavra comum, mas confira marca".replace(",", "."))
        return Avaliacao(Risco.RISCO,
                         f"o .com e site popular (Tranco #{posicao:,}), "
                         f"provavel marca".replace(",", "."))

    # marca embutida no meio do nome: lojanike, cursoudemy, creditogpt
    embutidas = sorted(m for m in MARCAS
                       if len(m) >= MINIMO_SUBSTRING and m in nome and nome != m)
    if embutidas:
        return Avaliacao(Risco.ATENCAO, f"contem marca: {embutidas[0]}")

    if len(nome) <= TAMANHO_SIGLA:
        return Avaliacao(Risco.ATENCAO,
                         "sigla curta, verifique INPI antes de usar comercialmente")

    return Avaliacao(Risco.OK)


def avaliar_dominio(dominio: str, **opcoes) -> Avaliacao:
    """Igual a avaliar(), mas aceita o dominio completo."""
    return avaliar(dominio.split(".")[0], **opcoes)


def parece_marca(rotulo: str) -> bool:
    """
    So a parte de avaliar() que reconhece marca pelo nome: lista fixa,
    typosquat e marca embutida. Sem sigla curta (nao e sobre marca) e sem
    `sites_populares`/`e_palavra` (pede o Tranco e o lexico, que a pagina
    que usa esta funcao nao tem a mao). Serve para reavaliar um rotulo na
    hora de montar a pagina, sem depender do risco gravado na ultima
    varredura: a lista fixa muda com o codigo, o instantaneo so na proxima.
    """
    nome = rotulo.lower()
    if nome in MARCAS:
        return True
    if any(padrao.match(nome) for padrao, _ in TYPOS):
        return True
    return any(len(m) >= MINIMO_SUBSTRING and m in nome and nome != m for m in MARCAS)


def parece_marca_dominio(dominio: str) -> bool:
    """Igual a parece_marca(), mas aceita o dominio completo."""
    return parece_marca(dominio.split(".")[0])
