# Processo de liberação

Todo mês o Registro.br devolve ao público os domínios `.br` que saíram do ar:
não renovados, cancelados pelo titular ou removidos por irregularidade
cadastral. Esses nomes não voltam direto para o pool livre — eles passam por
uma **rodada de liberação** de 7 dias.

## A regra que mais gera confusão

**Não é ordem de chegada.** Quem se candidata no primeiro minuto e quem se
candidata no último minuto têm exatamente o mesmo peso. O número do ticket
não desempata nada. Não adianta ficar acordado até as 15h em ponto.

## Os três finais possíveis

No fim da rodada, cada domínio termina de uma destas três formas:

| Candidatos | Resultado |
|---|---|
| zero | cai no pool livre — qualquer pessoa registra normalmente |
| **um** | esse candidato leva o domínio pagando a anuidade normal (R$ 40) |
| dois ou mais | ninguém leva: o nome **trava** e volta na rodada seguinte |

O caso do meio é o objetivo do garimpo. Um domínio bom que ninguém mais
notou custa uma anuidade comum.

## Ticket travado

Se o nome travou, **todos os tickets dele são cancelados**. O e-mail de
resultado diz que "todos os pedidos de registro para o domínio [...] foram
cancelados, pois houve mais de um concorrente para o mesmo nome durante o
processo de liberação", e o painel mostra o ticket como "Cancelado no
processo de liberação por concorrência". O nome fica aguardando a rodada
seguinte, e quem ainda o quiser precisa se candidatar de novo.

Até 12/09/2026 este doc dizia o contrário (ticket válido para a rodada
seguinte, vaga presa nele), sem fonte. As duas fontes que corrigem são
públicas e independentes: o texto do e-mail citado no Reddit (~03/2026) e
uma reclamação no Reclame Aqui (17/09/2025). Limitação S12.

Consequência para o limite: a página de regras do Registro.br define o
limite como "3 a 200 tickets pendentes", e um ticket cancelado não é
pendente, então a vaga volta quando a rodada é processada. Conferido no
painel em 16/09/2026: tickets de one.com.br e peca.com.br viraram
"Inativo" (ver abaixo); o limite em si não aparece no painel — confirmar na
primeira candidatura de outubro que ainda cabem 3.

### O que se vê logo depois do fechamento (16/09/2026)

- **15h02:** o e-mail de nome travado chega a cada candidato, com os
  "números dos tickets concorrentes ao seu" (120 na one.com.br). No
  painel, o ticket vira "Inativo", motivo "Cancelado no processo de
  liberação por concorrência", e vai para "Tickets antigos".
- **15h15:** o `avail` responde `status 5` para o nome travado; o RDAP
  responde 200 com objeto vazio e `Nicbr-Resource: release-process-waiting`.
  Os tickets somem de `publicIds`, mas `?ticket=` ainda responde.
- **Leilão:** nada muda no `avail` (`status 9`, `ends-at` ainda no fim da
  rodada); o RDAP passa a `competitive-release-process-closed`. Fim
  previsto às 15h do dia seguinte, empurrado pelas prorrogações de 10 min
  (`processo-competitivo.md`); um leilão de rodada anterior pode seguir
  aberto por meses (L5).

Limitação S16.

Nomes óbvios (palavras curtas, termos comerciais conhecidos) tendem a travar
mês após mês, porque sempre aparece mais de um interessado. Depois de
acumular rodadas travadas, o domínio migra para o
[processo competitivo](processo-competitivo.md).

## Limite de candidaturas

Cada titular tem um limite de candidaturas simultâneas, de **3 a 200**,
calculado pelo Registro.br conforme o número de domínios já registrados e o
histórico de pagamentos. Conta nova começa perto de 3.

Esse limite é a restrição central da estratégia: com 3 candidaturas, gastar
todas em nomes óbvios significa ficar travado por meses sem levar nada. Veja
[estratégia](estrategia.md).

> **Não existe cancelar candidatura** (conferido 09/09/2026, nem no painel
> nem na documentação): a vaga só volta quando a rodada resolve o nome, seja
> travando, seja atribuindo.

## Cadastro

Os dados do titular precisam ser reais e conferem com CPF/CNPJ. Divergência
cadastral pode gerar penalidade e é uma das causas de remoção que alimenta
justamente essas listas.

## Onde ver a lista

- Página oficial: <https://registro.br/dominio/processo-de-liberacao/>
- Arquivo bruto: <https://registro.br/dominio/lista-processo-liberacao.txt>

O arquivo vem em ISO-8859-1 e passa de 100 mil nomes. Use
[`baixar_listas.sh`](../baixar_listas.sh), que já converte para UTF-8.


