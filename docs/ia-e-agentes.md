# IA e agentes: como um assistente chega ao Liberados

Pesquisa de 13/09/2026. Pedido do dono: quando alguém pedir a uma IA
"domínios .br disponíveis de comida" ou "nomes curtos em português, até 7
letras, com .com.br livre", a IA deveria poder usar o Liberados. **Decisão
pendente**; a proposta está no fim. O que foi descartado, com motivo, está em
[`opcoes-atualizacao.md`](opcoes-atualizacao.md).

Fontes numeradas no fim. "Não confirmado" quer dizer que a página original
bloqueou a leitura e só sobrou resumo de busca.

## O que já existe

| Quem | O que faz | O que falta |
|---|---|---|
| Registro.br | as três listas em texto puro [4][5] | situação, tema, busca |
| ExpiredDomains.net | página `.br` com a lista da rodada (118.925 `.com.br`, o mesmo número do nosso `todos.json`) [6] | quem está sem concorrente; em inglês; nada pensado para IA |
| Dual Marcas | busca por trecho do nome na rodada de 09/2026 [7] | idem |
| processodeliberacao.com.br | "ferramenta para profissionais"; página ilegível para robôs | não confirmado |
| `registro-br-mcp`, Apify "Domain Checker Brazil", MCPs de RDAP genéricos | conferem um nome por vez pelo RDAP (o `rdap.registro.br` está na tabela da IANA) [8][9][10] | não sabem quais nomes existem para conferir |

Ninguém entrega a lista da rodada com a situação de cada nome, por tema, num
formato que uma IA leia.

## Como cada assistente chega a uma ferramenta de fora

O achado que decide o desenho: **nenhum assistente de conversa monta sozinho
uma URL com parâmetro** (`/api/buscar?q=pet`) que não tenha visto antes.

- **Claude:** o `web_fetch` só busca URL que já apareceu na conversa ou num
  resultado de busca; URL escrita por extenso num arquivo lido conta [1].
  Conector MCP remoto em todos os planos, um só no Free [14].
- **ChatGPT:** abre sozinho só URL que o índice já conhece; fora disso, pede
  ao usuário [2]. Ferramenta com parâmetro exige app MCP; o modo
  desenvolvedor existe do Plus para cima, só na web [29]. Os GPTs com
  Actions estariam sendo aposentados em favor de Plugins [13] (não
  confirmado).
- **Gemini:** lê só URL fornecida e não segue links [3].
- **Perplexity:** visita páginas ao responder [16]; conector remoto do Pro
  para cima [17] (não confirmado).
- **Google (AI Overviews, AI Mode):** só página indexada e elegível a
  trecho; não usa arquivo de texto para IA [18][19].

Consequência: para quem pergunta a um assistente comum, o que funciona é
**página indexada**. API, MCP e skill servem a quem instala ou a agentes de
código.

## llms.txt

- Ahrefs, 137.210 domínios (maio/2026): 97% dos arquivos com zero acesso; o
  GPTBot foi quem mais pediu, e o Claude Code apareceu antes dos robôs de
  busca [20].
- SE Ranking, 300 mil domínios: nenhum efeito nas citações [21].

Vale manter (custa zero e é o mapa dos agentes de código), mas não é canal
de descoberta.

## MCP remoto

- No Vercel, o caminho indicado é o pacote `mcp-handler` numa rota [22]; a
  versão 2 segue a spec 2026-07-28, sem sessão nem Redis [23][24]. Em Python,
  FastMCP com `stateless_http=True` [25].
- A documentação de MCP do Vercel não restringe plano [22] (ausência de
  restrição, não permissão explícita).
- Listagem: MCP Registry oficial (em teste, só metadados; `server.json` com
  `remotes` do tipo streamable-http; nome por `io.github.<usuario>` ou
  verificação do domínio) [26][27]; Smithery aceita a URL [28].

## Skills (`SKILL.md`)

