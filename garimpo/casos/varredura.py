"""
Varredura: consultar o Registro.br para uma lista de dominios.

Caso de uso. Nao sabe nada de HTTP nem de SQL, so orquestra: pede a leitura
ao adaptador, grava no repositorio, conta o que mudou e respeita o orcamento
de tempo e o pedido de parada.

O ritmo e sequencial e pausado por decisao explicita, nao por preguica. Ver a
nota em adaptadores/registrobr.py: paralelizar derruba o servico para o IP
inteiro, inclusive para o navegador de quem esta rodando.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field, replace

from ..adaptadores.registrobr import PAUSA_SEGURA
from ..dominio.situacao import Leitura, Situacao

RECUO_APOS_BLOQUEIO = 120   # segundos; o limite do Registro.br e por IP
# Freio (19/09/2026): o nome ainda LIMITADO depois do recuo encerra a
# varredura, e tantas falhas seguidas tambem. Antes a varredura passava ao
# nome seguinte, levava outro bloqueio e outro recuo, e um runner barrado
# gastava o orcamento inteiro de 120 em 120 s sem ler nada.
ERROS_SEGUIDOS_PARA_PARAR = 10
FATIA_DE_ESPERA = 0.1       # granularidade da pausa, para o Parar responder


@dataclass
class Mudanca:
    dominio: str
    de: Situacao
    para: Situacao
    candidatos: int

    def __str__(self) -> str:
        return f"{self.dominio}: {self.de.value} -> {self.para.value}"


@dataclass
class Progresso:
    """Estado observavel da varredura em andamento."""

    total: int = 0
    feitos: int = 0
    atual: str = ""
    mensagem: str = "pronto"
    erros: int = 0
    bloqueios: int = 0
    rodando: bool = False
    barrada: bool = False
    motivo: str | None = None     # "bloqueio" ou "rede", quando barrada
    mudancas: list[Mudanca] = field(default_factory=list)
    pausa: float = PAUSA_SEGURA

    @property
    def segundos_restantes(self) -> int:
        return int(max(0, self.total - self.feitos) * (self.pausa + 0.15))

    def como_dicionario(self) -> dict:
        d = {
            "rodando": self.rodando,
            "total": self.total,
            "feitos": self.feitos,
            "atual": self.atual,
            "mensagem": self.mensagem,
            "erros": self.erros,
            "bloqueios": self.bloqueios,
            "barrada": self.barrada,
            "motivo": self.motivo,
            "novidades": [{"dominio": m.dominio, "de": m.de.value,
                           "para": m.para.value, "candidatos": m.candidatos}
                          for m in self.mudancas],
        }
        if self.rodando and self.total:
            d["segundos_restantes"] = self.segundos_restantes
        return d


class Varredura:
    """
    Executa uma varredura, opcionalmente numa thread.

    `cliente` precisa expor verificar(dominio) -> Leitura.
    `repo` precisa expor gravar_leitura(dominio, leitura) e um(dominio).
    Injetar os dois deixa o caso de uso testavel sem rede e sem banco.
    """

    MAX_MUDANCAS = 40
    # Recontagem pelo RDAP quando o avail corta em 10 (limitacao A3). Poucos
    # nomes batem no corte, e o limite do RDAP nao e publicado (R4): no
    # maximo tantas por execucao, uma pausa propria, e no primeiro erro o
    # RDAP e abandonado ate a proxima execucao.
    LIMITE_RECONTAGENS = 20
    PAUSA_RDAP = 2.5

    def __init__(self, cliente, repo, *, relatar=None, contador=None):
        """`contador(dominio) -> int` conta os tickets sem o corte; opcional."""
        self._cliente = cliente
        self._repo = repo
        self._relatar = relatar or (lambda _: None)
        self._contador = contador
        self._recontagens = 0
        self._rdap_fora = False
        self._erros_seguidos = 0
        self._lock = threading.Lock()
        self._parar = False
        self.progresso = Progresso()

    # -- controle -----------------------------------------------------------

    def pedir_parada(self) -> None:
        self._parar = True

    def zerar_parada(self) -> None:
        """
        Libera a flag para uma nova execucao.

        Fica separado de executar() de proposito. O servidor agenda a
        varredura numa thread e volta na hora; se o zeramento acontecesse no
        inicio de executar(), um "Parar" clicado na janela entre agendar e a
        thread comecar seria engolido em silencio. Quem agenda zera; quem
        executa so obedece.
        """
        self._parar = False

    @property
    def parando(self) -> bool:
        return self._parar

    def _pausar(self, segundos: float) -> bool:
        """Dorme em fatias. False se pediram parada no meio."""
        fim = time.monotonic() + segundos
        while time.monotonic() < fim:
            if self._parar:
                return False
            time.sleep(FATIA_DE_ESPERA)
        return True

    def _atualizar(self, **campos) -> None:
        with self._lock:
            for chave, valor in campos.items():
                setattr(self.progresso, chave, valor)

    def instantaneo(self) -> dict:
        with self._lock:
            return self.progresso.como_dicionario()

    # -- execucao -----------------------------------------------------------

    def executar(self, dominios: list[str], pausa: float = PAUSA_SEGURA,
                 prazo: float | None = None) -> Progresso:
        """
        `pausa` nunca fica abaixo de PAUSA_SEGURA.
        `prazo` e um orcamento em segundos, para caber no limite de um runner.
        """
        pausa = max(PAUSA_SEGURA, pausa)
        self._recontagens = 0
        self._rdap_fora = False
        self._erros_seguidos = 0
        self._atualizar(rodando=True, total=len(dominios), feitos=0, erros=0,
                        bloqueios=0, barrada=False, motivo=None,
                        pausa=pausa, mudancas=[],
                        mensagem=f"verificando {len(dominios)} dominios")

        limite = time.monotonic() + prazo if prazo else None

        try:
            for indice, dominio in enumerate(dominios, 1):
                if self._parar:
                    self._atualizar(
                        mensagem=f"interrompido em {indice - 1} de {len(dominios)}")
                    break
                if limite and time.monotonic() >= limite:
                    self._atualizar(mensagem="orcamento de tempo esgotado")
                    break

                self._atualizar(atual=dominio)
                self._processar(dominio)
                self._atualizar(feitos=indice)

                if self.progresso.barrada:
                    # sem pausa nem proximo nome: insistir so estende o
                    # bloqueio, e a proxima execucao retoma pela fila
                    self._atualizar(
                        mensagem=f"barrada ({self.progresso.motivo}) em "
                                 f"{indice} de {len(dominios)}")
                    break

                if indice < len(dominios) and not self._pausar(pausa):
                    self._atualizar(
                        mensagem=f"interrompido em {indice} de {len(dominios)}")
                    break
            else:
                p = self.progresso
                self._atualizar(mensagem=f"pronto: {p.feitos} verificados, "
                                         f"{p.erros} erros")
        finally:
            self._atualizar(rodando=False, atual="")

        return self.progresso

    def _recontar(self, dominio: str, leitura: Leitura) -> Leitura:
        """
        Com 10 tickets no avail pode haver mais: pergunta ao RDAP uma vez.

        A contagem maior substitui a do avail e fica anotada no detalhe. O
        que nao muda: os tickets em si (continuam os 10 visiveis) e a
        situacao. Sem contador, sem cota ou depois de um erro, devolve a
        leitura como veio.
        """
        if (not leitura.cortado or self._contador is None or self._rdap_fora
                or self._recontagens >= self.LIMITE_RECONTAGENS):
            return leitura
        self._recontagens += 1
        try:
            total = self._contador(dominio)
        except Exception as e:
            self._rdap_fora = True
            self._relatar(f"RDAP falhou em {dominio} ({str(e)[:60]}); "
                          "sem recontagem ate a proxima execucao")
            return leitura
        finally:
            self._pausar(self.PAUSA_RDAP)
        if not isinstance(total, int) or total <= leitura.candidatos:
            return leitura
        self._relatar(f"{dominio}: {leitura.candidatos} no avail, {total} no RDAP")
        detalhe = "; ".join(x for x in (leitura.detalhe, f"rdap={total}") if x)
        return replace(leitura, candidatos=total, detalhe=detalhe)

    def _processar(self, dominio: str) -> None:
        antes = self._repo.um(dominio)
        situacao_antes = antes.situacao if antes else None

        leitura = self._cliente.verificar(dominio)

        if leitura.limitado:
            with self._lock:
                self.progresso.bloqueios += 1
            self._relatar(f"BLOQUEADO em {dominio}, recuando "
                          f"{RECUO_APOS_BLOQUEIO}s")
            self._atualizar(mensagem="bloqueado, recuando")
            if not self._pausar(RECUO_APOS_BLOQUEIO):
                return
            leitura = self._cliente.verificar(dominio)
            if leitura.limitado:
                # uma tentativa so: continua bloqueado, a varredura para
                self._relatar(f"ainda BLOQUEADO em {dominio} depois de "
                              f"{RECUO_APOS_BLOQUEIO}s: varredura encerrada")
                self._atualizar(barrada=True, motivo="bloqueio")
            else:
                self._atualizar(
                    mensagem=f"verificando {self.progresso.total} dominios")

        if not leitura.situacao.resolvida:
            with self._lock:
                self.progresso.erros += 1
            self._erros_seguidos += 1
            if (self._erros_seguidos >= ERROS_SEGUIDOS_PARA_PARAR
                    and not self.progresso.barrada):
                self._relatar(f"{self._erros_seguidos} erros seguidos: "
                              "varredura encerrada")
                self._atualizar(barrada=True, motivo="rede")
            # nao grava: deixar NULL faz o nome voltar na proxima varredura,
            # em vez de virar um resultado falso permanente
            return

        self._erros_seguidos = 0
        leitura = self._recontar(dominio, leitura)
        self._repo.gravar_leitura(dominio, leitura)

        if situacao_antes and situacao_antes is not leitura.situacao:
            mudanca = Mudanca(dominio, situacao_antes, leitura.situacao,
                              leitura.candidatos)
            self._relatar(f"MUDOU {mudanca}")
            with self._lock:
                self.progresso.mudancas.insert(0, mudanca)
                del self.progresso.mudancas[self.MAX_MUDANCAS:]
