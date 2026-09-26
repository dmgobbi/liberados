#!/usr/bin/env python3
"""
Escolhe que URLs avisar ao IndexNow (Bing) e manda o pedido.

    python3 avisar_indexnow.py site/sitemap.xml            # escolhe e manda
    python3 avisar_indexnow.py site/sitemap.xml --seco      # so imprime a lista

Ate 17/09/2026 o passo do workflow mandava sempre as mesmas 3 URLs fixas
(`/`, `/dominios/`, `/dados/`), entao nenhuma correcao de conteudo chegava
ao Bing antes de um rastreio por acaso. Agora tambem manda o que o
sitemap.xml (garimpo/web/paginas.sitemap) marca como revisado hoje ou ontem,
fuso America/Sao_Paulo: pega o `lastmod` de uma pagina que um agente
acabou de corrigir sem esperar o Bing passar por sorte.

Pagina de ramo (`/dominios/<ramo>/`, garimpo/web/ramos.py) fica de fora
mesmo com `lastmod` de hoje: ela e regravada a cada execucao do Garimpo
porque os nomes da lista mudam, entao "lastmod de hoje" ali nao significa
revisao de conteudo -- so ruido, contra o proprio protocolo (URL que
mudou, nao URL que existe).
"""

from __future__ import annotations

import argparse
import json
import re
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from datetime import date, datetime, timedelta
from urllib.parse import urlparse

from exportar_site import CHAVE_INDEXNOW
from garimpo.web.paginas import BASE_URL as BASE

FUSO_BRASILIA = "America/Sao_Paulo"
URLS_FIXAS = (f"{BASE}/", f"{BASE}/dominios/", f"{BASE}/dados/")
TETO = 20

_NS = {"s": "http://www.sitemaps.org/schemas/sitemap/0.9"}
_RAMO = re.compile(r"^/dominios/[^/]+/$")


def _hoje_em_brasilia() -> date:
    try:
        from zoneinfo import ZoneInfo
        return datetime.now(ZoneInfo(FUSO_BRASILIA)).date()
    except Exception:            # sem tzdata: fica no fuso do sistema
        return date.today()


def urls_para_indexnow(sitemap_xml: str, hoje: date) -> list[str]:
    """
    As 3 URLs fixas mais todo <loc> do sitemap com <lastmod> de hoje ou de
    ontem, sem pagina de ramo (/dominios/<ramo>/), sem repeticao e com no
    maximo TETO URLs.
    """
    ontem_iso = (hoje - timedelta(days=1)).isoformat()
    hoje_iso = hoje.isoformat()
    urls = list(URLS_FIXAS)
    vistas = set(urls)
    raiz = ET.fromstring(sitemap_xml)
    for url in raiz.findall("s:url", _NS):
        if len(urls) >= TETO:
            break
        loc = url.findtext("s:loc", default="", namespaces=_NS)
        lastmod = url.findtext("s:lastmod", default="", namespaces=_NS)
        if not loc or loc in vistas or lastmod[:10] not in (hoje_iso, ontem_iso):
            continue
        if _RAMO.match(urlparse(loc).path):
            continue
        vistas.add(loc)
        urls.append(loc)
    return urls


def avisar(urls: list[str]) -> int:
    """Manda o pedido ao IndexNow e devolve o HTTP (0 se a rede falhou)."""
    corpo = json.dumps({
        "host": urlparse(BASE).netloc,
        "key": CHAVE_INDEXNOW,
        "keyLocation": f"{BASE}/{CHAVE_INDEXNOW}.txt",
        "urlList": urls,
    }).encode()
    req = urllib.request.Request(
        "https://api.indexnow.org/indexnow", data=corpo,
        headers={"Content-Type": "application/json; charset=utf-8"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            print(f"IndexNow: HTTP {r.status}")
            return r.status
    except urllib.error.HTTPError as e:
        # 422 = chave nao confere com o arquivo servido; 403 = chave invalida.
        # Os dois sao erro de configuracao, nao de rede.
        print(f"IndexNow recusou: HTTP {e.code} {e.read()[:200]!r}")
        return e.code
    except Exception as e:
        print(f"IndexNow falhou: {e}")
        return 0


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.strip().splitlines()[0])
    ap.add_argument("sitemap", help="caminho do sitemap.xml exportado")
    ap.add_argument("--seco", action="store_true",
                     help="so escolhe e imprime a lista, nao manda")
    args = ap.parse_args()

    with open(args.sitemap, encoding="utf-8") as f:
        sitemap_xml = f.read()
    urls = urls_para_indexnow(sitemap_xml, _hoje_em_brasilia())
    print(f"{len(urls)} URLs: " + ", ".join(urls))
    if not args.seco:
        avisar(urls)


if __name__ == "__main__":
    main()
