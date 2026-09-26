#!/usr/bin/env python3
"""
Acentua o texto visivel do site, sem tocar em codigo.

    python3 acentuar.py --conferir     # so mostra o que mudaria
    python3 acentuar.py

POR QUE ISTO EXISTE

O texto do site nasceu sem acento por excesso de cautela com codificacao, e
ficou ruim de ler. Mas nao da para sair trocando no arquivo inteiro: o JS casa
aba e filtro por string (`data-aba="selecao"`), os ids sao consultados por
seletor, e os blocos de codigo contem nomes de dominio e comandos que nao
levam acento.

Entao a substituicao acontece SO em:
  - texto entre tags, fora de <code>, <pre>, <script> e <style>
  - os atributos que sao prosa lida por gente: placeholder, aria-label,
    title, alt e o content do meta description

E preserva:
  - todo o resto dos atributos, que o JS e o CSS usam como chave
  - conteudo de <code> e <pre>
  - nomes de dominio, datas e qualquer palavra encostada num ponto
    ou numa barra

Os textos que moram no JS foram acentuados a mao: sao poucos e cada um
precisa de julgamento.

Os arquivos Python continuam sem acento de proposito: e convencao do projeto
para identificador e comentario, e nao e o que o usuario le.
"""

import argparse
import os
import re
import sys

