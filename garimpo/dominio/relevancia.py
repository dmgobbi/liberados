"""
Pontuacao de relevancia de um dominio.

Camada de dominio: funcao pura. Recebe o nome e os vocabularios, devolve uma
nota de 0 a 100 e os motivos que a compuseram.

A nota NAO e estimativa de preco. Ela existe para ordenar a atencao: com 15
mil nomes na fila e 3 candidaturas por rodada, o que importa e olhar primeiro
o que tem chance de valer algo.
"""

from __future__ import annotations

import math
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from functools import cached_property

from . import extensoes

# Pesos. Estao juntos e nomeados de proposito: e a regra de negocio mais
# ajustada do projeto, e o valor solto no meio do codigo escondia a intencao.
PESO_SIGLA = 30           # 3 letras: escasso, mas costuma colidir com marca
PESO_CURTO = 35           # 4 a 6 letras: o ponto doce
PESO_MEDIO = 20           # 7 a 9
PESO_LONGO = 8            # 10 a 14
PESO_MUITO_LONGO = 2

PESO_PALAVRA_PT = 30      # o brasileiro busca em portugues
PESO_PALAVRA_EN = 18
PESO_NICHO = 15           # composto comercial reconhecivel

PESO_ELEGIVEL = 25        # ja provou demanda ao travar rodadas seguidas
PESO_COM_BR = 10
PESO_EXTENSAO_BOA = 6

# Achados medidos nos 125 mil nomes da rodada de setembro de 2026. Cada um
# existe porque a nota antiga deixava de fora algo que o dono do projeto
# achou na mao: "aprenda" e "confiar" (verbos), "petfriendly" e "lojaonline"
# (compostos de nicho), os de tres letras. Com eles, todas as candidaturas
# de setembro menos tres passam do corte de 45.
PESO_FLEXAO = 22          # forma verbal ou flexao: aprenda, estude, confiar
PESO_POPULAR = 6          # entre as 20 mil palavras mais usadas do portugues
PESO_COMPOSTO_NICHO = 14  # nicho + palavra comum: imoveisnovos, lojaonline
PESO_CIDADE_NICHO = 12    # nicho + cidade de 200 mil habitantes: imoveisembelem
# LLL .com.br e escasso e foi a classe mais disputada de setembro. Com 5,
# somava exatamente o corte e ggg.com.br (pena de repeticao) ficava em 35,
# fora do pool. 15 e o minimo que poe os 124 da rodada de setembro no corte
# ou acima; medido em 19/09/2026 (docs/criterios-de-valor.md): precisao@100
# contra os disputados de 24 para 27, @1000 igual (78).
PESO_TRES_COM_BR = 15

# Demanda medida no cadastro aberto de CNPJ (26,8 milhoes de empresas ativas,
# agosto de 2026). Das 86 palavras da rodada de setembro usadas por 100+
# empresas no nome fantasia, umas 25 eram candidaturas feitas a mao.
PESO_PALAVRA_DE_NEGOCIO = 8   # o nome e palavra comum em nome de empresa
PESO_NOME_DE_EMPRESAS = 8     # o nome e, colado, o nome fantasia de varias
MINIMO_EMPRESAS_PALAVRA = 100
MINIMO_EMPRESAS_NOME = 3      # 1 empresa e marca; 2 pode ser coincidencia

RANKING_POPULAR = 20_000

PENA_COMPRIDO = -10       # acima de 16 letras
PENA_REPETICAO = -10      # tres letras iguais seguidas
PENA_DIGITO = -12         # numero atrapalha o teste do radio
PENA_HIFEN = -15          # hifen atrapalha mais ainda

EXTENSOES_BOAS = ("app.br", "dev.br", "net.br", "ia.br", "tec.br")

# Radicais de nicho comercial. Nome composto nao passa no teste do radio, mas
# "creditoimobiliario" tem comprador obvio e trafego de busca.
NICHOS = (
    "imovel", "imoveis", "credito", "seguro", "advogad", "advocacia",
    "medic", "saude", "odonto", "dental", "pet", "vet", "auto", "carro",
    "moto", "casa", "reforma", "obra", "solar", "energia", "curso",
    "concurso", "emprego", "vaga", "loja", "oferta", "cupom", "guia",
    "agencia", "consult", "contab", "fintech", "cripto", "banco",
    "franquia", "aluguel", "viagem", "turismo", "hotel", "restaurante",
    "delivery", "nutri", "fitness", "academia", "estetica", "beleza",
    "cuidar", "idoso", "escola", "faculdade", "juridic", "prompt",
    "ia", "ai", "dev", "cloud", "app", "data",
)

