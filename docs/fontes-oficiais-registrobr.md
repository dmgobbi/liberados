# Fontes oficiais do Registro.br: o que existe, o que serve, o que não serve

Levantamento de 12/09/2026, a partir da conta `github.com/registrobr` e do
FTP público `ftp.registro.br/pub/`. O objetivo era descobrir se alguma fonte
oficial contradizia ou completava o que este projeto deduziu por sondagem.
Contradisse uma coisa importante (o `status` não é bitmask) e completou
várias. Cada achado está numerado em
[`limitacoes-registrobr.md`](limitacoes-registrobr.md).

## O que muda na prática

1. **O endpoint de disponibilidade é o proxy web de um serviço oficial e
   documentado, o ISAVAIL.** O `status` é uma enumeração de 0 a 9, não um
   bitmask. Os valores que este projeto viu (0, 2, 3, 6, 7, 8, 9) coincidiam
   com a leitura por bits por acaso. O valor 5, "aguardando processo de
   liberação", seria lido como 4|1, isto é, "em liberação, sem candidato": a
   joia falsa. `dominio/situacao.py` passou a mapear os dez valores.
2. **O Registro.br avisou que o endpoint web pode mudar.** Issue #98 do
   `whmcs-registrobr-epp`, aberta em 26/07/2025 pelo mantenedor do
   repositório oficial: trocar a checagem de disponibilidade "para utilizar RDAP ao
   invés do avail do site, que corre risco de alteração de localização e
   comportamento". O ISAVAIL (UDP) e o RDAP são as contingências.
3. **O RDAP diz se o DNS de um domínio funciona, e desde quando.** A
   extensão NIC.br traz, por servidor, o resultado da conferência do próprio
   registro (`ns aa`, `ns timeout`, `ns udn`...) e a data da última vez em
   que o servidor respondeu certo. Para um nome "em branco", é o "desde
   quando" sem precisar do Internet Archive. `historias.py` já lê.
4. **A entidade do RDAP diz quantos domínios o titular tem**
   (`nicbr_domainCount`). A titular de pneus.com.br tem 166. Um dono com 1
   domínio é uma empresa com seu nome; com 166 é uma carteira.
   `historias.py --titular` consulta, só para CNPJ.
5. **A especificação EPP lista as reservas que a consulta pública não
   explica**: nome reservado por ser marca conhecida, por ordem judicial,
   pelo CGI.br, e **por já ter sido oferecido em mais de 6 processos de
   liberação**. Está em [`processo-de-liberacao.md`](processo-de-liberacao.md).

## GitHub: `github.com/registrobr`

14 repositórios. Quatro interessam.

| Repositório | O que é | O que rendeu |
|---|---|---|
| `rdap` (Go, atualizado 08/2026) | biblioteca RDAP do NIC.br, com a extensão deles | os tipos da extensão: `nicbr_arbitration`, eventos `delegation check` e `last correct delegation check` com status `ns aa`/`ns timeout`/..., status de domínio `nicbr inactive court order` e `nicbr inactive CG`, `nicbr_domainCount` na entidade, `legalRepresentative` (nome de pessoa), e um tipo de consulta por ticket (`QueryTypeTicket`), que este projeto não usa |
| `rdap-client` (Go) | cliente de linha de comando | só o uso: `rdap-client -H rdap.registro.br nic.br` |
| `whmcs-registrobr-epp` (PHP, 01/2026) | módulo de registrar para WHMCS, mantido pelo Registro.br | `whoisjson.php` aponta o `avail/raw` como provedor de disponibilidade (semi-oficial); `TLDs.php` classifica todas as extensões por exigência (CPF, CNPJ, cidade, documentação); issue #98 é o aviso de mudança; issue #96 explica por que tanto domínio nasce em `auto.dns.br` (o módulo cria assim por padrão) |
| `Net-DRI` (Perl, fork) | cliente EPP com a extensão `.br` (`draft-neves-epp-brdomain`) | as respostas de exemplo em `t/635br_epp.t`: `hasConcurrent`, `inReleaseProcess`, `equivalentName`, `releaseProcessFlags`, `releaseProc status="waiting"`, `ticketNumberConc` |

Os outros dez (`pdf`, `pdfsign`, `pkcs7`, `dns`, `boulder`, `zxcvbn-go`,
`twofactorauth`, `trama`, `gostk`, `godeps-check`) são forks sem commit
próprio (o `dns` está 0 à frente e 9 atrás do original) ou ferramentas
internas em Go. Nada sobre domínios.

## FTP: `ftp.registro.br/pub/`

