"""
Rajada em casa: a lista da rodada conferida numa noite, na maquina do dono.

Caso de uso. A entrada fina e rajada.py na raiz, que so liga as pecas; aqui
mora a regra, com tudo injetado (cliente, repositorio, relogio, sono e o
executor de git/gh), para os testes rodarem sem rede, sem git e sem esperar.

Por que existe (plano de frescor, 19/09/2026): o cron do GitHub le ~700
nomes por dia no privado, e a lista da rodada tem ~16 a 18 mil. Sem casa, a
semana de outubro leria ~900 deles; a rajada le todos na primeira noite. Ela
NAO substitui o workflow: nunca o desliga, e so dispara um Garimpo quando
nenhum esta na fila nem andando.

O ciclo, bloco a bloco:

  1. `git fetch` e aplica o site/dados.json da origin/main pela leitura mais
     nova (Repositorio.restaurar), para nao reler o que o cron acabou de ler;
  2. monta o alvo: nome do pool sem leitura ou lido antes de `desde`, na
     ordem elegivel > com candidato > nota; nunca os 125 mil da lista;
  3. uma Varredura de ate 30 min (~700 consultas), sequencial, com a pausa
     nunca abaixo de PAUSA_SEGURA, sem recontagem pelo RDAP (a rajada so
     fala com o avail);
  4. grava leituras/casa.json (formato do dados.json v5, sem ritmo nem
     numero de ticket), comita so ele, `pull --rebase` e `push` (3 vezes);
  5. depois do 1o bloco e a cada 4, e no fim, dispara o Garimpo com
     `-f minutos=3` se `gh run list` nao mostra nenhum queued nem
     in_progress (dois Garimpos juntos reescrevem o dados.json);
  6. descansa 5 min e volta ao 1.

Para: com o alvo esgotado, em `ate`, em `maximo` consultas, ou no bloqueio.
No primeiro bloqueio (a Varredura ja recuou 120 s e desistiu) as leituras
feitas sao comitadas, a rajada recua 60 min e tenta mais um bloco; no
segundo, comita e sai com 2. Falha de rede em serie (motivo "rede") conta
igual: insistir do mesmo IP nao ajuda.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from ..adaptadores.registrobr import PAUSA_SEGURA
from ..adaptadores.repositorio import agora as agora_iso
from ..dominio import frescor
from ..dominio.calendario import BRASILIA
from ..dominio.situacao import Situacao
from . import instantaneo
from . import varredura as _varredura
from .varredura import Varredura

BLOCO_SEGUNDOS = 30 * 60
DESCANSO_SEGUNDOS = 5 * 60
RECUO_BLOQUEIO_SEGUNDOS = 60 * 60
DISPARO_A_CADA_BLOCOS = 4
TENTATIVAS_PUSH = 3
FOLGA_POR_CONSULTA = 0.2    # a consulta em si, alem da pausa (varrer.py)

CASA = os.path.join("leituras", "casa.json")
WORKFLOW = "Garimpo"
EM_ANDAMENTO = ("queued", "in_progress", "waiting", "requested", "pending")

# codigos de saida de rajada.py
OK, BARRADA, RECUSADA, ANTES_DA_ABERTURA = 0, 2, 3, 4


# ------------------------------------------------------------------ recusas

def motivo_para_recusar(ambiente: dict, git) -> str | None:
    """
    Onde a rajada nao roda. `git(args) -> (codigo, saida)`.

    No Actions: o IP do runner e compartilhado, e a rajada e da casa.
    No checkout principal (git-dir igual ao git-common-dir): ele e do dono,
    tem um dados.db antigo e a coleta do Wayback rodando; a rajada comita e
    faz pull --rebase, e precisa de uma arvore so dela.
    """
    if (ambiente.get("GITHUB_ACTIONS") or "").lower() == "true":
        return "no GitHub Actions a rajada nao roda: ela e da maquina de casa"
    cod1, git_dir = git(["rev-parse", "--absolute-git-dir"])
    cod2, comum = git(["rev-parse", "--path-format=absolute", "--git-common-dir"])
    if cod1 or cod2:
        return "fora de um repositorio git"
    if os.path.realpath(git_dir.strip()) == os.path.realpath(comum.strip()):
        return ("este e o checkout principal: rode numa worktree propria "
                "(docs/operacao.md, secao 6)")
    return None


# ------------------------------------------------------------- parametros

def resolver_desde(texto: str | None, rodada, agora: int) -> int | None:
    """
    `abertura`, `fechamento`, `12 h` (ha 12 horas) ou uma data ISO.

    Sem texto: `fechamento` se a rodada ja fechou, senao `abertura`. None
    quando a rodada nao tem a data pedida.
    """
    if not texto:
        fim = frescor.epoch(rodada.fim)
        texto = "fechamento" if fim is not None and agora >= fim else "abertura"
    t = texto.strip().lower()
    if t == "abertura":
        return frescor.epoch(rodada.inicio)
    if t == "fechamento":
        return frescor.epoch(rodada.fim)
    m = re.fullmatch(r"(\d+(?:[.,]\d+)?)\s*h", t)
    if m:
        return agora - int(float(m.group(1).replace(",", ".")) * 3600)
    quando = frescor.epoch(texto.strip())
    if quando is None:
        raise ValueError(f"--desde nao entendido: {texto!r}")
    if "T" not in texto and " " not in texto.strip():
        # so a data: meia-noite de Brasilia, nao de UTC
        quando = frescor.epoch(f"{texto.strip()}T00:00:00-03:00")
    return quando


def resolver_ate(texto: str | None, agora: int) -> int | None:
    """
    `HH:MM` de Brasilia (a proxima vez que o relogio marcar essa hora, entao
    uma rajada das 22h com --ate 07:00 vai ate a manha seguinte) ou uma data
    ISO completa, que pode estar no passado.
    """
    if not texto:
        return None
    m = re.fullmatch(r"(\d{1,2}):(\d{2})", texto.strip())
    if m:
        agora_br = datetime.fromtimestamp(agora, BRASILIA)
        alvo = agora_br.replace(hour=int(m.group(1)), minute=int(m.group(2)),
                                second=0, microsecond=0)
        if alvo <= agora_br:
            alvo += timedelta(days=1)
        return int(alvo.timestamp())
    quando = frescor.epoch(texto.strip())
    if quando is None:
        raise ValueError(f"--ate nao entendido: {texto!r}")
    return quando


def situacoes_de(texto: str | None) -> set[Situacao] | None:
    """`LIBERACAO_LIVRE,REGISTRADO` -> {Situacao...}; vazio = todas."""
    if not texto:
        return None
    saida = set()
    for parte in texto.split(","):
        nome = parte.strip().upper()
        if not nome:
            continue
        if nome not in Situacao.__members__:
            raise ValueError(f"--situacao desconhecida: {parte.strip()!r} "
                             f"(use {', '.join(Situacao.__members__)})")
        saida.add(Situacao[nome])
    return saida or None


# ------------------------------------------------------------------- alvo

def alvos(candidatos, desde: int | None,
          situacoes: set[Situacao] | None = None) -> list[str]:
    """
    Quem a rajada le, na ordem em que le.

    Entra quem nunca foi lido e quem foi lido antes de `desde`. O filtro de
    situacao vale so para quem tem leitura: nome sem leitura e justamente o
    que a rajada existe para ler. Ordem: elegivel ao leilao, depois quem ja
    teve candidato, depois a nota (a mesma do site), e o nome desempata.
    """
    escolhidos = []
    for c in candidatos:
        quando = frescor.epoch(c.verificado_em)
        if c.situacao is not None and quando is not None:
            if desde is not None and quando >= desde:
                continue
            if situacoes and c.situacao_atual not in situacoes:
                continue
        escolhidos.append(c)
    escolhidos.sort(key=lambda c: (not c.elegivel, not (c.candidatos or 0) > 0,
                                   -(c.nota or 0), c.dominio))
    return [c.dominio for c in escolhidos]


def por_bloco(pausa: float) -> int:
    return int(BLOCO_SEGUNDOS / (max(PAUSA_SEGURA, pausa) + FOLGA_POR_CONSULTA))


def previsao_de_fim(n: int, pausa: float, agora: int,
                    ate: int | None = None) -> int:
    """Quando a rajada acaba, com os descansos entre blocos, cortada em `ate`."""
    if n <= 0:
        return agora
    cabem = max(1, por_bloco(pausa))
    blocos = -(-n // cabem)
    fim = agora + int(n * (max(PAUSA_SEGURA, pausa) + FOLGA_POR_CONSULTA)
                      + (blocos - 1) * DESCANSO_SEGUNDOS)
    return min(fim, ate) if ate is not None else fim


def hora_br(epoch: int) -> str:
    return datetime.fromtimestamp(epoch, BRASILIA).strftime("%d/%m %H:%M")


# ------------------------------------------------------------ casa.json

def escrever_casa(caminho: str, repo, rodada, nomes: set[str]) -> int:
    """
    Grava as leituras de casa no formato do dados.json v5; sem nenhuma,
    nao grava e devolve 0.

    Sem `ritmo` (a serie traz numeros de ticket) e sem as tabelas que o
    varrer.py nao le daqui. `rodada.fim` vai como veio: e ele que o
    varrer.aplicar_leituras_de_casa compara para aceitar o arquivo.
    """
    lidos = [c for c in repo.buscar(limite=1_000_000)
             if c.dominio in nomes and c.situacao is not None]
    if not lidos:
        return 0    # nada lido ainda: o arquivo fica como estava
    meta = instantaneo.Metadados(gerado_em=agora_iso(), inicio=rodada.inicio,
                                 fim=rodada.fim)
    dados = instantaneo.exportar(lidos, meta)
    for chave in ("ritmo", "criterios", "frescor", "categorias"):
        dados.pop(chave, None)
    instantaneo.escrever(dados, caminho)
    return len(dados["itens"])


def nomes_da_casa(caminho: str, rodada) -> set[str]:
    """Os nomes que o casa.json da mesma rodada ja tem (de outra noite)."""
    casa = instantaneo.ler(caminho)
    if not casa or (casa.get("rodada") or {}).get("fim") != rodada.fim:
        return set()
    return {c.dominio for c in instantaneo.candidatos_de(casa)}


# ------------------------------------------------------------------ rajada

def sem_leitura_no_fim(p) -> int:
    """
    Quantos dos `p.feitos` do fim ficaram sem leitura porque a varredura
    barrou: 1 no bloqueio (o nome ainda limitado depois do recuo), a
    sequencia de erros no motivo "rede". Sem barrar, 0.
    """
    if not p.barrada:
        return 0
    if p.motivo == "bloqueio":
        return min(1, p.feitos)
    return min(_varredura.ERROS_SEGUIDOS_PARA_PARAR, p.feitos)


@dataclass
class Resultado:
    codigo: int = OK
    motivo: str = ""
    blocos: int = 0
    consultas: int = 0
    lidos: int = 0
    bloqueios: int = 0
    disparos: int = 0
    commits: int = 0
    falas: list[str] = field(default_factory=list)


class Rajada:
    """
    `git(args) -> (codigo, saida)` e `gh(args) -> (codigo, saida)` rodam na
    raiz da worktree; `relogio() -> epoch`; `dormir(segundos)`. A Varredura
    sai de `nova_varredura()`, para o teste poder trocar a pausa real.
    """

    def __init__(self, *, raiz: str, repo, cliente, rodada, git, gh,
                 relogio, dormir, relatar=print, pausa: float = PAUSA_SEGURA,
                 desde: int | None = None, situacoes=None,
                 ate: int | None = None, maximo: int | None = None,
                 nova_varredura=None):
        self.raiz = raiz
        self.repo = repo
        self.cliente = cliente
        self.rodada = rodada
        self.git = git
        self.gh = gh
        self.relogio = relogio
        self.dormir = dormir
        self._relatar = relatar
        self.pausa = max(PAUSA_SEGURA, pausa)
        self.desde = desde
        self.situacoes = situacoes
        self.ate = ate
        self.maximo = maximo
        self._nova_varredura = nova_varredura or (
            lambda: Varredura(self.cliente, self.repo,
                              relatar=lambda m: self.relatar(f"  {m}")))
        self.caminho_casa = os.path.join(raiz, CASA)
        self.resultado = Resultado()

    def relatar(self, msg: str) -> None:
        self.resultado.falas.append(msg)
        self._relatar(msg)

    # -- pecas --------------------------------------------------------------

    def fila(self) -> list[str]:
        return alvos(self.repo.buscar(limite=1_000_000), self.desde,
                     self.situacoes)

    def sincronizar(self) -> int:
        """Aplica o dados.json da origin/main, se for desta rodada."""
        self.git(["fetch", "-q", "origin", "main"])
        cod, texto = self.git(["show", "origin/main:site/dados.json"])
        if cod or not texto.strip():
            self.relatar("sem dados.json na origin/main; seguindo com o banco")
            return 0
        try:
            dados = json.loads(texto)
        except ValueError:
            self.relatar("dados.json da origin/main ilegivel; seguindo com o banco")
            return 0
        if (dados.get("rodada") or {}).get("fim") != self.rodada.fim:
            return 0
        return self.repo.restaurar(instantaneo.candidatos_de(dados))

    def garimpo_andando(self) -> bool | None:
        """True/False pelo gh; None quando o gh nao responde (nao dispara)."""
        cod, saida = self.gh(["run", "list", "--workflow", WORKFLOW,
                              "--limit", "20", "--json", "status"])
        if cod:
            return None
        try:
            runs = json.loads(saida or "[]")
        except ValueError:
            return None
        return any((r.get("status") or "") in EM_ANDAMENTO for r in runs)

    def disparar(self) -> bool:
        """
        Um Garimpo curto, so se nenhum esta na fila nem andando. Nunca
        desliga nem cancela o workflow: ele segue no cron dele.
        """
        andando = self.garimpo_andando()
        if andando is None:
            self.relatar("gh run list falhou: sem disparo agora")
            return False
        if andando:
            self.relatar("Garimpo na fila ou andando: sem disparo agora")
            return False
        cod, _ = self.gh(["workflow", "run", WORKFLOW, "--ref", "main",
                          "-f", "minutos=3"])
        if cod:
            self.relatar("gh workflow run falhou")
            return False
        self.resultado.disparos += 1
        self.relatar("Garimpo disparado (minutos=3) para publicar as leituras")
        return True

    def comitar(self, nomes: set[str]) -> bool:
        """
        Grava casa.json, comita SO ele e empurra para a main. Nada de
        `add -A`, nada de stash: a worktree da rajada so muda esse arquivo.
        """
        n = escrever_casa(self.caminho_casa, self.repo, self.rodada, nomes)
        if n == 0:
            return False
        self.git(["add", "--", CASA])
        cod, _ = self.git(["diff", "--cached", "--quiet", "--", CASA])
        if cod == 0:
            return False
        cod, _ = self.git(["commit", "-q", "-m",
                           f"Rajada em casa: {n} leituras "
                           f"(bloco {self.resultado.blocos})", "--", CASA])
        if cod:
            self.relatar("commit de leituras/casa.json falhou")
            return False
        self.resultado.commits += 1
        for tentativa in range(1, TENTATIVAS_PUSH + 1):
            cod, _ = self.git(["pull", "--rebase", "-q", "origin", "main"])
            if cod:
                self.git(["rebase", "--abort"])
            else:
                cod, _ = self.git(["push", "-q", "origin", "HEAD:main"])
                if cod == 0:
                    self.relatar(f"leituras/casa.json: {n} nomes, na main")
                    return True
            self.relatar(f"push falhou (tentativa {tentativa} de "
                         f"{TENTATIVAS_PUSH})")
            if tentativa < TENTATIVAS_PUSH:
                self.dormir(10)
        self.relatar("sem push: o commit fica local e vai no proximo bloco")
        return False

    # -- o laco -------------------------------------------------------------

    def executar(self) -> Resultado:
        r = self.resultado
        lidos = nomes_da_casa(self.caminho_casa, self.rodada)
        # tentado uma vez nesta rajada nao volta: um nome que so da ERRO
        # (sem leitura, entao ainda no alvo) prenderia o laco nele
        tentados: set[str] = set()
        ultimo_disparo = 0

        while True:
            agora = self.relogio()
            if self.ate is not None and agora >= self.ate:
                r.motivo = f"hora-limite ({hora_br(self.ate)})"
                break
            if self.maximo is not None and r.consultas >= self.maximo:
                r.motivo = f"maximo de {self.maximo} consultas"
                break

            self.sincronizar()
            fila = [n for n in self.fila() if n not in tentados]
            if not fila:
                r.motivo = "alvo esgotado"
                break
            if self.maximo is not None:
                fila = fila[:self.maximo - r.consultas]
            prazo = BLOCO_SEGUNDOS
            if self.ate is not None:
                prazo = min(prazo, self.ate - agora)

            r.blocos += 1
            self.relatar(f"bloco {r.blocos}: ate {min(len(fila), por_bloco(self.pausa))} "
                         f"de {len(fila)} nomes, {self.pausa}s entre consultas")
            p = self._nova_varredura().executar(fila, pausa=self.pausa,
                                                prazo=prazo)
            r.consultas += p.feitos
            r.bloqueios += int(p.barrada)
            # o nome que barrou (bloqueio) ou a sequencia de erros que
            # barrou (rede) nao foi lida: fica fora de `tentados` e abre o
            # bloco seguinte, depois do recuo
            feitos_ok = p.feitos - sem_leitura_no_fim(p)
            tentados.update(fila[:feitos_ok])
            lidos.update(fila[:feitos_ok])
            self.comitar(lidos)

            if r.blocos == 1 or (r.blocos - 1) % DISPARO_A_CADA_BLOCOS == 0:
                if self.disparar():
                    ultimo_disparo = r.blocos

            if p.barrada:
                if r.bloqueios >= 2:
                    r.codigo = BARRADA
                    r.motivo = f"barrada de novo ({p.motivo}): parando"
                    break
                self.relatar(f"barrada ({p.motivo}): recuando "
                             f"{RECUO_BLOQUEIO_SEGUNDOS // 60} min e tentando "
                             "mais um bloco")
                self.dormir(RECUO_BLOQUEIO_SEGUNDOS)
                continue

            if p.feitos >= len(fila):
                continue    # o proximo giro ve se sobrou alguem, sem descanso
            self.dormir(DESCANSO_SEGUNDOS)

        if r.blocos and ultimo_disparo != r.blocos:
            self.disparar()
        r.lidos = len(lidos)
        self.relatar(f"fim: {r.motivo}; {r.blocos} blocos, {r.consultas} "
                     f"consultas, {r.commits} commits, {r.disparos} disparos")
        return r
