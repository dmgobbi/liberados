# Processo competitivo (leilão)

Quando um domínio acumula rodadas de liberação travadas — sempre com dois ou
mais candidatos, nunca com um só — o Registro.br para de empurrar o nome para
o mês seguinte e resolve a disputa por dinheiro.

A regra oficial não dá número: fala em domínios "que já tenham participado de
**sucessivos** processos de liberação sem resolução". **Medido em 13/09/2026
(S13): três travas.** Nas listas guardadas pelo Internet Archive, 99,4% dos
10.807 elegíveis de jul/2019 a mai/2025 estavam nas três rodadas anteriores,
e só 1% nas quatro. Ou seja: travou em três rodadas seguidas, entra na quarta
como elegível. Detalhe em [`historico-das-rodadas.md`](historico-das-rodadas.md).

Nem todo nome é elegível: DPNs restritos ficam de fora, e os demais
simplesmente continuam retidos até a rodada seguinte.

## Como funciona

- **Começa com dois tickets.** Assim que dois candidatos são constatados no
  mesmo domínio elegível, o processo competitivo se abre.
- Dura **6 dias ou mais**, esticando para a data final cair em dia útil.
  Durante esse período **novos interessados ainda podem se candidatar** e
  fazer ofertas.
- O prazo para criar novos tickets fecha **um dia antes** do fim. Depois
  disso ainda há pelo menos **24h só para ofertas**, para quem já está dentro
  reagir a ser ultrapassado.
- Resolução por **ofertas financeiras sucessivas**: ganha a maior oferta.
- O valor **já inclui 1 ano de manutenção**. Depois disso, tabela normal:
  R$ 40 por 1 ano, R$ 76 por 2, e assim por diante, até 9 anos.

### Lance mínimo e incrementos

O menor lance possível é **R$ 50**. A partir daí vale a faixa da oferta
corrente, e o incremento mínimo muda com ela:

| Oferta atual a partir de | Até | Incremento mínimo |
|---|---|---|
| R$ 50 | R$ 1.000 | R$ 50 |
| R$ 1.000 | R$ 5.000 | R$ 100 |
| R$ 5.000 | R$ 10.000 | R$ 200 |
| R$ 10.000 | R$ 20.000 | R$ 500 |
| R$ 20.000 | R$ 50.000 | R$ 1.000 |
| R$ 50.000 | R$ 200.000 | R$ 5.000 |
| R$ 200.000 | R$ 500.000 | R$ 10.000 |
| R$ 500.000 | ilimitada | R$ 20.000 |

Exemplo do próprio Registro.br: se a oferta corrente é R$ 50, aceitam-se
ofertas entre R$ 100 e R$ 1.000.

O Registro.br pode **interromper** o processo de um domínio se identificar
padrão de ofertas sem intenção de serem honradas.

### Pagamento e a penalidade real

A oferta é **vinculante**, e paga-se exclusivamente por boleto ou Pix em até
**15 dias** após o fim do processo.

Não pagar gera **restrição de 6 meses** para participar de novos processos de
liberação. E a punição não fica só no titular que ofertou: alcança qualquer
código de usuário ou titular que o Registro.br consiga correlacionar por
característica técnica. Ou seja, não adianta trocar de ID.

## Duas armadilhas de operação

1. **O sistema não avisa quando você é ultrapassado.** Não existe e-mail de
   "você foi superado". O próprio Registro.br recomenda acompanhar nos
   10 minutos finais.
2. **O prazo se estende sozinho.** Oferta nos 10 minutos finais empurra o fim
   em mais 10 minutos, contados do encerramento anterior: lance às 14h57 com
   fim previsto para 15h leva o processo para 15h10. Se a prorrogação passar
   das 18h, o processo continua **no dia útil seguinte, às 15h**.

Na prática: defina um teto **por escrito antes**, e esteja na tela na última
meia hora.

## Quanto costuma custar

Dados do NIC.br sobre as primeiras rodadas do processo competitivo (2017):

| Métrica | Valor |
|---|---|
| mediana das ofertas vencedoras | R$ 750 |
| moda (valor mais frequente) | R$ 250 |
| média nos dois primeiros meses | R$ 1.563 (distorcida por casos atípicos) |
| caso com mais lances | 89 ofertas, fechou em R$ 16.500 |
| recorde de LLL `.com.br` | R$ 80 mil |
| recorde geral | `pneus.com.br`, R$ 220 mil (2019) |

A leitura correta desses números: **a maioria fecha na casa das centenas**.
A média alta é efeito de poucos casos extremos. O que estoura são palavras de
categoria comercial pura com um comprador óbvio — `pneus.com.br` foi comprado
por uma empresa que usa o nome na própria operação, não por um investidor.

Compare sempre com o preço do mercado secundário antes de subir a oferta:
[Afternic](https://www.afternic.com), [NameBio](https://namebio.com).

## Como termina, e o que dá para ver de fora

Medido em 17/09/2026, nos 9 nomes de um leilão da rodada de setembro.

- **O leilão não acaba junto com a rodada.** `lista-competicao.txt` é
  agrupada por rodada, e nomes de rodadas antigas continuam nela: uma hora
  depois do fim da rodada de setembro, a lista ainda trazia um leilão aberto
  em **julho** e 25 de **agosto**. Para saber se um nome ainda está em
  leilão, só a lista responde; a data da rodada não (L5 em
  [`limitacoes-registrobr.md`](limitacoes-registrobr.md)).
- **O fim real vem depois da hora anunciada.** As prorrogações de 10 min se
  somam: um processo marcado para as 15h pode fechar às 16h. Quem for
  acompanhar precisa estar na tela *depois* do horário oficial.
- **Cerca de um minuto depois do fim, o RDAP já mostra o vencedor** como
  titular, com `registration` no instante do fechamento — não é preciso
  esperar o pagamento. Um nome que não resolveu devolve objeto vazio com
  `Nicbr-Resource: release-process-waiting` e volta para a rodada seguinte:
  ticket aberto sem ninguém ofertar não vira domínio.
- **O valor não é público, e continua não sendo.** Quem tinha ticket recebe
  por e-mail o número do ticket vencedor e a oferta vencedora; o RDAP não
  traz valor nenhum, e o Liberados não publica valor de leilão.

## Onde ver

- Lista dos elegíveis: <https://registro.br/dominio/lista-processo-competitivo.txt>
- **Quem está em leilão agora:** <https://registro.br/dominio/lista-competicao.txt>
- Painel (exige login): <https://registro.br/painel/dominios/processo-competitivo/>


## Se ninguém puder levar

Quando as regras acima não resolvem, o processo pode ser reiniciado restrito
às candidaturas elegíveis iniciais, ou liberado direto se sobrar uma única
candidatura elegível. Não dando em nada, o nome volta para as rodadas
regulares seguintes ou é reservado.

O Registro.br pode **reservar para si** nomes que participaram sem sucesso e
que ele considere de interesse para a operação da Internet brasileira.

---

Fonte: [registro.br/dominio/processo-de-liberacao](https://registro.br/dominio/processo-de-liberacao/),
consultada em 09/09/2026. A página é renderizada por JavaScript, então
`curl` devolve vazio: é preciso abrir num navegador de verdade.