| Caminho | O que é | O que rendeu |
|---|---|---|
| `isavail/` (0.10, 01/2025) | o protocolo de disponibilidade, com clientes em Python, Perl, PHP, Java, C++ e Ruby | `Protocolo-ISAVAIL.txt`: UDP 43 em `avail.registro.br`, a tabela de status, o formato de cada resposta, o corte em 10 tickets, e o README que chama o endpoint web de "proxy no site" |
| `doc/br-rdap-extensions-02.txt` (2020) | a especificação da extensão NIC.br do RDAP | os mesmos campos da biblioteca Go, com exemplos |
| `libepp-nicbr/en-policy-restrictions-espec.txt` (arquivo de 08/2026, texto datado de 08/2021) | política e restrições do EPP do `.br` | as mensagens de erro do `domain:create` (as reservas acima, o limite de tickets por organização, "domínio aguardando o próximo processo de liberação"), a regra de que `flag1` significa "a organização detém a marca", e que `www.` não entra na liberação |
| `libepp-nicbr/draft-neves-epp-brdomain-05.txt` (2011) | o draft IETF da extensão EPP `.br` | a definição do processo de liberação no nível do protocolo: "um nome apagado não volta ao espaço livre; passa por um Release Process"; os três finais; `releaseProc` com status `resolved`, `waiting` ou `denied` |
| `saci-adm/` (07/2026) | decisões do SACI-Adm (disputas de domínio `.br`), em PDF | fonte para casos reais em `marcas-e-cybersquatting.md`; não lido ainda |
| `gter/gter40/05-RDAP-br.pdf` | apresentação do RDAP `.br` no GTER | contexto |
| `stats/`, `module-whmcs-epp-nicbr/`, `dnsshim/`, `geofeed/` | estatísticas de IPv6 de 2008, módulo WHMCS de 2013, ferramentas de DNS | nada para este projeto |

## Fora do Registro.br, mas sobre ele

| Fonte | O que é | O que rendeu |
|---|---|---|
| Internet Archive, cópias de `registro.br/dominio/lista-*.txt` (CDX com `collapse=digest`) | as listas de rodadas antigas, que o Registro.br não mantém | 87 rodadas de liberação e 69 de elegíveis de 2017 a 2026: a série de [`historico-das-rodadas.md`](historico-das-rodadas.md), a regra das três travas (S13) e o atraso de ~5 meses (S14) |
| `registro.br/dominio/estatisticas/` (JS) | base do `.br`, registrados e removidos em 24 h e 30 dias | conferência do tamanho da rodada: 123.273 removidos em 30 dias contra 125.453 nomes na rodada de 09/09/2026; base de 5.938.675 em 12/09/2026 |

## O que não foi feito, e por quê

- **Medir o limite do ISAVAIL.** Medir é bater; a regra do projeto é não
  bater. O adaptador (`garimpo/adaptadores/isavail.py`) e o script
  (`isavail.py`) existem para conferir nomes e como contingência, não para
  varrer. Se um dia o endpoint web sumir, a decisão de trocar o canal passa
  por medir o limite com cuidado, uma consulta a cada 2 s, parando no
  primeiro `ST 8`.
- **Consultar por ticket no site ou na varredura** (`/ticket/<n>` na
  biblioteca Go, `?ticket=<n>` no RDAP). Devolve nome e documento parcial do
  candidato. Só a ferramenta local `tickets.py` consulta, por decisão do dono
  em 12/09/2026. `/ticket/<n>` responde 403; a forma do site
  (`domain/<nome>?ticket=<n>`) foi conferida ao vivo nesse dia (R3 no
  catálogo).
- **Ler `legalRepresentative`** da entidade. É o nome de uma pessoa.
  `rdap.interpretar_entidade` devolve só a contagem de domínios.
- **Confiar nas datas do ISAVAIL.** Em 12/09/2026, para a rodada de 09/09 a
  16/09, ele devolveu `2026-09-26 15:00:00` nos três campos de vacina.com.br
  e nos dois de one.com.br. O endpoint web devolvia as datas certas. As
  datas ficam em `Resposta.datas` e não entram no payload.

## Conferido em 16/09/2026

Confirmado (S16): um nome travado (dois ou mais candidatos, sem leilão)
responde `status: 5` entre uma rodada e outra, a partir das 15h15 do
fechamento (one.com.br e peca.com.br). `desfecho.py` já tem a leitura certa
("travado: espera a próxima rodada"), e a lista de outubro pode ser
antecipada consultando os travados de setembro.
