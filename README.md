# Liberados: o motor de [liberados.com.br](https://liberados.com.br)

[![Testes](https://github.com/dmgobbi/liberados/actions/workflows/testes.yml/badge.svg)](https://github.com/dmgobbi/liberados/actions/workflows/testes.yml)
[![Licença MIT](https://img.shields.io/badge/licen%C3%A7a-MIT-blue.svg)](LICENSE)
[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue.svg)](https://www.python.org/)
[![Sem dependências](https://img.shields.io/badge/depend%C3%AAncias-nenhuma-success.svg)](CONTRIBUTING.md)
[![Lighthouse 100](https://img.shields.io/badge/lighthouse-100%20%C2%B7%20100%20%C2%B7%20100-success.svg)](https://liberados.com.br)

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/imagens/inicio-escuro.png">
  <img alt="A página inicial do Liberados: a contagem regressiva para a rodada de outubro, os três passos e os cartões com os números da rodada" src="docs/imagens/inicio-claro.png" width="100%">
</picture>

Todo mês o Registro.br devolve ao mercado cerca de 125 mil domínios `.br`
não renovados, numa lista pública que ninguém consegue ler. O
**[Liberados](https://liberados.com.br)** torna essa lista legível: quais
nomes valem a pena, quantos candidatos cada um já tem, quais vão a leilão,
quando um domínio registrado volta. Gratuito, sem cadastro, sem vínculo com
o Registro.br.

Este repositório é o **núcleo aberto** do Liberados (modelo *open core*):
a varredura que lê o processo de liberação respeitando os limites do
Registro.br, a nota que decide o que vale consultar, o exportador do site,
a interface local e os testes. Tudo em Python 3 puro, sem dependências
externas, sob licença MIT.

## O que é aberto e o que não é

| Aberto (este repositório) | Fechado (fica no repositório de trabalho) |
|---|---|
| `garimpo/`: regras, adaptadores do Registro.br, casos de uso, montagem do site | os artigos e insights de `/insights/` e as páginas editoriais (perguntas, regras, glossário, ciclo de vida) |
| `varrer.py`, `check_dominios.py`, `filtrar_lista.py`, `flag_marcas.py`, `desfecho.py` e os outros scripts | a pesquisa que sustenta os artigos (critérios de valor, histórico das rodadas, mercado, leilões) |
| `app.py` e `web/`: a interface local | as imagens de compartilhamento e das páginas de letra |
| `site_modelo/`: casca, estilo e scripts do site, e as páginas da ferramenta | o estado da varredura (`site/dados.json`, `site/todos.json`) e o histórico das listas (`docs/historico/`) |
| `.github/workflows/`: a varredura que roda sozinha e os testes | a operação do dono (visitas, agenda, lançamento) |
| `docs/`: o endpoint, o catálogo de limitações, as fontes oficiais, o processo | anotações pessoais |

O que é fechado continua público **no site**: os artigos estão em
[liberados.com.br/insights/](https://liberados.com.br/insights/) e a série
histórica em [liberados.com.br/dados/](https://liberados.com.br/dados/). O
que não está aqui é o direito de republicá-los como se fossem seus. O
workflow `Garimpo` roda neste repositório e busca o conteúdo fechado na
hora de montar o site (`CHAVE_PRIVADO` em `.github/workflows/garimpo.yml`);
sem a chave ele monta o site só com o que está aqui e não publica nada.

## Por que este repositório existe

O processo de liberação é público, mas mal documentado e cheio de detalhes
contraintuitivos que custam dinheiro a quem não os conhece:

- **não é ordem de chegada** — o primeiro e o último candidato têm o mesmo peso;
- se **duas ou mais** pessoas se candidatam, **ninguém leva** e o nome trava;
- se **uma só** pessoa se candidata, ela leva o domínio por **R$ 40** — vale
  inclusive para nome já elegível ao leilão; o leilão só existe com dois ou mais;
- sua conta tem um **limite de 3 a 200 candidaturas** simultâneas;
- no leilão, o sistema **não avisa** quando sua oferta é ultrapassada.

A consequência prática: o jogo não é achar o melhor nome, é achar um **bom
nome que ninguém mais notou**. Este repositório automatiza essa procura.

O detalhe que faz a diferença: o endpoint de disponibilidade do Registro.br
devolve **quantas candidaturas um domínio já tem**. Dá para saber que um nome
vai travar *antes* de gastar uma das suas 3 vagas.

## Instalação

```bash
git clone https://github.com/dmgobbi/liberados.git
cd liberados
```

Python 3.10+ e `curl`/`iconv` (para o script de download). Nada além disso.
Um clone deste repositório roda a varredura, a interface local e monta o
site da ferramenta; os artigos e o histórico ficam de fora (ver acima).

## Fluxo completo

```bash
# 1. baixar as listas oficiais da rodada atual (converte de ISO-8859-1)
./baixar_listas.sh

# 2. reduzir 125 mil nomes a algumas centenas
python3 filtrar_lista.py liberacao.txt \
    --tld com.br --min 4 --max 9 --sem-numero --sem-hifen \
    --out candidatos.txt

# 3. remover o que parece marca de terceiro
python3 flag_marcas.py candidatos.txt --out risco.csv
grep -v RISCO risco.csv | cut -d, -f1 | tail -n +2 > limpos.txt

# 4. consultar o status real (delay de 2s, lotes de 100 a 200)
python3 check_dominios.py limpos.txt --out resultado.csv --delay 2

# 5. os alvos: em liberação e ainda SEM candidato
grep LIBERACAO_LIVRE resultado.csv
```

O passo 5 é o produto final: nomes **sem candidato visível**. É neles que
vale gastar uma candidatura, porque candidato único leva o domínio pela
anuidade normal.

> **Leia "0" como "zero ou um".** O endpoint não expõe o array `tickets`
> quando existe um único candidato: em 1.305 domínios verificados não
> apareceu **nenhum** com exatamente 1 candidato, enquanto dezenas aparecem
> com exatamente 2 — numa distribuição natural a contagem em 1 seria maior.
> E ao reverificar, nomes pularam de `0` direto para `2`, sem passar por `1`.
>
> Ou seja: um nome marcado "sem competição" pode já ter um candidato. Se
> você se candidatar, vira o segundo, e com dois ou mais **ninguém leva**.
> A lista é um funil, não uma garantia.

## A interface

Além da linha de comando, há uma interface local que faz o fluxo inteiro
clicando:

```bash
python3 app.py
```

Abre em `http://localhost:8765`. Continua sendo Python 3 puro, sem nada para
instalar. O banco fica em `dados.db`, ao lado dos scripts.

No primeiro uso, clique em **Baixar listas oficiais** e depois em
**Verificar**. Os cartões do topo são os filtros:

| Cartão | O que é |
|---|---|
| **Joias** | elegível ao leilão **e** sem candidato visível — o nome já provou ter demanda e ninguém aparece disputando |
| **Sem competição** | nenhum candidato visível: zero ou um |
| **Disputados** | já tem candidato; com dois ou mais o nome trava |
| **Em leilão** | processo competitivo aberto |
| **Marcados** | sua lista de acompanhamento |
| **Não verificados** | ainda sem consulta |

A coluna **Competindo** é o número de candidaturas já feitas. Verde é zero,
âmbar é uma ou duas, vermelho é três ou mais.

A varredura roda em segundo plano, com barra de progresso e botão de parar; o
que já foi verificado fica salvo. Ao terminar, um bloco mostra o que mudou
desde a varredura anterior — é onde se vê um nome saindo de "sem competição"
para leilão.

### Publicando um instantâneo

```bash
python3 exportar_site.py
```

Gera `site/`, o site **Liberados**: uma versão **somente leitura** com os
mesmos filtros, lendo um JSON estático, mais as páginas de texto. Serve para compartilhar o resultado sem dar acesso à sua
máquina. Não varre nada: quem mantém o JSON em dia é o workflow (abaixo).
Cada linha mostra há quanto tempo foi consultada, e o botão *conferir*
pergunta ao RDAP do Registro.br direto do navegador de quem visita — ver
[Frescor dos dados](#frescor-dos-dados). O resultado fica guardado no
aparelho (localStorage) por até 7 dias e vale enquanto for mais novo que
a leitura do servidor: recarregar a página não desfaz a conferência. Nome
que muda ao ser conferido não some da lista: fica com o marcador "mudou:
era sem competição" até a troca de filtro, e o título separa quem saiu.

O `site/` só contém dado de domínio, que é público. Nada de tickets, ofertas
ou anotações pessoais.

O site mora no Cloudflare (desde 16/09/2026), num Worker só com arquivos
estáticos: `wrangler.jsonc` na raiz aponta para `site/`, e os cabeçalhos
(CSP, tipos de `.md`, `.ics` e `.txt`, cache) ficam em
`site_modelo/_headers`. Para publicar na mão (depois de `npx wrangler login`):

```bash
./publicar.sh
```

Cada execução regera o `site/`, sobe para o mesmo Worker e confere se a
página que o visitante recebe tem o conteúdo esperado.

## Varredura contínua

A varredura completa leva cerca de 9 horas no ritmo seguro, o que só funciona
com a máquina ligada a noite inteira. O
[workflow do GitHub Actions](.github/workflows/garimpo.yml) mantém isso
andando sozinho:

| Job | Quando | Duração | O que faz |
|---|---|---|---|
| `manter` | público: de hora em hora (15 min); privado: 4 horários, de 6 em 6 h (7 min) | 7 a 15 min | aplica a lista oficial de leilões e consulta pela fila de frescor |
| `desfecho` | à mão, umas 3 h depois do fechamento (`gh workflow run Garimpo --ref main -f modo=desfecho`) | até 60 min | mede quantos "0 candidatos" eram 1 |
| `demanda` | dia 20, 04h30 de Brasília | ~30 min | regera a contagem do CNPJ |

O estado mora em `site/dados.json`, versionado: o banco é descartável e
reconstruído a cada rodada. O workflow decide a cadência pela visibilidade
do repositório (em repositório público o Actions não cobra minutos; em
privado cabe na cota do plano, com a conta escrita no próprio arquivo do
workflow). No Liberados ele roda neste repositório público e, com o
segredo `CHAVE_PRIVADO`, lê e grava o estado no repositório de trabalho
(ver "O que é aberto e o que não é"); num clone sem a chave, o estado é
comitado no próprio clone. `conferir_frescor.py` deixa a execução vermelha
se algum nome quente passar do prazo (o dobro do intervalo: 2 h no
público, 12 h no privado) ou se a varredura foi barrada
(`work/varredura.json`), e o último passo confere que o `dados.json` no ar
é o desta execução. Disparo manual:
`gh workflow run Garimpo --ref main -f minutos=3` (3 min é o padrão).

Rodar na mão:

```bash
python3 varrer.py --minutos 7
python3 conferir_frescor.py          # confere o site/dados.json
```

Para publicar automático a cada rodada, adicione no repositório o segredo
`CLOUDFLARE_API_TOKEN` (modelo "Edit Cloudflare Workers") e a variável
`CLOUDFLARE_ACCOUNT_ID`. Sem eles o JSON fica comitado e você publica com
`./publicar.sh`.

**Não diminua o intervalo entre consultas.** O piso de 2 segundos é rígido no
`varrer.py`: em runner do GitHub o IP é compartilhado, então acelerar
respingaria em terceiros.

## O ritmo da rodada (desde 12/09/2026)

Os tickets do Registro.br são um contador global e sequencial. Duas
consequências que ninguém publica, e que a varredura passa a extrair a
partir desta versão (a primeira curva real é a que o workflow produzir):

- **A curva de demanda da rodada.** O maior ticket já visto é o total de
  tickets que o Registro.br emitiu até aquele instante, de **todos os tipos
  de pedido** (liberação e registro comum, pela especificação EPP):
  um teto para as candidaturas, não o número delas. A varredura anota um
  ponto cada vez que vê um ticket maior (`ritmo` no JSON).
  `dominio/ritmo.py` faz as contas; a taxa usa um ponto por execução, porque
  dentro de uma execução a subida é descoberta de nomes. Desde 13/09/2026 a
  página principal não mostra o contador (não serve a quem procura nome).
- **Quando os concorrentes chegaram.** O menor ticket de um nome é o
  primeiro candidato; o maior visível, o último. Interpolando na curva, cada
  nome disputado ganha "primeiro concorrente por volta de 09/09 16h" (no
  título da contagem). Os números de ticket ficam no banco; o site só
  recebe a estimativa.

Mais: quando o avail devolve 10 tickets (o corte), a varredura pergunta ao
RDAP a contagem real, no máximo 20 vezes por execução e parando no primeiro
erro. A tabela passa a mostrar 42 onde mostrava 10.

E o botão **quem disputa**, ao lado da contagem, no site e no app local:
lista os candidatos de um nome (instante do pedido, nome, documento
mascarado e, para empresas, quantos domínios têm), o mesmo que a busca do
Registro.br mostra ao clicar num ticket. A consulta é feita pelo navegador
de quem olha, direto no RDAP, dez tickets por vez (`web/disputa.js`). Nada
passa pelo servidor.

O interruptor **Mostrar o .com**, na barra da lista, confere o mesmo nome em
`.com` para todos os nomes da página: livre, à venda (aponta para vitrine
como Afternic ou Sedo), caindo ou com dono, e resume quantos estão livres.
Tocar na pílula abre a ficha: registrador, datas, travas, servidores de nome
e o dono como o registrador publica. Mesma regra: consulta do navegador ao
RDAP da Verisign e do registrador (`web/pontocom.js`).

Com execuções a cada 4 h a curva desta rodada sai esparsa; ela ganha
resolução em outubro.

## Frescor dos dados

Em 10/09/2026 o site mostrou 28 "joias" que já estavam todas em leilão. O
dado tinha 30 horas e aparecia como se fosse de agora. O desenho que nasceu
disso parte de um princípio: **o site é um cache do Registro.br, e cache não
promete estar certo, promete uma idade máxima e diz a idade que tem.**

| Camada | O que garante |
|---|---|
| lista oficial de leilões | refeita pelo Registro.br durante a rodada; baixada a cada execução, tira da lista de joias quem entrou em leilão, sem consulta por nome |
| idade por item | cada linha do JSON carrega quando foi consultada (instantâneo v4) |
| prazo por classe | nomes quentes (elegíveis fora do leilão, disputados, topo da lista, até 200) nunca passam do dobro do intervalo: 12 h no privado, 2 h no público; a fila é "o mais atrasado primeiro", que não abandona ninguém |
| alarme | `conferir_frescor.py`, depois de publicar: vermelho e e-mail se algum quente vencer ou se a varredura foi barrada; o último passo confere o `dados.json` no ar |
| tela | idade em cada linha, *a confirmar* quando vence |
| conferência ao vivo | botão *conferir* consulta o RDAP (CORS aberto) do navegador do visitante; as joias são conferidas sozinhas ao abrir; o resultado fica no aparelho e sobrevive ao recarregar |

A conferência ao vivo vale só para quem conferiu. Nada volta ao servidor:
resultado vindo de navegador alheio poderia ser forjado e contaminaria o
site para todos. E ela nunca segue os links `?ticket=` do RDAP, que devolvem
nome e CPF parcial de cada candidato.

As alternativas avaliadas e descartadas estão em
[docs/opcoes-atualizacao.md](docs/opcoes-atualizacao.md).

## De onde vem a nota

A nota (0 a 100) decide quais dos ~125 mil nomes de cada rodada são
consultados. Ela ordena atenção, não estima preço. Em setembro de 2026 ela
foi reconstruída depois de uma pergunta simples: **a ferramenta acha o que
eu achei na mão?** Não achava: *aprenda*, *petfriendly*, *lojaonline*,
*imoveisnovos* e os nomes de três letras ficavam abaixo do corte.

| Sinal | Fonte | Exemplo que passou a entrar |
|---|---|---|
| palavra em português | pythonprobr + LibreOffice + [MorphoBr](https://github.com/LR-POR/MorphoBr) (substantivos e adjetivos) | chinelo, imovel |
| forma verbal | hunspell pt_BR expandido pelas regras do `.aff` | aprenda, confiar |
| palavra popular | posição no [wordfreq](https://github.com/rspeer/wordfreq) | vacina |
| inglês | dicionário **e** entre as 80 mil mais usadas | tira lixo (teakettle) e marca (fitbit) |
| nicho + palavra comum | radicais de nicho, sem nome de pessoa (censo) | lojaonline, medicaemcasa |
| nicho + cidade grande | IBGE, 200 mil habitantes ou mais | imoveisembelem, cursosbrasilia |
| três letras .com.br | — | todos entram na consulta |

Medido na rodada de setembro: o pool foi de 15.359 para 17.361 nomes, e
das candidaturas feitas à mão só três ficam abaixo do corte, cada uma com o
motivo escrito no teste `TestSuasEscolhas`.

O filtro de marcas também cresceu: quando o `.com` do nome está entre o
1 milhão de sites mais acessados ([Tranco](https://tranco-list.eu/)), o nome
vira risco (jetbrains, deliveroo) ou, se for palavra de dicionário, atenção
(boots, melon). A lista fixa antiga pegava 5 dos 487 casos da rodada.

### Demanda: o que os negócios brasileiros põem no nome

O sinal mais forte veio do [cadastro aberto de CNPJ](https://arquivos.receitafederal.gov.br/index.php/s/YggdBLfdninEJX9)
da Receita: 26,8 milhões de empresas ativas, contando só a matriz. Quem abre
empresa precisa de domínio, e o nome fantasia é o nome que ela escolheu.

- **Palavra comum em nome de empresa** (100 ou mais): das 86 palavras da
  rodada de setembro nessa situação, umas 25 eram candidaturas feitas à mão.
- **Nome usado por várias empresas** (3 ou mais com exatamente aquele nome):
  2.948 rótulos da rodada são o nome fantasia de 2 ou mais empresas.
- **Ramo de negócio**: as 18 categorias do filtro saíram das palavras que
  cada grupo do CNAE usa muito mais que o resto do cadastro, com curadoria.
  A 19ª, **Nomes de pessoas**, casa pela lista de nomes e sobrenomes: um
  nome só (`carlos`) ou dois colados (`adrianosouza`), cada metade com 3
  letras ou mais. Na rodada de setembro, ~2 mil nomes, quase todos o
  domínio de um profissional liberal.

```bash
python3 demanda_cnpj.py            # baixa ~5,3 GB, conta, grava work/demanda.json
```

O dado é **CC BY-ND 3.0**: usar como insumo da nota é uma coisa, publicar a
tabela derivada é outra. Por isso `work/demanda.json` nunca vai para o git
(mora no cache do Actions, regerado todo mês pelo modo `demanda`), e a
página diz "palavra comum em nome de empresa", nunca quantas.

### Uma URL por assunto

Desde 11/09/2026 o site não é mais uma página com abas: cada assunto é
uma URL (`/perguntas/`, `/regras-do-br/`, `/insights/<artigo>/`). A fonte
é `site_modelo/`:

| Arquivo | Papel |
|---|---|
| `layout.html` | a casca comum: cabeçalho, navegação, tema, rodapé, metadados |
| `conteudo/*.html` | um arquivo por página, com os metadados num comentário no topo (`titulo`, `titulo_busca`, `descricao`, `tipo`, `data`, `modificado`) |
| `conteudo/glossario.html` | um termo por `<dt id>`, citável por âncora (`/glossario/#ticket`) |
| `og.png`, `og/*.png` | a prévia de link (1200x630) no WhatsApp, no X e no LinkedIn, do site e de cada insight (metadado `imagem:`), geradas a partir de `og.html`; as de cada insight são conteúdo fechado |
| `conteudo/insights/*.html` | um artigo por arquivo; o índice `/insights/` é montado sozinho. Conteúdo fechado: aqui só existe a pasta que o exportador espera |
| `tema.js` | o botão de tema, em toda página |
| `app.js` | só a ferramenta (a raiz) |
| `agenda.js` | o lembrete na agenda (Google, Outlook, Calendário da Apple): fim do leilão, próxima rodada e volta de um domínio |
| `ficha.js` | a ficha de `/quando-volta/`: um domínio qualquer, consultado no RDAP pelo navegador de quem olha |

`garimpo/web/paginas.py` monta tudo, grava no HTML os números do
instantâneo que as páginas citam, e escreve `sitemap.xml`, `robots.txt`,
`llms.txt` e `llms-full.txt` (o texto do site inteiro, para agentes de IA).
Cada página leva JSON-LD num `@graph`: `Dataset` na ferramenta, `Article`
nos insights, `FAQPage` nas perguntas, `DefinedTermSet` no glossário e
`BreadcrumbList` em todas menos a raiz. O contrato de escrita (resposta
curta, título de busca, denominador em todo número) está no
[`AGENTS.md`](AGENTS.md). Para escrever uma página nova basta criar um arquivo em
`conteudo/`. Nenhum `noindex` no site inteiro nem no `_headers`; só as
páginas ralas saem com `noindex, follow` — ramo com menos de `MINIMO = 10`
nomes (`garimpo/web/ramos.py`) e as letras sem história
(`garimpo/web/letras.py`) — fora do sitemap e do `llms.txt`. O canonical, o
sitemap e o Open Graph saem de `BASE_URL` em `garimpo/web/paginas.py`
(`https://liberados.com.br`).

### Toda a rodada

O cartão **Toda a rodada** carrega `todos.json` sob demanda: os 125 mil
nomes da lista oficial com nota, motivos, risco de marca e ramo. Nome já
consultado aparece com situação e idade; o resto como *não verificado*, com
o botão *conferir*.

### Acompanhar e lembrar

- **Estrela**: acompanha o nome neste aparelho. Na volta, a página compara
  com o instantâneo novo, confere ao vivo e mostra o que mudou ("passou de
  sem competição para disputado"). Aberta, reconfere a cada 20 minutos e,
  com permissão, avisa pelo sistema. Nada sai do navegador.
- **Lembrar do fim** (nomes em leilão): Google Agenda e Outlook por link,
  e no iPhone ou Mac o `.ics` servido em `lembretes/`, que o Safari abre
  direto em "Adicionar ao Calendário".

Aviso com a página fechada precisa de servidor (Web Push, bot ou e-mail):
custos em [docs/opcoes-atualizacao.md](docs/opcoes-atualizacao.md).

### O ano todo (desde 14/09/2026)

A rodada dura uma semana; o site serve nas outras três:

- **Início entre rodadas**: depois do fechamento, o cartão *Voltam na
  próxima rodada* junta os nomes que travaram (dois ou mais candidatos),
  cada um com lembrete; a contagem regressiva vai até a próxima lista.
  As datas saem de `garimpo/dominio/calendario.py` (a regra da segunda
  quarta-feira) e vão no HTML como `p-calendario`; os `.ics` de cada rodada
  ficam em `lembretes/rodadas/`.
- **Quando volta** (`/quando-volta/?d=nome.com.br`): qualquer domínio .br,
  não só os da lista. O RDAP diz se está livre, na rodada, em leilão,
  congelado ou registrado; se tem dono, a ficha mostra o vencimento, a
  rodada provável (cerca de 5 meses depois, limitação S14) e se o nome já
  passou pela lista antes. Esse histórico é um índice estático em
  `docs/historico/passagens/` (256 fatias por hash FNV-1a, só nomes que
  passaram 2 vezes ou mais), gravado por `historico_listas.py passagens`;
  o navegador baixa só a fatia do nome.
- **Domínios por ramo** (`/dominios/`): uma página por ramo e por recorte
  (curtos, três letras), gerada por `garimpo/web/ramos.py` a cada build,
  com o texto da fase da rodada.

Não existe lista de todos os .br registrados para filtrar: o Registro.br
não publica a zona, e consultar nome a nome esbarra no limite por IP. Por
isso a busca geral é a ficha, um nome por vez, no navegador de quem olha.

## O candidato escondido

Vale entender a principal limitação da ferramenta.

Pela regra do NIC.br, **candidato único leva o domínio pela anuidade normal**,
inclusive em nome já elegível ao leilão — o leilão só existe com dois ou mais.
Isso torna os nomes sem concorrente o alvo óbvio.

O problema é que **o endpoint não expõe o array `tickets` quando há um único
candidato**. Em 1.305 domínios verificados não apareceu nenhum com exatamente
1 candidato, enquanto dezenas aparecem com exatamente 2 — numa distribuição
natural a contagem em 1 seria maior. E ao reverificar, nomes pularam de `0`
direto para `2`, sem passar por `1`.

Então `0` deve ser lido como **"zero ou um"**. E a assimetria é cruel:
candidatar-se a um nome que já tem um candidato invisível te faz o segundo, e
aí **ninguém leva** — nem você, nem quem já estava lá.

### Como medir isso, de graça

Quando a rodada fecha, cada nome denuncia o que era:

| Situação real | Desfecho | Status depois |
|---|---|---|
| tinha mesmo 0 candidatos | cai no pool livre | `LIVRE` |
| tinha 1 candidato oculto | é atribuído a ele | `REGISTRADO` |
| tinha 2 ou mais | trava e volta na próxima | `LIBERACAO_*` |

```bash
python3 desfecho.py --antes site/dados.json
```

Compara o instantâneo de antes do fechamento com uma varredura de agora e diz
que fração dos "sem competição" tinha candidato oculto. Roda quando
disparado à mão (`gh workflow run Garimpo --ref main -f modo=desfecho`),
uma vez, antes da lista seguinte — desde 16/09/2026 não há mais cron para
isso.

## Os scripts

| Script | O que faz |
|---|---|
| [`baixar_listas.sh`](baixar_listas.sh) | baixa as listas de liberação e de leilão, converte para UTF-8 |
| [`filtrar_lista.py`](filtrar_lista.py) | filtra a lista bruta por TLD, tamanho, dicionário, nicho |
| [`flag_marcas.py`](flag_marcas.py) | marca nomes com risco de marca registrada (`OK` / `ATENCAO` / `RISCO`) |
| [`check_dominios.py`](check_dominios.py) | consulta o status real e **quantos candidatos** cada nome já tem |
| [`app.py`](app.py) | servidor local da interface |
| [`historias.py`](historias.py) | descobre o que aconteceu com dominios que **ja tem dono**: cruza RDAP (titular, prazos, e a conferência de DNS do próprio registro), DNS (resolve?) e Internet Archive (ja resolveu?); `--titular` diz quantos domínios o dono tem |
| [`isavail.py`](isavail.py) | consulta o ISAVAIL, o serviço oficial (UDP 43) por trás do endpoint web; mostra o pacote cru com `--bruto`. Consulta pontual e contingência, não varredura |
| [`exportar_site.py`](exportar_site.py) | gera o instantâneo estático em `site/` |
| [`varrer.py`](varrer.py) | varredura com orçamento de tempo, para o GitHub Actions |
| [`conferir_frescor.py`](conferir_frescor.py) | confere se o instantâneo cumpre o prazo de cada classe; sai com erro se não |
| [`desfecho.py`](desfecho.py) | depois da rodada fechar, revela quais "0 candidatos" eram na verdade 1 |
| [`sinais_do_desfecho.py`](sinais_do_desfecho.py) | cruza o desfecho com o que se sabia antes (nota, tamanho, dicionário, elegibilidade, extensão): em que faixa um "0" costuma esconder alguém. Roda junto com `desfecho.py` no modo `desfecho` do workflow, quando disparado à mão |

Os scripts na raiz são entradas finas: a lógica mora no pacote
[`garimpo/`](garimpo/). Fora daqui, no repositório de trabalho, ficam os
que só servem ao conteúdo fechado: a série histórica das rodadas, as
imagens de compartilhamento, o índice do Wayback, a leitura de tickets
(dado pessoal, nunca versionada) e as métricas do site.

## Como o código está organizado

Camadas, com a dependência apontando sempre para dentro:

```
garimpo/
├── dominio/        regras puras: sem rede, sem banco, sem I/O
│   ├── situacao.py    enumeração do status (ISAVAIL) -> Situacao
│   ├── relevancia.py  pontuação 0-100
│   ├── marcas.py      risco de marca registrada
│   ├── calendario.py  datas das rodadas e a previsão de volta
│   ├── passagens.py   o índice de passagens pela lista, em fatias
│   └── frescor.py     prazo de cada classe e a fila da varredura
├── adaptadores/    a fronteira com o mundo
│   ├── registrobr.py  cliente HTTP e as três listas oficiais
│   ├── repositorio.py SQLite; o único lugar com SQL
│   └── dicionarios.py cache dos vocabulários
├── casos/          orquestração
│   ├── pool.py        monta o conjunto que vale consultar
│   ├── varredura.py   varre respeitando pausa, orçamento e parada
│   ├── instantaneo.py serializa e restaura o estado em JSON
│   ├── lembretes.py   os .ics do fim de cada leilão e de cada rodada
│   └── manutencao.py  monta a fila de cada execução a partir do banco
├── web/            apresentação
│   ├── paginas.py     monta o site estático a partir de site_modelo/
│   ├── ramos.py       as páginas /dominios/, por ramo e por recorte
│   ├── consultas.py   traduz os filtros da tela em SQL
│   └── servidor.py    só transporte HTTP
└── contexto.py     ponto de composição: liga tudo, sabe onde ficam os arquivos
```

`dominio/` não importa nada das outras camadas, o que deixa a lógica de
negócio testável sem rede e sem banco. `casos/` recebe os adaptadores por
parâmetro, então os testes injetam um cliente falso.

```bash
python3 -m unittest test_scripts     # nenhum teste toca a rede
```

Todos aceitam `--help`. Nenhum deles se candidata a nada nem faz login: a
candidatura é manual, no painel do Registro.br. Estas ferramentas só ajudam a
**decidir**.

### Status devolvidos pelo `check_dominios.py`

| Status | Significado | O que fazer |
|---|---|---|
| `LIVRE` | disponível para registro imediato | registre pelo painel, R$ 40 |
| `LIBERACAO_LIVRE` | em liberação, **sem candidato visível** (zero ou um) | o alvo — mas veja a ressalva acima |
| `LIBERACAO_DISPUTADA` | em liberação, já tem candidato | vai travar; não gaste vaga |
| `COMPETITIVO` | em leilão | custa dinheiro, não candidatura |
| `REGISTRADO` | já tem dono | veja a data em `expires-at` |
| `LIMITADO` | bloqueado por excesso de consultas | aumente o `--delay`, espere e refaça |
| `ERRO` | falha de rede ou resposta inesperada | reveja o `--delay` |

## Documentação

- [Processo de liberação](docs/processo-de-liberacao.md) — as regras da rodada mensal, e o limite de candidaturas
- [Processo competitivo](docs/processo-competitivo.md) — como funciona o leilão e quanto costuma custar
- [O endpoint do Registro.br](docs/api-registrobr.md) — o JSON, a enumeração de `status`, e os limites de uso
- [Limitações do Registro.br, catálogo](docs/limitacoes-registrobr.md) — toda limitação da API, do RDAP, das listas e do painel, numerada e datada
- [Fontes oficiais do Registro.br](docs/fontes-oficiais-registrobr.md) — o GitHub e o FTP do Registro.br: o ISAVAIL (o `status` é enumeração, não bitmask), a extensão NIC.br do RDAP, a especificação EPP do processo de liberação
- [Opções para manter o site atualizado](docs/opcoes-atualizacao.md) — o que foi avaliado e descartado, com custo
- [IA e agentes](docs/ia-e-agentes.md) — como um assistente chega ao Liberados
- [Rumo](docs/rumo.md) — propósito, meta, princípios e a fronteira do núcleo aberto

A pesquisa que sustenta os artigos (critérios de valor, marcas, estratégia
com poucas candidaturas, o histórico das rodadas desde 2017, o mercado
brasileiro contra o americano, o preço dos leilões) é conteúdo fechado; o
resultado dela está no site, em [Insights](https://liberados.com.br/insights/)
e em [Regras do .br](https://liberados.com.br/regras-do-br/).

## O que este projeto descobriu

Coisas que não estavam publicadas em lugar nenhum e saíram de rodar isto:

- **O `.br` mais caro da história foi desligado em silêncio.** `pneus.com.br`
  saiu por R$ 220 mil em 2019 e hoje não resolve para endereço nenhum, pago
  até 2029. Mas não foi engavetado: o Internet Archive mostra que de 2019 a
  2023 ele redirecionava para `sunset-tires.com`, e a última captura já
  apontava para `/pt/`. Foi usado por quase cinco anos, desligado, e o negócio
  mudou para `sunset-pneus.com.br` — registrado só em maio de 2025. Reproduza
  com `python3 historias.py`.
- **Os genéricos mais valiosos são cemitérios.** Dos 18 nomes verificados, 6
  não entregam nada — e **todos os 6 já foram sites de verdade**.
  `viagem.com.br` teve site em 20 anos distintos e parou em julho de 2024;
  `advogado.com.br`, no ar desde 1996, parou em abril de 2022. Não é nome
  comprado e engavetado: é negócio que acabou e domínio que ninguém devolveu.
- **O Registro.br descarta hífens e acentos ao comparar nomes.**
  `casa-verde.com.br` e `casaverde.com.br` são o mesmo nome; `café.com.br`
  volta bloqueado porque `cafe.com.br` existe. Por isso os 125.457 nomes de
  uma rodada têm **zero** rótulos com hífen — e por isso uma prateleira
  inteira do investidor americano não existe aqui.
- **Nenhum domínio tem exatamente 1 candidato.** Em 13.630 verificados: 13.487
  com zero, **nenhum com um**, 80 com dois. Numa distribuição natural "1"
  seria a contagem mais comum. É o sistema escondendo informação, e é o limite
  mais importante desta ferramenta.
- **`carros.com.br` é da estatal de dados do Rio Grande do Sul** (PROCERGS),
  está apagado desde 2017 e pago até 2029. R$ 40 por ano é barato demais para
  doer, e barato demais para soltar.

A comparação completa com o mercado americano — onde uma única empresa chegou
a controlar 43% dos registradores credenciados do mundo, e onde nada disso
funcionaria — está no site, em
[Brasil e EUA](https://liberados.com.br/insights/brasil-vs-eua/).

## Use com responsabilidade

O endpoint de disponibilidade é público, mas **não é uma API documentada** —
é o que a caixa de busca do site usa. O Registro.br limita requisições por IP.

- delay mínimo de **2 segundos** entre consultas (é o padrão dos scripts);
- **filtre antes**: nunca rode a lista inteira de 125 mil nomes;
- **uma conexão só** — não paralelize.

Medido em 09/09/2026: a 2s numa conexão dá 0,46 req/s e passa limpo. Com três
conexões a 1s chega-se a 2,7 req/s e o Registro.br **bloqueia o IP inteiro** —
inclusive o navegador da própria máquina, não só o script.

E há uma armadilha: o bloqueio volta como **HTTP 200 com `status: 8`**, que na
tabela oficial é "erro" — mas que este projeto, lendo o status como bits até
11/09/2026, confundiu com leilão. Sem tratar isso, cada resposta bloqueada
vira um falso domínio em leilão. Detalhes em
[docs/api-registrobr.md](docs/api-registrobr.md).

Se você for bloqueado por excesso de requisições, o problema foi seu.

## Aviso

Este projeto **não é afiliado ao Registro.br, ao NIC.br nem ao CGI.br**.

O formato do endpoint pode mudar sem aviso — os testes em
[`test_scripts.py`](test_scripts.py) guardam respostas reais para que uma
mudança quebre o build em vez de passar despercebida:

```bash
python3 -m unittest -v test_scripts.py
```

Nada aqui é aconselhamento jurídico. Antes de investir num nome, confira
marcas registradas em [busca.inpi.gov.br](https://busca.inpi.gov.br/pePI/).

## Contribuindo

Contribuições bem-vindas, especialmente:

- **ampliar a lista de marcas** em `flag_marcas.py` (é o filtro mais frágil);
- **corrigir o mapeamento de `status`** se o Registro.br mudar o formato;
- **dados de leilões recentes** — os números públicos que temos são de 2017;
- **domínios notáveis**, com fonte — cada um vira uma investigação de
  `historias.py`.

Leia o [CONTRIBUTING.md](CONTRIBUTING.md) antes. Em resumo: só biblioteca
padrão, nenhum teste toca a rede, e o piso de 2 segundos entre consultas não
se negocia.

## Licença

[MIT](LICENSE).
