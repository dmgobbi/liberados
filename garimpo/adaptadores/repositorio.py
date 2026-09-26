"""
Persistencia em SQLite.

Adaptador: o unico lugar do projeto que escreve SQL. Quem chama trabalha com
`Candidato`, nao com linhas.

O banco e descartavel de proposito. Na nuvem ele e reconstruido a cada
execucao e o estado volta de um JSON versionado no git (ver
casos/instantaneo.py). Isso mantem o historico auditavel em vez de preso num
arquivo binario.
"""

from __future__ import annotations

import sqlite3
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone

from ..dominio import frescor
from ..dominio.marcas import Risco
from ..dominio.situacao import (Leitura, Situacao, com_leilao_anunciado,
                                situacao_de)

# marca no `detalhe` de quem virou leilao pela lista, e nao por consulta.
# Nao pode ficar vazio: limpar_contaminados() trata COMPETITIVO sem detalhe
# como bloqueio disfarcado e apagaria a leitura.
DETALHE_DA_LISTA = "fonte=lista-competicao"

ESQUEMA = """
CREATE TABLE IF NOT EXISTS dominios (
    dominio       TEXT PRIMARY KEY,
    fonte         TEXT,
    elegivel      INTEGER DEFAULT 0,
    em_leilao     INTEGER DEFAULT 0,
    nota          INTEGER DEFAULT 0,
    motivos       TEXT,
    status        TEXT,
    status_num    INTEGER,
    candidatos    INTEGER,
    detalhe       TEXT,
    nivel_marca   TEXT,
    motivo_marca  TEXT,
    marcado       INTEGER DEFAULT 0,
    nota_pessoal  TEXT,
    verificado_em TEXT
);
CREATE INDEX IF NOT EXISTS idx_status  ON dominios(status);
CREATE INDEX IF NOT EXISTS idx_nota    ON dominios(nota);
CREATE INDEX IF NOT EXISTS idx_marcado ON dominios(marcado);

CREATE TABLE IF NOT EXISTS meta (
    chave TEXT PRIMARY KEY,
    valor TEXT
);
-- o ritmo da rodada: em tal instante, o maior ticket ja visto era tal
-- (dominio/ritmo.py). Um ponto por avanco, nunca por consulta.
CREATE TABLE IF NOT EXISTS ritmo (
    observado_em INTEGER NOT NULL,
    ticket       INTEGER NOT NULL PRIMARY KEY
);
"""

# colunas adicionadas depois da primeira versao do esquema
MIGRACOES = (
    ("em_leilao", "ALTER TABLE dominios ADD COLUMN em_leilao INTEGER DEFAULT 0"),
    # 12/09/2026: os tickets de cada nome (menor e maior visivel) e a
    # estimativa de quando chegaram, em segundos UTC. Os numeros ficam no
    # banco; so a estimativa vai para o site.
    ("ticket_min", "ALTER TABLE dominios ADD COLUMN ticket_min INTEGER"),
    ("ticket_max", "ALTER TABLE dominios ADD COLUMN ticket_max INTEGER"),
    ("chegada_min", "ALTER TABLE dominios ADD COLUMN chegada_min INTEGER"),
    ("chegada_max", "ALTER TABLE dominios ADD COLUMN chegada_max INTEGER"),
)


def agora() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


