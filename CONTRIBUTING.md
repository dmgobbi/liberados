# Como contribuir

Obrigado pelo interesse. Este projeto é pequeno e tem opinião própria sobre
algumas coisas; este arquivo existe para você saber quais antes de gastar
tempo.

## O básico

```bash
git clone https://github.com/dmgobbi/liberados.git
cd liberados
python3 -m unittest -v test_scripts.py
```

Python 3.10 ou mais novo. **Não há o que instalar** — e é assim de propósito.

## As quatro regras que não mudam

### 1. Só biblioteca padrão

Nada de `pip install`. O projeto inteiro roda com o Python que já veio na
máquina, e isso é uma decisão de produto: quem quer garimpar domínio não
deveria precisar aprender ambiente virtual antes.

Se algo parece exigir uma dependência, quase sempre dá para resolver com
`urllib`, `sqlite3`, `json`, `csv` ou `socket`. O cliente RDAP e o teste de
resolução de DNS em `garimpo/adaptadores/rdap.py` são exemplos disso.

### 2. Nenhum teste toca a rede

A suíte roda em segundos e funciona sem internet. Adaptadores entram nos
casos de uso **por parâmetro**, e os testes injetam falsos — veja
`ClienteFalso` e `ClienteRdapFalso` em `test_scripts.py`.

Isso é verificado no CI. Um teste que chama a rede de verdade reprova.

Precisa testar código que fala HTTP? Separe a parte que decide da parte que
busca: `rdap.interpretar()` recebe o JSON já baixado justamente para poder
ser testado sem rede.

### 3. O piso de 2 segundos entre consultas é rígido

Medido em 09/09/2026 contra o Registro.br:

| Ritmo | Taxa | Resultado |
|---|---|---|
| 2s, uma conexão | 0,46 req/s | limpo |
| 1s, uma conexão | 0,87 req/s | começam falhas |
| 1s, três conexões | 2,7 req/s | **bloqueia** |

A 2,7 req/s o próprio navegador da máquina passou a receber "serviço
temporariamente indisponível": o limite é por IP e afeta terceiros, inclusive
quando o código roda num runner de CI com IP compartilhado.

**Não aceitamos PR que diminua a pausa, paralelize consultas ou contorne o
limite.** A lista muda uma vez por mês; não há motivo para apressar.

### 4. Dado publicado é só dado de domínio

O site gerado (`site/`) não leva ticket de ninguém, oferta, anotação pessoal
nem domínio da sua conta. Só o que já é público no Registro.br. A única
coisa parecida com ticket que atravessa é o **ritmo da rodada** (`ritmo` no
JSON): uma série de pares "instante, maior número de ticket já visto", que
é o contador global de tickets do Registro.br, não a candidatura de alguém. Por nome,
o site recebe só a estimativa de quando os concorrentes chegaram, nunca os
números.

## Arquitetura

Dependência sempre para dentro:

```
dominio/      regras puras, sem I/O — situacao, relevancia, marcas
adaptadores/  a fronteira — registrobr, rdap, repositorio, dicionarios
casos/        orquestração — pool, varredura, instantaneo, historias
web/          consultas em SQL e o servidor HTTP
contexto.py   ponto de composição: o único que sabe onde ficam os arquivos
```

Regra prática: se um arquivo em `dominio/` precisou importar algo de
`adaptadores/`, a modelagem está errada.

Os scripts na raiz são entradas finas — argparse e impressão, nada de lógica.

## Estilo

- Código, comentários e documentação em **português**.
- Comentário explica **por que**, não o que. O melhor comentário do
  repositório é o que conta que o bloqueio por excesso de consultas volta com
  HTTP 200 e `status: 8`, que na tabela oficial é "erro" mas que este
  projeto, lendo o status como bits até 11/09/2026, confundiu com o de
  leilão, e já transformou 370 respostas bloqueadas em falsos "domínios em
  leilão".
- Quando corrigir um engano, deixe registrado o que era e o que provou o
  contrário. Vários comentários aqui são cicatrizes, e é isso que os torna
  úteis.

## Números precisam de procedência

Este projeto faz afirmações verificáveis sobre um mercado real. Se você
acrescentar um número:

- diga **de onde veio** e **quando foi medido**;
- prefira o que dá para reproduzir com um comando do próprio repositório;
- separe o que foi medido do que foi inferido.

`notaveis.csv` tem uma coluna `fonte` obrigatória exatamente por isso.

## Abrindo um PR

1. Rode `python3 -m unittest -v test_scripts.py`.
2. Descreva o **problema**, não só a mudança.
3. Mexeu em regra do Registro.br? Cite a página oficial e a data da consulta —
   as regras mudam e a documentação deles nem sempre acompanha.

Achou um erro nos dados ou na interpretação das regras? Abra uma issue. Este
repositório já corrigiu várias coisas que estavam erradas com convicção.
