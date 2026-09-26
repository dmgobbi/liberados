"""
Categorias de negocio, para quem procura nome do proprio ramo.

Camada de dominio: funcao pura. Recebe o rotulo, devolve as categorias.

DE ONDE SAIRAM AS PALAVRAS. Nao de uma lista escrita de cabeca: do cadastro
aberto de CNPJ (agosto de 2026, 26,8 milhoes de empresas ativas). Para cada
categoria juntei os grupos do CNAE correspondentes (restaurantes: 561;
imobiliarias: 681 e 682; oficinas: 452...) e separei as palavras que os
negocios daquele ramo usam no nome fantasia muito mais do que o resto do
cadastro. Depois, curadoria a mao: o grupo CNAE mistura vizinhos (racao e
floricultura cairam em "moda"; funeraria em "beleza") e isso saiu.

Aqui fica so a lista curta de raizes, sem contagem nenhuma. A contagem e
derivada de dado CC BY-ND e nao vai para o git; a lista de palavras e a
conclusao, e e nossa.

COMO CASA. Rotulo de dominio nao tem espaco, entao a busca e por pedaco:
  - raiz de 5 letras ou mais casa em qualquer posicao (imoveisembelem)
  - raiz de ate 4 letras so casa no comeco ou no fim, senao "pet" acharia
    competencia e "cao" acharia comunicacao
"""

from __future__ import annotations

