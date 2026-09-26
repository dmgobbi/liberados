"""
Instantaneo: serializar e restaurar o estado num JSON.

Caso de uso com duas metades:

  exportar()   banco -> JSON, para publicar o site estatico
  restaurar()  JSON -> banco, para o estado sobreviver entre execucoes

Por que o JSON e a fonte de verdade na nuvem: no GitHub Actions o banco e
descartado a cada execucao. Guardar o estado num JSON versionado no git deixa
o historico auditavel (`git log site/dados.json` mostra a rodada mudando) e
dispensa banco gerenciado.

O formato e compacto de proposito. Cada dominio e uma lista posicional e os
motivos viram indices num vocabulario, porque eles se repetem muito: 15 mil
dominios em objetos nomeados passariam de 3 MB, e assim ficam em ~500 KB.
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass

from ..adaptadores.repositorio import Candidato
from ..dominio import categorias, frescor, relevancia, ritmo
from ..dominio.marcas import MARCAS, Risco
from ..dominio.situacao import Situacao, situacao_de
from .manutencao import classes_de

# A ordem define os indices gravados no JSON. Acrescente no fim; reordenar
# invalida todo instantaneo ja publicado.
SITUACOES = (
    Situacao.LIBERACAO_LIVRE,
    Situacao.LIBERACAO_DISPUTADA,
    Situacao.COMPETITIVO,
    Situacao.LIVRE,
    Situacao.REGISTRADO,
    # acrescentados em 12/09/2026, com a enumeracao oficial do ISAVAIL
    Situacao.AGUARDANDO_LIBERACAO,
    Situacao.INDISPONIVEL,
    Situacao.LIVRE_COM_TICKET,
)
RISCOS = (Risco.OK, Risco.ATENCAO, Risco.RISCO)

# posicoes dentro de cada item
I_DOMINIO, I_SITUACAO, I_CANDIDATOS, I_NOTA, I_ELEGIVEL, I_MOTIVOS, I_RISCO = range(7)
I_EM_LEILAO, I_VERIFICADO, I_CLASSE, I_CATEGORIAS = 7, 8, 9, 10
# 12/09/2026: quando o primeiro concorrente chegou e quando o ultimo visivel
# chegou (epoch UTC, 0 = desconhecido). Estimativa pelo ritmo da rodada
# (dominio/ritmo.py); os numeros de ticket em si nunca vao para o site.
I_CHEGADA_MIN, I_CHEGADA_MAX = 11, 12

# 2 adicionou em_leilao; 3 os criterios; 4 a idade e a classe de frescor de
# cada item. Antes do 4 o JSON so tinha o `gerado_em` global, e restaurar
# carimbava todo mundo com ele: dado de 30 horas voltava parecendo novo.
# 5: categorias de negocio (bits), para o filtro por ramo.
VERSAO_FORMATO = 5


def criterios(nota_minima: int) -> dict:
    """
    Os pesos da pontuacao, lidos do proprio modulo que pontua.

    Vao para o JSON para que a pagina explique o criterio a partir da fonte
    de verdade. Documentacao escrita a mao sobre numero que mora no codigo
    diverge na primeira vez que alguem ajusta um peso.
    """
    r = relevancia
    return {
        "nota_minima": nota_minima,
        "tamanho": [
            {"ate": 3, "peso": r.PESO_SIGLA, "rotulo": "3 letras ou menos"},
            {"ate": 6, "peso": r.PESO_CURTO, "rotulo": "4 a 6 letras"},
            {"ate": 9, "peso": r.PESO_MEDIO, "rotulo": "7 a 9 letras"},
            {"ate": 14, "peso": r.PESO_LONGO, "rotulo": "10 a 14 letras"},
            {"ate": None, "peso": r.PESO_MUITO_LONGO, "rotulo": "15 letras ou mais"},
        ],
        "vocabulario": [
            {"peso": r.PESO_PALAVRA_PT, "rotulo": "palavra de dicionário em português"},
            {"peso": r.PESO_PALAVRA_EN, "rotulo": "palavra de dicionário em inglês"},
            {"peso": r.PESO_FLEXAO, "rotulo": "forma verbal ou flexão (aprenda, confiar)"},
            {"peso": r.PESO_NICHO, "rotulo": "contém radical de nicho comercial"},
        ],
        "bonus": [
            {"peso": r.PESO_ELEGIVEL, "rotulo": "elegível ao leilão"},
            {"peso": r.PESO_COMPOSTO_NICHO, "rotulo": "nicho + palavra comum (lojaonline, imoveisnovos)"},
            {"peso": r.PESO_CIDADE_NICHO, "rotulo": "nicho + cidade de 200 mil habitantes ou mais"},
            {"peso": r.PESO_COM_BR, "rotulo": "extensão .com.br"},
            {"peso": r.PESO_POPULAR, "rotulo": "entre as 20 mil palavras mais usadas do português"},
            {"peso": r.PESO_EXTENSAO_BOA, "rotulo": "extensão boa (.app.br, .dev.br, .ia.br...)"},
            {"peso": r.PESO_TRES_COM_BR, "rotulo": "três letras .com.br"},
        ],
        "penalidades": [
            {"peso": r.PENA_HIFEN, "rotulo": "tem hífen"},
            {"peso": r.PENA_DIGITO, "rotulo": "tem número"},
            {"peso": r.PENA_COMPRIDO, "rotulo": "mais de 16 letras"},
            {"peso": r.PENA_REPETICAO, "rotulo": "três letras iguais seguidas"},
        ],
        "nichos": list(r.NICHOS),
        "extensoes_boas": list(r.EXTENSOES_BOAS),
        "total_marcas": len(MARCAS),
    }


@dataclass
class Metadados:
    gerado_em: str
    total_rodada: int = 0
    total_elegiveis: int = 0
    nao_verificados: int = 0
    inicio: str | None = None
    fim: str | None = None
    nota_minima: int = 45
    em_leilao_em: str | None = None     # quando a lista de leiloes foi gerada


def _chegada(c: Candidato, serie, ticket: int | None, guardada: int | None) -> int:
    """A estimativa nova quando ha ticket e serie; senao, a que veio do JSON."""
    if ticket and serie:
        estimado = ritmo.estimar(serie, ticket)
        if estimado:
            return estimado
    return guardada or 0


def exportar(candidatos: list[Candidato], meta: Metadados, *,
             pessoas: frozenset[str] = frozenset(),
             serie=None, primeiro: int | None = None,
             agora_epoch: int | None = None) -> dict:
    """
    Monta o dicionario que vai virar dados.json. `pessoas` e a mesma lista
    que todos.json usa para a categoria de nomes (dicionarios.pessoas()).
    `serie` e `primeiro` sao o ritmo da rodada (repositorio.serie_ritmo).
    """
    vocabulario: dict[str, int] = {}
    serie = [tuple(p) for p in serie or []]
    agora_epoch = agora_epoch or int(time.time())

    def indice_do_motivo(motivo: str) -> int:
        return vocabulario.setdefault(motivo, len(vocabulario))

    classes = classes_de(candidatos, frescor.epoch(meta.inicio))
    itens = []
    for c in candidatos:
        situacao = c.situacao_atual
        if situacao not in SITUACOES:
            # LIMITADO, ERRO e afins nao sao fato sobre o dominio: ficam fora,
            # e como saem do JSON serao reconsultados na proxima varredura
            continue
        itens.append([
            c.dominio,
            SITUACOES.index(situacao),
            c.candidatos or 0,
            c.nota,
            int(c.elegivel),
            [indice_do_motivo(m) for m in c.motivos],
            RISCOS.index(c.risco) if c.risco in RISCOS else 0,
            int(c.em_leilao),
            frescor.epoch(c.verificado_em) or 0,
            frescor.CLASSES.index(classes[c.dominio]),
            categorias.mascara(relevancia.separar(c.dominio)[0] or "", pessoas),
            _chegada(c, serie, c.ticket_min, c.chegada_min),
            _chegada(c, serie, c.ticket_max, c.chegada_max),
        ])

    return {
        "versao": VERSAO_FORMATO,
        "criterios": criterios(meta.nota_minima),
        "frescor": frescor.tabela(),
        "categorias": categorias.tabela(),
        "ritmo": ritmo.resumo(serie, primeiro, agora_epoch),
        "gerado_em": meta.gerado_em,
        "em_leilao_em": meta.em_leilao_em,
        "rodada": {"inicio": meta.inicio, "fim": meta.fim},
        "total_rodada": meta.total_rodada,
        "total_elegiveis": meta.total_elegiveis,
        "nao_verificados": meta.nao_verificados,
        "status": [s.value for s in SITUACOES],
        "marcas": [r.value for r in RISCOS],
        "motivos": sorted(vocabulario, key=vocabulario.get),
        "itens": itens,
    }


def escrever(dados: dict, caminho: str) -> int:
    os.makedirs(os.path.dirname(caminho) or ".", exist_ok=True)
    with open(caminho, "w", encoding="utf-8") as f:
        json.dump(dados, f, ensure_ascii=False, separators=(",", ":"))
    return os.path.getsize(caminho)


def ler(caminho: str) -> dict | None:
    if not os.path.exists(caminho):
        return None
    with open(caminho, encoding="utf-8") as f:
        return json.load(f)


def candidatos_de(dados: dict) -> list[Candidato]:
    """Reconstroi Candidatos a partir de um instantaneo."""
    situacoes = dados.get("status") or []
    riscos = dados.get("marcas") or []
    vocabulario = dados.get("motivos") or []
    quando = dados.get("gerado_em")

    saida: list[Candidato] = []
    for item in dados.get("itens") or []:
        if not isinstance(item, list) or len(item) <= I_ELEGIVEL:
            continue
        indice = item[I_SITUACAO]
        if not 0 <= indice < len(situacoes):
            continue

        motivos = item[I_MOTIVOS] if len(item) > I_MOTIVOS else []
        indice_risco = item[I_RISCO] if len(item) > I_RISCO else 0
        # v4 traz a idade de cada item; v3 so tinha a data global, que e o
        # melhor que da para fazer com ela
        segundos = item[I_VERIFICADO] if len(item) > I_VERIFICADO else 0
        verificado_em = frescor.iso_utc(segundos) if segundos else quando

        saida.append(Candidato(
            dominio=item[I_DOMINIO],
            fonte="historico",
            elegivel=bool(item[I_ELEGIVEL]),
            em_leilao=bool(item[I_EM_LEILAO]) if len(item) > I_EM_LEILAO else False,
            nota=item[I_NOTA],
            motivos=tuple(vocabulario[i] for i in motivos
                          if 0 <= i < len(vocabulario)),
            situacao=situacao_de(situacoes[indice]),
            candidatos=item[I_CANDIDATOS],
            risco=Risco(riscos[indice_risco])
                  if 0 <= indice_risco < len(riscos) else Risco.OK,
            verificado_em=verificado_em,
            chegada_min=(item[I_CHEGADA_MIN] or None) if len(item) > I_CHEGADA_MIN else None,
            chegada_max=(item[I_CHEGADA_MAX] or None) if len(item) > I_CHEGADA_MAX else None,
        ))
    return saida


def ritmo_de(dados: dict) -> tuple[list[tuple[int, int]], int | None]:
    """A serie do ritmo e o primeiro ticket, como o instantaneo os guardou."""
    r = dados.get("ritmo") or {}
    serie = [(int(p[0]), int(p[1])) for p in r.get("serie") or []
             if isinstance(p, (list, tuple)) and len(p) == 2]
    primeiro = r.get("primeiro")
    return serie, (int(primeiro) if isinstance(primeiro, int) else None)


def frescor_de(dados: dict, agora: int) -> list[dict]:
    """
    Quantos nomes de cada classe passaram do prazo prometido.

    Le so o JSON, sem banco: e o que o alarme do workflow confere depois de
    publicar, e o que qualquer um pode rodar contra o site no ar.
    """
    classes = (dados.get("frescor") or {}).get("classes") or []
    linhas = [{"nome": c["nome"], "prazo_horas": c.get("prazo_horas"),
               "nomes": 0, "vencidos": 0, "mais_velho_h": 0.0, "exemplos": []}
              for c in classes]
    for item in dados.get("itens") or []:
        if len(item) <= I_CLASSE or not 0 <= item[I_CLASSE] < len(linhas):
            continue
        linha = linhas[item[I_CLASSE]]
        linha["nomes"] += 1
        if not item[I_VERIFICADO]:
            continue
        horas = max(0, agora - item[I_VERIFICADO]) / 3600
        linha["mais_velho_h"] = max(linha["mais_velho_h"], horas)
        if linha["prazo_horas"] and horas > linha["prazo_horas"]:
            linha["vencidos"] += 1
            if len(linha["exemplos"]) < 5:
                linha["exemplos"].append(item[I_DOMINIO])
    return linhas
