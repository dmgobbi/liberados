# Rumo do Liberados

Propósito, meta, lema, público e princípios num só lugar, para toda sessão
partir do mesmo norte e ter uma régua para dizer não. Este documento pode
ir ao repositório público: nenhuma anotação pessoal do dono mora aqui.

## Propósito

O Registro.br publica, todo mês, a lista dos domínios `.br` que voltam ao
mercado no processo de liberação. A lista é pública, mas ilegível: um
arquivo com cerca de 120 mil domínios, a situação de cada nome se consulta
uma por uma, e as regras que decidem quem leva um domínio estão em
documentos técnicos. O **Liberados** existe para tornar isso legível, de
graça, sem cadastro.

## Meta

- **Lançamento**: o repositório público nasce novo, com histórico limpo e
  só com o núcleo (ver "O que é aberto e o que não é"). O dono quer a
  fronteira pronta antes de 12/10/2026; criar o repositório e a data de
  abri-lo são decisão dele.
- **Ser achado**: aparecer nos resultados do Google para quem busca sobre
  domínios `.br` liberados e ser citado por assistentes de IA (SEO e GEO) —
  o vácuo é o vocabulário genérico do ciclo de vida do domínio, que hoje só
  tem conteúdo sobre gTLD, e não sobre o `.br` (ver
  [`/ciclo-de-vida-do-dominio-br/`](../site_modelo/conteudo/ciclo-de-vida-do-dominio-br.html)).
- **Viralizar**: alguém abrir o Liberados, achar um fato que surpreende e
  mandar para um amigo, sem precisar explicar o processo antes.

Nenhuma dessas metas tem um número-alvo fechado; quando alguém propuser um,
ele entra aqui como proposta, não como decisão.

## Lema

**"Todo mês, domínio bom volta."** — proposto em revisão de produto de
18/09/2026; o dono delegou a escolha ao conselho das sessões em
19/09/2026. A ideia: um fato que surpreende, sem
número (que exigiria data e denominador, ver `AGENTS.md`) e sem prometer
velocidade — o que faz alguém tocar num card compartilhado.

O site já tem uma frase-tese, publicada em
[`/insights/o-que-fazer-com-isso/`](../site_modelo/conteudo/insights/o-que-fazer-com-isso.html):
"O nome bom não é comprado, é percebido." Ela continua como a tese central
do produto; o lema acima é o gancho para quem ainda não conhece o site.

## Definição

A frase que define o Liberados **não mora aqui**: a fonte da verdade é a
constante `DEFINICAO` em
[`garimpo/web/paginas.py`](../garimpo/web/paginas.py). Ela sai igual no
rodapé de toda página, no JSON-LD da organização e no `llms.txt` (regra em
`AGENTS.md`, "Para quem é cada aba": mudou o produto, muda a frase ali,
nunca em cópia solta).

Para referência, o texto lido em `paginas.py` em 18/09/2026:

> O Liberados mostra, de graça, quais domínios .br o Registro.br devolve ao
> mercado todo mês e quais ainda estão sem concorrente à vista.

Se este trecho e o `paginas.py` atual divergirem, **vale o `paginas.py`**,
nunca este documento. Há uma proposta de reescrita em avaliação (mesmo
achado do lema, acima): cobrir os três trabalhos do site — o que está livre
agora, o que está sem concorrente na rodada aberta e quando um nome com
dono pode voltar — e a cunha "sem cadastro" contra os concorrentes com
login. Enquanto o conselho não decidir, `paginas.py` manda.

## Público

Detalhado por aba em `AGENTS.md`, "Para quem é cada aba". Resumo: gente que
quer registrar um domínio `.br` — para o próprio negócio, o próprio nome ou
para garimpar — e não quer ler uma lista de cerca de 120 mil nomes nem
pagar para ver o que o Registro.br já publica de graça.

## Princípios

- **De graça e sem cadastro.** É a cunha contra qualquer concorrente que
  cobre ou pede login para mostrar o mesmo dado público.
- **O dado vem do Registro.br, lido de novo.** O Liberados não inventa
  status, não promete o que o Registro.br não garante e, quando algo é
  opinião (a nota de relevância), diz que é opinião.