- Padrão aberto (agentskills.io), lido por Claude, Claude Code, Codex,
  Gemini CLI, Cursor, Copilot e outros [31].
- Distribuição: marketplace de plugins do Claude Code [32], upload no
  claude.ai [33][34], `npx skills add` [35], plugins do Codex/ChatGPT [36].
- Uma skill pode mandar o agente rodar `curl`, o que escapa da regra do "URL
  já vista". Depende da rede do ambiente: Claude Code tem [34]; Codex vem com
  rede desligada [38]; no claude.ai varia por plano [37].

## Vercel Hobby

O site saiu do Vercel em 16/09/2026 (motivos em
[`opcoes-atualizacao.md`](opcoes-atualizacao.md)); fica o registro. Um MCP
remoto no Cloudflare seria código de Worker, que conta no limite diário de
requisições do plano grátis, ao contrário dos arquivos estáticos.


- Grátis e só para uso pessoal não comercial. Cobrança, anúncio de produto
  e site cujo fim principal é afiliado contam como comercial [39].
  **Anunciar qualquer produto pago neste site o tira do Hobby.**
- Por mês: 1 milhão de chamadas de função, 4 h de CPU ativa, 100 GB de
  tráfego [39][40]. JSON estático não gasta função.

## Google: páginas geradas em escala

A política de spam (atualizada em 28/08/2026) pune muitas páginas feitas
"para manipular rankings e não ajudar usuários", citando feed ou resultado
de busca virado em páginas, e páginas quase iguais para buscas parecidas
[41]. Automação é aceita quando a página é útil e diz como foi gerada [42].
Para uma página por tema passar: dado próprio e datado (situação conferida,
contagem com denominador), texto que explica o processo, e nada de página
quase vazia (menos de N nomes: não gerar, ou `noindex`).

## Proposta (fase 1 feita em 14/09/2026)

Estado: a fase 1 está no ar desde 14/09/2026 (`/dominios/` e uma página por
ramo, `garimpo/web/ramos.py`), junto com a ficha `/quando-volta/`, que
também serve a agentes (`/quando-volta/?d=nome.com.br`, e o RDAP direto
documentado em Para devs). Fases 2 e 3 continuam pendentes.

Regra que vale para as três fases: **só o instantâneo publicado**. Nada
consulta o Registro.br no servidor a pedido de alguém (A6, A7, R4, R5; ver
`opcoes-atualizacao.md`). Conferir um nome ao vivo é sempre do lado de quem
pergunta: navegador (`web/disputa.js`) ou terminal do agente.

1. **Páginas por filtro, geradas no build** (Google e todo assistente). Os
   19 ramos de `dominio/categorias.py` já existem nos dois JSON. Instantâneo
   de 13/09/2026 23h UTC, nomes sem competição no pool: tecnologia 353, pet
   191, saúde 154, nomes de pessoas 149, construção 77, imóveis 63,
   alimentação 48, beleza 39; transporte 6 e eventos 8 não passariam do
   corte. Mais os recortes que respondem pergunta real: `.com.br` até 7
   letras que são palavra em português (316 na rodada, 262 sem candidato
   visível), três letras. Cada página com `titulo_busca`, data, denominador,
   a fase da rodada e linha no `llms.txt`.
2. **JSON documentado + `SKILL.md`** (agentes de código). O formato
   compacto dos dois JSON só está descrito em comentário de código
   (`app.js`, `casos/instantaneo.py`, `casos/todos.py`); falta uma seção
   em Para devs. A skill ensina a baixar e filtrar, conferir no RDAP com 2 s
   de pausa e parar no `Nicbr-Rate-Limit-Exceeded`, e as regras que a IA
   erra: candidato único invisível (A2), acento e hífen não criam nome novo
   (A5), quem pode registrar (`med.br` e `adv.br` só CPF, sem comprovação;
   `gov.br`, `edu.br` e `b.br` exigem elegibilidade e não aparecem na lista:
   zero na rodada de 09/09/2026).
