"""
"O que aconteceu com esse nome depois?"

O resto do projeto olha para a RODADA: quem esta em liberacao, quem tem
candidato, quem vai a leilao. Este modulo olha para o outro lado do funil —
os nomes que ja tem dono — e pergunta o que foi feito deles.

A pergunta nasceu de um caso concreto. O `.br` mais caro ja vendido em leilao
do Registro.br foi `pneus.com.br`, R$ 220 mil em 2019. Hoje esta pago ate
2029, delegado ao DNS do proprio Registro.br, e nao entrega nada.

Isso exige cruzar fontes que ninguem cruza: RDAP (quem, desde quando, ate
quando), resolucao de DNS (chega a algum lugar?) e o Internet Archive (ja
chegou?). A terceira nao e enfeite — foi ela que impediu uma afirmacao falsa:
com as duas primeiras, a conclusao seria "compraram e nunca usaram", quando
na verdade o dominio redirecionou para sunset-tires.com de 2019 a 2023.

O valor de fazer disso um modulo, e nao uma consulta manual: a resposta muda
com o tempo. Rodar de novo daqui a seis meses e uma linha de comando, e cada
execucao pode revelar um nome que mudou de estado.
"""

from __future__ import annotations

import csv
import os
import time
from dataclasses import dataclass

from ..adaptadores import rdap, wayback

# As categorias existem para responder "isso vale contar?". A ordem e do mais
# interessante para o menos.
EM_BRANCO = "em branco"       # registrado, pago, e nao entrega nada
ESTACIONADO = "estacionado"   # no DNS do registro; resolve, mas nao e site proprio
ATIVO = "ativo"               # resolve em servidor proprio
LIVRE = "livre"               # nao esta registrado
ERRO = "erro"

CATEGORIAS = (EM_BRANCO, ESTACIONADO, ATIVO, LIVRE, ERRO)


@dataclass(frozen=True)
class Historia:
    """Uma ficha de RDAP mais o contexto de por que esse nome interessa."""

    ficha: rdap.Ficha
    valor: str | None = None       # quanto se sabe que foi pago, se se sabe
    ano: str | None = None
    fonte: str | None = None       # de onde veio o valor; sem fonte, sem valor
    historico: wayback.Historico | None = None

    @property
    def dominio(self) -> str:
        return self.ficha.dominio

    @property
    def ja_teve_site(self) -> bool:
        """
        O arquivo viu conteudo proprio ali algum dia.

        Separa "nunca foi nada" de "morreu" — do lado de fora os dois
        parecem iguais, e so o segundo e uma historia.
        """
        return bool(self.historico and self.historico.teve_site)

    @property
    def categoria(self) -> str:
        f = self.ficha
        if f.erro:
            return ERRO
        if not f.existe:
            return LIVRE
        if not f.resolve:
            return EM_BRANCO
        return ESTACIONADO if f.estacionado else ATIVO

    @property
    def notavel(self) -> bool:
        """
        Vale contar? Nome caro que nao entrega nada e a historia toda.

        Nome que simplesmente funciona nao e noticia — e o esperado.
        """
        return self.categoria in (EM_BRANCO, ESTACIONADO)


def classificar(historias) -> dict[str, int]:
    contagem = {c: 0 for c in CATEGORIAS}
    for h in historias:
        contagem[h.categoria] += 1
    return contagem


def investigar(alvos, cliente=rdap, pausa: float = rdap.PAUSA_SEGURA,
               aviso=None, arquivo=wayback, titular: bool = False) -> list[Historia]:
    """
    Levanta a ficha de cada alvo, e o que o arquivo lembra dele.

    `alvos` sao dicionarios com ao menos `dominio`, e opcionalmente `valor`,
    `ano` e `fonte`. `cliente` e `arquivo` entram por parametro para o teste
    injetar falsos — nenhum teste deste projeto toca a rede.

    Passar `arquivo=None` pula a consulta ao Internet Archive: e uma
    requisicao a mais por dominio, e nem toda pergunta precisa dela.
    `titular=True` faz uma consulta a mais ao RDAP, a entidade do titular
    (so CNPJ), para saber quantos dominios ele tem: 1 e uma empresa com
    seu nome; 166 e uma carteira.
    """
    saida: list[Historia] = []
    for i, alvo in enumerate(alvos):
        dominio = alvo["dominio"].strip().lower()
        if aviso:
            aviso(f"[{i + 1}/{len(alvos)}] {dominio}")
        ficha = (cliente.ficha(dominio, com_titular_=True, pausa=pausa)
                 if titular else cliente.ficha(dominio))

        historico = None
        if arquivo is not None:
            if pausa:
                time.sleep(pausa)      # servico diferente, mesma educacao
            historico = arquivo.historico(dominio)

        saida.append(Historia(
            ficha=ficha,
            valor=alvo.get("valor") or None,
            ano=alvo.get("ano") or None,
            fonte=alvo.get("fonte") or None,
            historico=historico,
        ))
        # o ultimo nao precisa esperar por ninguem
        if pausa and i + 1 < len(alvos):
            time.sleep(pausa)
    return saida