CATEGORIAS: dict[str, tuple[str, tuple[str, ...]]] = {
    "alimentacao": ("Alimentação", (
        "restaurante", "mercado", "mercearia", "pizza", "lanche", "lanchonete",
        "bebida", "conveniencia", "carne", "acougue", "sabor", "emporio",
        "padaria", "panificadora", "cafe", "cafeteria", "acai", "churrasc",
        "adega", "sushi", "burger", "burguer", "hamburg", "delivery",
        "hortifruti", "grill", "sorvete", "confeitaria", "doce", "doceria",
        "salgado", "marmita", "gourmet", "cozinha", "comida", "bistro",
        "cervej", "vinho", "pastel", "tapioca")),
    "moda": ("Moda e acessórios", (
        "moda", "modas", "confec", "calcado", "joia", "semijoia", "fashion",
        "boutique", "jeans", "uniforme", "lingerie", "intima", "roupa",
        "vestuario", "bolsa", "closet", "outlet", "tenis", "sapato",
        "sandalia", "chinelo", "bijou", "relogio", "brecho", "camiseta",
        "vestido", "biquini")),
    "beleza": ("Beleza e estética", (
        "beleza", "estetica", "cosmetic", "perfum", "barbearia", "barber",
        "salao", "cabele", "hair", "beauty", "maquiag", "makeup", "esmalteria",
        "unha", "manicure", "tattoo", "sobrancelha", "depila", "cilios",
        "bronze", "micropigment", "skincare")),
    "saude": ("Saúde", (
        "saude", "clinica", "medic", "odonto", "dentist", "dental", "psicolog",
        "fisio", "fonoaud", "laborat", "nutri", "terapia", "terapeut",
        "enfermag", "reabilit", "sorriso", "farmacia", "farma", "drogaria",
        "otica", "oftalm", "ortoped", "cardio", "dermato", "pediatr", "exame",
        "vacina", "hospital", "autismo", "fonoaudiolog")),
    "imoveis": ("Imóveis", (
        "imove", "imovel", "imobil", "imob", "loteamento",
        "condomin", "incorpor", "aluguel", "alugue", "apartament", "terreno",
        "residencial", "realty", "estate", "moradia", "sindico", "kitnet")),
    "construcao": ("Construção e reforma", (
        "constru", "materiais", "engenharia", "reforma", "instalac", "pintura",
        "tinta", "empreiteira", "vidro", "vidracaria", "gesso", "ferrag",
        "eletrica", "solar", "refrigerac", "climatiz", "madeira", "ferramenta",
        "acabamento", "obra", "obras", "piso", "pisos", "hidraul", "esquadria",
        "telha", "elevador", "piscina", "calha", "serralheria", "pedreiro",
        "arquitet", "guindaste", "andaime", "impermeabil")),
    "automotivo": ("Automotivo", (
        "autopeca", "automot", "automove", "autocenter", "carro", "veicul",
        "mecanic", "moto", "motos", "pneu", "diesel", "oficina", "borrachar",
        "funilar", "bateria", "radiador", "caminh", "truck", "garage", "freio",
        "retifica", "lanternag", "martelinho", "multimarca", "seminovo",
        "lavajato", "lavacar", "motors", "carros")),
    "pet": ("Pet", (
        "pet", "pets", "veterin", "animal", "patas", "bicho", "canil", "gato",
        "dog", "cachorro", "aquario", "petshop", "tosa", "petisco")),
    "educacao": ("Educação e cursos", (
        "escola", "colegio", "educa", "ensino", "curso", "treinamento",
        "creche", "idioma", "ingles", "english", "school", "faculdade",
        "capacitac", "professor", "aula", "aulas", "autoescola", "bercario",
        "vestibular", "concurso", "enem", "gabarito", "apostila", "estude",
        "aprenda", "mentoria")),
    "juridico": ("Jurídico e contábil", (
        "contab", "advog", "advocacia", "juridic", "cartorio", "tabeli",
        "notarial", "auditoria", "contador", "tributar", "fiscal", "pericia",
        "despachante", "direito", "custas", "previdenciar")),
    "tecnologia": ("Tecnologia", (
        "tecnolog", "tech", "software", "sistema", "digital", "informatica",
        "dados", "data", "code", "cloud", "labs", "app", "dev", "web",
        "automac", "inovac", "internet", "host", "ciber", "cyber", "byte",
        "robot", "prompt", "crypto", "cripto")),
    "turismo": ("Turismo e hospedagem", (
        "hotel", "pousada", "turismo", "viage", "travel", "tour", "hostel",
        "hospedag", "passage", "chale", "resort", "trip", "milhas", "praia",
        "intercambio", "cruzeiro", "camping", "albergue", "voo")),
    "financas": ("Finanças e seguros", (
        "seguro", "invest", "financ", "consorcio", "credito", "cred",
        "factoring", "emprestim", "previdenc", "pagamento", "banco", "bank",
        "cambio", "bitcoin", "cartao", "fintech", "cobranca", "contas")),
    "esporte": ("Esporte e academia", (
        "academia", "fitness", "pilates", "esport", "sport", "futebol",
        "crossfit", "treino", "trainer", "arena", "musculac", "ginastica",
        "natacao", "luta", "jiujitsu", "yoga", "bike", "corrida", "surf",
        "skate", "sneaker")),
    "transporte": ("Transporte e entregas", (
        "transport", "logistic", "carga", "frete", "mudanca", "expresso",
        "entrega", "motoboy", "taxi", "fretamento", "guincho", "cargo",
        "encomenda", "viacao", "rodoviar", "courier", "tracker")),
    "eventos": ("Eventos e festas", (
        "evento", "festa", "buffet", "producoes", "artistic", "entretenim",
        "show", "banda", "cerimonial", "formatura", "iluminac", "sonorizac",
        "casamento", "noiva", "aniversario", "recepc", "cenograf")),
    "marketing": ("Marketing e comunicação", (
        "marketing", "publicidade", "propaganda", "agencia", "midia", "media",
        "branding", "design", "fotograf", "foto", "comunicac", "criativ",
        "creative", "promoc", "growth", "conteudo", "video")),
    "casa": ("Casa e decoração", (
        "movel", "moveis", "planejado", "colchao", "colchoes", "marcenaria",
        "decor", "estofado", "eletro", "eletrodomest", "utilidade", "tecido",
        "enxoval", "cortina", "persiana", "tapete", "jardim", "jardinagem",
        "flores", "floricultura", "presente", "home", "vassoura", "limpeza")),
    # Sem raiz: casa pela lista de nomes de gente (ver pessoa()), que vem do
    # adaptador. Na rodada de setembro, 166 nomes exatos e ~1.900 compostos
    # como adrianosouza: o dominio de profissional liberal.
    "pessoas": ("Nomes de pessoas", ()),
}