3. **MCP remoto, depois do domínio próprio.** Ferramentas sobre o mesmo
   instantâneo (buscar por ramo, trecho, tamanho e extensão; regras de uma
   extensão; próxima rodada). Registry e diretórios pedem endereço estável,
   (liberados.com.br, desde 16/09/2026).

### Fora da rodada

Nome que termina a rodada com zero candidato cai no pool livre e qualquer um
registra na hora ([`processo-de-liberacao.md`](processo-de-liberacao.md)).
Entre rodadas, as mesmas páginas mudariam de "sem candidato, candidate-se
até X" para "livre agora, registre direto", e o site já tem o cartão Livres
e o texto da fase `entre` em `app.js`. Quanto do "sem candidato" vira livre
de fato só se mede no desfecho de 16/09/2026 20:30 UTC; a versão entre
rodadas espera esse número. Se o status 5 se confirmar (A9), dá também para
antecipar a lista seguinte.

O que se busca no Google o ano todo, e por que a ficha "quando esse domínio
volta?" serve fora da rodada: [`perguntas-do-publico.md`](perguntas-do-publico.md),
seção de 13/09/2026.

## Fontes

1. platform.claude.com/docs/en/agents-and-tools/tool-use/web-fetch-tool
2. gend.co/blog/openai-ai-agent-link-safety (original openai.com/index/ai-agent-link-safety/ bloqueou)
3. ai.google.dev/gemini-api/docs/url-context
4. registro.br/dominio/lista-processo-liberacao.txt
5. registro.nic.br/dominio/lista-competicao.txt
6. expireddomains.net/tld/br/
7. dualmarcas.com.br/dominios-em-processo-de-liberacao/
8. github.com/yvesmariano/registro-br-mcp
9. apify.com/cloway/domain-checker-br/api/mcp
10. data.iana.org/rdap/dns.json
13. help.openai.com/en/articles/8554407-gpts-in-chatgpt
14. support.claude.com/en/articles/11175166-get-started-with-custom-connectors-using-remote-mcp
16. docs.perplexity.ai/guides/bots
17. perplexity.ai/help-center/en/articles/13915507-adding-custom-remote-connectors
18. developers.google.com/search/docs/appearance/ai-features
19. developers.google.com/search/docs/fundamentals/ai-optimization-guide
20. ahrefs.com/blog/llmstxt-study/
21. searchenginejournal.com/llms-txt-shows-no-clear-effect-on-ai-citations-based-on-300k-domains/561542/
22. vercel.com/docs/mcp/deploy-mcp-servers-to-vercel
23. github.com/vercel/mcp-handler
24. modelcontextprotocol.io/specification/2026-07-28/changelog
25. dev.to/surendergupta/building-a-stateless-python-mcp-server-with-fastapi-and-fastmcp-1c9g
26. modelcontextprotocol.io/registry/remote-servers
27. modelcontextprotocol.io/registry/quickstart
28. smithery.ai/docs/build
29. developers.openai.com/api/docs/guides/developer-mode
31. agentskills.io/home
32. code.claude.com/docs/en/plugin-marketplaces
33. support.claude.com/en/articles/12512180-use-skills-in-claude
34. platform.claude.com/docs/en/agents-and-tools/agent-skills/overview
35. vercel.com/changelog/introducing-skills-the-open-agent-skills-ecosystem
36. learn.chatgpt.com/docs/build-skills
37. support.claude.com/en/articles/12111783-create-and-edit-files-with-claude
38. learn.chatgpt.com/docs/agent-approvals-security
39. vercel.com/docs/limits/fair-use-guidelines
40. vercel.com/docs/plans/hobby
41. developers.google.com/search/docs/essentials/spam-policies
42. developers.google.com/search/docs/fundamentals/using-gen-ai-content
