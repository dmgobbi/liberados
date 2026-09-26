# Opções para manter o site atualizado

Registro da discussão de 10/09/2026, depois que evangeliza.com.br apareceu
como "joia" (elegível e sem candidato) quando já tinha 3 tickets e estava em
leilão. Na conferência, as 28 joias do site estavam TODAS erradas.

## Causa

`varrer.py` reconstrói o banco a partir de `site/dados.json` a cada execução,
e `instantaneo.candidatos_de()` carimba todos os itens com o mesmo
`verificado_em` (o `gerado_em` do instantâneo). A vigia ordena por
`verificado_em ASC, nota DESC`: como o primeiro critério sempre empata, vale só
a nota. Cabem 195 consultas em 7 minutos, a fila tem 246, e os 51 de menor
nota nunca são reverificados. As joias são justamente nomes longos e de nota
baixa, então caíram todas na cauda esquecida.

Agravante: o site mostra uma data global ("gerado em"), que faz um dado de 30
horas parecer recém-verificado.

## Por que o navegador não consulta o endpoint de disponibilidade

`registro.br/v2/ajax/avail/raw/` responde
`access-control-allow-origin: https://registro.br`. O CORS é aplicado pelo
navegador: a requisição sai, mas o JavaScript de outra origem não pode ler a
resposta. Os cabeçalhos da página do Registro.br também fecham os truques
comuns:

| Via | Funciona? | Motivo |
|---|---|---|
| `fetch` com `mode: 'no-cors'` | não | resposta opaca, não dá para ler |
| iframe da busca | não | `frame-ancestors 'none'` e `X-Frame-Options: SAMEORIGIN` |
| popup + leitura | não | `Cross-Origin-Opener-Policy: same-origin` |
| JSONP / `<script>` | não | o endpoint devolve JSON puro |
| extensão / userscript (Tampermonkey) | sim | extensão com permissão de host ignora CORS; roda do IP do visitante |
| bookmarklet | provavelmente | roda na origem registro.br; `connect-src 'self'` impede POST para fora, mas pode navegar para `liberados.com.br/#resultados=...` (não testado) |
| app nativo / desktop | sim | fora do navegador não há CORS; exige instalação |
| proxy CORS | sim | mas a consulta sai do IP do proxy, não do visitante |

## Botão "atualizar para todos"

Exige uma função no servidor, que consulta do IP do servidor (hoje
Cloudflare), não do visitante, e grava num armazenamento compartilhado.
Proteções obrigatórias: lista branca
(só nomes do pool), carência por domínio (verificado há menos de 5 min
devolve o que já tem), e limite global de 1 consulta a cada 2 s somando todo
mundo. Padrão: instantâneo base + camada de resultados mais novos, vence o
carimbo de tempo mais recente.

## O problema de confiança

Tudo que roda na máquina do visitante é controlado por ele. Se o resultado
de um visitante for publicado para todos, qualquer um pode injetar "0
tickets" num nome. Visitante pode ver o próprio resultado; para publicar,
ou o servidor reconfere, ou o envio do visitante vale só como DICA que
antecipa a reverificação daquele nome.

## Achado posterior: RDAP tem CORS aberto

`rdap.registro.br/domain/<nome>` responde `access-control-allow-origin: *` e,
para nomes em liberação, lista cada ticket (`links` com `rel: archives` e
`publicIds` do tipo `ticket`). Em 45 nomes a contagem bateu exatamente com o
endpoint de disponibilidade, e também nunca mostrou exatamente 1 ticket.

ATENÇÃO: `rdap.registro.br/domain/<nome>?ticket=<n>` devolve nome e CPF
parcial do candidato. Dado pessoal: nunca consultar nem exibir.

O cabeçalho `Nicbr-Resource` (exposto pelo CORS) completa o quadro:

| Resposta do RDAP | Situação |
|---|---|
| `competitive-release-process-running` | leilão |
| `release-process-running` e 0 tickets | em liberação, sem candidato visível |
| `release-process-running` e 2+ tickets | em liberação, disputado |
| `competitive-release-process-closed` | leilão com a rodada fechada, ofertas até o dia seguinte (16/09/2026) |
| `release-process-waiting` (200, objeto vazio) | travado, espera a próxima rodada (16/09/2026) |
| 200 sem o cabeçalho | registrado |
| 404 | livre |

Conferido nome a nome contra o endpoint de disponibilidade em 10/09/2026.
Não há limite oficial publicado; fontes de terceiros falam em ~20 a 30
consultas a cada 5 minutos por IP. 45 consultas em ~4 minutos passaram sem
bloqueio.

