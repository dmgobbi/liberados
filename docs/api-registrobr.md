# O endpoint de disponibilidade do Registro.br

Não existe API HTTP documentada para consultar o processo de liberação. O
que existe é o endpoint que a **própria caixa de busca do site** usa, e ele
devolve JSON:

```
GET https://registro.br/v2/ajax/avail/raw/<dominio>
```

Não é documentado nem versionado como contrato público: pode mudar sem aviso,
e o próprio Registro.br disse isso (issue #98 do `whmcs-registrobr-epp`,
26/07/2025: o avail "corre risco de alteração de localização e
comportamento"). O [`test_scripts.py`](../test_scripts.py) guarda respostas
reais para que uma mudança de formato quebre os testes em vez de passar
despercebida.

O que este endpoint **é**, descoberto em 12/09/2026: o "proxy no site" de um
serviço oficial e documentado, o **ISAVAIL** (UDP, porta 43), descrito
[abaixo](#isavail-o-serviço-oficial-por-trás-do-endpoint). Toda a
semântica do JSON vem de lá. O levantamento das fontes oficiais está em
[`fontes-oficiais-registrobr.md`](fontes-oficiais-registrobr.md).

## Respostas reais

Domínio livre para registro imediato:

```json
{"status": 0, "fqdn": "exemplolivre.com.br", "exempt": false}
```

Domínio registrado e no ar:

```json
{"status": 2, "fqdn": "google.com.br", "publication-status": "published",
 "expires-at": "2027-05-18T00:00:00-03:00",
 "hosts": ["ns1.google.com", "ns2.google.com"]}
```

Em liberação, **sem nenhum candidato** — este é o alvo do garimpo:

```json
{"status": 6, "fqdn": "anabolizantes.com.br",
 "begins-at": "2026-09-09T15:00:00-03:00",
 "ends-at": "2026-09-16T15:00:00-03:00"}
```

Em liberação, **já com candidatos** (tende a travar):

```json
{"status": 7, "fqdn": "medidas.com.br",
 "tickets": [30001101, 30001102],
 "begins-at": "2026-09-09T15:00:00-03:00",
 "ends-at": "2026-09-16T15:00:00-03:00"}
```

Em processo competitivo (leilão):

```json
{"status": 9, "fqdn": "combustiveis.com.br",
 "tickets": [30002201, 30002202],
 "ends-at": "2026-09-16T15:00:00-03:00",
 "accepting-new-tickets-until": "2026-09-16T15:00:00-03:00"}
```

Bloqueado por excesso de consultas — **cuidado com este**:

```json
{"status": 8, "fqdn": "", "fqdnace": "", "exempt": false,
 "reasons": ["Taxa máxima de consultas excedida"]}
```

## A armadilha do status 8

O bloqueio por excesso de consultas volta com **HTTP 200**, não 429, e com
`status: 8` no corpo. Na tabela oficial, 8 é simplesmente "erro". Mas quem
lê o status como bitmask (como este projeto leu até 11/09/2026) vê em `0x8`
o bit de processo competitivo, e um mapeamento ingênuo transforma **toda
resposta bloqueada num falso "domínio em leilão"**.

Foi exatamente o que aconteceu em 09/09/2026: 370 domínios foram rotulados
como leilão quando na verdade eram respostas de bloqueio. O sintoma que
denuncia é `COMPETITIVO` com zero candidatos e sem `ends-at` — leilão de
verdade sempre traz os dois.

Como distinguir, e nesta ordem:

1. se vier o campo `reasons`, é resposta de erro, **não** classifique pelo
   status;
2. resposta válida sempre traz `fqdn` preenchido;
3. só então leia o status pela tabela.

É o que `situacao.classificar()` faz (`garimpo/dominio/situacao.py`), e há
teste para isso em [`test_scripts.py`](../test_scripts.py).

## O campo `status` é uma enumeração (não um bitmask)

Até 11/09/2026 este documento dizia "bitmask, confirmado por sondagem":
`0x1` tickets, `0x2` existe, `0x4` liberação, `0x8` competitivo. Os valores
observados (0, 2, 3, 6, 7, 8, 9) batiam com essa leitura, e foi coincidência.
Em 12/09/2026 a tabela oficial apareceu em `Protocolo-ISAVAIL.txt`
(`ftp.registro.br/pub/isavail/`):

| `status` | Oficial | Leitura neste projeto |
|---|---|---|
| `0` | disponível | `LIVRE` |
| `1` | disponível, com tickets concorrentes | `LIVRE_COM_TICKET`: fora da rodada, mas alguém tem pedido pendente. Visto em cagada.com.br (16/09/2026, ~17h); concluído, o RDAP perde o ticket (R13) |
| `2` | registrado | `REGISTRADO` |
| `3` | indisponível (vem o motivo) | `INDISPONIVEL`: equivalente já registrado, reserva, transição EDU.BR... ver abaixo |
| `4` | consulta inválida | `ERRO` |
| `5` | **aguardando processo de liberação** | `AGUARDANDO_LIBERACAO`: apagado, mas ainda não oferecido. É o que um nome travado responde entre rodadas (conferido em 16/09/2026, one/peca/liberado.com.br) |
| `6` | em liberação | `LIBERACAO_LIVRE` (zero **ou um** candidato) |
| `7` | em liberação, com tickets | `LIBERACAO_DISPUTADA` |
| `8` | erro | `LIMITADO` quando é "taxa máxima de consultas excedida", senão `ERRO` |
| `9` | processo competitivo | `COMPETITIVO` |

Por que a diferença importa: lido como bits, o `5` é `4|1`, "em liberação
com tickets", e como não vem array `tickets`, cairia em "em liberação, sem
candidato". Ou seja, um nome que **nem está na rodada** apareceria como
joia. É o mesmo tipo de erro das 28 joias falsas de 10/09/2026, só que
esperando para acontecer. `dominio/situacao.py` mapeia os dez valores um a
um desde 12/09/2026.

### `status: 3` e a regra de equivalência

Sondado em 10/09/2026. O `status: 3` não traz `tickets`: vem com `reasons` e
significa que o nome **colide com um equivalente já registrado por outro
titular**.

```
café.com.br        -> status 3, fqdnace xn--caf-dma.com.br,
                      reasons ["Domínio já registrado sob sintaxe similar"]
cafe.com.br        -> status 2, registrado, expira 02/06/2027
casa-verde.com.br  -> status 3, "Domínio já registrado sob sintaxe similar"
casaverde.com.br   -> status 2, registrado
```

A regra é oficial: para efeito de comparação o Registro.br **converte
acentos e cedilha para as versões sem acento e "c", e descarta os hífens**.
`aventura-esportes` e `aventuraesportes` são o mesmo nome, e só coexistem se
forem do mesmo dono.

Duas consequências práticas:

1. **Hífen e acento não são inventário.** Em `.com`, `casa-verde.com` e
   `casaverde.com` são dois ativos independentes. Em `.br` são um só. A
   varredura confirma: nos **125.457** nomes da rodada de setembro/2026 há
   **zero** rótulos com hífen — não porque brasileiro não use hífen, mas
   porque o hífen não cria nome novo.
2. `status: 3` também aparece com outros motivos (`açaí.com.br` responde
   `"Domínio reservado para a transição EDU.BR"`). Trate o `3` como
   "bloqueado, leia `reasons`", não como um motivo único.

## Por que isso importa

O array `tickets` é a informação mais valiosa do endpoint: ele diz **quantas
candidaturas já existem antes de você gastar a sua**.

Com uma ressalva documentada pelo Registro.br: o array **só aparece quando há
mais de um candidato**. Um domínio com exatamente 1 candidato responde igual a
um com 0. Ver [processo-de-liberacao.md](processo-de-liberacao.md#o-candidato-invisível). Com um limite de 3
candidaturas, saber que um nome já tem 10 interessados (e portanto vai travar
com certeza) vale mais do que qualquer outra coisa nesta lista.

## As três listas da rodada

São três arquivos, e a diferença entre o segundo e o terceiro é sutil o
bastante para ter custado um erro de leitura neste projeto:

| Arquivo | O que é |
|---|---|
| `lista-processo-liberacao.txt` | todos os nomes da rodada (~125 mil) |
| `lista-processo-competitivo.txt` | os **elegíveis** ao leilão, por já terem acumulado rodadas travadas. A maioria está na rodada normal, muitos sem candidato nenhum |
| `lista-competicao.txt` | os que estão **com leilão acontecendo agora** |

Confundir o segundo com o terceiro faz parecer que centenas de nomes estão em
leilão quando estão apenas habilitados a ir.

A terceira lista serve de conferência independente do status. Em 09/09/2026 a
classificação por `status` concordou com ela em 58 de 59 nomes, sem nenhum
falso positivo — o que resta era um nome ainda não verificado.

Todos vêm em **ISO-8859-1**.

**Nome de arquivo ausente não é erro HTTP: é HTML.** Pedir um nome que não
existe devolve `200`, `Content-Type: text/html`, e o corpo é a página do
site (conferido com HEAD em 18/09/2026, num nome inventado: 4.636 bytes,
começando em `<!doctype html>`). Não conferido: se o mesmo acontece na URL
real no instante em que a lista do mês troca (o risco do dia 12/10).
`garimpo/adaptadores/registrobr.py` (`validar_lista`) recusa um corpo que
comece com `<` ou que não tenha, nas 6 primeiras linhas, o cabeçalho
`# Processo de liberação no período de ...` — em `lista-competicao.txt` ele
não é a primeira linha, "# Arquivo gerado em ..." é — e o rodapé `# Fim do
arquivo` de toda lista oficial, sem exigir Content-Type (catálogo L6 em
[`limitacoes-registrobr.md`](limitacoes-registrobr.md)). Lista de liberação
ou de elegíveis inválida para a execução; a de leilões (`lista-competicao.txt`)
mantém a leitura anterior quando o instantâneo publicado é da mesma rodada, e
só segue sem leilão nenhum quando não há instantâneo aproveitável — nunca
zera a coluna `em_leilao` de quem já estava confirmado.

## O array `tickets` para em 10

Medido em 11/09/2026: `avail/raw` devolve no máximo 10 tickets, enquanto o
RDAP (`publicIds`) lista todos. one.com.br: 10 contra 67; vacina.com.br: 10
contra 42; peca.com.br e evangeliza.com.br: 6 e 6 nos dois. Contagem acima
de 10 só pelo RDAP.

## ISAVAIL: o serviço oficial por trás do endpoint

Descoberto em 12/09/2026 em `ftp.registro.br/pub/isavail/` (versão 0.10,
de 01/2025). É um protocolo de texto sobre **UDP, porta 43, em
`avail.registro.br`**, com especificação (`Protocolo-ISAVAIL.txt`) e
clientes-exemplo em Python, Perl, PHP, Java, C++ e Ruby. O README oficial
lista três formas de uso: "o proxy no site do Registro.br" (o endpoint
acima), os clientes-exemplo, ou "implementação própria".

```
pergunta   2 <cookie> 1 <qid> vacina.com.br 0
resposta   % Copyright Nic.br
           ST 9 727976103
           vacina.com.br
           2026-09-26 15:00:00|2026-09-26 15:00:00|2026-09-26 15:00:00
           90000001|90000002|...|90000010
```

(tickets sintéticos: os reais identificam candidatos de verdade, e
`?ticket=` ainda responde depois da rodada — S15 em
[`limitacoes-registrobr.md`](limitacoes-registrobr.md))

Sem cookie válido a resposta é `CK <cookie> <qid>`; guarda-se o cookie e
repete-se. O último campo (`0`, "não sugerir outras extensões") é
obrigatório na versão 1 em diante: sem ele, `ST 4 consulta inválida`.

O que confere com o endpoint web, medido nos mesmos nomes no mesmo minuto:
status, fqdn (com o ACE para nomes acentuados), tickets (**também cortados
em 10**, é a especificação: `ticket1|...|ticket10`), motivo do 3 ("Domínio
já registrado sob sintaxe similar" para café.com.br).

O que **não** confere: as datas. Para a rodada de 09/09 a 16/09, o ISAVAIL
devolveu `2026-09-26 15:00:00` nos três campos de vacina.com.br e nos dois
de one.com.br, enquanto o endpoint web devolvia 09/09 e 16/09. O adaptador
guarda as datas para inspeção e não as usa.

Uso neste projeto: `garimpo/adaptadores/isavail.py` traduz a resposta para
a mesma forma do JSON web, então `situacao.classificar()` serve para os
dois canais; `python3 isavail.py <nome>` consulta e mostra o pacote. **Não
entra na varredura**: o limite de consultas não é publicado, e medi-lo é
bater nele. É a contingência para o dia em que o endpoint web mudar.

## A extensão NIC.br do RDAP

O RDAP do `.br` implementa os RFCs 7480 a 7484 e uma extensão própria,
documentada em `ftp.registro.br/pub/doc/br-rdap-extensions-02.txt` e
tipada em `github.com/registrobr/rdap` (`protocol/`). Conferido em
12/09/2026 contra respostas reais. O que ela acrescenta e este projeto lê:

- **Por servidor de DNS, a conferência do próprio registro.** Cada item de
  `nameservers` traz `events` com `delegation check` (status `ns aa`,
  `ns timeout`, `ns noaa`, `ns udn`, `ns uh`, `ns fail`, `ns query
  refused`, `ns connection refused`, `ns cname`, `ns soaVersion`...) e
  `last correct delegation check`, a data da última resposta com
  autoridade. pneus.com.br: `a.auto.dns.br` e `b.auto.dns.br` com `ns aa`
  em 04/09/2026. Para um nome que não resolve, a data do último `ok` é o
  "desde quando", sem Internet Archive. `rdap.Ficha.delegacao_quebrada` e
  `delegacao_ok_em`.
- **`secureDNS.dsData[].events`** faz o mesmo para DNSSEC (`ds ok`,
  `ds nosig`, `ds expiredsig`...).
- **Status só do NIC.br**: `nicbr waiting activation`, `nicbr waiting
  inactivation`, `nicbr inactive court order`, `nicbr inactive CG`. Os dois
  últimos são nome tirado do ar por ordem judicial ou pelo CGI.br
  (`Ficha.fora_do_ar_por_decisao`).
- **`nicbr_arbitration`**: o titular aceitou a política de arbitragem (o
  SACI-Adm). `true` em pneus.com.br e meridianlab.com.br; ausente em
  google.com.br, provavelmente por ser anterior à política (não conferido).
- **Na entidade** (`GET https://rdap.registro.br/entity/<cnpj sem
  pontuação>`): `nicbr_domainCount`, quantos domínios o titular tem (a
  titular de pneus.com.br: 166), `nicbr_inetCount`, `nicbr_autnumCount`, e
  `legalRepresentative`, o **nome de uma pessoa**. `rdap.interpretar_entidade`
  devolve só a contagem; `historias.py --titular` consulta só para CNPJ.
- **O registro de um ticket** (`domain/<nome>?ticket=<n>`; o caminho
  `/ticket/<n>` da biblioteca oficial responde 403), conferido em
  12/09/2026: objeto `domain` com handle `<nome>#<ticket>`, evento
  `registration` com o instante exato de emissão do ticket, um link
  `rel: archives` por concorrente (todos, sem corte), e a entidade do
  candidato (nome, documento mascarado, endereço; e-mail no contato
  técnico). `web/disputa.js` lê no navegador do visitante; uma ferramenta
  local do dono, fora do repositório público, repete a leitura em lote.
  Endereço e e-mail nunca são exibidos.
- **Limite sinalizado por cabeçalho**: `access-control-expose-headers`
  inclui `Nicbr-Rate-Limit-Exceeded`. Quem consulta do navegador deve
  parar ao vê-lo.

## O painel autenticado (leilão ao vivo)

Lido nos bundles públicos do painel. Detalhes e consequências em
[`leilao-ao-vivo.md`](leilao-ao-vivo.md).

- `wss://registro.br/v2/ws/liveauction`: o servidor empurra `Auctions`, uma
  linha por **ticket do usuário logado**, com `MaxPlacedValue`,
  `NextValidBidValue`, `NextValidIncrement`, `RangeLimit`, `EndsAt`,
  `CandidateStatus` e `HolderDocument` (CPF/CNPJ, nunca sair da aba).
- Origem conferida no handshake: `Origin` estranho recebe 403.
- `PUT /v2/ajax/auction/bid/<fqdn>` envia oferta. Vinculante; nunca chamar.
- Não há endpoint que liste todos os leilões com preço.

## Limite de requisições

O Registro.br limita consultas por IP. Regras de convivência:

- **delay mínimo de 2 segundos** entre consultas (padrão do script);
- filtre a lista **antes** — nunca rode os 125 mil nomes da rodada;
- **uma conexão só**, nada de paralelizar;
- em bloqueio, o script recua 120 segundos e reconsulta o nome uma vez;
  se continuar bloqueado, a varredura para ali (e 10 erros seguidos também
  a param), e a próxima execução retoma pela fila.

Medições de 09/09/2026, com o detector de bloqueio já correto:

| Ritmo | Taxa | Resultado |
|---|---|---|
| 2,0s, uma conexão | 0,46 req/s | limpo |
| 1,0s, uma conexão | 0,87 req/s | começam a aparecer falhas |
| 1,0s, três conexões | 2,7 req/s | **bloqueia** |

A 2,7 req/s o `registro.br` passou a responder "Taxa máxima de consultas
excedida" **para o navegador do próprio usuário**, não só para o script. O
limite é por IP e derruba a máquina inteira. Não vale acelerar: a lista muda
uma vez por mês, então varrer 15 mil nomes numa noite está de bom tamanho.

Isto aqui é uma ferramenta de pesquisa pessoal em cima de um endpoint público.
Trate a infraestrutura de quem hospeda o `.br` com respeito: se você for
bloqueado por excesso de requisições, o problema foi seu.