## O candidato invisível

Esta é a limitação mais importante de qualquer ferramenta construída sobre o
endpoint de disponibilidade, e está **documentada pelo próprio Registro.br**:

> "A interface de verificação de disponibilidade de domínios somente informará
> que existem tickets para um domínio em processo de liberação caso este
> possua **mais de um candidato**. Ou seja, se o domínio exemplo.com.br
> possuir apenas a empresa Exemplo Ltda. como candidata, uma consulta a
> exemplo.com.br não informará que já existe um ticket emitido para o mesmo."

Consequência prática: quando a ferramenta mostra **0 candidatos**, o número
real é **zero ou um**. Não há como separar os dois casos enquanto a rodada
está aberta.

Isso importa porque a assimetria é cruel:

- se havia mesmo 0 e você se candidata, você leva por R$ 40;
- se já havia 1 e você se candidata, vocês viram 2 e **ninguém leva**.

Ou seja, candidatar-se a um nome com candidato oculto não só falha: também
tira o domínio de quem já estava lá. A lista de "sem competição" é um funil de
atenção, não uma lista de vitórias garantidas.

Os dados batem com a regra. Em 1.657 domínios verificados em 09/09/2026 não
apareceu **nenhum** com exatamente 1 candidato, enquanto dezenas apareciam com
exatamente 2 — numa distribuição natural a contagem em 1 seria maior que a
contagem em 2. E ao reverificar os elegíveis, nomes pularam de `0` direto para
`2`, sem nunca passar por `1`.

### Como medir depois que a rodada fecha

O desfecho denuncia o que era:

| Situação real | Desfecho | Status depois |
|---|---|---|
| tinha mesmo 0 candidatos | volta ao espaço de nomes livres | `LIVRE` |
| tinha 1 candidato oculto | é atribuído a ele | `REGISTRADO` |
| tinha 2 ou mais | trava ou vai a leilão | `AGUARDANDO_LIBERACAO` (status 5) ou `COMPETITIVO` |

`desfecho.py` faz essa comparação a partir de um instantâneo anterior ao
fechamento, e não custa candidatura nenhuma.

**Medido em 16/09/2026** (run 35149065140, 17h52 a 18h48, amostra num CSV
local, fora do repositório público): amostra de 1.359 dos 15.736 nomes com 0
visíveis na última leitura (de 10/09, 22h55), até 450 por faixa de nota.
Ponderado: 93,7% livres, 4,1% registrados (candidato escondido ou chegado
depois da leitura), 2,2% travados, 0,05% livres com pedido novo. Taxa de
escondido entre os resolvidos por nota: abaixo de 50, 3% (14/445); 50 a 64,
9% (37/416); 65 a 79, 12% (49/405); 80+, 4 de 8. No site:
`/insights/o-candidato-que-nao-aparece/`.

## Os tickets são um contador global (medido em 12/09/2026)

O número do ticket é sequencial e único para o Registro.br inteiro, não por
nome: one.com.br e vacina.com.br tinham tickets emitidos poucos minutos
depois da abertura da rodada de 09/09 (números sintéticos aqui, 90000001 e
90000190 — os reais identificam candidatos de verdade, e `?ticket=` ainda
responde depois da rodada, S15); em 12/09 de madrugada o contador já
estava em 90021244 (o número sintético preserva a diferença real:
~21.200 tickets em três dias).

**Não é contador de candidaturas.** A especificação EPP do Registro.br
(mapeamento `brdomain`, seção 2.1) define o ticket como o identificador
único e sequencial de um pedido de registro .br, e a resposta de todo
`domain:create` traz obrigatoriamente `brdomain:creData` com o
`ticketNumber` (seção 3.2.1); o ticket depois "é convertido" em domínio. A
política EPP ainda tem "Ticket created with pendings" para o registro comum.
Então a mesma sequência numera candidatura da liberação e todo registro
comum. Em 12/09/2026 o contador tinha
andado 24.785 tickets desde o primeiro visto na rodada, contra 1.187 tickets
visíveis nos 15.167 nomes conferidos: a maior parte é registro comum. O
maior ticket é um **teto** para as candidaturas e um termômetro do .br
inteiro; a separação por tipo não é pública (limitação A11).

Duas leituras práticas, que a varredura passou a fazer
(`garimpo/dominio/ritmo.py`):

- **a curva do contador**, um ponto a cada ticket maior visto. Se ela
  empinar no último dia da rodada, a diferença é a corrida pelos nomes
  liberados;