## Sinais pesquisados e adiados (11/09/2026)

Da pesquisa "o que as pessoas querem" para extrair mais dos 125 mil nomes.
Entraram na nota: MorphoBr, hunspell expandido, wordfreq, IBGE (cidades e
sobrenomes), Tranco e o nome fantasia do CNPJ. Ficaram para depois:

| Sinal | Por que ficou | Custo medido |
|---|---|---|
| `.com` registrado, via DNS, para os 125 mil | é o sinal nº 1 das ferramentas de domínio (ExpiredDomains, Dynadot, EstiBot), mas não cabe no orçamento do Actions; a Tranco já dá a metade valiosa (o `.com` com site de verdade) sem rede | 300 nomes em 10,4 s por DNS-over-HTTPS: ~72 min por rodada; 26% dos `.com.br` têm o `.com` registrado |
| marcas e famosos da Wikidata | a consulta precisa de `SELECT DISTINCT`, e a classe de marca traz franquias (a primeira era Star Wars); vira curadoria, não download | 2.384 marcas e 2.635 brasileiros famosos em ~4 s cada |
| popularidade pelo clickstream da pt.wikipedia | resolve só o título final; geladeira, barbearia e seguradora vêm vazias porque são redirecionamentos, e cruzar com a tabela de redirecionamentos é mais um dump grande | 20 MB por mês |
| ano da primeira captura no Wayback | limite de ~60 requisições por minuto, e bloqueio que dobra a cada reincidência | ~70 min para o pool |
| categorias como nomes próprios, países, animais, planetas | medido e sem ouro: nomes comuns e países já estavam no pool; animais e objetos já estavam no dicionário | — |

## Avisos para quem visita (11/09/2026)

Pedido: "lembrar do fim" só baixava um `.ics` no celular, e faltava avisar
quando um nome muda (sem competição → disputado). O que entrou:

- **Lembrete no calendário.** O botão abre uma escolha na ordem do aparelho:
  link do Google Agenda e do Outlook (o evento abre pronto, é só salvar) e,
  no iPhone e no Mac, o `.ics` servido pelo site em `lembretes/<nome>.ics`
  com `Content-Type: text/calendar`, que o Safari abre direto na tela
  "Adicionar ao Calendário". Blob gerado no navegador só baixa; `data:` no
  topo da janela o Chrome bloqueia. Para prazo fixo, calendário é a
  ferramenta certa: alarme confiável, sem servidor, sem conta.
- **Acompanhar (estrela).** Guarda nome e última situação no aparelho. Na
  volta, compara com o instantâneo novo, confere ao vivo no RDAP (dentro do
  teto de 20 consultas, somado com as joias) e mostra "o que mudou". Com a
  página aberta, reconfere a cada 20 min e, se a pessoa permitiu, manda
  aviso do sistema pelo service worker (o Chrome do Android não aceita
  `new Notification()`). Nada volta ao servidor.

Avisar com a página FECHADA ficou de fora, com o custo de cada caminho:

| Caminho | O que exige | Por que não agora |
|---|---|---|
| Web Push | chaves VAPID, função no Vercel para receber a inscrição, armazenamento (Vercel KV/Blob ou Upstash), e o envio no Actions com dependência de criptografia (`pywebpush`); no iPhone só funciona com o site instalado na tela de início | conta e armazenamento novos, e o Actions checa só a cada 4 h (menos com o orçamento privado) |
| Bot do Telegram | token do BotFather como segredo, `getUpdates` a cada execução, e guardar quem segue o quê | a lista de chat ids é dado pessoal e não pode ir para um repositório que talvez fique público; teria de morar em cache do Actions ou fora |
| E-mail | provedor de envio e cadastro de endereço | coleta de dado pessoal, e o mesmo problema de onde guardar |

Os três dependem da decisão do repositório público: com minutos ilimitados
a checagem pode ser de hora em hora, e aí um aviso fora da página passa a
chegar a tempo de agir.

## Decisão

Princípio: o site é um cache do Registro.br. Cache não promete estar certo;
promete uma idade máxima, e diz a idade que tem. Aplicado em camadas:

1. **A lista oficial de leilões manda.** `lista-competicao.txt` é regerada
   a cada 5 minutos durante a rodada (medido em 10/09: 22h30, 22h35 ...
   23h15) e já é baixada a cada execução. Quem está nela vira
   COMPETITIVO na hora, com a data da lista. Sozinha, teria evitado as 28
   joias falsas: todas estavam na lista.
2. **Idade por item.** Instantâneo v4 guarda quando cada nome foi consultado,
   em segundos UTC (o banco mistura fusos; comparar texto ordena errado).