# Mapa de palavras. Chave sem acento, valor com. Aplicado sobre a palavra
# inteira e preservando a caixa da primeira letra.
PALAVRAS = {
    # navegacao e rotulos
    "dominio": "domínio", "dominios": "domínios",
    "situacao": "situação", "situacoes": "situações",
    "competicao": "competição", "competitivo": "competitivo",
    "leilao": "leilão", "leiloes": "leilões",
    "relevancia": "relevância",
    "elegivel": "elegível", "elegiveis": "elegíveis",
    "selecao": "seleção", "selecionamos": "selecionamos",
    "paginacao": "paginação", "pagina": "página", "paginas": "páginas",
    "acoes": "ações", "acao": "ação",
    "extensao": "extensão", "extensoes": "extensões",
    "criterio": "critério", "criterios": "critérios",
    "documentacao": "documentação",
    "instantaneo": "instantâneo",
    "ultima": "última", "ultimo": "último",
    "proximo": "próximo", "proximos": "próximos", "proxima": "próxima",
    "minimo": "mínimo", "minima": "mínima",
    "maximo": "máximo", "maxima": "máxima",
    "numero": "número", "numeros": "números",
    "publico": "público", "publica": "pública", "publicas": "públicas",
    "publicos": "públicos",
    "unico": "único", "unica": "única",
    "possivel": "possível", "possiveis": "possíveis",
    "impossivel": "impossível",
    "disponivel": "disponível", "indisponivel": "indisponível",
    "responsavel": "responsável",
    "util": "útil", "uteis": "úteis",
    "voce": "você", "voces": "vocês",
    "nao": "não", "sao": "são", "entao": "então",
    "tambem": "também", "porem": "porém", "alem": "além",
    "ja": "já", "so": "só", "ate": "até", "apos": "após",
    "tres": "três", "seis": "seis",
    "mes": "mês", "meses": "meses",
    "dia": "dia", "dias": "dias",
    "horario": "horário", "calendario": "calendário",
    "candidatura": "candidatura", "candidaturas": "candidaturas",
    "titular": "titular", "titulares": "titulares",
    "usuario": "usuário", "usuarios": "usuários",
    "codigo": "código", "codigos": "códigos",
    "caracteristica": "característica",
    "tecnica": "técnica", "tecnico": "técnico",
    "restricao": "restrição", "restricoes": "restrições",
    "referencia": "referência",
    "ofertas": "ofertas", "oferta": "oferta",
    "incremento": "incremento", "incrementos": "incrementos",
    "pagamento": "pagamento",
    "conclusao": "conclusão", "consequencia": "consequência",
    "limitacao": "limitação", "limitacoes": "limitações",
    "verificacao": "verificação", "verificado": "verificado",
    "verificados": "verificados", "verificar": "verificar",
    "consulta": "consulta", "consultas": "consultas",
    "consultado": "consultado", "consultada": "consultada",
    "atencao": "atenção",
    "informacao": "informação", "informacoes": "informações",
    "opcao": "opção", "opcoes": "opções",
    "opiniao": "opinião",
    "razao": "razão",
    "duvida": "dúvida", "duvidas": "dúvidas",
    "pratica": "prática", "praticas": "práticas",
    "historico": "histórico",
    "automatico": "automático", "automaticamente": "automaticamente",
    "sequencial": "sequencial",
    "arbitrario": "arbitrário",
    "obvio": "óbvio", "obvia": "óbvia",
    "proprio": "próprio", "propria": "própria",
    "proprios": "próprios", "proprias": "próprias",
    "ninguem": "ninguém", "alguem": "alguém",
    "atribuido": "atribuído", "atribuidos": "atribuídos",
    "sucessivas": "sucessivas", "sucessivos": "sucessivos",
    "financeiras": "financeiras",
    "anuidade": "anuidade",
    "manutencao": "manutenção",
    "renovacao": "renovação",
    "cancelamento": "cancelamento",
    "irregularidade": "irregularidade",
    "cadastrais": "cadastrais", "cadastral": "cadastral",
    "reserva": "reserva", "reservados": "reservados",
    "quarta-feira": "quarta-feira",
    "vinculante": "vinculante", "vinculo": "vínculo",
    "estatistica": "estatística", "estatisticas": "estatísticas",
    "diferenca": "diferença", "diferencas": "diferenças",
    "presenca": "presença",
    "comeca": "começa", "comecando": "começando", "comecar": "começar",
    "intencao": "intenção",
    "revenda": "revenda", "revender": "revender",
    "ma-fe": "má-fé",
    "prejuizo": "prejuízo",
    "juridico": "jurídico", "juridica": "jurídica",
    "visivel": "visível", "visiveis": "visíveis",
    "explicito": "explícito", "explicita": "explícita",
    # "ha" fica de fora: colide com o verbo haver e com "a"
    "cartao": "cartão", "cartoes": "cartões",
    "facil": "fácil", "dificil": "difícil",
    "preco": "preço", "precos": "preços",
    "pontuacao": "pontuação",
    "mao": "mão", "maos": "mãos",
    "versao": "versão", "versoes": "versões",
    "rapidos": "rápidos", "rapidas": "rápidas",
    "secoes": "seções", "secao": "seção",
    "resumo": "resumo",
    "marcar": "marcar",
    "invisivel": "invisível",
    "servico": "serviço", "servicos": "serviços",
    "sucessivos": "sucessivos",
    "referente": "referente",
    "criterios2": "critérios",
    "estao": "estão",          # "esta" fica de fora: e demonstrativo tambem
    "penalidades": "penalidades",
    "sera": "será", "serao": "serão",
    "havera": "haverá",
    "podera": "poderá", "poderao": "poderão",
    "levara": "levará",
    "ficara": "ficará", "ficarao": "ficarão",
    "aguardara": "aguardará",
    "informara": "informará",
    "provavel": "provável", "provavelmente": "provavelmente",
    "fisico": "físico",
    "conveniencia": "conveniência",
    "escondidos": "escondidos", "escondido": "escondido",
    "escondida": "escondida", "escondidas": "escondidas",
    "sinalizados": "sinalizados",
    "conotacao": "conotação",
    "significado": "significado",
    "substitui": "substitui",
    "garantia": "garantia",
    "chance": "chance",
    "mercado": "mercado",
    "comparaveis": "comparáveis",
    "trafego": "tráfego",
    "julgamento": "julgamento",
    "radicais": "radicais",
    "buracos": "buracos",
    "curva": "curva",
    "volume": "volume",
    "explode": "explode",
    "recalcula": "recalcula",
    "biblioteca": "biblioteca",
    "padrao": "padrão",
    "instalar": "instalar",
    "maquina": "máquina",
    "cruel": "cruel",
    "assimetria": "assimetria",
    "milhares": "milhares",
    "dezenas": "dezenas",
    "aparecem": "aparecem",
    "reverificar": "reverificar",
    "bitmask": "bitmask",
    "armadilha": "armadilha",
    "bloqueio": "bloqueio", "bloqueado": "bloqueado",
    "bloqueia": "bloqueia",
    "excesso": "excesso",
    "abuso": "abuso",
    "pesquisa": "pesquisa",
    "separa": "separa",
    "temporariamente": "temporariamente",
    "conexao": "conexão", "conexoes": "conexões",
    "medido": "medido",
    "afeta": "afeta",
    "leitura": "leitura",
    "cabecalho": "cabeçalho",
    "descontar": "descontar",
    "escolhidos": "escolhidos",
    "generico": "genérico", "generica": "genérica",
    "acrescentar": "acrescentar",
    "exige": "exige",
    "mexer": "mexer",
    "montada": "montada", "montado": "montado",
    "finalidade": "finalidade",
    "discordar": "discordar", "discorda": "discorda",
    "abaixo": "abaixo", "acima": "acima",
    "resto": "resto",
    "corte": "corte",
    "topo": "topo",
    "ranking": "ranking",
    "fila": "fila",
    "zerar": "zerar",
    "fechar": "fechar",
    "rodada": "rodada", "rodadas": "rodadas",
    "travado": "travado", "travada": "travada", "travar": "travar",
    "demanda": "demanda",
    "observada": "observada",
    "palpite": "palpite",
    "soar": "soar",
    "cruza": "cruza",
    "concorrente": "concorrente", "concorrencia": "concorrência",
    "atraem": "atraem",
    "disputa": "disputa", "disputados": "disputados", "disputado": "disputado",
    "dinheiro": "dinheiro",
    "vale": "vale",
    "olhar": "olhar",
    "ordenar": "ordenar",
    "lidos": "lidos",
    "divergir": "divergir",
    "ferramenta": "ferramenta",
    "realmente": "realmente",
    "tamanho": "tamanho",
    "rotulo": "rótulo",
    "radio": "rádio",
    "ouviu": "ouviu",
    "digita": "digita",
    "certo": "certo",
    "comprido": "comprido",
    "dicionario": "dicionário", "dicionarios": "dicionários",
    "portugues": "português", "ingles": "inglês",
    "brasileiro": "brasileiro", "brasileira": "brasileira",
    "busca": "busca", "buscar": "buscar",
    "composto": "composto",
    "nicho": "nicho", "nichos": "nichos",
    "comercial": "comercial",
    "comprador": "comprador",
    "bonito": "bonito",
    "bonus": "bônus",
    "eliminacoes": "eliminações",
    "perde": "perde",
    "pontos": "pontos",
    "continua": "continua",
    "lista": "lista",
    "marca": "marca", "marcas": "marcas",
    "registrada": "registrada", "registrado": "registrado",
    "terceiro": "terceiro", "terceiros": "terceiros",
    "reproduz": "reproduz",
    "recupera": "recupera",
    "filtro": "filtro",
    "exclusao": "exclusão",
    "alvos": "alvos",
    "arquivo": "arquivo", "arquivos": "arquivos",
    "sutil": "sutil",
    "endpoint": "endpoint",
    "documentada": "documentada",
    "caixa": "caixa",
    "site": "site",
    "aviso": "aviso",
    "existe": "existe", "existem": "existem",
    "medida": "medida",
    "oficial": "oficial",
    "qualidade": "qualidade",
    "pessoa": "pessoa",
    "achar": "achar",
    "nome": "nome", "nomes": "nomes",
    "peso": "peso", "pesos": "pesos",
    "vaga": "vaga", "vagas": "vagas",
    "gasta": "gasta",
    "resolve": "resolve",
    "anunciadas": "anunciadas",
    "participantes": "participantes",
    "chegada": "chegada",
    "primeiro": "primeiro", "ultimo2": "último",
    "minuto": "minuto",
    "desempata": "desempata",
    "finais": "finais",
    "espaco": "espaço",
    "livres": "livres",
    "qualquer": "qualquer",
    "registra": "registra",
    "candidato": "candidato", "candidatos": "candidatos",
    "candidata": "candidata",
    "pendencias": "pendências",
    "seguinte": "seguinte",
    "valido": "válido",
    "graca": "graça",
    "recandidatar": "recandidatar",
    "limite": "limite", "limites": "limites",
    "conforme": "conforme",
    "perfil": "perfil",
    "conta": "conta",
    "perto": "perto",
    "opcional": "opcional",
    "politicas": "políticas",
    "regras": "regras",
    "processo": "processo", "processos": "processos",
    "liberacao": "liberação",
    "removidos": "removidos",
    "mensal": "mensal",
    "segunda": "segunda",
    "antes": "antes",
    "inicio": "início",
}

