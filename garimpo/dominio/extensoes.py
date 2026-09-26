"""
As extensoes do .br (o Registro.br chama de DPNs) e quem pode registrar em
cada uma.

Importa para o garimpo porque a exigencia de quem registra e o tamanho do
mercado de revenda: um `.adv.br` e destinado a advogados e so aceita CPF,
um `.med.br` a medicos, um `.ind.br` a industrias e so aceita CNPJ. O
Registro.br nao pede comprovacao da profissao (ajuda 2.6; Res. CGI.br
2008/008, art. 14, chama essas categorias de "sem restricao"), mas sao
nomes que interessam a poucos compradores, por mais bonito que seja o rotulo.
Um `.com.br` ou um `.app.br` qualquer pessoa ou empresa registra.

Fonte: o arquivo TLDs.php do modulo oficial do Registro.br para WHMCS
(github.com/registrobr/whmcs-registrobr-epp, versao de 17/01/2026), que
separa as extensoes por exigencia de documento, com os comentarios do
proprio arquivo sobre as que ficam de fora por exigirem documentacao. Cinco
extensoes que aparecem na lista da rodada nao constam do TLDs.php (ia, api,
seg, social, xyz): ficam como genericas ate conferencia na pagina de
categorias do Registro.br. Para `restrita()` da no mesmo, porque nem
generica nem desconhecida restringe.

Sem I/O, sem dependencia: e uma tabela com tres funcoes.
"""

from __future__ import annotations

# qualquer CPF ou CNPJ, sem exigencia alem do cadastro
GENERICAS = frozenset("""
app art com dev eco log net ong tec
ia api seg social xyz
""".split())

# tambem sem exigencia de profissao, mas ligadas a uma cidade
CIDADES = frozenset("""
9guacu abc aju anani aparecida barueri belem bhz boavista bsb campinagrande
campinas caxias curitiba feira floripa fortal foz goiania gru jab jampa jdf
joinville londrina macapa maceio manaus maringa morena natal niteroi osasco
palmas poa pvh recife ribeirao rio riobranco riopreto salvador sampa
santamaria santoandre saobernardo saogonca sjc slz sorocaba the udi vix
""".split())

# so pessoa fisica, sem exigir profissao
PESSOAS = frozenset("blog flog vlog wiki nom".split())

# so CPF, categoria destinada a uma profissao (adv a advogados, med a
# medicos...). O Registro.br nao pede comprovacao (ajuda 2.6, achado de
# 18/09/2026). E o grupo que mais engana: rotulo bonito, mercado minusculo.
PROFISSIONAIS = frozenset("""
adm adv arq ato bib bio bmd cim cng cnt coz des det ecn enf eng eti fnd fot
fst geo ggf jor lel mat med mus not ntr odo ppg pro psc qsl rep slg taxi teo
trd vet zlg
""".split())

# so CNPJ, e do ramo correspondente
EMPRESAS = frozenset("agr esp etc far imb ind inf radio rec srv tmp tur tv".split())

# exigem documentacao ou elegibilidade especial (orgao publico, escola,
# cooperativa, entidade sem fins lucrativos, emissora...)
RESTRITAS = frozenset("""
emp am coop fm g12 gov mil org psi b def jus leg mp tc edu
""".split())

GENERICA, CIDADE, PESSOA, PROFISSIONAL, EMPRESA, RESTRITA, DESCONHECIDA = (
    "genérica", "cidade", "pessoa física", "profissão regulamentada",
    "só CNPJ do ramo", "restrita", "desconhecida")

_QUEM = {
    GENERICA: "qualquer pessoa ou empresa",
    CIDADE: "qualquer pessoa ou empresa",
    PESSOA: "só pessoa física",
    PROFISSIONAL: "só CPF, categoria destinada à profissão, sem comprovação",
    EMPRESA: "só empresa do ramo, com CNPJ",
    RESTRITA: "só quem comprova elegibilidade",
    DESCONHECIDA: "não catalogada",
}


def _rotulo(extensao: str) -> str:
    """'com.br' -> 'com'; 'br' -> ''."""
    extensao = extensao.strip().lower().lstrip(".")
    if extensao == "br":
        return ""
    if extensao.endswith(".br"):
        extensao = extensao[:-3]
    return extensao


def categoria(extensao: str) -> str:
    """A categoria da extensao, como texto legivel."""
    r = _rotulo(extensao)
    if not r:
        return RESTRITA                     # o ".br" puro exige documentacao
    for grupo, nome in ((GENERICAS, GENERICA), (CIDADES, CIDADE),
                        (PESSOAS, PESSOA), (PROFISSIONAIS, PROFISSIONAL),
                        (EMPRESAS, EMPRESA), (RESTRITAS, RESTRITA)):
        if r in grupo:
            return nome
    return DESCONHECIDA


def restrita(extensao: str) -> bool:
    """True quando nem toda pessoa ou empresa pode registrar."""
    return categoria(extensao) in (PESSOA, PROFISSIONAL, EMPRESA, RESTRITA)


def quem_registra(extensao: str) -> str:
    return _QUEM[categoria(extensao)]