3. **Prazo por classe e fila "mais velho primeiro"** (`dominio/frescor.py`).
   Quente: até 200 nomes, prazo de 8 h. Cada execução pega os urgentes
   (passariam do prazo antes da próxima) ou a cota de rodízio (quentes × 4 h
   / 8 h), o que for maior. A cota evita dois defeitos da primeira versão:
   todo quente vencendo em toda execução (a fila nunca andava) e quentes
   vencendo em rajada.
4. **Alarme.** `conferir_frescor.py` no fim do workflow, depois de publicar.
5. **Tela honesta.** Idade por linha e *a confirmar* quando vence.
6. **Conferência ao vivo no navegador**, via RDAP, só para quem conferiu.
   Automática para as joias (teto de 20, uma a cada 2,5 s, para no
   primeiro erro).

Descartados:

| Opção | Por quê |
|---|---|
| botão "atualizar para todos" no servidor | consulta sai do IP do servidor (hoje Cloudflare), um abuso bloqueia o site inteiro, e exige armazenamento compartilhado; a conferência no navegador entrega o dado ao vivo sem nada disso |
| aceitar resultado enviado pelo visitante | forjável; no máximo serviria de dica para reverificar antes, e a fila por prazo já faz isso |
| repositório público (minutos ilimitados) | **decidido: vira público no lançamento** (`dmgobbi/liberados`). A cadência troca sozinha pela visibilidade (`github.event.repository.private`), sem mudar código. As anotações pessoais já ficam fora do git (`.gitignore`), e nenhum arquivo versionado tem dado pessoal. Tornar público não se desfaz de verdade |
| Cloudflare Workers / Deno Deploy para consultar o Registro.br | IP compartilhado não testado contra o Registro.br, e mais uma conta para manter (vale para a consulta; hospedar o site estático lá é outra coisa, ver "Hospedagem" abaixo) |
| cron-job.org disparando o workflow | token do GitHub guardado por terceiro; o cron do Actions atrasa, mas o alarme acusa |
| extensão / bookmarklet | exigem instalação ou gesto do visitante; o RDAP com CORS aberto torna os dois desnecessários |

## Compartilhar lista e busca por link (15/09/2026)

Pedido do dono: mandar a lista de acompanhados e a busca filtrada para um
amigo. Feito sem servidor: o endereço carrega o cartão, os filtros e, na
lista, os próprios nomes (`/?lista=cale,pizza,x.ia.br&ordem=candidatos`).
Decisão do dono: **o link fica completo.** É transparente (quem recebe lê
o que vai abrir), não expira, não passa por terceiro e sobrevive à troca de
domínio; no WhatsApp vira prévia e a URL quase não aparece.

| Opção | Por quê |
|---|---|
| encurtador próprio (função no Vercel + Upstash Redis, `/l/k3F9x2`) | servidor e banco só para encurtar é overengineering; seria o primeiro dado guardado no servidor e mais uma conta para manter |
| encurtador público (is.gd, TinyURL, Bitly) | is.gd não tem CORS (o navegador não lê a resposta), TinyURL e Bitly pedem chave que não pode ficar no site; a lista iria para terceiro e o link perde a marca e a transparência |
| comprimir a lista no link (deflate + base64) | medido em 15/09/2026: 15 nomes dão 116 caracteres nos dois jeitos, 40 nomes 293 contra 259; nomes curtos e variados não comprimem, e o link deixa de ser legível |
| índice do nome no instantâneo em vez do nome | encurta ~35%, mas o instantâneo muda a cada rodada e o link quebraria |

## Ferramenta para IAs (13/09/2026)

Pedido: que um assistente de IA use o Liberados quando alguém pedir domínios
`.br` disponíveis. Pesquisa e proposta em [`ia-e-agentes.md`](ia-e-agentes.md).
Descartados:

| Opção | Por quê |
|---|---|
| API que responde "este nome está livre?" para qualquer nome, consultando o Registro.br no servidor | é o "atualizar para todos" com outra roupa: a consulta sai do IP do servidor (hoje Cloudflare) e um abuso bloqueia o site inteiro (A6, R4); o RDAP proíbe distribuir o dado (R5). Conferir ao vivo fica com quem pergunta, no navegador ou no terminal do agente |
| API com parâmetro (`/api/buscar?q=`) como caminho principal para assistentes de conversa | Claude, ChatGPT e Gemini não montam URL que não viram; só agentes com terminal, MCP ou skill chegam lá. Para quem pergunta a um assistente comum, o que funciona é página indexada |
| GPT com Actions (OpenAPI) | a OpenAI estaria aposentando em favor de Plugins (não confirmado); o MCP remoto cobre ChatGPT e Claude com um servidor só |
| apostar no `llms.txt` como canal | estudos de 2026 com 137 mil e 300 mil domínios: quase ninguém lê e nenhum efeito nas citações. Fica, porque custa zero e os agentes de código leem |