@dataclass
class Candidato:
    """Um dominio no pool, com o que sabemos dele."""

    dominio: str
    fonte: str = "liberacao"
    elegivel: bool = False
    em_leilao: bool = False
    nota: int = 0
    motivos: tuple[str, ...] = ()
    situacao: Situacao | None = None
    candidatos: int | None = None
    detalhe: str = ""
    risco: Risco = Risco.OK
    motivo_marca: str = ""
    marcado: bool = False
    verificado_em: str | None = None
    # ritmo: os tickets vistos (banco) e quando chegaram (estimativa, site)
    ticket_min: int | None = None
    ticket_max: int | None = None
    chegada_min: int | None = None      # epoch UTC do primeiro concorrente
    chegada_max: int | None = None      # epoch UTC do ultimo visivel

    @property
    def verificado(self) -> bool:
        return self.situacao is not None

    @property
    def situacao_atual(self) -> Situacao | None:
        """A leitura corrigida pela lista oficial de leiloes."""
        return com_leilao_anunciado(self.situacao, self.em_leilao)

    @property
    def joia(self) -> bool:
        """Elegivel ao leilao e sem candidato visivel: o melhor cruzamento."""
        return self.elegivel and self.situacao_atual is Situacao.LIBERACAO_LIVRE

    @classmethod
    def da_linha(cls, r: sqlite3.Row) -> "Candidato":
        chaves = r.keys()
        return cls(
            dominio=r["dominio"],
            fonte=r["fonte"] or "liberacao",
            elegivel=bool(r["elegivel"]),
            em_leilao=bool(r["em_leilao"]) if "em_leilao" in chaves else False,
            nota=r["nota"] or 0,
            motivos=tuple(m.strip() for m in (r["motivos"] or "").split(";")
                          if m.strip()),
            situacao=situacao_de(r["status"]) if r["status"] else None,
            candidatos=r["candidatos"],
            detalhe=r["detalhe"] or "",
            risco=Risco(r["nivel_marca"]) if r["nivel_marca"] in
                  Risco._value2member_map_ else Risco.OK,
            motivo_marca=r["motivo_marca"] or "",
            marcado=bool(r["marcado"]),
            verificado_em=r["verificado_em"],
            ticket_min=r["ticket_min"] if "ticket_min" in chaves else None,
            ticket_max=r["ticket_max"] if "ticket_max" in chaves else None,
            chegada_min=r["chegada_min"] if "chegada_min" in chaves else None,
            chegada_max=r["chegada_max"] if "chegada_max" in chaves else None,
        )