- **Nenhum número sem data e denominador** (`AGENTS.md`, "Como escrever uma
  página do site"). Taxa calculada sobre nomes conferidos avisa que eles
  foram escolhidos pela nota.
- **Privacidade por desenho:** consulta que expõe alguém (quem disputa um
  nome, o dono do `.com`) roda no navegador de quem olha, nunca na
  varredura; nada fica guardado no servidor nem no git. Regras completas em
  `AGENTS.md`, "Regras que não se negociam".
- **Não fala em nome do Registro.br.** Sem vínculo com o Registro.br, o
  NIC.br ou o CGI.br; na dúvida, a regra oficial manda.

## O que o site não faz

- **Não vende domínio** nem recebe por indicação de nenhum: quem registra
  ou dá lance faz isso direto no Registro.br, e o Liberados não intermedeia
  nada.
- **Não tem anúncio nem link de afiliado.**
- **Não vende dado.** Vender é fechado pelo contrato do titular e pelo
  aviso do RDAP.
- **Não pede login nem senha** do Registro.br, e não se inscreve nem dá
  lance por ninguém — isso é feito na própria conta de quem usa.

## Para onde vamos

- **Até 07/10/2026:** construção livre, com teste verde antes de cada
  commit (`python3 -m pytest test_scripts.py -q`). É a janela para fechar
  pendências de conteúdo, SEO/GEO e correções encontradas em revisão.
- **De 08/10 a 22/10/2026 (Brasília):** congelamento da rodada
  (`docs/operacao.md`, seção 3). A lista de outubro sai em 12/10; a rodada
  vai de 14/10 15h a 21/10 15h. Nessa janela, só hotfix com teste nos
  arquivos que decidem a fase e a varredura (lista em `docs/operacao.md`);
  conteúdo novo (`site_modelo/conteudo/`) segue solto, com teste verde.
- **Depois de 21/10/2026:** desfecho da rodada (`gh workflow run Garimpo
  --ref main -f modo=desfecho`, ~3 h depois do fechamento) e revisão das
  métricas em 22/10. O lançamento do repositório público (ver "Meta") é
  decisão do dono, não uma data automática deste checklist.

## O que é aberto e o que não é (open core)

Decisão do dono de 19/09/2026 (chegou pela sessão 401dc167, que falava
com ele): **o repositório público é só o núcleo**, no modelo do VS Code,
do Gumroad e do algoritmo do X. Ninguém deve conseguir clonar o site
inteiro copiando o repositório público.

**Fronteira decidida em 25/09/2026** (o dono pediu o público pronto para o
anúncio no LinkedIn de 26/09, "só a aplicação principal"):

- **Aberto**, em `github.com/dmgobbi/liberados`, MIT: o motor (`garimpo/`
  inteiro, inclusive `garimpo/web/`, que monta o site), os scripts de
  entrada, a interface local (`app.py`, `web/`), a casca, o estilo, os
  scripts e as páginas de ferramenta do site (`site_modelo/` sem o
  conteúdo editorial), os workflows Garimpo e Testes, a suíte de testes e
  os `docs/` que descrevem o Registro.br (endpoint, limitações, fontes
  oficiais, processo) e o projeto (rumo, opções, IA e agentes).
- **Fechado**, só no repositório de trabalho: os insights e as páginas
  editoriais (perguntas, regras, glossário, ciclo de vida, comprar,
  onde registrar, quem é o dono, privacidade, extensões), as imagens deles
  (`og/`, `imagens/`, `letras/`), a pesquisa que os sustenta (critérios de
  valor, estratégia, marcas, histórico das rodadas, mercado, leilão ao
  vivo, Wayback, perguntas do público, `.com`), o estado da varredura e o
  histórico das listas (`site/dados.json`, `site/todos.json`,
  `docs/historico/`), a operação do dono (lançamento, operação, visitas,
  agenda) e tudo que é pessoal.
- A lista exata é `NAO_ATRAVESSA` em `sincronizar-publico.sh`, que continua
  sendo a lista do que NÃO atravessa: a proposta de inverter para "o que
  atravessa" foi descartada porque o núcleo é a maior parte dos arquivos e
  a lista curta é a do fechado. A fronteira é reversível numa linha: para
  fechar a casca do site também (`site_modelo/`, `garimpo/web/`), basta
  acrescentá-las e marcar os testes que as leem com `so_com(...)`.
- **O workflow Garimpo roda no público** (Actions sem limite de minutos em
  repositório público, cadência de hora em hora) e busca o fechado do
  privado na hora de montar o site, por uma deploy key (`CHAVE_PRIVADO`);
  o estado volta para o privado pelo mesmo caminho e o público nunca
  recebe commit do robô. O clone do público monta o site só com a
  ferramenta, sem artigos: é o que "não dá para clonar o site" quer dizer
  na prática, porque o que faz o Liberados ser o Liberados é o conteúdo.
- O site diz "código aberto" com o link do GitHub e dizendo o quê (Sobre e
  Perguntas): o aberto é o motor.

As demais perguntas da revisão de 18/09/2026 (lema, licença dos dados, a
skill, receita, divulgação, linha de base, proteção da `main`) o dono
delegou ao conselho das sessões, pela opção reversível e conservadora; a
decisão de cada uma entra nesta página quando for tomada. O que só o dono
pode clicar fica em `docs/operacao.md`, "Só o dono". Os minutos do
GitHub Actions não se pagam: com o Garimpo no repositório público eles
não têm limite, e o que sobrar no privado (testes, visitas, agenda) cabe
na cota do plano.

## Métricas

Cada painel foi ligado em 17/09/2026. Leituras já marcadas na agenda do
projeto: 01/10 (antes da rodada de outubro) e 22/10 (dia seguinte ao
fechamento dela):

| Painel | O que mede | Linha de base |
|---|---|---|
| Cloudflare AI Crawl Control | visitas de robôs de IA | 17/09/2026 (primeiro dia): 25 visitas — 20 Google, 2 OpenAI, 1 Anthropic, 1 Perplexity |
| Cloudflare Web Analytics | visitas de gente (só navegador) | ligado em 17/09/2026; primeira leitura marcada para 01/10 |
| Google Search Console | páginas indexadas, buscas | propriedade verificada em 17/09/2026; primeira leitura marcada para 01/10 |
| Bing Webmaster Tools, aba "AI Performance" | citações no Copilot | ligado em 17/09/2026; primeira leitura marcada para 01/10 |

Nenhum número aqui vale como meta: são só a origem e a data de partida.
Ferramenta local para ler o Cloudflare: `python3 visitas.py --pessoas`
(gente) ou sem a opção (por dia no servidor); precisa de credencial local,
descrita em `visitas.py --help`.