_REPETICAO = re.compile(r"(.)\1{2,}")

_RAIZES = frozenset(n for n in NICHOS if len(n) >= 3)
# palavra de ligacao dentro de composto: medica-EM-casa, loja-DA-moda
CONECTIVOS = ("para", "pra", "em", "de", "da", "do", "na", "no", "ja", "e")


@dataclass(frozen=True)
class Lexico:
    """
    O que a nota sabe alem das listas de portugues e ingles.

    Tudo opcional: com o Lexico vazio a nota e exatamente a antiga, o que
    mantem os testes antigos validos e deixa a nota degradar, em vez de
    quebrar, quando uma fonte nao baixa.
    """

    flexoes: frozenset[str] = frozenset()          # aprenda, estude, confiar
    popularidade: Mapping[str, int] = field(default_factory=dict)  # 0 = mais usada
    comuns: frozenset[str] = frozenset()           # palavras de uso comum, pt e en
    pessoas: frozenset[str] = frozenset()          # nomes e sobrenomes comuns
    cidades: tuple[str, ...] = ()                  # 200 mil habitantes ou mais
    # do cadastro de CNPJ: palavra -> empresas que a usam no nome fantasia,
    # e rotulo colado -> empresas com exatamente esse nome
    negocios: Mapping[str, int] = field(default_factory=dict)
    nomes_de_empresa: Mapping[str, int] = field(default_factory=dict)

    @cached_property
    def padrao_cidades(self) -> re.Pattern | None:
        if not self.cidades:
            return None
        # a mais comprida primeiro, para "saojosedoscampos" ganhar de "campos"
        nomes = sorted(set(self.cidades), key=len, reverse=True)
        return re.compile("|".join(map(re.escape, nomes)))


LEXICO_VAZIO = Lexico()


def e_nicho(parte: str) -> bool:
    """Parte de nome que e um radical de nicho, com ate 2 letras de sufixo."""
    if not parte.isalpha():
        return False
    return any(parte[:k] in _RAIZES
               for k in range(max(3, len(parte) - 2), len(parte) + 1))


def composto_de_nicho(rotulo: str, lexico: Lexico) -> tuple[str, ...] | None:
    """
    Nicho + palavra comum, com conectivo opcional: loja+online, medica+em+casa.

    Regra apertada de proposito. As versoes mais soltas, medidas na rodada de
    setembro, poriam 3.950 nomes no pool, quase todos loja/imoveis + nome de
    pessoa (lojacarolbraga, leandraimoveis). Por isso: exatamente duas partes
    de conteudo; a que nao e nicho precisa ter 4 letras e ser palavra comum;
    nome e sobrenome comuns nao contam.
    """
    if not lexico.comuns or not rotulo.isalpha():
        return None

    def conteudo(parte: str, outra_e_nicho: bool) -> bool:
        if parte in lexico.pessoas:
            return False
        if e_nicho(parte):
            return True
        return outra_e_nicho and len(parte) >= 4 and parte in lexico.comuns

    for corte in range(3, len(rotulo) - 2):
        a, resto = rotulo[:corte], rotulo[corte:]
        for liga in ("",) + CONECTIVOS:
            if liga and not resto.startswith(liga):
                continue
            b = resto[len(liga):]
            if len(b) < 3:
                continue
            if (conteudo(a, e_nicho(b)) and conteudo(b, e_nicho(a))
                    and (e_nicho(a) or e_nicho(b))):
                return tuple(p for p in (a, liga, b) if p)
    return None


@dataclass(frozen=True)
class Nota:
    valor: int
    motivos: tuple[str, ...] = ()

    def __str__(self) -> str:
        return f"{self.valor} ({'; '.join(self.motivos)})"


def separar(dominio: str) -> tuple[str | None, str | None]:
    """"exemplo.com.br" -> ("exemplo", "com.br"). Sem ponto, devolve (None, None)."""
    rotulo, ponto, extensao = dominio.partition(".")
    if not ponto:
        return None, None
    return rotulo, extensao


def _peso_do_tamanho(n: int) -> tuple[int, str | None]:
    if n <= 3:
        return PESO_SIGLA, "sigla de 3 letras"
    if n <= 6:
        return PESO_CURTO, "nome curto"
    if n <= 9:
        return PESO_MEDIO, None
    if n <= 14:
        return PESO_LONGO, None
    return PESO_MUITO_LONGO, None