# so mexe em texto entre tags; nunca em atributo, code, pre, script ou style
BLOCOS_PROTEGIDOS = re.compile(
    r"(<(?:code|pre|script|style)\b[^>]*>.*?</(?:code|pre|script|style)>)",
    re.S | re.I)
# Separa tags de texto. A primeira versao casava `>texto<`, o que falhava nas
# bordas de um bloco protegido: um paragrafo com <code> no meio virava um
# fragmento sem `>` inicial e ficava inteiro sem acento.
TAG = re.compile(r"(<[^>]*>)")


def _trocar_palavra(m):
    palavra = m.group(0)
    baixa = palavra.lower()
    novo = PALAVRAS.get(baixa)
    if not novo or novo == baixa:
        return palavra
    if palavra[0].isupper():
        return novo[0].upper() + novo[1:]
    return novo


# Os lookarounds impedem que a palavra encoste num ponto, o que protege
# "Registro.br", "exemplo.com.br" e "09/09/2026" sem precisar descartar o
# paragrafo inteiro. A primeira versao descartava, e paragrafos que apenas
# CITAVAM o Registro.br ficavam sem acento nenhum.
# Antes: `(?![\w.\-/])` no fim. Isso rejeitava tambem a palavra seguida de
# ponto FINAL DE FRASE, e a maioria do texto ficava sem acento. O que precisa
# ser rejeitado e so o ponto que continua em letra, como "Registro.br".
_PALAVRA = re.compile(
    r"(?<![\w.\-/])"          # nao encostada a esquerda
    r"[A-Za-zÀ-ÿ][A-Za-zÀ-ÿ]*"
    r"(?![\w\-/])(?!\.\w)"    # nem a direita, e o ponto so vale se vier letra
)