# Palavra que engole a raiz: dentro dela, a raiz nao conta. Cada linha veio
# de uma amostra da rodada de setembro de 2026 em que o ramo saiu errado
# (imoveis viravam "casa" por causa de "movel"; transportadoras viravam
# "esporte" por causa de "sport"...). "racao" e "corretor" sairam das
# listas de vez: estao dentro de refrigeracao, decoracao, geracao, e
# corretora de seguros e tao comum quanto de imoveis.
# "sport" e "esport" dentro de "s" + porto: colchoesportoalegre,
# terrenosportoseguro, domusportoes (portoes).
_PORTO = ("portoalegre", "portoseguro", "portoes")
EXCLUSOES: dict[str, tuple[str, ...]] = {
    "movel": ("imovel", "automovel"), "moveis": ("imoveis", "automoveis"),
    "sport": ("transport",) + _PORTO, "esport": _PORTO,
    "vestido": ("investido",),
    "carne": ("carneir",), "pet": ("petr", "petit"),
    "media": ("intermedia",), "otica": ("robotic",), "home": ("homem",),
    "flores": ("floresta",), "host": ("hostel",), "dev": ("devoc",),
    "cred": ("credenc",), "doce": ("docent",), "moda": ("modal",),
    # Hotfix de 19/09/2026 (amostra rotulada da rodada de setembro): a raiz
    # curta ou comum dentro de nome de gente, de empresa ou de cidade.
    # "sobras" ficou de fora: "s" + obras e mais comum que a palavra
    # (servicosobraseconcreto, jasolucoesobras, ciadasobras).
    "unha": ("cunha",), "aula": ("paula",),
    "obras": ("obrasil", "eletrobras", "petrobras"),
    "eletro": ("eletrobras",), "carga": ("recarga",),
    "dados": ("bordado", "cuidado"),
}

# Raiz que so vale sozinha: "dados" e "digital" sao modificador (marketing
# digital, agencia digital, pousadadosul). Com outro ramo no nome, o ramo
# delas sai; sem outro, fica (lojadigital continua tecnologia).
MODIFICADORES = frozenset({"dados", "digital"})

# A ordem define o bit de cada categoria no JSON. Acrescente no fim.
ORDEM = tuple(CATEGORIAS)
CURTA = 4        # raiz ate este tamanho so casa no comeco ou no fim


def _casa(raiz: str, rotulo: str) -> bool:
    for engolidora in EXCLUSOES.get(raiz, ()):
        rotulo = rotulo.replace(engolidora, "#")
    if len(raiz) > CURTA:
        return raiz in rotulo
    return rotulo.startswith(raiz) or rotulo.endswith(raiz)


PEDACO_DE_NOME = 3   # cada metade de um nome composto tem pelo menos isto


def pessoa(rotulo: str, pessoas: frozenset[str]) -> bool:
    """
    Nome de gente: um nome so (carlos, araujo) ou dois colados
    (adrianosouza, alinebianca). A lista vem de nomes com 2 mil pessoas ou
    mais e dos sobrenomes do IBGE; os sobrenomes sao so as primeiras 10
    paginas da API (~200), entao nome + sobrenome raro nao casa.
    """
    if not pessoas:
        return False
    if rotulo in pessoas:
        return True
    return any(rotulo[:k] in pessoas and rotulo[k:] in pessoas
               for k in range(PEDACO_DE_NOME, len(rotulo) - PEDACO_DE_NOME + 1))


def categorias_de(rotulo: str, pessoas: frozenset[str] = frozenset()) -> tuple[str, ...]:
    rotulo = rotulo.lower()
    casadas = {nome: {raiz for raiz in raizes if _casa(raiz, rotulo)}
               for nome, (_, raizes) in CATEGORIAS.items()}
    fortes = {nome for nome, raizes in casadas.items()
              if raizes - MODIFICADORES}
    achadas = tuple(nome for nome, raizes in casadas.items()
                    if raizes and (nome in fortes or not fortes))
    return achadas + (("pessoas",) if pessoa(rotulo, pessoas) else ())


def mascara(rotulo: str, pessoas: frozenset[str] = frozenset()) -> int:
    """
    As categorias como bits, na ORDEM: e o que vai para o JSON. Os dois
    exportadores (dados.json e todos.json) precisam receber o MESMO conjunto
    de pessoas, senao o filtro discorda entre os cartoes e a rodada inteira.
    """
    bits = 0
    for nome in categorias_de(rotulo, pessoas):
        bits |= 1 << ORDEM.index(nome)
    return bits


def tabela() -> list[dict]:
    """Nome e rotulo de cada bit, para a pagina montar o seletor."""
    return [{"nome": n, "rotulo": CATEGORIAS[n][0]} for n in ORDEM]