class Repositorio:
    """
    Acesso ao banco. Uma conexao por thread, porque o servidor web atende
    cada requisicao numa thread e sqlite3 nao gosta de conexao compartilhada.
    """

    def __init__(self, caminho: str):
        self.caminho = caminho
        self._local = threading.local()

    # -- conexao ------------------------------------------------------------

    @property
    def con(self) -> sqlite3.Connection:
        if getattr(self._local, "con", None) is None:
            con = sqlite3.connect(self.caminho, timeout=30)
            con.row_factory = sqlite3.Row
            con.execute("PRAGMA journal_mode=WAL")
            con.executescript(ESQUEMA)
            self._migrar(con)
            self._local.con = con
        return self._local.con

    @staticmethod
    def _migrar(con: sqlite3.Connection) -> None:
        existentes = {r["name"] for r in con.execute("PRAGMA table_info(dominios)")}
        for coluna, sql in MIGRACOES:
            if coluna not in existentes:
                con.execute(sql)
        con.commit()

    def fechar(self) -> None:
        con = getattr(self._local, "con", None)
        if con is not None:
            con.close()
            self._local.con = None

    # -- meta ---------------------------------------------------------------

    def set_meta(self, chave: str, valor) -> None:
        self.con.execute(
            "INSERT INTO meta(chave, valor) VALUES(?, ?) "
            "ON CONFLICT(chave) DO UPDATE SET valor=excluded.valor",
            (chave, str(valor)))
        self.con.commit()

    def meta(self, chave: str, padrao=None):
        linha = self.con.execute("SELECT valor FROM meta WHERE chave=?",
                                 (chave,)).fetchone()
        return linha["valor"] if linha else padrao

    # -- escrita ------------------------------------------------------------

    def gravar_pool(self, candidatos) -> int:
        """
        Insere ou atualiza o pool. Nao toca em status, candidatos, marcado nem
        nota_pessoal: aquilo e resultado de varredura e escolha do usuario, e
        remontar o pool nao pode apagar nenhum dos dois.
        """
        linhas = [(c.dominio, c.fonte, int(c.elegivel), int(c.em_leilao),
                   c.nota, "; ".join(c.motivos), c.risco.value, c.motivo_marca)
                  for c in candidatos]
        self.con.executemany("""
            INSERT INTO dominios (dominio, fonte, elegivel, em_leilao, nota,
                                  motivos, nivel_marca, motivo_marca)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(dominio) DO UPDATE SET
                fonte        = excluded.fonte,
                elegivel     = excluded.elegivel,
                em_leilao    = excluded.em_leilao,
                nota         = excluded.nota,
                motivos      = excluded.motivos,
                nivel_marca  = excluded.nivel_marca,
                motivo_marca = excluded.motivo_marca
        """, linhas)
        self.con.commit()
        return len(linhas)

    def gravar_leitura(self, dominio: str, leitura: Leitura,
                       epoch: int | None = None) -> None:
        tickets = leitura.tickets
        if tickets:
            ticket_min, ticket_max = min(tickets), max(tickets)
        else:
            ticket_min = ticket_max = None
        self.con.execute("""
            UPDATE dominios
               SET status=?, status_num=?, candidatos=?, detalhe=?,
                   verificado_em=?, ticket_min=?, ticket_max=?
             WHERE dominio=?
        """, (leitura.situacao.value, leitura.status_bruto, leitura.candidatos,
              leitura.detalhe, agora(), ticket_min, ticket_max, dominio))
        if tickets:
            self._anotar_ritmo(epoch if epoch is not None else int(time.time()),
                               ticket_min, ticket_max)
        self.con.commit()

    # -- ritmo da rodada ----------------------------------------------------

    def _anotar_ritmo(self, epoch: int, menor: int, maior: int) -> None:
        primeiro = self.ticket_primeiro()
        if primeiro is None or menor < primeiro:
            self.con.execute(
                "INSERT INTO meta(chave, valor) VALUES('ticket_primeiro', ?) "
                "ON CONFLICT(chave) DO UPDATE SET valor=excluded.valor", (str(menor),))
        ultimo = self.con.execute("SELECT MAX(ticket) m FROM ritmo").fetchone()["m"]
        if ultimo is None or maior > ultimo:
            self.con.execute("INSERT OR IGNORE INTO ritmo(observado_em, ticket) "
                             "VALUES(?, ?)", (epoch, maior))

    def ticket_primeiro(self) -> int | None:
        valor = self.meta("ticket_primeiro")
        return int(valor) if valor and str(valor).isdigit() else None

    def serie_ritmo(self) -> list[tuple[int, int]]:
        return [(r["observado_em"], r["ticket"]) for r in self.con.execute(
            "SELECT observado_em, ticket FROM ritmo ORDER BY ticket")]

    def restaurar_ritmo(self, serie, primeiro: int | None) -> int:
        """Repoe a serie do instantaneo anterior. Pontos repetidos nao entram."""
        pontos = [(int(e), int(t)) for e, t in serie or []]
        if pontos:
            self.con.executemany(
                "INSERT OR IGNORE INTO ritmo(observado_em, ticket) VALUES(?, ?)",
                pontos)
        if primeiro is not None:
            atual = self.ticket_primeiro()
            if atual is None or primeiro < atual:
                self.set_meta("ticket_primeiro", primeiro)
        self.con.commit()
        return len(pontos)

    def restaurar(self, candidatos) -> int:
        """
        Repoe resultados de um instantaneo anterior.

        Insere a linha quando ela nao existe. Isso importa: o pool e remontado
        a partir da lista oficial, que muda o tempo todo, e um dominio ja
        verificado que saiu do pool nao teria linha para atualizar. Com UPDATE
        puro uma execucao devolveu 818 dominios tendo recebido 859.

        A leitura mais nova manda, venha de onde vier (19/09/2026). Antes um
        COALESCE deixava o banco vencer sempre, e uma leitura feita fora do
        GitHub (a de casa, que o varrer.py repoe) perdia para a mais velha
        que o instantaneo tinha acabado de repor. A comparacao e em segundos, em Python: o
        banco mistura -03:00 (maquina de casa) e +00:00 (runner), e como
        texto 22:00-03:00 viria antes de 00:30+00:00. Empate fica com o banco.

        Quando o instantaneo vence, o que era da leitura velha do banco
        (detalhe, status bruto, tickets) sai junto: os tickets velhos
        refariam a estimativa de chegada por cima da que veio no JSON.
        """
        candidatos = list(candidatos)
        if not candidatos:
            return 0
        no_banco = {r["dominio"]: (r["status"], r["verificado_em"])
                    for r in self.con.execute(
                        "SELECT dominio, status, verificado_em FROM dominios")}

        novos, trocar = [], []
        for c in candidatos:
            status = c.situacao.value if c.situacao else None
            if c.dominio not in no_banco:
                novos.append((c.dominio, c.nota, int(c.elegivel),
                              "; ".join(c.motivos), c.risco.value, status,
                              c.candidatos, c.verificado_em, c.chegada_min,
                              c.chegada_max))
                continue
            if status is None:
                continue
            status_banco, quando_banco = no_banco[c.dominio]
            if (status_banco is None or (frescor.epoch(c.verificado_em) or 0)
                    > (frescor.epoch(quando_banco) or 0)):
                trocar.append((status, c.candidatos, c.verificado_em,
                               c.chegada_min, c.chegada_max, c.dominio))

        self.con.executemany("""
            INSERT INTO dominios (dominio, fonte, nota, elegivel, motivos,
                                  nivel_marca, status, candidatos, verificado_em,
                                  chegada_min, chegada_max)
            VALUES (?, 'historico', ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(dominio) DO NOTHING
        """, novos)
        self.con.executemany("""
            UPDATE dominios
               SET status=?, candidatos=?, verificado_em=?, chegada_min=?,
                   chegada_max=?, detalhe=NULL, status_num=NULL,
                   ticket_min=NULL, ticket_max=NULL
             WHERE dominio=?
        """, trocar)
        self.con.commit()

        # conta o que de fato ficou com status, nao o que foi tentado: era
        # justamente esse engano que escondia a perda de 41 dominios
        nomes = {c.dominio for c in candidatos}
        return sum(1 for r in self.con.execute(
            "SELECT dominio FROM dominios WHERE status IS NOT NULL")
            if r["dominio"] in nomes)

    def aplicar_lista_de_leiloes(self, quando: str | None = None) -> int:
        """
        Grava como observacao o que a lista oficial de leiloes ja sabe.

        `em_leilao` vem de lista-competicao.txt a cada gravar_pool(). Quem esta
        nela e ainda consta como em liberacao passa a COMPETITIVO, com a data
        da propria lista. A contagem de candidatos fica como estava: a lista
        diz que ha leilao, nao quantos tickets. Inventar um numero seria
        trocar um dado errado por outro.
        """
        cur = self.con.execute("""
            UPDATE dominios
               SET status=?, detalhe=?, verificado_em=?
             WHERE em_leilao = 1 AND status IN (?, ?)
        """, (Situacao.COMPETITIVO.value, DETALHE_DA_LISTA, quando or agora(),
              Situacao.LIBERACAO_LIVRE.value,
              Situacao.LIBERACAO_DISPUTADA.value))
        self.con.commit()
        return cur.rowcount

    def encerrar_leiloes_fora_da_lista(self) -> int:
        """
        O outro sentido de `aplicar_lista_de_leiloes`: quem SAIU da lista.

        A lista oficial manda nos dois sentidos, e ate 17/09/2026 so mandava
        num: nada rebaixava um COMPETITIVO ja gravado quando o nome deixava
        `lista-competicao.txt`. O leilao acabou, mas a leitura antiga seguia
        dizendo "leilao aberto" ate o nome ser reconsultado um por um — com
        16 mil nomes na fila, dias. E a mesma armadilha das "joias falsas"
        de 10/09: tela decidindo por leitura velha contra a lista nova.

        Nao da para adivinhar o desfecho (quem levou, ou se travou e volta),
        entao a leitura e apagada em vez de trocada por um palpite: o nome
        volta para a fila da varredura e o proximo avail diz o que houve. Sao
        poucos por rodada, e a classe de leilao tem prioridade no frescor.
        """
        cur = self.con.execute("""
            UPDATE dominios
               SET status=NULL, status_num=NULL, candidatos=NULL,
                   detalhe=NULL, verificado_em=NULL
             WHERE em_leilao = 0 AND status = ?
        """, (Situacao.COMPETITIVO.value,))
        self.con.commit()
        return cur.rowcount

    def marcar(self, dominio: str, marcado: bool) -> None:
        self.con.execute("UPDATE dominios SET marcado=? WHERE dominio=?",
                         (int(marcado), dominio))
        self.con.commit()

    def anotar(self, dominio: str, texto: str) -> None:
        self.con.execute("UPDATE dominios SET nota_pessoal=? WHERE dominio=?",
                         (texto, dominio))
        self.con.commit()

    def esquecer_leituras(self) -> int:
        """
        Zera todas as leituras, mantendo o pool e o que o usuario marcou.

        Usado quando a rodada vira: a lista muda inteira todo mes, e o
        resultado do mes passado nao diz nada sobre a disputa deste mes.
        """
        cur = self.con.execute("""
            UPDATE dominios SET status=NULL, status_num=NULL, candidatos=NULL,
                                detalhe=NULL, verificado_em=NULL,
                                ticket_min=NULL, ticket_max=NULL,
                                chegada_min=NULL, chegada_max=NULL
             WHERE status IS NOT NULL
        """)
        self.con.execute("DELETE FROM dominios WHERE fonte='historico'")
        # o contador de tickets nao zera entre rodadas, mas a curva e por
        # rodada: comeca de novo
        self.con.execute("DELETE FROM ritmo")
        self.con.execute("DELETE FROM meta WHERE chave='ticket_primeiro'")
        self.con.commit()
        return cur.rowcount

    def esquecer_leituras_antes(self, inicio: str | None) -> int:
        """
        Zera as leituras feitas antes da abertura da rodada (18/09/2026).

        Entre a saida da lista e a abertura, um nome travado deve responder
        status 5 (AGUARDANDO_LIBERACAO; medido so depois do fechamento, S16;
        a confirmar no dia da lista, 12/10), que o frescor trata como fixo e o
        site como "volta na proxima rodada". Vale para qualquer status lido
        antes da abertura. Aberta a rodada, essa leitura e de outra
        fase: apagada, o nome volta a fila e o site o mostra como ainda nao
        verificado, em vez de travado. O banco guarda texto com fuso local,
        entao a comparacao e em segundos (frescor.epoch), nao em SQL.
        """
        limite = frescor.epoch(inicio)
        if limite is None:
            return 0
        velhos = [(d,) for d, quando in self.con.execute(
                      "SELECT dominio, verificado_em FROM dominios "
                      "WHERE verificado_em IS NOT NULL")
                  if (frescor.epoch(quando) or 0) < limite]
        self.con.executemany("""
            UPDATE dominios SET status=NULL, status_num=NULL, candidatos=NULL,
                                detalhe=NULL, verificado_em=NULL,
                                ticket_min=NULL, ticket_max=NULL,
                                chegada_min=NULL, chegada_max=NULL
             WHERE dominio=?
        """, velhos)
        self.con.commit()
        return len(velhos)

    def limpar_contaminados(self) -> int:
        """
        Apaga leituras que foram bloqueio disfarcado de leilao.

        Um COMPETITIVO legitimo sempre traz `ends-at` no detalhe; sem isso a
        resposta era "Taxa maxima de consultas excedida" classificada errado.
        """
        cur = self.con.execute("""
            UPDATE dominios
               SET status=NULL, status_num=NULL, candidatos=NULL,
                   detalhe=NULL, verificado_em=NULL
             WHERE status IS NOT NULL
               AND ((status='COMPETITIVO' AND (detalhe IS NULL OR detalhe=''))
                    OR status IN ('LIMITADO','ERRO','INDESCONHECIDO'))
        """)
        self.con.commit()
        return cur.rowcount

    # -- leitura ------------------------------------------------------------

    def um(self, dominio: str) -> Candidato | None:
        linha = self.con.execute("SELECT * FROM dominios WHERE dominio=?",
                                 (dominio,)).fetchone()
        return Candidato.da_linha(linha) if linha else None

    def buscar(self, onde: str = "1=1", parametros=(), ordem: str = "nota DESC",
               limite: int = 200, deslocamento: int = 0) -> list[Candidato]:
        linhas = self.con.execute(
            f"SELECT * FROM dominios WHERE {onde} ORDER BY {ordem} "
            f"LIMIT ? OFFSET ?", (*parametros, limite, deslocamento)).fetchall()
        return [Candidato.da_linha(l) for l in linhas]

    def contar(self, onde: str = "1=1", parametros=()) -> int:
        return self.con.execute(
            f"SELECT COUNT(*) c FROM dominios WHERE {onde}",
            parametros).fetchone()["c"]

    def dominios_de(self, onde: str, ordem: str, limite: int) -> list[str]:
        return [r["dominio"] for r in self.con.execute(
            f"SELECT dominio FROM dominios WHERE {onde} ORDER BY {ordem} "
            f"LIMIT ?", (limite,))]

    def verificados(self) -> list[Candidato]:
        return self.buscar(onde="status IS NOT NULL",
                           ordem="nota DESC, LENGTH(dominio) ASC, dominio ASC",
                           limite=1_000_000)

    def distribuicao(self) -> dict[str, int]:
        return {r["status"]: r["c"] for r in self.con.execute(
            "SELECT status, COUNT(*) c FROM dominios "
            "WHERE status IS NOT NULL GROUP BY status")}