def _peso_do_vocabulario(rotulo: str, pt, en,
                         lexico: Lexico) -> tuple[int, str | None]:
    if rotulo in pt:
        return PESO_PALAVRA_PT, "palavra em português"
    if rotulo in en:
        return PESO_PALAVRA_EN, "palavra em inglês"
    if rotulo in lexico.flexoes:
        return PESO_FLEXAO, "palavra em português (flexão)"
    achados = sorted({k for k in NICHOS if len(k) >= 3 and k in rotulo})
    if achados:
        return PESO_NICHO, f"nicho: {', '.join(achados[:3])}"
    return 0, None


def e_palavra(rotulo: str, pt, en, lexico: Lexico = LEXICO_VAZIO) -> bool:
    return rotulo in pt or rotulo in en or rotulo in lexico.flexoes


def pontuar(dominio: str, pt, en, *, elegivel: bool = False,
            lexico: Lexico | None = None) -> Nota:
    """Nota de 0 a 100. `pt` e `en` sao conjuntos de palavras sem acento."""
    lexico = lexico or LEXICO_VAZIO
    rotulo, extensao = separar(dominio)
    if not rotulo:
        return Nota(0)

    # Digito e hifen pioram o nome, mas nao o anulam: 2dev.com.br e
    # 1btc.com.br sao elegiveis ao leilao, ou seja, ja provaram demanda.
    # Antes qualquer nome nao-alfabetico caia para nota 0 e ia para o fim da
    # fila, o que deixou 41 elegiveis no fundo do ranking.
    if not rotulo.replace("-", "").isalnum():
        return Nota(0)

    total = 0
    motivos: list[str] = []

    for peso, motivo in (_peso_do_tamanho(len(rotulo)),
                         _peso_do_vocabulario(rotulo, pt, en, lexico)):
        total += peso
        if motivo:
            motivos.append(motivo)

    if e_palavra(rotulo, pt, en, lexico):
        if lexico.popularidade.get(rotulo, math.inf) < RANKING_POPULAR:
            total += PESO_POPULAR
            motivos.append("palavra popular")
    else:
        partes = composto_de_nicho(rotulo, lexico)
        if partes:
            total += PESO_COMPOSTO_NICHO
            motivos.append(f"composto: {' + '.join(partes)}")
        cidades = lexico.padrao_cidades
        if cidades and any(n in rotulo for n in _RAIZES if len(n) >= 4):
            achada = cidades.search(rotulo)
            if achada:
                total += PESO_CIDADE_NICHO
                motivos.append(f"nicho + cidade: {achada.group(0)}")

    if len(rotulo) == 3 and extensao == "com.br" and rotulo.isalpha():
        total += PESO_TRES_COM_BR
        motivos.append("três letras .com.br")

    # Os motivos NAO dizem quantas empresas: a contagem e derivada de dado
    # CC BY-ND 3.0 e nao deve ir para a pagina publica. O motivo diz o que o
    # sinal significa, a nota carrega o peso.
    if lexico.negocios.get(rotulo, 0) >= MINIMO_EMPRESAS_PALAVRA:
        total += PESO_PALAVRA_DE_NEGOCIO
        motivos.append("palavra comum em nome de empresa")
    if lexico.nomes_de_empresa.get(rotulo, 0) >= MINIMO_EMPRESAS_NOME:
        total += PESO_NOME_DE_EMPRESAS
        motivos.append("nome usado por várias empresas")

    if elegivel:
        total += PESO_ELEGIVEL
        motivos.append("elegível ao leilão")

    if extensao == "com.br":
        total += PESO_COM_BR
    elif extensao in EXTENSOES_BOAS:
        total += PESO_EXTENSAO_BOA
        motivos.append(f"extensão {extensao}")
    # Rotulo, nao peso: quem pode registrar limita o mercado de revenda
    # (adv.br so CPF, ind.br so CNPJ), e isso e uma decisao de
    # quem escolhe, nao da nota. Fonte: dominio/extensoes.py.
    if extensoes.restrita(extensao):
        motivos.append(f"extensão restrita: {extensoes.quem_registra(extensao)}")

    if len(rotulo) > 16:
        total += PENA_COMPRIDO
    if _REPETICAO.search(rotulo):
        total += PENA_REPETICAO
    if any(c.isdigit() for c in rotulo):
        total += PENA_DIGITO
        motivos.append("tem número")
    if "-" in rotulo:
        total += PENA_HIFEN
        motivos.append("tem hífen")

    return Nota(max(0, min(100, total)), tuple(motivos))
