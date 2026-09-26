"""
Servidor HTTP local.

Apresentacao: so transporte. Recebe requisicao, chama caso de uso ou consulta,
devolve JSON. Nenhuma regra de negocio mora aqui.

Usa apenas a stdlib de proposito: o projeto inteiro roda com `python3 app.py`
numa maquina limpa, sem passo de instalacao.
"""

from __future__ import annotations

import json
import mimetypes
import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from ..adaptadores.registrobr import PAUSA_SEGURA
from ..casos import instantaneo, pool
from ..casos.varredura import Varredura
from ..dominio.marcas import avaliar_dominio
from ..dominio.relevancia import pontuar
from ..adaptadores.repositorio import Candidato, agora
from .consultas import Consultas

PORTA_PADRAO = 8765
NOTA_MINIMA_MANUAL = 50   # nome adicionado a mao nunca some do topo por nota


class Servico:
    """Reune o que as rotas precisam. Uma varredura por vez, por IP."""

    def __init__(self, contexto):
        self.ctx = contexto
        self.repo = contexto.repo
        self.consultas = Consultas(self.repo)
        self.varredura = Varredura(contexto.cliente, self.repo,
                                   contador=getattr(contexto, "contador", None))
        self._thread: threading.Thread | None = None
        self._tarefa = ""

    # -- tarefas de fundo ---------------------------------------------------

    @property
    def ocupado(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def _rodar(self, nome, alvo, *args):
        if self.ocupado:
            return False, "ja existe uma tarefa rodando"
        self._tarefa = nome
        # zera aqui, nao dentro da varredura: ver Varredura.zerar_parada
        self.varredura.zerar_parada()
        self._thread = threading.Thread(target=alvo, args=args, daemon=True)
        self._thread.start()
        return True, "iniciada"

    def importar(self, nota_minima: int, teto: int):
        return self._rodar("importar", self._importar, nota_minima, teto)

    def _importar(self, nota_minima: int, teto: int):
        def aviso(msg):
            self.varredura._atualizar(mensagem=msg, rodando=True)

        try:
            rodada = self.ctx.baixar_rodada(aviso)
            aviso("carregando dicionarios")
            vocabularios = self.ctx.vocabularios.carregar(aviso)
            aviso("montando o pool de candidatos")
            candidatos, resumo = pool.montar(rodada, vocabularios,
                                             nota_minima=nota_minima, teto=teto)
            self.repo.gravar_pool(candidatos)
            self.repo.aplicar_lista_de_leiloes(rodada.em_leilao_em)
            self.repo.encerrar_leiloes_fora_da_lista()
            self.repo.set_meta("importado_em", agora())
            self.repo.set_meta("total_liberacao", rodada.total)
            self.repo.set_meta("total_elegiveis", len(rodada.elegiveis))
            self.repo.set_meta("total_em_leilao", len(rodada.em_leilao))
            if rodada.em_leilao_em:
                self.repo.set_meta("em_leilao_em", rodada.em_leilao_em)
            if rodada.inicio:
                self.repo.set_meta("rodada_inicio", rodada.inicio)
                self.repo.set_meta("rodada_fim", rodada.fim)
            aviso(f"pool com {resumo.total} dominios. agora clique em Verificar.")
        finally:
            self.varredura._atualizar(rodando=False)

    def verificar(self, dominios: list[str], pausa: float):
        return self._rodar("verificar", self.varredura.executar,
                           dominios, pausa)

    def adicionar(self, texto: str):
        """Aceita nomes colados a mao, um por linha ou separados por virgula."""
        nomes = [n.strip().lower()
                 for n in texto.replace(",", "\n").splitlines()
                 if n.strip() and not n.startswith("#")]
        nomes = [n for n in nomes if "." in n]
        if not nomes:
            return []

        vocabularios = self.ctx.vocabularios.carregar()
        elegiveis = set(self.consultas.alvos("elegiveis", 100_000))
        novos = []
        for nome in nomes:
            elegivel = nome in elegiveis
            # a mesma regra do pool: nome posto a mao nao pode ter nota
            # diferente do mesmo nome vindo da lista oficial
            nota = pool.nota_de(nome, vocabularios, elegivel=elegivel)
            marca = pool.marca_de(nome, vocabularios)
            novos.append(Candidato(
                dominio=nome, fonte="manual", elegivel=elegivel,
                nota=max(nota.valor, NOTA_MINIMA_MANUAL),
                motivos=nota.motivos + ("adicionado à mão",),
                risco=marca.risco, motivo_marca=marca.motivo))
        self.repo.gravar_pool(novos)
        return nomes

    def exportar_instantaneo(self) -> dict:
        verificados = self.repo.verificados()
        meta = instantaneo.Metadados(
            gerado_em=agora(),
            total_rodada=int(self.repo.meta("total_liberacao") or 0),
            total_elegiveis=int(self.repo.meta("total_elegiveis") or 0),
            nao_verificados=self.repo.contar("status IS NULL"),
        )
        return instantaneo.exportar(verificados, meta,
                                    serie=self.repo.serie_ritmo(),
                                    primeiro=self.repo.ticket_primeiro())


# ---------------------------------------------------------------------------
# HTTP
# ---------------------------------------------------------------------------

def criar_handler(servico: Servico, diretorio_web: str):
    """Fabrica o handler com o servico ja injetado."""

    class Handler(BaseHTTPRequestHandler):
        server_version = "garimpobr/2.0"

        def log_message(self, *_):
            pass    # o log de acesso so polui o terminal

        # -- utilidades -----------------------------------------------------

        def _responder(self, dados, codigo=200):
            corpo = json.dumps(dados, ensure_ascii=False).encode("utf-8")
            self.send_response(codigo)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(corpo)))
            self.end_headers()
            self.wfile.write(corpo)

        def _corpo(self) -> dict:
            tamanho = int(self.headers.get("Content-Length") or 0)
            if not tamanho:
                return {}
            try:
                return json.loads(self.rfile.read(tamanho).decode("utf-8"))
            except (ValueError, UnicodeDecodeError):
                return {}

        def _arquivo(self, caminho):
            # nao serve nada fora do diretorio web
            caminho = os.path.realpath(caminho)
            if not caminho.startswith(os.path.realpath(diretorio_web)) \
                    or not os.path.isfile(caminho):
                return self._responder({"erro": "nao encontrado"}, 404)
            tipo = mimetypes.guess_type(caminho)[0] or "application/octet-stream"
            with open(caminho, "rb") as f:
                corpo = f.read()
            self.send_response(200)
            self.send_header("Content-Type", f"{tipo}; charset=utf-8")
            self.send_header("Content-Length", str(len(corpo)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(corpo)

        # -- rotas ----------------------------------------------------------

        def do_GET(self):
            url = urlparse(self.path)
            q = parse_qs(url.query)
            def um(chave, padrao=None):
                return q.get(chave, [padrao])[0]

            if url.path in ("/", "/index.html"):
                return self._arquivo(os.path.join(diretorio_web, "index.html"))

            if url.path.startswith("/static/"):
                return self._arquivo(
                    os.path.join(diretorio_web, os.path.basename(url.path)))

            if url.path == "/api/resumo":
                return self._responder(servico.consultas.resumo())

            if url.path == "/api/progresso":
                return self._responder(servico.varredura.instantaneo())

            if url.path == "/api/dominios":
                pagina = servico.consultas.listar(
                    filtro=um("filtro", "joias"),
                    busca=um("busca", "") or "",
                    ordem=um("ordem", "nota"),
                    limite=int(um("limite", 200)),
                    deslocamento=int(um("deslocamento", 0)),
                    esconder_risco=um("risco", "esconder") == "esconder")
                return self._responder({
                    "total": pagina.total,
                    "itens": [servico.consultas.como_dicionario(c)
                              for c in pagina.itens],
                })

            if url.path == "/api/exportar":
                pagina = servico.consultas.listar(
                    filtro=um("filtro", "todos"),
                    busca=um("busca", "") or "",
                    ordem=um("ordem", "nota"),
                    limite=100_000,
                    esconder_risco=um("risco", "esconder") == "esconder")
                linhas = ["dominio,status,candidatos,nota,elegivel,marca"]
                for c in pagina.itens:
                    linhas.append(",".join((
                        c.dominio,
                        c.situacao.value if c.situacao else "",
                        "" if c.candidatos is None else str(c.candidatos),
                        str(c.nota),
                        "sim" if c.elegivel else "nao",
                        c.risco.value)))
                corpo = "\n".join(linhas).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "text/csv; charset=utf-8")
                self.send_header("Content-Disposition",
                                 'attachment; filename="garimpo.csv"')
                self.send_header("Content-Length", str(len(corpo)))
                self.end_headers()
                return self.wfile.write(corpo)

            return self._responder({"erro": "rota desconhecida"}, 404)

        def do_POST(self):
            url = urlparse(self.path)
            dados = self._corpo()

            if url.path == "/api/importar":
                ok, msg = servico.importar(int(dados.get("nota_minima", 45)),
                                           int(dados.get("teto", 20000)))
                return self._responder({"ok": ok, "mensagem": msg},
                                       200 if ok else 409)

            if url.path == "/api/verificar":
                alvos = dados.get("dominios") or servico.consultas.alvos(
                    dados.get("filtro", "elegiveis"),
                    int(dados.get("limite", 200)),
                    bool(dados.get("apenas_nao_verificados")))
                if not alvos:
                    return self._responder(
                        {"ok": False, "mensagem": "nenhum dominio nesse filtro"},
                        400)
                pausa = max(PAUSA_SEGURA, float(dados.get("delay", PAUSA_SEGURA)))
                ok, msg = servico.verificar(alvos, pausa)
                return self._responder(
                    {"ok": ok, "mensagem": msg, "total": len(alvos)},
                    200 if ok else 409)

            if url.path == "/api/parar":
                servico.varredura.pedir_parada()
                return self._responder({"ok": True})

            if url.path == "/api/marcar":
                servico.repo.marcar(dados.get("dominio", ""),
                                    bool(dados.get("marcado")))
                return self._responder({"ok": True})

            if url.path == "/api/anotar":
                servico.repo.anotar(dados.get("dominio", ""),
                                    dados.get("texto", ""))
                return self._responder({"ok": True})

            if url.path == "/api/adicionar":
                novos = servico.adicionar(dados.get("texto", ""))
                if not novos:
                    return self._responder(
                        {"ok": False, "mensagem": "nada valido"}, 400)
                return self._responder({"ok": True, "adicionados": len(novos),
                                        "dominios": novos})

            return self._responder({"erro": "rota desconhecida"}, 404)

    return Handler


def servir(contexto, porta: int = PORTA_PADRAO, abrir_navegador: bool = True):
    servico = Servico(contexto)
    diretorio_web = os.path.join(contexto.raiz, "web")
    handler = criar_handler(servico, diretorio_web)

    url = f"http://localhost:{porta}"
    try:
        servidor = ThreadingHTTPServer(("127.0.0.1", porta), handler)
    except OSError as e:
        if e.errno == 98:   # EADDRINUSE
            raise SystemExit(
                f"a porta {porta} ja esta em uso. Ou o garimpo ja esta "
                f"rodando em {url}, ou use --porta com outro numero.")
        raise

    print(f"garimpo .br rodando em {url}")
    print("ctrl+c para parar")

    if abrir_navegador:
        import webbrowser
        threading.Timer(0.6, lambda: webbrowser.open(url)).start()

    try:
        servidor.serve_forever()
    except KeyboardInterrupt:
        print("\nate mais")