def ler_alvos(caminho: str) -> list[dict]:
    """Le o CSV de alvos. Colunas: dominio, valor, ano, fonte."""
    with open(caminho, encoding="utf-8") as f:
        return [linha for linha in csv.DictReader(f)
                if (linha.get("dominio") or "").strip()]


def escrever(historias, caminho: str) -> None:
    with open(caminho, "w", encoding="utf-8", newline="") as f:
        escritor = csv.writer(f)
        escritor.writerow(["dominio", "categoria", "titular", "documento",
                           "registrado_em", "expira_em", "servidores",
                           "enderecos", "arquivo_primeira", "arquivo_ultima",
                           "arquivo_ultima_viva", "arquivo_teve_site",
                           "valor", "ano", "fonte",
                           "dns_segundo_o_registro", "dns_ok_em",
                           "dominios_do_titular", "arquivo_erro"])
        for h in historias:
            f_ = h.ficha
            a = h.historico
            escritor.writerow([
                h.dominio, h.categoria, f_.titular or "", f_.documento or "",
                f_.registrado_em or "", f_.expira_em or "",
                " ".join(f_.servidores), " ".join(f_.enderecos),
                (a.primeira if a else "") or "", (a.ultima if a else "") or "",
                (a.ultima_viva if a else "") or "",
                # "nao" so quando o arquivo respondeu: com erro, nao se sabe
                "erro" if a and a.erro else ("sim" if h.ja_teve_site else "nao"),
                h.valor or "", h.ano or "", h.fonte or "",
                dns_segundo_o_registro(f_), f_.delegacao_ok_em or "",
                "" if f_.dominios_do_titular is None else f_.dominios_do_titular,
                (a.erro if a else "") or "",
            ])


def dns_segundo_o_registro(f: rdap.Ficha) -> str:
    """O veredito do proprio Registro.br sobre os servidores de DNS."""
    if not f.delegacoes or all(d.responde is None for d in f.delegacoes):
        return ""
    if f.delegacao_quebrada:
        return "quebrado"
    if all(d.responde for d in f.delegacoes if d.responde is not None):
        return "ok"
    return "parcial"


def resumir(historias) -> str:
    """Texto curto para o terminal: a contagem e o que vale contar."""
    contagem = classificar(historias)
    linhas = [f"{len(historias)} dominios investigados"]
    for categoria in CATEGORIAS:
        if contagem[categoria]:
            linhas.append(f"  {categoria:12} {contagem[categoria]}")

    notaveis = [h for h in historias if h.notavel]
    if notaveis:
        linhas.append("")
        linhas.append("Vale olhar:")
        for h in notaveis:
            preco = f" ({h.valor}, {h.ano})" if h.valor else ""
            ate = f", pago ate {h.ficha.expira_em[:4]}" if h.ficha.expira_em else ""
            linhas.append(f"  {h.dominio}{preco}: {h.categoria}{ate}")
            # o arquivo separa "nunca foi nada" de "morreu", e a diferenca e
            # a historia inteira
            if h.historico and (h.historico.existe or h.historico.erro):
                linhas.append(f"      arquivo: {h.historico.resumo()}")
            # o registro conferiu os servidores: se nenhum responde, ele
            # sabe desde quando
            if h.ficha.delegacao_quebrada:
                desde = h.ficha.delegacao_ok_em
                linhas.append("      DNS: nenhum servidor responde segundo o "
                              "Registro.br" + (f", desde {desde[:10]}" if desde else ""))
            if h.ficha.fora_do_ar_por_decisao:
                linhas.append("      fora do ar por ordem judicial ou do CGI.br")
            if h.ficha.dominios_do_titular is not None:
                linhas.append(f"      titular tem {h.ficha.dominios_do_titular} "
                              "domínios .br")
    return "\n".join(linhas)
