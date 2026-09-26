# Segurança

## Reportar uma vulnerabilidade

Use o [Security Advisory privado do GitHub](../../security/advisories/new).
Não abra issue pública para falha de segurança.

## O que este projeto trata como dado sensível

Este é um projeto de pesquisa sobre dados públicos de domínios. A
varredura, o exportador e o servidor **nunca** consultam nem armazenam
dado pessoal. O navegador de quem visita o site faz até quatro consultas
sob demanda, cada uma só ao abrir a página que a usa, com a cota de IP
daquele visitante, e o resultado fica só naquele aparelho: não volta para
o servidor, porque dado vindo de navegador alheio pode ser forjado.

- **Quem disputa** (`web/disputa.js`, ao tocar na contagem de "Competindo"
  na lista ou no botão "Ver quem disputa" da ficha de um nome travado):
  `rdap.registro.br/domain/<nome>?ticket=<n>` devolve nome e documento
  mascarado de quem se candidatou, o mesmo que a busca do Registro.br mostra
  a qualquer pessoa. Mostra nome, tipo e número mascarado do documento,
  instante do pedido e, para empresas, quantos domínios têm. Uma ferramenta
  local do dono, fora do repositório público, repete a mesma leitura em
  lote, com saída fora do git.
- **Ficha de um domínio registrado** (`/quando-volta/`, `site_modelo/ficha.js`)
  e **página de letra** (`/insights/dominios-de-uma-letra/*/`,
  `site_modelo/letra.js`): RDAP do próprio `.br`, mostra só o nome do
  titular (o `fn` do `registrant`).
- **Mostrar o .com** (`web/pontocom.js`, na ficha): Verisign e RDAP do
  registrador, mostra `fn`, organização e o código do país do dono do
  `.com`, como o WHOIS publica.

Em nenhuma das quatro saem documento (fora o mascarado de *quem disputa*),
endereço, e-mail, telefone nem `legalRepresentative`. O feed autenticado do
painel do Registro.br traz o documento do titular; nada aqui se conecta a
ele.

## Métricas

As visitas ao site são contadas pelo beacon do Web Analytics do
Cloudflare, injetado pela zona (não por este código). Ele não identifica
quem visita; detalhes em "Privacidade" na aba Sobre do site.

## Limites de consulta

O Registro.br limita por IP e o limite vale para a máquina inteira, não só
para o script. Pull request que acelere a varredura além de uma conexão a
cada 2 segundos não será aceito. Detalhes medidos em
[`docs/limitacoes-registrobr.md`](docs/limitacoes-registrobr.md).