- **quando os concorrentes de um nome chegaram**: o menor ticket é o
  primeiro candidato, o maior visível é o último. Nome cujos dois candidatos
  chegaram na primeira hora e nome que ganhou três no último dia são
  histórias diferentes.

Cuidado com o corte em 10 (limitação A3): o maior ticket visível pode não
ser o maior de verdade. E a estimativa de horário é por cima: o ticket pode
ter sido emitido bem antes de a varredura vê-lo.

## O que a especificação EPP conta (lido em 12/09/2026)

O Registro.br publica a extensão EPP do `.br` como draft IETF
(`draft-neves-epp-brdomain-05`, 2011) e uma especificação de política
(`en-policy-restrictions-espec.txt`, arquivo de 08/2026 com texto de
08/2021), ambos em `ftp.registro.br/pub/libepp-nicbr/`. É o processo de
liberação visto por quem opera um provedor, e completa o que a consulta
pública não explica. Detalhe das fontes em
[`fontes-oficiais-registrobr.md`](fontes-oficiais-registrobr.md).

- **A definição.** "Quando um nome é apagado ele não volta ao espaço livre.
  Precisa passar por um *Release Process*, que oferece esses nomes ao
  público por um período fixo. Dependendo do número de interessados e da
  demonstração de direitos específicos, ao fim do processo o nome pode ser
  atribuído a um interessado, voltar ao espaço livre, ou voltar a uma lista
  para ser oferecido de novo num processo futuro." São os três finais da
  tabela acima, em texto oficial.
- **Existe uma fila antes da rodada.** O `status: 5` do ISAVAIL,
  "aguardando processo de liberação", e a mensagem de erro "Domain name
  waiting for next release process" descrevem um nome apagado que ainda não
  foi oferecido. É o estado de um nome travado entre rodadas (conferido em
  16/09/2026, S16).
- **Até 2017, depois de 6 processos o nome virava reservado.** Regra
  histórica (Res. CGI.br 2008/008, art. 11º), com mensagem de erro do
  `domain:create` que ainda existe na especificação EPP: "Domain name is
  reserved because it was already offered in more than 6 release
  processes". A Res. 2017/031 revogou essa reserva, pôs o leilão no lugar
  (o processo competitivo desta página) e devolveu à liberação os nomes já
  reservados por ela. Na prática confere: `fao.org.br` passou 57 rodadas
  seguidas na lista sem virar reservado (S13).
- **Outras reservas que a consulta pública não nomeia**: "reserved for
  being a known brand", "reserved by court order", "reserved by the
  Brazilian Internet Steering Committee", "is a dirty word". Um `status: 3`
  pode ser qualquer um; a lista de marcas conhecidas do registro não é
  pública.
- **`flag1` ainda existe no EPP, mas sem efeito documentado.** O
  `releaseProcessFlags` tem três flags cuja semântica "é anunciada antes de
  cada processo"; a especificação de política diz que só `flag1` é aceita e
  que ela "indica que a entidade é detentora de marca registrada do nome de
  domínio". A flag vem da regra de 2008, que dava preferência ao dono da
  marca na liberação (art. 10º, IV e VI c); a Res. 2017/031 tirou essa
  preferência ao reescrever o art. 10º, e a página oficial do processo não
  diz que a marcação tenha efeito hoje. Só um provedor de serviços
  credenciado no EPP enxerga o campo — não um provedor de hospedagem.
- **Cada ticket tem um pendente `releaseProc`** com status `waiting`,
  `resolved` ou `denied` e um prazo (`limit`). É o que o painel mostra
  como "registro pendente".
- **Ticket vê os concorrentes.** A resposta ao provedor traz
  `ticketNumberConc`, os números dos outros tickets do mesmo nome. É o
  mesmo dado que o `avail` mostra como `tickets`, com o mesmo corte
  documentado de "só quando há mais de um".
- **Limite por organização, no protocolo**: "Limit of release process
  active tickets exceeded for organization" e "Limit of active tickets
  exceeded for organization". É o limite de 3 a 200 visto do outro lado.
- **`www.` não participa**: "It's not permitted to register names of the
  release process with the 'www' prefix", e um `www.nome` só pode ser do
  dono de `nome`.
- **Apagar domínio é raro e limitado**: só nos 5 primeiros dias, só pelo
  provedor que criou, e no máximo 3% dos criados nos últimos 5 dias. Isso
  explica por que a lista de liberação é quase toda de não renovação, e
  não de arrependimento.

## Calendário

A rodada é mensal, começa na segunda quarta-feira e dura 7 dias. A lista de
domínios participantes sai **2 dias antes** do início.

Próximas rodadas anunciadas: **14/10/2026** e **11/11/2026**.