def acentuar_texto(texto: str) -> str:
    return _PALAVRA.sub(_trocar_palavra, texto)


# Atributos cujo valor e frase lida por alguem, e nao chave de codigo.
# aria-label importa tanto quanto o texto na tela: e o que o leitor de tela
# anuncia.
ATRIBUTOS_DE_PROSA = re.compile(
    r'\b(placeholder|aria-label|title|alt)="([^"]*)"', re.I)
META_DESCRICAO = re.compile(
    r'(<meta\s+name="description"\s+content=")([^"]*)(")', re.I)


def acentuar_atributos(trecho: str) -> str:
    trecho = ATRIBUTOS_DE_PROSA.sub(
        lambda m: f'{m.group(1)}="{acentuar_texto(m.group(2))}"', trecho)
    return META_DESCRICAO.sub(
        lambda m: m.group(1) + acentuar_texto(m.group(2)) + m.group(3), trecho)


def acentuar_html(html: str) -> str:
    partes = BLOCOS_PROTEGIDOS.split(html)
    saida = []
    for i, parte in enumerate(partes):
        if i % 2 == 1:                       # bloco protegido
            saida.append(parte)
            continue
        # indices pares sao texto, impares sao tag
        pedacos = TAG.split(parte)
        saida.append("".join(
            acentuar_atributos(p) if i % 2 else acentuar_texto(p)
            for i, p in enumerate(pedacos)))
    return "".join(saida)


# Atributos cujo valor e chave de codigo: JS casa por string, CSS por seletor.
# Acento aqui quebra silenciosamente, e a pagina so parece "meio torta".
# Aconteceu: um replace global trocou class="cartao" por class="cartão" e os
# cartoes do painel perderam o layout em producao.
ATRIBUTOS_DE_CODIGO = re.compile(
    r'\b(class|id|for|data-[a-z-]+|aria-controls|aria-labelledby|href|src)'
    r'="([^"]*)"', re.I)


def conferir_identificadores(html: str, caminho: str) -> list[str]:
    """Devolve os atributos de codigo que ficaram com acento."""
    problemas = []
    for m in ATRIBUTOS_DE_CODIGO.finditer(html):
        valor = m.group(2)
        if m.group(1).lower() in ("href", "src"):
            continue                      # URL pode ter acento legitimamente
        if any(c in "áàâãéêíóôõúüç" for c in valor.lower()):
            problemas.append(f"{caminho}: {m.group(1)}=\"{valor}\"")
    return problemas


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--conferir", action="store_true",
                    help="mostra o que mudaria, sem gravar")
    ap.add_argument("arquivos", nargs="*",
                    default=["site_modelo/index.html", "web/index.html"])
    args = ap.parse_args()

    for caminho in args.arquivos:
        if not os.path.exists(caminho):
            print(f"  {caminho}: nao existe", file=sys.stderr)
            continue
        original = open(caminho, encoding="utf-8").read()
        novo = acentuar_html(original)
        if original == novo:
            print(f"  {caminho}: nada a mudar")
            continue
        mudancas = sum(1 for a, b in zip(original.split(), novo.split()) if a != b)
        if args.conferir:
            print(f"  {caminho}: {mudancas} palavras mudariam")
        else:
            problemas = conferir_identificadores(novo, caminho)
            if problemas:
                print("  ABORTADO: acento em atributo de codigo", file=sys.stderr)
                for p in problemas:
                    print(f"    {p}", file=sys.stderr)
                return 1
            open(caminho, "w", encoding="utf-8").write(novo)
            print(f"  {caminho}: {mudancas} palavras acentuadas")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