## O `.com` do mesmo nome (15/09/2026)

Pedido: saber, ao lado de cada domínio, se o mesmo nome em `.com` está
livre. Ficou o interruptor "Mostrar o `.com`" (`web/pontocom.js`): lote da
página no navegador de quem olha, no RDAP da Verisign, e uma ficha com o
dono como o registrador publica. Plano, medidas e a lista completa em
[`consulta-ponto-com.md`](consulta-ponto-com.md). Descartados:

| Opção | Por quê |
|---|---|
| gravar o estado do `.com` no `dados.json` pela varredura | fica velho em horas (cerca de 84 mil `.com` caem por dia) e seriam 16 mil consultas de um IP do GitHub a um limite não publicado |
| arquivo de zona do `.com` (CZDS da ICANN) | acesso sob aprovação, termos que restringem publicar derivado, vários GB por dia contra o orçamento do Actions; e a zona só tem nome com DNS |
| DNS pelo navegador (DoH) | ter nameserver não é ter dono, e vice-versa |
| API de registrador (GoDaddy, Domainr) | chave exposta ou proxy no servidor, e o site amarrado a uma empresa |
| botão `.com?` em cada linha | poluía a lista; virou um interruptor só |
| `connect-src https:` para consultar o dono em qualquer registrador | afrouxa a CSP do site inteiro por 17% dos nomes; decisão do dono, se a lista de 31 não bastar |
| buscar o dono no lote | centenas de registradores com limites próprios (Tucows respondeu 429 cedo); só ao abrir a ficha |
| link para o ICANN Lookup | pede captcha e não abre com o nome preenchido: o link daria num formulário vazio |

Revisto: "conferir o `.com` da página inteira" estava descartado por limite
não publicado. Medido em 15/09/2026 (200 consultas sem 429), o lote da
página ficou, 2 consultas por vez e parando no primeiro erro.

## Hospedagem: do Vercel para o Cloudflare (16/09/2026)

Decisão do dono, pensando num site que viraliza e fica no ar por anos. O
site é só arquivo estático (630 arquivos, 37 MB), e cada visita baixa ao
menos o `dados.json` (116 KB comprimido; com o `todos.json`, mais 890 KB).

| | Vercel Hobby | Cloudflare Workers, só arquivos estáticos |
|---|---|---|
| tráfego | cerca de 100 GB/mês; passou, o projeto pausa até o mês virar | requisição a arquivo estático "free and unlimited" |
| uso comercial | proibido no Hobby (doação é zona cinzenta) | permitido |
| limites que importam | | 20.000 arquivos e 25 MiB por arquivo por versão; `_headers` com até 100 regras e 2.000 caracteres por linha |
| cabeçalhos | `vercel.json` | `site_modelo/_headers` (conferido no `wrangler dev`: CSP, `.md`, `.ics`, `.txt`) |

Escolhido o Workers, e não o Pages, porque o Cloudflare recomenda o Workers
para projeto novo e o Pages grátis limita publicações por mês (a cadência
pública, de hora em hora, chega a ~720). O `noindex` do endereço provisório
saiu junto: o `*.workers.dev` foi desligado no `wrangler.jsonc` em
17/09/2026, quando o domínio entrou no ar. Fontes: developers.cloudflare.com/workers/static-assets/
(billing-and-limitations, headers, routing/advanced/html-handling) e
developers.cloudflare.com/workers/platform/limits/, lidas em 16/09/2026.

## Vigia de fora do GitHub (19/09/2026)

Proposta da revisão de 18/09/2026 (achado `preparacao-ops:vigia-externo`):
um serviço externo como o healthchecks.io avisaria se o Garimpo parasse,
inclusive quando o próprio GitHub Actions para (sem minutos, por exemplo).
**Descartado:** o dono não cria conta nova em serviço nenhum (decisão de
19/09/2026). O que sobra sem conta nova: o workflow Visitas, o alarme de
frescor e o `gerado_em` conferido no ar no fim de cada Garimpo, todos dentro
do próprio GitHub, e portanto cegos no caso em que o Actions inteiro para.
Alternativa sem conta nova, a avaliar: um cron do Cloudflare, onde a conta
já existe.

