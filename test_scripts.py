#!/usr/bin/env python3
"""
Testes das funcoes puras e dos casos de uso (sem rede, sem banco de verdade).

    python3 -m unittest -v test_scripts.py

Os payloads sao respostas reais do endpoint de disponibilidade, capturadas em
09/09/2026. Se o Registro.br mudar o formato, estes testes quebram e voce sabe
que precisa reajustar garimpo/dominio/situacao.py.

O teste mais importante do arquivo e TestBloqueioDisfarcado: o bloqueio por
excesso de consultas volta com HTTP 200 e status 8, que e o mesmo bit de
processo competitivo, e ja transformou 370 respostas bloqueadas em falsos
"dominios em leilao".
"""

import contextlib
import datetime
import io
import re
import subprocess
import json
import os
import tempfile
import unittest
import unittest.mock

from filtrar_lista import separar as separar_antigo
from filtrar_lista import sem_acento
from garimpo.adaptadores.repositorio import Candidato, Repositorio
from garimpo.adaptadores import isavail, rdap, wayback
from garimpo.casos import historias, instantaneo, pool
from garimpo.dominio import extensoes
from garimpo.casos.varredura import Varredura
from garimpo.dominio.marcas import Risco, avaliar
from garimpo.dominio.relevancia import pontuar, separar
from garimpo.dominio.situacao import Leitura, Situacao, classificar


# Nucleo aberto (25/09/2026): o repositorio publico nao leva o conteudo
# fechado (insights, paginas editoriais, pesquisa em docs/, estado em
# docs/historico/, a operacao do dono). Teste que le um desses arquivos
# pula quando ele nao existe, em vez de reprovar num clone do publico.
_RAIZ_TESTES = os.path.dirname(os.path.abspath(__file__))


def so_com(*caminhos):
    """Pula o teste (ou a classe) se algum dos caminhos nao existe aqui."""
    faltam = [c for c in caminhos if not os.path.exists(os.path.join(_RAIZ_TESTES, c))]
    return unittest.skipIf(faltam, f"conteudo fechado, so no repositorio de trabalho: {', '.join(faltam)}")

# --------------------------------------------------------------------------
# respostas reais, encurtadas
# --------------------------------------------------------------------------
LIVRE = {"status": 0, "fqdn": "zzzzqwertyx9.com.br"}
REGISTRADO = {"status": 2, "fqdn": "google.com.br",
              "publication-status": "published",
              "expires-at": "2027-05-18T00:00:00-03:00"}
LIBERACAO_SEM_CANDIDATO = {"status": 6, "fqdn": "anabolizantes.com.br",
                           "ends-at": "2026-09-16T15:00:00-03:00"}
LIBERACAO_DISPUTADA = {"status": 7, "fqdn": "medidas.com.br",
                       "tickets": [30001101, 30001102],
                       "ends-at": "2026-09-16T15:00:00-03:00"}
COMPETITIVO = {"status": 9, "fqdn": "combustiveis.com.br",
               "tickets": [30002201, 30002202],
               "ends-at": "2026-09-16T15:00:00-03:00",
               "accepting-new-tickets-until": "2026-09-16T15:00:00-03:00"}

# O bloqueio: HTTP 200, status 8, fqdn vazio.
LIMITE_EXCEDIDO = {"status": 8, "fqdn": "", "fqdnace": "", "exempt": False,
                   "reasons": ["Taxa máxima de consultas excedida"]}
LIMITE_SEM_MOTIVO = {"status": 8, "fqdn": "", "fqdnace": "", "exempt": False}


class TestClassificar(unittest.TestCase):
    def test_livre(self):
        self.assertIs(classificar(LIVRE).situacao, Situacao.LIVRE)

    def test_registrado(self):
        leitura = classificar(REGISTRADO)
        self.assertIs(leitura.situacao, Situacao.REGISTRADO)
        self.assertEqual(leitura.candidatos, 0)
        self.assertIn("expires-at", leitura.detalhe)

    def test_liberacao_sem_candidato(self):
        """O alvo do garimpo: pode sair pela anuidade normal."""
        leitura = classificar(LIBERACAO_SEM_CANDIDATO)
        self.assertIs(leitura.situacao, Situacao.LIBERACAO_LIVRE)
        self.assertEqual(leitura.candidatos, 0)

    def test_liberacao_disputada(self):
        leitura = classificar(LIBERACAO_DISPUTADA)
        self.assertIs(leitura.situacao, Situacao.LIBERACAO_DISPUTADA)
        self.assertEqual(leitura.candidatos, 2)

    def test_competitivo(self):
        leitura = classificar(COMPETITIVO)
        self.assertIs(leitura.situacao, Situacao.COMPETITIVO)
        self.assertEqual(leitura.candidatos, 2)
        self.assertIn("accepting-new-tickets-until", leitura.detalhe)

    def test_resposta_invalida(self):
        self.assertIs(classificar("nao e json").situacao, Situacao.ERRO)
        self.assertIs(classificar({"status": "x"}).situacao,
                      Situacao.INDESCONHECIDO)


class TestBloqueioDisfarcado(unittest.TestCase):
    """Regressao do bug que rotulou 370 dominios como leilao."""

    def test_limite_excedido_nao_e_leilao(self):
        leitura = classificar(LIMITE_EXCEDIDO)
        self.assertIs(leitura.situacao, Situacao.LIMITADO)
        self.assertIsNot(leitura.situacao, Situacao.COMPETITIVO)
        self.assertTrue(leitura.limitado)
        self.assertEqual(leitura.candidatos, 0)
        self.assertIn("Taxa", leitura.detalhe)

    def test_limite_sem_campo_reasons(self):
        """Rede de seguranca: sem fqdn e status 8 tambem e bloqueio."""
        self.assertIs(classificar(LIMITE_SEM_MOTIVO).situacao, Situacao.LIMITADO)

    def test_leilao_de_verdade_tem_fqdn_e_prazo(self):
        """O que separa leilao real de bloqueio."""
        leitura = classificar(COMPETITIVO)
        self.assertTrue(COMPETITIVO["fqdn"])
        self.assertIn("ends-at", leitura.detalhe)

    def test_bloqueio_nao_e_situacao_resolvida(self):
        """Bloqueio nao pode ser gravado como se fosse fato."""
        self.assertFalse(classificar(LIMITE_EXCEDIDO).situacao.resolvida)
        self.assertTrue(classificar(COMPETITIVO).situacao.resolvida)


class TestCandidatoOculto(unittest.TestCase):
    """
    O Registro.br documenta que so informa tickets com mais de um candidato,
    entao LIBERACAO_LIVRE quer dizer "zero ou um".
    """

    def test_um_candidato_e_indistinguivel_de_zero(self):
        # nao existe payload com exatamente 1 ticket: o endpoint omite
        um_candidato_como_o_endpoint_devolve = LIBERACAO_SEM_CANDIDATO
        leitura = classificar(um_candidato_como_o_endpoint_devolve)
        self.assertEqual(leitura.candidatos, 0)
        self.assertIs(leitura.situacao, Situacao.LIBERACAO_LIVRE)

    def test_dois_candidatos_ja_aparecem(self):
        self.assertEqual(classificar(LIBERACAO_DISPUTADA).candidatos, 2)


class TestRelevancia(unittest.TestCase):
    PT = {"vaca", "muro", "botica"}
    EN = {"farm", "hunt"}

    def test_curto_em_portugues_pontua_mais_que_longo(self):
        curto = pontuar("vaca.com.br", self.PT, self.EN)
        longo = pontuar("umnomemuitocompridoassim.com.br", self.PT, self.EN)
        self.assertGreater(curto.valor, longo.valor)

    def test_portugues_vale_mais_que_ingles(self):
        pt = pontuar("muro.com.br", self.PT, self.EN)
        en = pontuar("farm.com.br", self.PT, self.EN)
        self.assertGreater(pt.valor, en.valor)

    def test_elegivel_ao_leilao_soma(self):
        sem = pontuar("botica.com.br", self.PT, self.EN)
        com = pontuar("botica.com.br", self.PT, self.EN, elegivel=True)
        self.assertGreater(com.valor, sem.valor)
        self.assertIn("elegível ao leilão", com.motivos)

    def test_nicho_comercial_e_reconhecido(self):
        nota = pontuar("creditoimobiliario.com.br", self.PT, self.EN)
        self.assertTrue(any("nicho" in m for m in nota.motivos))

    def test_nota_fica_entre_0_e_100(self):
        for nome in ("a.com.br", "vaca.com.br", "xxx.com.br", "naoalfanumerico1.com.br"):
            self.assertTrue(0 <= pontuar(nome, self.PT, self.EN).valor <= 100)

    def test_separar(self):
        self.assertEqual(separar("combustiveis.com.br"), ("combustiveis", "com.br"))
        self.assertEqual(separar("doc.app.br"), ("doc", "app.br"))
        self.assertEqual(separar("semponto"), (None, None))


class TestMarcas(unittest.TestCase):
    def test_generico_e_ok(self):
        self.assertEqual(avaliar("vacina").risco, Risco.OK)
        self.assertEqual(avaliar("moradias").risco, Risco.OK)

    def test_marca_conhecida(self):
        self.assertEqual(avaliar("netflix").risco, Risco.RISCO)

    def test_typosquat(self):
        self.assertEqual(avaliar("googles").risco, Risco.RISCO)
        self.assertEqual(avaliar("airnb").risco, Risco.RISCO)

    def test_marca_embutida(self):
        avaliacao = avaliar("lojanike")
        self.assertEqual(avaliacao.risco, Risco.ATENCAO)
        self.assertIn("nike", avaliacao.motivo)

    def test_sigla_curta(self):
        self.assertEqual(avaliar("xyz").risco, Risco.ATENCAO)

    def test_desempacota_como_tupla(self):
        """O codigo antigo faz `nivel, motivo = avaliar(x)`."""
        nivel, motivo = avaliar("netflix")
        self.assertEqual(nivel, "RISCO")
        self.assertIn("netflix", motivo)

    def test_marcas_compostas_do_top10_de_setembro(self):
        """brasiltelecom e brfoods abriram o ranking de /dados/ como OK
        (achado produto-ceo:ranking-marca-no-titulo, S18): a lista fixa
        tinha "oi" e "brf", nao os nomes compostos que o Registro.br mostra."""
        for nome in ("brasiltelecom", "brfoods", "brasilfoods"):
            self.assertEqual(avaliar(nome).risco, Risco.RISCO, nome)

    def test_farm_e_marca_conhecida(self):
        """FARM Rio: ~130 lojas, grife da Azzas 2154 (maior grupo de moda
        da America Latina), estava no top 10 de setembro como OK."""
        self.assertEqual(avaliar("farm").risco, Risco.RISCO)

    def test_marca_curta_ainda_pega_substring_generica(self):
        """farm entrar na lista fixa tem o mesmo efeito colateral que azul
        (ja aceito: azulejo vira ATENCAO por causa da Azul aerea) -- nao e
        regressao nova, e o MINIMO_SUBSTRING de sempre."""
        self.assertEqual(avaliar("azulejo").risco, Risco.ATENCAO)
        self.assertEqual(avaliar("farmacia").risco, Risco.ATENCAO)

    def test_parece_marca_e_so_o_reconhecimento_por_nome(self):
        """parece_marca() reavalia na hora de montar a pagina (paginas.py),
        sem o instantaneo: por isso nao tem sigla curta (nao e sobre marca)
        nem site popular (pede o Tranco, que a pagina nao tem)."""
        from garimpo.dominio.marcas import parece_marca, parece_marca_dominio
        self.assertTrue(parece_marca("brasiltelecom"))
        self.assertTrue(parece_marca("lojanike"))          # marca embutida
        self.assertTrue(parece_marca("googles"))            # typosquat
        self.assertFalse(parece_marca("xyz"))               # sigla curta: nao conta aqui
        self.assertFalse(parece_marca("vacina"))
        self.assertTrue(parece_marca_dominio("brasiltelecom.com.br"))


class TestInstantaneo(unittest.TestCase):
    def _amostra(self):
        return [
            Candidato("muro.com.br", elegivel=True, em_leilao=True, nota=100,
                      motivos=("nome curto", "palavra em portugues"),
                      situacao=Situacao.COMPETITIVO, candidatos=4),
            Candidato("botica.com.br", nota=75, motivos=("nome curto",),
                      situacao=Situacao.LIBERACAO_LIVRE, candidatos=0),
            Candidato("bloqueado.com.br", nota=50,
                      situacao=Situacao.LIMITADO, candidatos=0),
        ]

    def test_ida_e_volta_preserva_o_essencial(self):
        meta = instantaneo.Metadados(gerado_em="2026-09-09T21:00:00-03:00")
        dados = instantaneo.exportar(self._amostra(), meta)
        voltou = {c.dominio: c for c in instantaneo.candidatos_de(dados)}

        self.assertIn("muro.com.br", voltou)
        muro = voltou["muro.com.br"]
        self.assertIs(muro.situacao, Situacao.COMPETITIVO)
        self.assertEqual(muro.candidatos, 4)
        self.assertEqual(muro.nota, 100)
        self.assertTrue(muro.elegivel)
        self.assertIn("nome curto", muro.motivos)

    def test_bloqueado_fica_de_fora(self):
        """LIMITADO nao e fato: sai do JSON para ser reconsultado depois."""
        dados = instantaneo.exportar(
            self._amostra(), instantaneo.Metadados(gerado_em="agora"))
        self.assertNotIn("bloqueado.com.br",
                         [i[0] for i in dados["itens"]])


class TestRepositorio(unittest.TestCase):
    def setUp(self):
        self.arquivo = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.arquivo.close()
        self.repo = Repositorio(self.arquivo.name)

    def tearDown(self):
        self.repo.fechar()
        os.unlink(self.arquivo.name)

    def test_gravar_pool_nao_apaga_resultado(self):
        c = Candidato("teste.com.br", nota=50)
        self.repo.gravar_pool([c])
        self.repo.gravar_leitura("teste.com.br",
                                 Leitura(Situacao.LIBERACAO_LIVRE, 0, "x", 6))

        # remontar o pool nao pode perder o que ja foi verificado
        self.repo.gravar_pool([Candidato("teste.com.br", nota=70)])
        guardado = self.repo.um("teste.com.br")
        self.assertIs(guardado.situacao, Situacao.LIBERACAO_LIVRE)
        self.assertEqual(guardado.nota, 70)

    def test_restaurar_insere_quem_saiu_do_pool(self):
        """
        Regressao: com UPDATE puro, uma execucao devolveu 818 tendo 859.
        Dominio que saiu da lista oficial nao pode sumir do historico.
        """
        historico = [Candidato("sumiu.com.br", nota=60,
                               situacao=Situacao.LIBERACAO_LIVRE, candidatos=0)]
        self.repo.gravar_pool([Candidato("outro.com.br", nota=10)])

        restaurados = self.repo.restaurar(historico)
        self.assertEqual(restaurados, 1)
        self.assertIsNotNone(self.repo.um("sumiu.com.br"))

    def test_restaurar_nao_sobrescreve_o_mais_novo(self):
        self.repo.gravar_pool([Candidato("x.com.br", nota=50)])
        self.repo.gravar_leitura("x.com.br",
                                 Leitura(Situacao.COMPETITIVO, 5, "novo", 9))
        self.repo.restaurar([Candidato("x.com.br", nota=50,
                                       situacao=Situacao.LIBERACAO_LIVRE,
                                       candidatos=0)])
        self.assertIs(self.repo.um("x.com.br").situacao, Situacao.COMPETITIVO)

    def _restaurar_duas(self, primeiro, segundo):
        self.repo.gravar_pool([Candidato("x.com.br", nota=50)])
        for quando, situacao in (primeiro, segundo):
            self.repo.restaurar([Candidato("x.com.br", nota=50,
                                           situacao=situacao, candidatos=1,
                                           verificado_em=quando)])
        return self.repo.um("x.com.br")

    def test_restaurar_fica_a_leitura_mais_nova(self):
        """19/09/2026: o COALESCE deixava o banco vencer sempre."""
        t1 = ("2026-10-15T10:00:00-03:00", Situacao.LIBERACAO_LIVRE)
        t2 = ("2026-10-15T12:00:00-03:00", Situacao.LIBERACAO_DISPUTADA)
        self.assertIs(self._restaurar_duas(t1, t2).situacao,
                      Situacao.LIBERACAO_DISPUTADA)

    def test_restaurar_nao_troca_por_leitura_mais_velha(self):
        t1 = ("2026-10-15T12:00:00-03:00", Situacao.LIBERACAO_DISPUTADA)
        t0 = ("2026-10-15T10:00:00-03:00", Situacao.LIBERACAO_LIVRE)
        guardado = self._restaurar_duas(t1, t0)
        self.assertIs(guardado.situacao, Situacao.LIBERACAO_DISPUTADA)
        self.assertEqual(guardado.verificado_em, t1[0])

    def test_restaurar_compara_fusos_em_segundos(self):
        """22:00-03:00 e 01:00 UTC: vence 00:30+00:00, embora o texto diga o contrario."""
        casa = ("2026-10-14T22:00:00-03:00", Situacao.LIBERACAO_DISPUTADA)
        runner = ("2026-10-15T00:30:00+00:00", Situacao.LIBERACAO_LIVRE)
        for ordem in ((casa, runner), (runner, casa)):
            self.repo.esquecer_leituras()
            self.assertIs(self._restaurar_duas(*ordem).situacao,
                          Situacao.LIBERACAO_DISPUTADA, ordem)

    def test_restaurar_mais_novo_leva_junto_os_tickets_velhos(self):
        """Tickets da leitura vencida refariam a chegada por cima da do JSON."""
        self.repo.gravar_pool([Candidato("x.com.br", nota=50)])
        self.repo.gravar_leitura("x.com.br", Leitura(
            Situacao.LIBERACAO_DISPUTADA, 1, "velho", 6, tickets=(1000,)))
        self.repo.restaurar([Candidato("x.com.br", nota=50,
                                       situacao=Situacao.LIBERACAO_DISPUTADA,
                                       candidatos=2, chegada_min=1790000000,
                                       verificado_em="2099-01-01T00:00:00+00:00")])
        guardado = self.repo.um("x.com.br")
        self.assertEqual(guardado.candidatos, 2)
        self.assertIsNone(guardado.ticket_min)
        self.assertEqual(guardado.chegada_min, 1790000000)

    def test_limpar_contaminados(self):
        self.repo.gravar_pool([Candidato("falso.com.br"),
                               Candidato("real.com.br")])
        # leilao sem ends-at: era bloqueio classificado errado
        self.repo.gravar_leitura("falso.com.br",
                                 Leitura(Situacao.COMPETITIVO, 0, "", 8))
        self.repo.gravar_leitura("real.com.br",
                                 Leitura(Situacao.COMPETITIVO, 3,
                                         "ends-at=2026-09-16", 9))
        self.assertEqual(self.repo.limpar_contaminados(), 1)
        self.assertIsNone(self.repo.um("falso.com.br").situacao)
        self.assertIs(self.repo.um("real.com.br").situacao, Situacao.COMPETITIVO)


class ClienteFalso:
    """Substitui o Registro.br nos testes de varredura."""

    def __init__(self, respostas):
        self.respostas = respostas
        self.consultados = []

    def verificar(self, dominio):
        self.consultados.append(dominio)
        resposta = self.respostas.get(dominio,
                                      Leitura(Situacao.LIBERACAO_LIVRE, 0, "", 6))
        # lista: uma resposta por consulta, e a ultima se repete
        if isinstance(resposta, list):
            return resposta.pop(0) if len(resposta) > 1 else resposta[0]
        return resposta


class TestVarredura(unittest.TestCase):
    def setUp(self):
        self.arquivo = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.arquivo.close()
        self.repo = Repositorio(self.arquivo.name)
        self.repo.gravar_pool([Candidato("a.com.br"), Candidato("b.com.br")])

    def tearDown(self):
        self.repo.fechar()
        os.unlink(self.arquivo.name)

    def test_grava_e_conta(self):
        cliente = ClienteFalso({})
        v = Varredura(cliente, self.repo)
        progresso = v.executar(["a.com.br", "b.com.br"], pausa=0)
        self.assertEqual(progresso.feitos, 2)
        self.assertEqual(progresso.erros, 0)
        self.assertIs(self.repo.um("a.com.br").situacao, Situacao.LIBERACAO_LIVRE)

    def test_erro_nao_vira_resultado(self):
        """Falha deixa o dominio NULL, para ser reconsultado depois."""
        cliente = ClienteFalso({"a.com.br": Leitura(Situacao.ERRO, 0, "rede")})
        v = Varredura(cliente, self.repo)
        progresso = v.executar(["a.com.br"], pausa=0)
        self.assertEqual(progresso.erros, 1)
        self.assertIsNone(self.repo.um("a.com.br").situacao)

    def test_detecta_mudanca(self):
        self.repo.gravar_leitura("a.com.br",
                                 Leitura(Situacao.LIBERACAO_LIVRE, 0, "", 6))
        cliente = ClienteFalso({
            "a.com.br": Leitura(Situacao.COMPETITIVO, 2, "ends-at=x", 9)})
        v = Varredura(cliente, self.repo)
        progresso = v.executar(["a.com.br"], pausa=0)
        self.assertEqual(len(progresso.mudancas), 1)
        self.assertIs(progresso.mudancas[0].para, Situacao.COMPETITIVO)

    def _pausas(self, v):
        pausas = []
        v._pausar = lambda s: pausas.append(s) or True
        return pausas

    def test_bloqueio_que_persiste_encerra_a_varredura(self):
        """19/09/2026: LIMITADO depois do recuo para tudo, sem ir ao proximo."""
        from garimpo.adaptadores.registrobr import PAUSA_SEGURA
        from garimpo.casos import varredura as mod
        limitado = Leitura(Situacao.LIMITADO, 0, "", None)
        cliente = ClienteFalso({"a.com.br": [limitado, limitado]})
        v = Varredura(cliente, self.repo)
        pausas = self._pausas(v)
        p = v.executar(["a.com.br", "b.com.br"], pausa=0)
        self.assertEqual(cliente.consultados, ["a.com.br", "a.com.br"])
        self.assertTrue(p.barrada)
        self.assertEqual(p.motivo, "bloqueio")
        self.assertEqual(p.bloqueios, 1)
        self.assertEqual(mod.RECUO_APOS_BLOQUEIO, 120)
        self.assertEqual(pausas, [120])
        self.assertIn("barrada", p.mensagem)
        self.assertTrue(v.instantaneo()["barrada"])
        self.assertEqual(p.pausa, PAUSA_SEGURA)

    def test_bloqueio_que_passa_no_recuo_segue(self):
        from garimpo.adaptadores.registrobr import PAUSA_SEGURA
        limitado = Leitura(Situacao.LIMITADO, 0, "", None)
        boa = Leitura(Situacao.LIBERACAO_LIVRE, 0, "", 6)
        cliente = ClienteFalso({"a.com.br": [limitado, boa]})
        v = Varredura(cliente, self.repo)
        pausas = self._pausas(v)
        p = v.executar(["a.com.br", "b.com.br"], pausa=0)
        self.assertEqual(cliente.consultados, ["a.com.br", "a.com.br", "b.com.br"])
        self.assertFalse(p.barrada)
        self.assertIsNone(p.motivo)
        self.assertEqual(p.erros, 0)
        # nenhuma pausa abaixo do piso, mesmo pedindo 0
        self.assertEqual(min(pausas), PAUSA_SEGURA)

    def test_dez_erros_seguidos_encerram_com_motivo_rede(self):
        from garimpo.casos.varredura import ERROS_SEGUIDOS_PARA_PARAR
        self.assertEqual(ERROS_SEGUIDOS_PARA_PARAR, 10)
        nomes = [f"n{i:02d}.com.br" for i in range(12)]
        self.repo.gravar_pool([Candidato(n) for n in nomes])
        erro = Leitura(Situacao.ERRO, 0, "rede")
        cliente = ClienteFalso({n: erro for n in nomes})
        v = Varredura(cliente, self.repo)
        self._pausas(v)
        p = v.executar(nomes, pausa=0)
        self.assertEqual(len(cliente.consultados), 10)
        self.assertTrue(p.barrada)
        self.assertEqual(p.motivo, "rede")
        self.assertEqual(p.erros, 10)

    def test_nove_erros_e_uma_leitura_boa_seguem(self):
        nomes = [f"n{i:02d}.com.br" for i in range(20)]
        self.repo.gravar_pool([Candidato(n) for n in nomes])
        erro = Leitura(Situacao.ERRO, 0, "rede")
        # 9 erros, uma boa, mais 9 erros e uma boa: o contador zera
        respostas = {n: erro for i, n in enumerate(nomes) if i % 10 != 9}
        cliente = ClienteFalso(respostas)
        v = Varredura(cliente, self.repo)
        self._pausas(v)
        p = v.executar(nomes, pausa=0)
        self.assertEqual(cliente.consultados, nomes)
        self.assertFalse(p.barrada)
        self.assertEqual(p.erros, 18)

    def test_parada_interrompe(self):
        cliente = ClienteFalso({})
        v = Varredura(cliente, self.repo)
        v.pedir_parada()
        progresso = v.executar(["a.com.br", "b.com.br"], pausa=0)
        self.assertEqual(progresso.feitos, 0)
        self.assertIn("interrompido", progresso.mensagem)


class TestPool(unittest.TestCase):
    def test_elegivel_entra_mesmo_com_nota_baixa(self):
        from garimpo.adaptadores.registrobr import Rodada
        rodada = Rodada(liberacao=["xyzabcdefghij.com.br"],
                        elegiveis={"qq.com.br"}, em_leilao=set())
        candidatos, resumo = pool.montar(rodada, (set(), set()),
                                         nota_minima=90)
        nomes = {c.dominio for c in candidatos}
        self.assertIn("qq.com.br", nomes)
        self.assertEqual(resumo.elegiveis, 1)


class TestLeilaoAnunciado(unittest.TestCase):
    """
    Regressao de 10/09/2026: as 28 joias do site estavam todas em leilao.

    A lista oficial (lista-competicao.txt) ja dizia isso, e a coluna em_leilao
    do JSON tambem. Mas a situacao exibida era a da ultima consulta, de 30
    horas antes, e o filtro de joias nunca olhava a lista.
    """

    def setUp(self):
        self.arquivo = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.arquivo.close()
        self.repo = Repositorio(self.arquivo.name)

    def tearDown(self):
        self.repo.fechar()
        os.unlink(self.arquivo.name)

    def _joia_velha(self, dominio="evangeliza.com.br", em_leilao=True):
        """Como evangeliza estava: elegivel, lida sem candidato, ja na lista."""
        self.repo.gravar_pool([Candidato(dominio, elegivel=True,
                                         em_leilao=em_leilao, nota=43)])
        self.repo.gravar_leitura(dominio,
                                 Leitura(Situacao.LIBERACAO_LIVRE, 0, "", 6))

    def test_lista_manda_sobre_leitura_de_liberacao(self):
        from garimpo.dominio.situacao import com_leilao_anunciado
        for antes in (Situacao.LIBERACAO_LIVRE, Situacao.LIBERACAO_DISPUTADA):
            self.assertIs(com_leilao_anunciado(antes, True),
                          Situacao.COMPETITIVO)
            self.assertIs(com_leilao_anunciado(antes, False), antes)

    def test_lista_nao_mexe_em_quem_nao_esta_em_liberacao(self):
        """REGISTRADO e LIVRE ja sairam da rodada; a lista nao os ressuscita."""
        from garimpo.dominio.situacao import com_leilao_anunciado
        for s in (Situacao.REGISTRADO, Situacao.LIVRE, None):
            self.assertIs(com_leilao_anunciado(s, True), s)

    def test_nome_na_lista_nunca_e_joia(self):
        c = Candidato("evangeliza.com.br", elegivel=True, em_leilao=True,
                      situacao=Situacao.LIBERACAO_LIVRE, candidatos=0)
        self.assertFalse(c.joia)
        self.assertIs(c.situacao_atual, Situacao.COMPETITIVO)

    def test_aplicar_grava_leilao_com_a_data_da_lista(self):
        self._joia_velha()
        self._joia_velha("custas.com.br", em_leilao=False)
        viraram = self.repo.aplicar_lista_de_leiloes("2026-09-10T22:30:00-03:00")

        self.assertEqual(viraram, 1)
        guardado = self.repo.um("evangeliza.com.br")
        self.assertIs(guardado.situacao, Situacao.COMPETITIVO)
        self.assertEqual(guardado.verificado_em, "2026-09-10T22:30:00-03:00")
        # quem nao esta na lista continua como estava
        self.assertIs(self.repo.um("custas.com.br").situacao,
                      Situacao.LIBERACAO_LIVRE)

    def test_saiu_da_lista_volta_para_a_fila(self):
        """
        A lista oficial manda nos dois sentidos (17/09/2026).

        Ate entao so subia: quem saia de lista-competicao.txt guardava
        "leilao aberto" ate ser reconsultado um a um. Com 16 mil nomes na
        fila isso levava dias, e a tela afirmava leilao em nome ja resolvido
        — a armadilha das "joias falsas" de 10/09 pelo avesso.
        """
        self._joia_velha()
        self.repo.aplicar_lista_de_leiloes("2026-09-10T22:30:00-03:00")
        self.assertIs(self.repo.um("evangeliza.com.br").situacao,
                      Situacao.COMPETITIVO)

        # a rodada acabou e o nome saiu da lista
        self.repo.con.execute("UPDATE dominios SET em_leilao=0")
        self.repo.con.commit()
        self.assertEqual(self.repo.encerrar_leiloes_fora_da_lista(), 1)

        guardado = self.repo.um("evangeliza.com.br")
        self.assertIsNot(guardado.situacao, Situacao.COMPETITIVO)
        self.assertIsNone(guardado.verificado_em)
        self.assertIsNone(guardado.candidatos)
        # idempotente: nada sobrou para rebaixar
        self.assertEqual(self.repo.encerrar_leiloes_fora_da_lista(), 0)

    def test_quem_segue_na_lista_nao_e_rebaixado(self):
        """Leilao que atravessa a rodada continua aberto (groupon, 17/09)."""
        self._joia_velha()
        self.repo.aplicar_lista_de_leiloes("x")
        self.assertEqual(self.repo.encerrar_leiloes_fora_da_lista(), 0)
        self.assertIs(self.repo.um("evangeliza.com.br").situacao,
                      Situacao.COMPETITIVO)

    def test_aplicar_nao_inventa_contagem(self):
        """A lista diz que ha leilao, nao quantos tickets."""
        self._joia_velha()
        self.repo.aplicar_lista_de_leiloes("x")
        self.assertEqual(self.repo.um("evangeliza.com.br").candidatos, 0)

    def test_limpeza_de_contaminados_nao_apaga_o_que_veio_da_lista(self):
        """COMPETITIVO sem detalhe e tratado como bloqueio disfarcado."""
        self._joia_velha()
        self.repo.aplicar_lista_de_leiloes("x")
        self.assertEqual(self.repo.limpar_contaminados(), 0)
        self.assertIs(self.repo.um("evangeliza.com.br").situacao,
                      Situacao.COMPETITIVO)

    def test_instantaneo_nao_publica_joia_que_esta_na_lista(self):
        c = Candidato("evangeliza.com.br", elegivel=True, em_leilao=True,
                      situacao=Situacao.LIBERACAO_LIVRE, candidatos=0)
        dados = instantaneo.exportar([c], instantaneo.Metadados(gerado_em="x"))
        self.assertEqual(dados["status"][dados["itens"][0][1]], "COMPETITIVO")

    def test_filtros_da_tela_respeitam_a_lista(self):
        from garimpo.web.consultas import Consultas
        self._joia_velha()
        self._joia_velha("custas.com.br", em_leilao=False)
        consultas = Consultas(self.repo)

        joias = [c.dominio for c in consultas.listar(filtro="joias").itens]
        leilao = [c.dominio for c in consultas.listar(filtro="leilao").itens]
        self.assertEqual(joias, ["custas.com.br"])
        self.assertEqual(leilao, ["evangeliza.com.br"])

    def test_le_a_data_do_cabecalho_da_lista(self):
        from garimpo.adaptadores.registrobr import gerado_em
        cabecalho = ("# Arquivo gerado em 2026-09-10T22:30:00-03:00\n"
                     "# Mais informações em https://registro.br/dominio/\n"
                     "\nevangeliza.com.br\n")
        self.assertEqual(gerado_em(cabecalho), "2026-09-10T22:30:00-03:00")
        self.assertIsNone(gerado_em("evangeliza.com.br\n"))


class _RespostaFalsa:
    """Imita o retorno de urllib.request.urlopen para testar baixar_rodada
    sem ir a rede: cabecalhos num dict e .read() devolvendo bytes."""

    def __init__(self, corpo: bytes, content_type="text/plain"):
        self._corpo = corpo
        self.headers = {"Content-Type": content_type}

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def read(self):
        return self._corpo


class TestValidarLista(unittest.TestCase):
    """
    O achado py-bugs:lista-html-200: uma lista ausente no registro.br volta
    HTTP 200 com o HTML do site, nao um erro. Sem validar o corpo, isso
    viraria uma "lista" de dominios lida do HTML.
    """

    HTML = ("<!doctype html>\n<html><head><title>Registro.br</title></head>"
           "<body>pagina do site</body></html>")

    def _lista_boa(self, nomes=("a.com.br", "b.com.br")):
        linhas = ["# Processo de liberação no período de "
                 "2026-10-14T15:00:00-03:00 a 2026-10-21T15:00:00-03:00",
                 "# Mais informações em https://registro.br/dominio/"
                 "processo-de-liberacao/",
                 "# Arquivo gerado em 2026-10-12T10:00:00-03:00"]
        linhas.extend(nomes)
        linhas.append("# Fim do arquivo")
        return "\n".join(linhas)

    @so_com("docs/historico/listas")
    def test_aceita_as_listas_reais_comitadas(self):
        # Roda o validador sobre toda lista comitada em
        # docs/historico/listas/, descomprimida: elas tem de continuar
        # passando, senao o validador esta estrito demais.
        import gzip
        pasta = os.path.join(os.path.dirname(__file__), "docs", "historico",
                             "listas")
        arquivos = [n for n in os.listdir(pasta) if n.endswith(".gz")]
        self.assertTrue(arquivos, "nenhuma lista comitada para testar")
        from garimpo.adaptadores.registrobr import validar_lista
        for nome in arquivos:
            with gzip.open(os.path.join(pasta, nome), "rt",
                           encoding="utf-8", errors="replace") as f:
                texto = f.read()
            validar_lista("teste://" + nome, texto)  # nao pode levantar

    @so_com("docs/historico/listas/2026-09-09-liberacao.txt.gz")
    def test_tolera_decodificacao_trocada(self):
        # PREFIXO_LISTA e RODAPE_LISTA sao ASCII de proposito: se o
        # registro.br um dia mudar de Latin-1 para UTF-8 (ou vice-versa), a
        # acentuacao vira mojibake, mas o validador nao pode rejeitar por
        # causa disso (so o conteudo importa). Decodifica os mesmos bytes
        # dos dois jeitos e confere que os dois passam.
        import gzip
        from garimpo.adaptadores.registrobr import validar_lista
        caminho = os.path.join(os.path.dirname(__file__), "docs", "historico",
                               "listas", "2026-09-09-liberacao.txt.gz")
        with gzip.open(caminho, "rb") as f:
            bruto = f.read()
        for codificacao in ("utf-8", "latin-1"):
            texto = bruto.decode(codificacao, errors="replace")
            validar_lista("teste://" + codificacao, texto)  # nao pode levantar

    def test_aceita_lista_boa(self):
        from garimpo.adaptadores.registrobr import validar_lista
        validar_lista("https://registro.br/dominio/lista-x.txt",
                      self._lista_boa())  # nao pode levantar

    def test_aceita_cabecalho_fora_da_primeira_linha(self):
        # lista-competicao.txt nao comeca pelo periodo: comeca por
        # "# Arquivo gerado em ...", igual a um work/leilao/lista-competicao.txt
        # real conferido em 18/09/2026. O validador nao pode exigir que o
        # periodo seja a primeira linha.
        from garimpo.adaptadores.registrobr import validar_lista
        texto = ("# Arquivo gerado em 2026-09-14T20:30:00-03:00\n"
                 "# Mais informações em https://registro.br/dominio/"
                 "processo-de-liberacao/\n\n"
                 "# Processo de liberação no período de "
                 "2026-09-09T15:00:00-03:00 a 2026-09-16T15:00:00-03:00\n"
                 "a.com.br\nb.com.br\n# Fim do arquivo")
        validar_lista("https://registro.br/dominio/lista-competicao.txt",
                      texto)  # nao pode levantar

    def test_rejeita_corpo_html_servido_com_200(self):
        from garimpo.adaptadores.registrobr import ListaInvalida, validar_lista
        with self.assertRaises(ListaInvalida) as ctx:
            validar_lista("https://registro.br/dominio/lista-x.txt",
                          self.HTML, content_type="text/html")
        msg = str(ctx.exception)
        # a mensagem traz a URL, o Content-Type e os 80 primeiros caracteres
        self.assertIn("lista-x.txt", msg)
        self.assertIn("text/html", msg)
        self.assertIn(repr(self.HTML[:80]), msg)

    def test_rejeita_sem_cabecalho_ou_sem_rodape(self):
        from garimpo.adaptadores.registrobr import ListaInvalida, validar_lista
        sem_cabecalho = "a.com.br\nb.com.br\n# Fim do arquivo"
        sem_rodape = self._lista_boa().replace("# Fim do arquivo", "")
        for corpo in (sem_cabecalho, sem_rodape, ""):
            with self.assertRaises(ListaInvalida):
                validar_lista("https://registro.br/dominio/lista-x.txt", corpo)

    def test_baixar_rodada_para_a_execucao_se_a_liberacao_vier_html(self):
        # Elegiveis e leilao vem antes de liberacao no download; se a de
        # liberacao vier HTML, a excecao tem de propagar mesmo assim.
        from garimpo.adaptadores import registrobr as rb

        def abrir(url, timeout=None):
            if url == rb.LISTA_LIBERACAO:
                return _RespostaFalsa(self.HTML.encode(rb.CODIFICACAO_LISTAS),
                                      "text/html")
            return _RespostaFalsa(self._lista_boa().encode(rb.CODIFICACAO_LISTAS))

        with unittest.mock.patch.object(rb, "_abrir", side_effect=abrir):
            with self.assertRaises(rb.ListaInvalida):
                rb.baixar_rodada()

    def test_baixar_rodada_para_a_execucao_se_elegiveis_vier_html(self):
        # A primeira lista baixada: tem de parar antes de baixar as outras.
        from garimpo.adaptadores import registrobr as rb
        chamadas = []

        def abrir(url, timeout=None):
            chamadas.append(url)
            if url == rb.LISTA_ELEGIVEIS:
                return _RespostaFalsa(self.HTML.encode(rb.CODIFICACAO_LISTAS),
                                      "text/html")
            return _RespostaFalsa(self._lista_boa().encode(rb.CODIFICACAO_LISTAS))

        with unittest.mock.patch.object(rb, "_abrir", side_effect=abrir):
            with self.assertRaises(rb.ListaInvalida):
                rb.baixar_rodada()
        self.assertEqual(chamadas, [rb.LISTA_ELEGIVEIS])

    def test_baixar_rodada_so_avisa_se_a_lista_de_leiloes_vier_html(self):
        # A de leiloes e a unica das tres com um "ramo de queda" (a de rede
        # ja existia); lista invalida so gera aviso e segue sem ela.
        from garimpo.adaptadores import registrobr as rb
        avisos = []

        def abrir(url, timeout=None):
            if url == rb.LISTA_EM_LEILAO:
                return _RespostaFalsa(self.HTML.encode(rb.CODIFICACAO_LISTAS),
                                      "text/html")
            return _RespostaFalsa(self._lista_boa().encode(rb.CODIFICACAO_LISTAS))

        with unittest.mock.patch.object(rb, "_abrir", side_effect=abrir):
            rodada = rb.baixar_rodada(aviso=avisos.append)
        self.assertEqual(rodada.em_leilao, set())
        # o flag distingue "nao sei" de "nenhum leilao": sem ele,
        # varrer.preparar() nao tinha como saber que precisava reaproveitar
        # o instantaneo anterior em vez de confiar no conjunto vazio
        # (correcao de 18/09/2026, apos revisao)
        self.assertFalse(rodada.em_leilao_lido)
        self.assertTrue(any("leiloes indisponivel" in a for a in avisos), avisos)
        # as outras duas listas nao sao afetadas
        self.assertEqual(rodada.total, 2)
        self.assertEqual(rodada.elegiveis, {"a.com.br", "b.com.br"})

    def test_lista_de_leiloes_boa_marca_lido(self):
        from garimpo.adaptadores import registrobr as rb

        def abrir(url, timeout=None):
            return _RespostaFalsa(self._lista_boa().encode(rb.CODIFICACAO_LISTAS))

        with unittest.mock.patch.object(rb, "_abrir", side_effect=abrir):
            rodada = rb.baixar_rodada()
        self.assertTrue(rodada.em_leilao_lido)


class TestReaproveitarLeilao(unittest.TestCase):
    """
    Correcao pedida na revisao de 18/09/2026: 'lista de leiloes invalida
    mantem a anterior' so era cumprido de nome. `_reaproveitar_leilao`
    reconstroi `rodada.em_leilao` do instantaneo anterior ANTES do
    pool.montar, para o pool gravar a coluna certa (em vez de zerar todo
    mundo e o encerrar_leiloes_fora_da_lista() apagar o COMPETITIVO ja lido).
    """

    def _rodada(self, fim, em_leilao_lido, em_leilao=()):
        from garimpo.adaptadores.registrobr import Rodada
        return Rodada(liberacao=["leilao.com.br"], elegiveis={"leilao.com.br"},
                      em_leilao=set(em_leilao), fim=fim,
                      em_leilao_lido=em_leilao_lido)

    def _instantaneo(self, fim, em_leilao_em="2026-10-15T09:00:00-03:00"):
        meta = instantaneo.Metadados(
            gerado_em="2026-10-15T10:00:00-03:00", fim=fim,
            em_leilao_em=em_leilao_em)
        candidato = Candidato("leilao.com.br", elegivel=True, em_leilao=True,
                              nota=60, situacao=Situacao.COMPETITIVO,
                              candidatos=3)
        return instantaneo.exportar([candidato], meta)

    def test_lista_lida_nao_mexe_em_nada(self):
        from varrer import _reaproveitar_leilao
        rodada = self._rodada("2026-10-21T15:00:00-03:00", em_leilao_lido=True)
        nova, reaproveitado = _reaproveitar_leilao(rodada, self._instantaneo(
            "2026-10-21T15:00:00-03:00"))
        self.assertIs(nova, rodada)
        self.assertFalse(reaproveitado)

    def test_reaproveita_do_instantaneo_da_mesma_rodada(self):
        from varrer import _reaproveitar_leilao
        fim = "2026-10-21T15:00:00-03:00"
        rodada = self._rodada(fim, em_leilao_lido=False)
        nova, reaproveitado = _reaproveitar_leilao(rodada, self._instantaneo(fim))
        self.assertTrue(reaproveitado)
        self.assertEqual(nova.em_leilao, {"leilao.com.br"})
        self.assertEqual(nova.em_leilao_em, "2026-10-15T09:00:00-03:00")

    def test_nao_reaproveita_de_outra_rodada(self):
        from varrer import _reaproveitar_leilao
        rodada = self._rodada("2026-10-21T15:00:00-03:00", em_leilao_lido=False)
        anterior = self._instantaneo("2026-09-16T15:00:00-03:00")  # rodada velha
        nova, reaproveitado = _reaproveitar_leilao(rodada, anterior)
        self.assertFalse(reaproveitado)
        self.assertEqual(nova.em_leilao, set())

    def test_sem_instantaneo_nao_reaproveita(self):
        from varrer import _reaproveitar_leilao
        rodada = self._rodada("2026-10-21T15:00:00-03:00", em_leilao_lido=False)
        nova, reaproveitado = _reaproveitar_leilao(rodada, None)
        self.assertFalse(reaproveitado)
        self.assertEqual(nova.em_leilao, set())


class TestPrepararMantemLeilaoSemLista(unittest.TestCase):
    """
    Ponta a ponta: varrer.preparar() com a lista de leiloes invalida nao
    pode apagar um COMPETITIVO que o instantaneo anterior, da mesma rodada,
    ja tinha confirmado.
    """

    class _VocabFalso:
        def carregar(self, diga=None):
            return (set(), set())

    def setUp(self):
        import shutil
        import tempfile
        from garimpo.contexto import Contexto
        self.raiz = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.raiz, ignore_errors=True)
        self.ctx = Contexto(raiz=self.raiz)
        self.addCleanup(self.ctx.repo.fechar)

    def test_competitivo_do_instantaneo_sobrevive_a_lista_invalida(self):
        from garimpo.adaptadores.registrobr import Rodada
        import varrer

        fim = "2026-10-21T15:00:00-03:00"
        candidato_anterior = Candidato(
            "leilao.com.br", fonte="elegivel", elegivel=True, em_leilao=True,
            nota=60, situacao=Situacao.COMPETITIVO, candidatos=3,
            verificado_em="2026-10-15T10:00:00-03:00")
        meta = instantaneo.Metadados(
            gerado_em="2026-10-15T10:00:00-03:00",
            inicio="2026-10-14T15:00:00-03:00", fim=fim,
            em_leilao_em="2026-10-15T09:00:00-03:00")
        instantaneo.escrever(instantaneo.exportar([candidato_anterior], meta),
                             self.ctx.instantaneo)

        rodada = Rodada(liberacao=["leilao.com.br"],
                        elegiveis={"leilao.com.br"}, em_leilao=set(),
                        inicio="2026-10-14T15:00:00-03:00", fim=fim,
                        em_leilao_lido=False)
        self.ctx.baixar_rodada = lambda aviso=None: rodada
        self.ctx.vocabularios = self._VocabFalso()

        varrer.preparar(self.ctx, pool.NOTA_MINIMA, pool.TETO_LIBERACAO)

        guardado = self.ctx.repo.um("leilao.com.br")
        self.assertTrue(guardado.em_leilao)
        self.assertIs(guardado.situacao_atual, Situacao.COMPETITIVO)
        self.assertEqual(self.ctx.repo.meta("total_em_leilao"), "1")


class TestAntesDaAbertura(unittest.TestCase):
    """
    18/09/2026: entre a saida da lista e a abertura da rodada, o varrer.py
    aplica a lista nova e exporta, mas nao consulta o Registro.br; e depois
    da abertura as leituras da janela anterior voltam para a fila.
    """

    INICIO = "2026-10-14T15:00:00-03:00"
    FIM = "2026-10-21T15:00:00-03:00"

    class _VocabFalso:
        def carregar(self, diga=None):
            return (set(), set())

    def setUp(self):
        import shutil
        from garimpo.contexto import Contexto
        self.raiz = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.raiz, ignore_errors=True)
        self.ctx = Contexto(raiz=self.raiz)
        self.addCleanup(self.ctx.repo.fechar)

    def test_antes_da_abertura(self):
        from garimpo.dominio.frescor import epoch
        from varrer import antes_da_abertura
        self.assertTrue(antes_da_abertura(self.INICIO, epoch("2026-10-13T10:00:00-03:00")))
        self.assertFalse(antes_da_abertura(self.INICIO, epoch("2026-10-14T15:00:00-03:00")))
        # depois do fim a varredura segue (leiloes e desfecho)
        self.assertFalse(antes_da_abertura(self.INICIO, epoch("2026-10-22T10:00:00-03:00")))
        self.assertFalse(antes_da_abertura(None, 0))

    def test_esquecer_leituras_antes_compara_em_segundos(self):
        repo = self.ctx.repo
        repo.restaurar([
            # 14:30 em Brasilia: antes das 15h
            Candidato("antes.com.br", fonte="elegivel", nota=90,
                      situacao=Situacao.AGUARDANDO_LIBERACAO,
                      verificado_em="2026-10-14T14:30:00-03:00"),
            # 18:05 UTC = 15:05 em Brasilia: depois, embora o texto seja menor
            Candidato("depois.com.br", fonte="elegivel", nota=90,
                      situacao=Situacao.LIBERACAO_LIVRE,
                      verificado_em="2026-10-14T18:05:00+00:00"),
        ])
        self.assertEqual(repo.esquecer_leituras_antes(self.INICIO), 1)
        self.assertIsNone(repo.um("antes.com.br").verificado_em)
        self.assertIsNone(repo.um("antes.com.br").situacao)
        self.assertIs(repo.um("depois.com.br").situacao, Situacao.LIBERACAO_LIVRE)
        self.assertEqual(repo.esquecer_leituras_antes(None), 0)

    def _rodar_main(self, agora_iso, instantaneo_anterior=None):
        from garimpo.adaptadores.registrobr import Rodada
        from garimpo.dominio.frescor import epoch
        import varrer
        if instantaneo_anterior:
            instantaneo.escrever(instantaneo_anterior, self.ctx.instantaneo)
        rodada = Rodada(liberacao=["travado.com.br"],
                        elegiveis={"travado.com.br"}, em_leilao=set(),
                        inicio=self.INICIO, fim=self.FIM, em_leilao_lido=True)
        self.ctx.baixar_rodada = lambda aviso=None: rodada
        self.ctx.vocabularios = self._VocabFalso()
        varredura = unittest.mock.MagicMock()
        varredura.return_value.executar.return_value = unittest.mock.Mock(
            feitos=0, erros=0, bloqueios=0, mudancas=[], barrada=False,
            motivo=None)
        with unittest.mock.patch.object(varrer, "padrao", self.ctx), \
             unittest.mock.patch.object(varrer, "Varredura", varredura), \
             unittest.mock.patch.object(varrer.exportar_site, "main") as exportar, \
             unittest.mock.patch("garimpo.adaptadores.registrobr.consultar") as consultar, \
             unittest.mock.patch("time.time", return_value=epoch(agora_iso)), \
             unittest.mock.patch("sys.argv", ["varrer.py", "--minutos", "1"]), \
             unittest.mock.patch("builtins.print"):
            varrer.main()
        with open(os.path.join(self.ctx.trabalho, "varredura.json")) as f:
            resumo = json.load(f)
        return varredura, consultar, exportar, resumo

    def test_antes_da_abertura_nao_consulta_e_exporta(self):
        varredura, consultar, exportar, resumo = self._rodar_main(
            "2026-10-13T10:00:00-03:00")
        varredura.assert_not_called()
        consultar.assert_not_called()
        exportar.assert_called_once()
        self.assertEqual(resumo["pulada"], "antes_da_abertura")
        self.assertEqual(resumo["alvos"], 0)
        # a lista nova foi aplicada: o nome esta no pool, sem leitura
        self.assertIsNotNone(self.ctx.repo.um("travado.com.br"))

    def test_depois_da_abertura_le_de_novo_o_status5_de_antes(self):
        anterior = instantaneo.exportar(
            [Candidato("travado.com.br", fonte="elegivel", elegivel=True,
                       nota=90, situacao=Situacao.AGUARDANDO_LIBERACAO,
                       verificado_em="2026-10-13T10:00:00-03:00")],
            instantaneo.Metadados(gerado_em="2026-10-13T10:00:00-03:00",
                                  inicio=self.INICIO, fim=self.FIM))
        varredura, consultar, exportar, resumo = self._rodar_main(
            "2026-10-14T15:01:00-03:00", anterior)
        self.assertIsNone(resumo["pulada"])
        # o resumo sempre diz se a varredura foi barrada, e por que
        self.assertIs(resumo["barrada"], False)
        self.assertIsNone(resumo["motivo"])
        self.assertIsNone(self.ctx.repo.um("travado.com.br").situacao)
        alvos = varredura.return_value.executar.call_args[0][0]
        self.assertIn("travado.com.br", alvos)
        exportar.assert_called_once()

    # -- leituras/casa.json (19/09/2026) ---------------------------------

    def _casa(self, itens, fim=None):
        dados = instantaneo.exportar(
            itens, instantaneo.Metadados(gerado_em="2026-10-15T12:00:00-03:00",
                                         inicio=self.INICIO, fim=fim or self.FIM))
        dados.pop("ritmo", None)
        instantaneo.escrever(dados, os.path.join(self.raiz, "leituras", "casa.json"))
        return dados

    def _preparar(self, anterior, em_leilao=frozenset()):
        from garimpo.adaptadores.registrobr import Rodada
        from garimpo.dominio.frescor import epoch
        import varrer
        instantaneo.escrever(anterior, self.ctx.instantaneo)
        rodada = Rodada(liberacao=["casa.com.br", "leilao.com.br"],
                        elegiveis={"casa.com.br", "leilao.com.br"},
                        em_leilao=set(em_leilao), inicio=self.INICIO,
                        fim=self.FIM, em_leilao_lido=True,
                        em_leilao_em="2026-10-15T13:00:00-03:00")
        self.ctx.baixar_rodada = lambda aviso=None: rodada
        self.ctx.vocabularios = self._VocabFalso()
        falas = []
        with unittest.mock.patch("time.time",
                                 return_value=epoch("2026-10-15T14:00:00-03:00")), \
             unittest.mock.patch("builtins.print",
                                 side_effect=lambda *a, **k: falas.append(" ".join(map(str, a)))):
            varrer.preparar(self.ctx, pool.NOTA_MINIMA, pool.TETO_LIBERACAO)
        return falas

    def _leitura(self, nome, situacao, quando, candidatos=0):
        return Candidato(nome, fonte="elegivel", elegivel=True, nota=90,
                         situacao=situacao, candidatos=candidatos,
                         verificado_em=quando)

    def _anterior(self):
        return instantaneo.exportar(
            [self._leitura("casa.com.br", Situacao.LIBERACAO_LIVRE,
                           "2026-10-15T09:00:00+00:00"),
             self._leitura("leilao.com.br", Situacao.LIBERACAO_DISPUTADA,
                           "2026-10-15T09:00:00+00:00", 1)],
            instantaneo.Metadados(gerado_em="2026-10-15T09:00:00+00:00",
                                  inicio=self.INICIO, fim=self.FIM))

    def test_casa_da_mesma_rodada_vence_o_instantaneo_mais_velho(self):
        casa = self._casa([
            self._leitura("casa.com.br", Situacao.LIBERACAO_DISPUTADA,
                          "2026-10-15T12:00:00-03:00", 3),
            self._leitura("leilao.com.br", Situacao.LIBERACAO_LIVRE,
                          "2026-10-15T12:00:00-03:00")])
        # o arquivo segue o formato do dados.json, sem numero de ticket
        self.assertNotIn("ticket", json.dumps(casa))
        self._preparar(self._anterior(), em_leilao={"leilao.com.br"})
        guardado = self.ctx.repo.um("casa.com.br")
        self.assertIs(guardado.situacao, Situacao.LIBERACAO_DISPUTADA)
        self.assertEqual(guardado.candidatos, 3)
        # a lista oficial de leiloes continua mandando sobre a leitura de casa
        self.assertIs(self.ctx.repo.um("leilao.com.br").situacao_atual,
                      Situacao.COMPETITIVO)
        # e a leitura nova sai no dados.json
        saida = instantaneo.exportar(
            self.ctx.repo.buscar(),
            instantaneo.Metadados(gerado_em="agora", inicio=self.INICIO,
                                  fim=self.FIM))
        item = next(i for i in saida["itens"] if i[0] == "casa.com.br")
        self.assertEqual(saida["status"][item[instantaneo.I_SITUACAO]],
                         Situacao.LIBERACAO_DISPUTADA.value)

    def test_casa_mais_velha_nao_troca_o_instantaneo(self):
        self._casa([self._leitura("casa.com.br", Situacao.LIBERACAO_DISPUTADA,
                                  "2026-10-15T05:00:00-03:00", 3)])
        self._preparar(self._anterior())
        self.assertIs(self.ctx.repo.um("casa.com.br").situacao,
                      Situacao.LIBERACAO_LIVRE)

    def test_casa_de_outra_rodada_e_ignorada_com_aviso(self):
        self._casa([self._leitura("casa.com.br", Situacao.LIBERACAO_DISPUTADA,
                                  "2026-10-15T12:00:00-03:00", 3)],
                   fim="2026-09-16T15:00:00-03:00")
        falas = self._preparar(self._anterior())
        self.assertIs(self.ctx.repo.um("casa.com.br").situacao,
                      Situacao.LIBERACAO_LIVRE)
        self.assertTrue(any("casa.json" in f and "ignorado" in f for f in falas))


class TestRajada(unittest.TestCase):
    """
    Rajada em casa (19/09/2026): a lista da rodada conferida numa noite, em
    blocos, pela maquina do dono. Tudo falso: git, gh, relogio, sono e o
    Registro.br; nenhuma consulta, nenhum commit de verdade.
    """

    INICIO = "2026-09-09T15:00:00-03:00"
    FIM = "2026-09-16T15:00:00-03:00"
    AGORA = "2026-09-19T22:00:00-03:00"
    NOMES = ["aaa.com.br", "bbb.com.br", "ccc.com.br"]

    class _VocabFalso:
        def carregar(self, diga=None):
            return (set(), set())

    class _Git:
        """git falso: rev-parse de worktree, show do dados.json, o resto 0."""

        def __init__(self, principal=False, dados=""):
            self.chamadas = []
            self.principal = principal
            self.dados = dados

        def __call__(self, args):
            self.chamadas.append(list(args))
            if args[:2] == ["rev-parse", "--absolute-git-dir"]:
                return 0, "/r/.git\n" if self.principal else "/r/.git/worktrees/x\n"
            if args[0] == "rev-parse":
                return 0, "/r/.git\n"
            if args[0] == "show":
                return (0, self.dados) if self.dados else (128, "")
            if args[:2] == ["diff", "--cached"]:
                return 1, ""        # houve mudanca no casa.json
            return 0, ""

    class _Gh:
        def __init__(self, status=()):
            self.chamadas = []
            self.status = list(status)

        def __call__(self, args):
            self.chamadas.append(list(args))
            if args[:2] == ["run", "list"]:
                return 0, json.dumps([{"status": s} for s in self.status])
            return 0, ""

        @property
        def disparos(self):
            return [c for c in self.chamadas if c[:2] == ["workflow", "run"]]

    class _Relogio:
        def __init__(self, inicio):
            self.t = inicio
            self.sonos = []

        def __call__(self):
            return self.t

        def dormir(self, s):
            self.sonos.append(s)
            self.t += s

    class _Cliente(ClienteFalso):
        """ClienteFalso que tambem confere que nunca ha duas consultas juntas."""

        def __init__(self, respostas):
            super().__init__(respostas)
            self.juntas = 0
            self.max_juntas = 0

        def verificar(self, dominio):
            self.juntas += 1
            self.max_juntas = max(self.max_juntas, self.juntas)
            try:
                return super().verificar(dominio)
            finally:
                self.juntas -= 1

    def setUp(self):
        import shutil
        import rajada
        from garimpo.dominio.frescor import epoch
        self.rajada = rajada
        self.raiz = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.raiz, ignore_errors=True)
        self.cliente = self._Cliente({})
        cliente = self.cliente

        class Ctx(rajada.ContextoDaRajada):
            @property
            def cliente(self):
                return cliente

        self.ctx = Ctx(raiz=self.raiz)
        self.addCleanup(self.ctx.repo.fechar)
        from garimpo.adaptadores.registrobr import Rodada
        self.rodada = Rodada(liberacao=list(self.NOMES),
                             elegiveis=set(self.NOMES), em_leilao=set(),
                             inicio=self.INICIO, fim=self.FIM,
                             em_leilao_lido=True)
        self.ctx.baixar_rodada = lambda aviso=None: self.rodada
        self.ctx.vocabularios = self._VocabFalso()
        self.relogio = self._Relogio(epoch(self.AGORA))
        self.pausas = []

    def _varredura(self):
        v = Varredura(self.cliente, self.ctx.repo)
        v._pausar = lambda s: self.pausas.append(s) or True
        return v

    def _main(self, argv, ambiente=None, git=None, gh=None):
        git = git or self._Git()
        gh = gh or self._Gh()
        saida = io.StringIO()
        with contextlib.redirect_stdout(saida), \
             contextlib.redirect_stderr(io.StringIO()) as erro:
            codigo = self.rajada.main(
                argv, ctx=self.ctx, ambiente={} if ambiente is None else ambiente,
                git=git, gh=gh, relogio=self.relogio, dormir=self.relogio.dormir,
                nova_varredura=self._varredura)
        return codigo, saida.getvalue(), erro.getvalue(), git, gh

    def _rajada(self, **opcoes):
        import varrer
        from garimpo.casos import rajada as caso
        with contextlib.redirect_stdout(io.StringIO()):
            rodada = varrer.preparar(self.ctx, pool.NOTA_MINIMA, pool.TETO_LIBERACAO)
        git = opcoes.pop("git", None) or self._Git()
        gh = opcoes.pop("gh", None) or self._Gh()
        r = caso.Rajada(raiz=self.raiz, repo=self.ctx.repo, cliente=self.cliente,
                        rodada=rodada, git=git, gh=gh, relogio=self.relogio,
                        dormir=self.relogio.dormir, relatar=lambda m: None,
                        nova_varredura=self._varredura, **opcoes)
        return r.executar(), git, gh

    # -- --seco e recusas -------------------------------------------------

    def test_seco_imprime_sem_consultar(self):
        codigo, saida, _, git, gh = self._main(["--seco"])
        self.assertEqual(codigo, 0)
        self.assertEqual(self.cliente.consultados, [])
        self.assertIn("3 nomes", saida)
        for nome in self.NOMES:
            self.assertIn(nome, saida)
        self.assertIn("fim previsto", saida)
        self.assertFalse(any(c[0] in ("commit", "push") for c in git.chamadas))
        self.assertEqual(gh.chamadas, [])

    def test_recusa_no_actions_e_no_checkout_principal(self):
        codigo, *_ , git, _ = self._main(["--seco"], ambiente={"GITHUB_ACTIONS": "true"})
        self.assertEqual(codigo, 3)
        self.assertEqual(git.chamadas, [])
        codigo, *_ , git, _ = self._main([], git=self._Git(principal=True))
        self.assertEqual(codigo, 3)
        self.assertFalse(any(c[0] == "fetch" for c in git.chamadas))
        self.assertEqual(self.cliente.consultados, [])

    def test_recusa_antes_da_abertura(self):
        from garimpo.dominio.frescor import epoch
        self.relogio.t = epoch("2026-09-08T10:00:00-03:00")
        codigo, *_ = self._main([])
        self.assertEqual(codigo, 4)
        self.assertEqual(self.cliente.consultados, [])

    def test_help_roda_mesmo_no_actions(self):
        import sys
        saida = subprocess.run(
            [sys.executable, "rajada.py", "--help"],
            cwd=os.path.dirname(os.path.abspath(__file__)),
            env={**os.environ, "GITHUB_ACTIONS": "true"},
            capture_output=True, text=True)
        self.assertEqual(saida.returncode, 0, saida.stderr)
        self.assertIn("--desde", saida.stdout)

    # -- o laco ----------------------------------------------------------

    def test_bloco_comita_so_o_casa_json_e_dispara_uma_vez(self):
        import varrer
        r, git, gh = self._rajada()
        self.assertEqual(r.codigo, 0)
        self.assertEqual(sorted(self.cliente.consultados), sorted(self.NOMES))
        adds = [c for c in git.chamadas if c[0] == "add"]
        self.assertEqual(adds, [["add", "--", "leituras/casa.json"]])
        commits = [c for c in git.chamadas if c[0] == "commit"]
        self.assertEqual(len(commits), 1)
        self.assertEqual(commits[0][-2:], ["--", "leituras/casa.json"])
        self.assertIn(["push", "-q", "origin", "HEAD:main"], git.chamadas)
        self.assertEqual(len(gh.disparos), 1)
        self.assertIn("minutos=3", gh.disparos[0])
        # o arquivo sai sem ticket e o varrer.py o aceita (mesma rodada)
        caminho = os.path.join(self.raiz, "leituras", "casa.json")
        with open(caminho) as f:
            texto = f.read()
        self.assertNotIn("ticket", texto)
        self.assertNotIn("ritmo", texto)
        self.assertEqual(json.loads(texto)["rodada"]["fim"], self.FIM)
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(varrer.aplicar_leituras_de_casa(
                self.ctx, self.rodada, lambda m: None), 3)

    def test_sem_disparo_com_garimpo_andando(self):
        for status in ("queued", "in_progress"):
            self.cliente.consultados.clear()
            r, _, gh = self._rajada(gh=self._Gh([status]), desde=None)
            self.assertEqual(gh.disparos, [], status)
            self.assertTrue(any(c[:2] == ["run", "list"] for c in gh.chamadas))

    def test_bloqueio_recua_60_min_uma_vez_e_sai_com_2(self):
        limitado = Leitura(Situacao.LIMITADO, 0, "", None)
        self.cliente.respostas.update({"bbb.com.br": [limitado],
                                       "ccc.com.br": [limitado]})
        r, git, _ = self._rajada()
        self.assertEqual(r.codigo, 2)
        self.assertEqual(r.blocos, 2)
        self.assertEqual(self.relogio.sonos.count(3600), 1)
        # o recuo de 120 s da Varredura aconteceu (falso) nos dois blocos
        self.assertEqual(self.pausas.count(120), 2)
        # a leitura boa do bloco 1 ja esta comitada
        self.assertTrue(any(c[0] == "commit" for c in git.chamadas))
        with open(os.path.join(self.raiz, "leituras", "casa.json")) as f:
            self.assertEqual([i[0] for i in json.load(f)["itens"]], ["aaa.com.br"])

    def test_nome_barrado_abre_o_bloco_seguinte(self):
        limitado = Leitura(Situacao.LIMITADO, 0, "", None)
        livre = Leitura(Situacao.LIBERACAO_LIVRE, 0, "", 6)
        # barra em bbb (a consulta e a do recuo), e depois da 1 h responde
        self.cliente.respostas["bbb.com.br"] = [limitado, limitado, livre]
        r, _, _ = self._rajada()
        self.assertEqual(r.codigo, 0)
        self.assertEqual(r.blocos, 2)
        self.assertEqual(self.relogio.sonos.count(3600), 1)
        self.assertEqual(self.cliente.consultados,
                         ["aaa.com.br", "bbb.com.br", "bbb.com.br",
                          "bbb.com.br", "ccc.com.br"])
        with open(os.path.join(self.raiz, "leituras", "casa.json")) as f:
            self.assertEqual(sorted(i[0] for i in json.load(f)["itens"]),
                             sorted(self.NOMES))

    def test_erros_seguidos_voltam_no_bloco_seguinte(self):
        from garimpo.casos import varredura as mod
        from garimpo.dominio.situacao import Situacao as S
        erro = Leitura(S.ERRO, 0, "", None)
        livre = Leitura(S.LIBERACAO_LIVRE, 0, "", 6)
        with unittest.mock.patch.object(mod, "ERROS_SEGUIDOS_PARA_PARAR", 2):
            self.cliente.respostas.update({"bbb.com.br": [erro, livre],
                                           "ccc.com.br": [erro, livre]})
            r, _, _ = self._rajada()
        self.assertEqual(r.codigo, 0)
        self.assertEqual(r.blocos, 2)
        self.assertEqual(self.cliente.consultados[3:],
                         ["bbb.com.br", "ccc.com.br"])
        with open(os.path.join(self.raiz, "leituras", "casa.json")) as f:
            self.assertEqual(len(json.load(f)["itens"]), 3)

    def test_nao_rele_o_que_o_cron_leu_depois_do_desde(self):
        from garimpo.dominio.frescor import epoch

        def dados_da_main(fim):
            return json.dumps(instantaneo.exportar(
                [Candidato("aaa.com.br", fonte="elegivel", elegivel=True,
                           nota=90, situacao=Situacao.REGISTRADO,
                           verificado_em="2026-09-17T10:00:00-03:00")],
                instantaneo.Metadados(gerado_em="2026-09-17T10:00:00-03:00",
                                      inicio=self.INICIO, fim=fim)))

        # o cron leu aaa.com.br depois do fechamento: a rajada nao o rele
        self._rajada(git=self._Git(dados=dados_da_main(self.FIM)),
                     desde=epoch(self.FIM))
        self.assertNotIn("aaa.com.br", self.cliente.consultados)
        self.assertIn("bbb.com.br", self.cliente.consultados)
        # dados.json de outra rodada nao conta
        self.ctx.repo.esquecer_leituras()
        self.cliente.consultados.clear()
        self._rajada(git=self._Git(dados=dados_da_main("2026-08-19T15:00:00-03:00")),
                     desde=epoch(self.FIM))
        self.assertIn("aaa.com.br", self.cliente.consultados)

    def test_ate_no_passado_nao_consulta(self):
        r, git, gh = self._rajada(ate=self.relogio.t - 60)
        self.assertEqual(self.cliente.consultados, [])
        self.assertEqual(r.blocos, 0)
        self.assertFalse(any(c[0] == "commit" for c in git.chamadas))
        self.assertEqual(gh.chamadas, [])

    def test_maximo_e_pausa_segura_sem_paralelo(self):
        from garimpo.adaptadores.registrobr import PAUSA_SEGURA
        r, *_ = self._rajada(maximo=2, pausa=0.1)
        self.assertEqual(len(self.cliente.consultados), 2)
        self.assertEqual(r.codigo, 0)
        self.assertTrue(self.pausas)
        self.assertGreaterEqual(min(self.pausas), PAUSA_SEGURA)
        self.assertEqual(self.cliente.max_juntas, 1)

    # -- o alvo ------------------------------------------------------------

    def test_desde_fechamento_e_a_ordem(self):
        from garimpo.casos import rajada as caso
        from garimpo.dominio.frescor import epoch
        antes, depois = "2026-09-15T10:00:00-03:00", "2026-09-17T10:00:00-03:00"
        c = [
            Candidato("nota.com.br", nota=90, situacao=Situacao.LIBERACAO_LIVRE,
                      candidatos=0, verificado_em=antes),
            Candidato("baixa.com.br", nota=50, situacao=Situacao.LIBERACAO_LIVRE,
                      candidatos=0, verificado_em=antes),
            Candidato("disputa.com.br", nota=40,
                      situacao=Situacao.LIBERACAO_DISPUTADA, candidatos=2,
                      verificado_em=antes),
            Candidato("elegivel.com.br", nota=30, elegivel=True),
            Candidato("relido.com.br", nota=99, situacao=Situacao.LIVRE,
                      verificado_em=depois),
        ]
        desde = caso.resolver_desde("fechamento", self.rodada, epoch(self.AGORA))
        self.assertEqual(desde, epoch(self.FIM))
        self.assertEqual(caso.alvos(c, desde),
                         ["elegivel.com.br", "disputa.com.br", "nota.com.br",
                          "baixa.com.br"])
        # o filtro de situacao vale para quem tem leitura; sem leitura entra
        self.assertEqual(caso.alvos(c, desde, {Situacao.LIBERACAO_DISPUTADA}),
                         ["elegivel.com.br", "disputa.com.br"])
        # sem --desde, com a rodada fechada, e o fechamento
        self.assertEqual(caso.resolver_desde(None, self.rodada, epoch(self.AGORA)),
                         epoch(self.FIM))
        self.assertEqual(caso.resolver_desde("12 h", self.rodada, 100_000),
                         100_000 - 12 * 3600)
        self.assertEqual(caso.resolver_desde("abertura", self.rodada, 0),
                         epoch(self.INICIO))

    def test_ate_hh_mm_e_a_proxima_vez_em_brasilia(self):
        from garimpo.casos import rajada as caso
        from garimpo.dominio.frescor import epoch
        agora = epoch(self.AGORA)     # 22h
        self.assertEqual(caso.resolver_ate("07:00", agora),
                         epoch("2026-09-20T07:00:00-03:00"))
        self.assertEqual(caso.resolver_ate("23:30", agora),
                         epoch("2026-09-19T23:30:00-03:00"))
        self.assertLess(caso.resolver_ate("2026-09-19T20:00:00-03:00", agora), agora)

    # -- onde a rajada aparece ---------------------------------------------

    @so_com("docs/operacao.md")
    def test_workflow_docs_e_agenda(self):
        base = os.path.dirname(os.path.abspath(__file__))
        with open(os.path.join(base, ".github", "workflows", "testes.yml")) as f:
            wf = f.read()
        laco = wf[wf.index("for script in"):wf.index("done", wf.index("for script in"))]
        self.assertIn("rajada.py", laco)
        self.assertIn('"leituras/**"', wf)
        with open(os.path.join(base, "docs", "operacao.md"), encoding="utf-8") as f:
            doc = f.read()
        secao = doc[doc.index("## 6. Rajada em casa"):]
        for trecho in ("pode rodar a rajada", "14/10", "20/10", "21/10",
                       "--seco", "--desde fechamento", "worktree"):
            self.assertIn(trecho, secao)
        import agenda_do_projeto as ag
        from garimpo.dominio import calendario
        _, abre, fecha = ag.eventos_da_rodada(calendario.abertura(2026, 10))
        self.assertIn("rajada.py", abre.corpo)
        self.assertIn("rajada.py", fecha.corpo)

class TestFrescor(unittest.TestCase):
    """
    A promessa de idade maxima, e a regressao da fila que abandonava gente.

    Em 10/09/2026 a vigia desempatava por nota com o carimbo sempre igual:
    195 vagas, 246 nomes, e os 51 de nota mais baixa nunca voltavam.
    """

    HORA = 3600

    def _item(self, nome, nota=50, **campos):
        from garimpo.dominio import frescor
        campos.setdefault("situacao", Situacao.LIBERACAO_LIVRE)
        return frescor.Item(nome, nota=nota, **campos)

    def test_promessa_dos_quentes_so_com_a_rodada_aberta(self):
        """16/09/2026: fechada a rodada, o alarme nao cobra os quentes."""
        from garimpo.dominio.frescor import epoch, rodada_aberta
        ini, fim = "2026-09-09T15:00:00-03:00", "2026-09-16T15:00:00-03:00"
        self.assertTrue(rodada_aberta(ini, fim, epoch("2026-09-16T14:59:00-03:00")))
        self.assertFalse(rodada_aberta(ini, fim, epoch("2026-09-16T15:01:00-03:00")))
        # lista de outubro saiu, rodada ainda nao abriu
        self.assertFalse(rodada_aberta("2026-10-14T15:00:00-03:00", "2026-10-21T15:00:00-03:00",
                                       epoch("2026-10-12T10:00:00-03:00")))
        self.assertTrue(rodada_aberta(None, fim, 0))

    def test_epoch_compara_fusos_diferentes(self):
        """Como texto, 22:00-03:00 viria antes de 00:30+00:00. E depois."""
        from garimpo.dominio.frescor import epoch
        local = epoch("2026-09-10T22:00:00-03:00")
        runner = epoch("2026-09-11T00:30:00+00:00")
        self.assertGreater(local, runner)
        self.assertEqual(epoch("2026-09-11T01:00:00Z"), local)
        self.assertIsNone(epoch("nao e data"))
        self.assertIsNone(epoch(None))

    def test_classes(self):
        from garimpo.dominio.frescor import Classe, classificar
        itens = [
            self._item("joia.com.br", elegivel=True, nota=10),
            self._item("leilao.com.br", elegivel=True, em_leilao=True),
            self._item("dono.com.br", situacao=Situacao.REGISTRADO),
            self._item("topo.com.br", nota=90),
            self._item("fundo.com.br", nota=20),
        ]
        c = classificar(itens, limite_quente=2)
        self.assertIs(c["joia.com.br"], Classe.QUENTE)   # elegivel vem antes
        self.assertIs(c["topo.com.br"], Classe.QUENTE)
        self.assertIs(c["fundo.com.br"], Classe.FRIO)    # passou do limite
        self.assertIs(c["leilao.com.br"], Classe.LEILAO)
        self.assertIs(c["dono.com.br"], Classe.FIXO)

    def test_faixas_em_ordem_e_fixo_nunca(self):
        from garimpo.dominio.frescor import escolher
        agora = 100 * self.HORA
        itens = [
            self._item("frio.com.br", nota=1, verificado_em=agora - 50 * self.HORA),
            self._item("nunca.com.br", nota=60),
            self._item("quente.com.br", nota=99, verificado_em=agora - 9 * self.HORA),
            self._item("fresco.com.br", nota=98, verificado_em=agora - self.HORA),
            self._item("dono.com.br", situacao=Situacao.REGISTRADO,
                       verificado_em=agora - 99 * self.HORA),
        ]
        # limite 2: so "quente" e "fresco" sao quentes; "nunca" cai na fila
        from garimpo.dominio import frescor
        fila = escolher(itens, agora, 10,
                        intervalo=frescor.INTERVALO_HORAS * self.HORA,
                        limite_quente=2)
        self.assertEqual(fila[:3], ["quente.com.br", "nunca.com.br", "frio.com.br"])
        self.assertNotIn("fresco.com.br", fila)   # dentro do prazo
        self.assertNotIn("dono.com.br", fila)     # ja saiu da rodada

    def test_status5_lido_antes_da_abertura_volta_a_fila(self):
        """
        18/09/2026: um nome travado lido entre a lista (12/10) e a abertura
        (14/10, 15h) responde status 5, que e FIXO. Sem `rodada_inicio`, ele
        nunca mais era relido: 0 de 2.500 na fila da rodada inteira.
        """
        from garimpo.dominio.frescor import Classe, classificar, epoch, escolher
        inicio = epoch("2026-10-14T15:00:00-03:00")
        agora = epoch("2026-10-14T15:01:00-03:00")
        antes = self._item("travado.com.br", nota=95, elegivel=True,
                           situacao=Situacao.AGUARDANDO_LIBERACAO,
                           verificado_em=epoch("2026-10-13T10:00:00-03:00"))
        depois = self._item("dono.com.br", situacao=Situacao.REGISTRADO,
                            verificado_em=epoch("2026-10-14T15:00:30-03:00"))
        fresco = self._item("fresco.com.br", nota=99, verificado_em=agora - 60)
        itens = [antes, depois, fresco]

        # sem a abertura, o comportamento antigo (e a prova do bug)
        self.assertIs(classificar(itens)["travado.com.br"], Classe.FIXO)
        self.assertNotIn("travado.com.br", escolher(itens, agora, 10))

        classes = classificar(itens, rodada_inicio=inicio)
        self.assertIsNot(classes["travado.com.br"], Classe.FIXO)
        self.assertIs(classes["dono.com.br"], Classe.FIXO)   # lido depois
        fila = escolher(itens, agora, 10, rodada_inicio=inicio)
        self.assertEqual(fila[0], "travado.com.br")
        self.assertNotIn("dono.com.br", fila)
        self.assertNotIn("fresco.com.br", fila)

        # capacidade infinita, 2.500 lidos em 13/10: todos voltam
        muitos = [self._item(f"top{n}.com.br", nota=100 - n % 50,
                             situacao=Situacao.AGUARDANDO_LIBERACAO,
                             verificado_em=epoch("2026-10-13T10:00:00-03:00"))
                  for n in range(2500)]
        fila = escolher(muitos, epoch("2026-10-18T09:00:00-03:00"), 10**6,
                        rodada_inicio=inicio)
        self.assertEqual(len(fila), 2500)

    def test_leilao_vencido_nao_espera_a_fila(self):
        """
        A regressao de 16/09/2026: rodada fechada, 200 quentes de leitura
        antiga, 1.474 nunca verificados e 190 vagas. Os 160 leiloes ficavam
        atras da fila e chegaram a 143 h com prazo de 48 h.
        """
        from garimpo.dominio import frescor
        agora = 200 * self.HORA
        antigo = agora - 143 * self.HORA
        itens = ([self._item(f"q{n:03}.com.br", nota=90, verificado_em=antigo)
                  for n in range(200)]
                 + [self._item(f"f{n:04}.com.br", nota=60) for n in range(1474)]
                 + [self._item(f"l{n:03}.com.br", situacao=Situacao.COMPETITIVO,
                               em_leilao=True, verificado_em=antigo)
                    for n in range(160)]
                 + [self._item("recente.com.br", situacao=Situacao.COMPETITIVO,
                               em_leilao=True, verificado_em=agora - self.HORA)])
        fila = frescor.escolher(itens, agora, 190, intervalo=4 * self.HORA,
                                limite_quente=200)
        leiloes = [d for d in fila if d.startswith("l")]
        # cota: 161 leiloes x 4 h / 48 h, sem rajada dos 160 de uma vez
        self.assertEqual(len(leiloes), 14)
        self.assertEqual(fila[0], "l000.com.br")
        self.assertNotIn("recente.com.br", fila)   # dentro das 48 h
        self.assertEqual(len(fila), 190)

    def test_leilao_na_frente_nao_estoura_o_prazo_dos_quentes(self):
        from garimpo.dominio import frescor
        itens = ([self._item(f"q{n:03}.com.br", nota=60 + n % 40, verificado_em=0)
                  for n in range(200)]
                 + [self._item(f"l{n:03}.com.br", situacao=Situacao.COMPETITIVO,
                               em_leilao=True) for n in range(160)]
                 + [self._item(f"f{n:03}.com.br", nota=1) for n in range(500)])
        antes = frescor.INTERVALO_HORAS
        frescor.configurar(4)          # o privado: 4 h, prazo dos quentes 8 h
        try:
            piores, estado = self._simular(itens, capacidade=190, execucoes=16,
                                           intervalo=4, limite_quente=200)
        finally:
            frescor.configurar(antes)
        self.assertLessEqual(max(piores[2:]), 8)
        self.assertTrue(all(estado[f"l{n:03}.com.br"].verificado_em for n in range(160)))

    def _simular(self, itens, capacidade, execucoes, intervalo=None,
                 limite_quente=150, frios_por_execucao=None):
        """
        Roda a fila N vezes. Devolve a maior idade quente vista antes de cada
        execucao e o estado final; se `frios_por_execucao` for uma lista,
        anota nela quantas vagas de cada execucao foram para nao quentes.

        O intervalo padrao e o real (`frescor.INTERVALO_HORAS`), e o prazo
        cobrado tambem sai da constante: a promessa e a razao entre os dois,
        entao fixar um dos lados aqui faria o teste passar a medir uma
        politica que nao existe mais. Foi o que aconteceu ao baixar a
        cadencia de 4 h para 1 h em 12/09/2026.
        """
        from garimpo.dominio import frescor
        if intervalo is None:
            intervalo = frescor.INTERVALO_HORAS
        import dataclasses
        estado = {i.dominio: i for i in itens}
        piores = []
        for n in range(execucoes):
            agora = (n + 1) * intervalo * self.HORA
            classes = frescor.classificar(list(estado.values()), limite_quente)
            idades = [frescor.idade(i, agora) for i in estado.values()
                      if classes[i.dominio] is frescor.Classe.QUENTE]
            piores.append(max(idades) / self.HORA)
            escolhidos = frescor.escolher(list(estado.values()), agora,
                                          capacidade,
                                          intervalo=intervalo * self.HORA,
                                          limite_quente=limite_quente)
            if frios_por_execucao is not None:
                frios_por_execucao.append(sum(
                    1 for d in escolhidos
                    if classes[d] is not frescor.Classe.QUENTE))
            for nome in escolhidos:
                estado[nome] = dataclasses.replace(estado[nome],
                                                   verificado_em=agora)
        return piores, estado

    def test_quente_nao_come_todas_as_vagas(self):
        """
        A regressao da primeira versao, pega em revisao antes de publicar.

        200 quentes, 190 vagas, todos com o mesmo carimbo (como volta um
        instantaneo v3). Com `>=` e horizonte de uma execucao, todo quente
        vencia em toda execucao e a fila de nunca verificados ficava com
        zero vagas para sempre, com o alarme verde. A cota espalha: metade
        da faixa quente por execucao, o resto para a fila, e ainda assim
        ninguem passa do prazo.
        """
        from garimpo.dominio import frescor
        itens = ([self._item(f"q{n:03}.com.br", nota=60 + n % 40,
                             verificado_em=0) for n in range(200)]
                 + [self._item(f"f{n:03}.com.br", nota=1) for n in range(500)])
        frios = []
        piores, _ = self._simular(itens, capacidade=190, execucoes=8,
                                  limite_quente=200, frios_por_execucao=frios)
        self.assertTrue(all(n > 0 for n in frios), frios)
        self.assertLessEqual(max(piores),
                             frescor.PRAZOS[frescor.Classe.QUENTE])

    def test_ninguem_quente_passa_do_prazo(self):
        """
        A regressao. 150 quentes, 100 vagas, na cadencia e no prazo reais:
        cabe, desde que a fila nao abandone ninguem. O de nota mais baixa e
        justamente o que a vigia antiga esquecia.
        """
        from garimpo.dominio import frescor
        itens = ([self._item(f"q{n:03}.com.br", nota=100 - n % 90)
                  for n in range(150)]
                 + [self._item(f"f{n:04}.com.br", nota=1) for n in range(1000)])
        piores, _ = self._simular(itens, capacidade=100, execucoes=30)
        prazo = frescor.PRAZOS[frescor.Classe.QUENTE]
        # as duas primeiras execucoes ainda estao consumindo os nunca vistos
        self.assertLessEqual(max(piores[2:]), prazo)

    def test_sobra_de_vaga_esvazia_a_fila_de_nunca_verificados(self):
        itens = ([self._item(f"q{n:02}.com.br", nota=90) for n in range(50)]
                 + [self._item(f"f{n:03}.com.br", nota=1) for n in range(300)])
        _, estado = self._simular(itens, capacidade=100, execucoes=12,
                                  limite_quente=50)
        nunca = [i for i in estado.values() if i.verificado_em is None]
        self.assertEqual(nunca, [])

    def test_instantaneo_guarda_a_idade_de_cada_um(self):
        """v4: a idade volta do JSON. Antes todo mundo voltava com gerado_em."""
        velho = Candidato("velho.com.br", nota=50, situacao=Situacao.LIBERACAO_LIVRE,
                          candidatos=0, verificado_em="2026-09-09T12:00:00-03:00")
        novo = Candidato("novo.com.br", nota=50, situacao=Situacao.LIBERACAO_LIVRE,
                         candidatos=0, verificado_em="2026-09-10T20:00:00+00:00")
        meta = instantaneo.Metadados(gerado_em="2026-09-10T21:00:00-03:00")
        voltou = {c.dominio: c for c in instantaneo.candidatos_de(
            instantaneo.exportar([velho, novo], meta))}

        from garimpo.dominio.frescor import epoch
        self.assertEqual(epoch(voltou["velho.com.br"].verificado_em),
                         epoch(velho.verificado_em))
        self.assertEqual(epoch(voltou["novo.com.br"].verificado_em),
                         epoch(novo.verificado_em))

    def test_instantaneo_v3_cai_na_data_global(self):
        dados = {"status": ["LIBERACAO_LIVRE"], "marcas": ["OK"], "motivos": [],
                 "gerado_em": "2026-09-10T20:34:18-03:00",
                 "itens": [["x.com.br", 0, 0, 50, 0, [], 0, 0]]}
        c = instantaneo.candidatos_de(dados)[0]
        self.assertEqual(c.verificado_em, "2026-09-10T20:34:18-03:00")

    def test_relatorio_conta_os_vencidos(self):
        from garimpo.dominio.frescor import epoch
        agora = epoch("2026-09-11T12:00:00+00:00")
        velho = Candidato("velho.com.br", elegivel=True, nota=50,
                          situacao=Situacao.LIBERACAO_LIVRE, candidatos=0,
                          verificado_em="2026-09-10T12:00:00+00:00")
        novo = Candidato("novo.com.br", elegivel=True, nota=50,
                         situacao=Situacao.LIBERACAO_LIVRE, candidatos=0,
                         verificado_em="2026-09-11T11:00:00+00:00")
        dados = instantaneo.exportar([velho, novo],
                                     instantaneo.Metadados(gerado_em="x"))
        quente = [l for l in instantaneo.frescor_de(dados, agora)
                  if l["nome"] == "quente"][0]
        self.assertEqual(quente["nomes"], 2)
        self.assertEqual(quente["vencidos"], 1)
        self.assertEqual(quente["exemplos"], ["velho.com.br"])


class TestWordfreq(unittest.TestCase):
    """O leitor de msgpack feito a mao, contra bytes montados a mao."""

    def _arquivo(self, conteudo: bytes) -> str:
        import gzip
        f = tempfile.NamedTemporaryFile(suffix=".msgpack.gz", delete=False)
        f.write(gzip.compress(conteudo))
        f.close()
        self.addCleanup(os.unlink, f.name)
        return f.name

    def test_ranking_segue_a_ordem_dos_baldes(self):
        from garimpo.adaptadores import wordfreq
        # [ {}, ["a","b"], ["c"] ]: array de 3, mapa vazio, dois baldes
        dados = bytes([0x93, 0x80, 0x92, 0xA1]) + b"a" + bytes([0xA1]) + b"b" \
            + bytes([0x91, 0xA1]) + b"c"
        self.assertEqual(wordfreq.ranking(self._arquivo(dados)),
                         {"a": 0, "b": 1, "c": 2})

    def test_tipos_longos(self):
        from garimpo.adaptadores import wordfreq
        palavra = "x" * 40                       # str8: nao cabe no fixstr
        dados = bytes([0xDC, 0, 1, 0xD9, 40]) + palavra.encode()  # array16
        self.assertEqual(wordfreq.desempacotar(dados), [palavra])
        self.assertEqual(wordfreq.desempacotar(bytes([0xD0, 0xFF])), -1)


class TestHunspell(unittest.TestCase):
    AFF = "SET UTF-8\nSFX A Y 2\nSFX A ar a ar\nSFX A ar ou ar\n"

    def test_expande_sufixos(self):
        from garimpo.adaptadores import hunspell
        formas = hunspell.expandir("2\nvacinar/A\nconfiar/A\n", self.AFF)
        for forma in ("vacinar", "vacina", "vacinou", "confia"):
            self.assertIn(forma, formas)

    def test_nome_proprio_fica_de_fora(self):
        """Sobrenome no .dic viraria "palavra" e daria pontos a qualquer um."""
        from garimpo.adaptadores import hunspell
        self.assertNotIn("silva", hunspell.expandir("1\nSilva/A\n", self.AFF))

    def test_tira_acento(self):
        from garimpo.adaptadores import hunspell
        self.assertIn("cafe", hunspell.expandir("1\ncafé\n", self.AFF))


class TestNotaComLexico(unittest.TestCase):
    """
    Os sinais que entraram em 09/2026, cada um com o caso que o motivou: um
    nome que o dono do projeto achou na mao e a nota antiga deixava de fora.
    """

    def _nota(self, dominio, pt=(), en=(), **lexico):
        from garimpo.dominio.relevancia import Lexico
        return pontuar(dominio, set(pt), set(en), lexico=Lexico(**lexico))

    def test_lexico_vazio_e_a_nota_antiga(self):
        from garimpo.dominio.relevancia import Lexico
        antiga = pontuar("custas.com.br", {"custas"}, set())
        nova = pontuar("custas.com.br", {"custas"}, set(), lexico=Lexico())
        self.assertEqual(antiga, nova)

    def test_forma_verbal_conta_como_palavra(self):
        nota = self._nota("aprenda.com.br", flexoes=frozenset({"aprenda"}))
        self.assertGreaterEqual(nota.valor, 45)
        self.assertIn("palavra em português (flexão)", nota.motivos)

    def test_palavra_popular_ganha_um_pouco(self):
        com = self._nota("vacina.com.br", pt={"vacina"}, popularidade={"vacina": 6506})
        sem = self._nota("vacina.com.br", pt={"vacina"})
        self.assertGreater(com.valor, sem.valor)

    def test_composto_de_nicho(self):
        from garimpo.dominio.relevancia import Lexico, composto_de_nicho
        lex = Lexico(comuns=frozenset({"online", "casa", "novos", "friendly"}))
        self.assertEqual(composto_de_nicho("lojaonline", lex), ("loja", "online"))
        self.assertEqual(composto_de_nicho("medicaemcasa", lex), ("medica", "em", "casa"))
        nota = pontuar("imoveisnovos.com.br", set(), set(), lexico=lex)
        self.assertGreaterEqual(nota.valor, 45)

    def test_composto_nao_aceita_nome_de_pessoa(self):
        """A versao solta poria 3.950 nomes no pool, quase todos loja + nome."""
        from garimpo.dominio.relevancia import Lexico, composto_de_nicho
        lex = Lexico(comuns=frozenset({"carol", "valter"}),
                     pessoas=frozenset({"carol", "valter", "leandra"}))
        for nome in ("lojacarol", "casadovalter", "leandraimoveis"):
            self.assertIsNone(composto_de_nicho(nome, lex), nome)

    def test_composto_exige_parte_de_quatro_letras(self):
        from garimpo.dominio.relevancia import Lexico, composto_de_nicho
        lex = Lexico(comuns=frozenset({"ces", "ref"}))
        self.assertIsNone(composto_de_nicho("cesimoveis", lex))

    def test_nicho_com_cidade_grande(self):
        nota = self._nota("imoveisembelem.com.br", cidades=("belem",))
        self.assertIn("nicho + cidade: belem", nota.motivos)
        self.assertGreaterEqual(nota.valor, 45)

    def test_tres_letras_com_br_sempre_entra(self):
        """Recorde de LLL .com.br: R$ 80 mil. hyd saia do pool sem isto."""
        self.assertGreaterEqual(pontuar("hyd.com.br", set(), set()).valor, 45)
        # o pior caso: a pena de repeticao (-10) o deixava em 35 com peso 5
        self.assertGreaterEqual(pontuar("ggg.com.br", set(), set()).valor, 45)

    def test_todo_lll_com_br_de_setembro_passa_do_corte(self):
        """Os 124 LLL .com.br da rodada de 09/09/2026, sem vocabulario."""
        import gzip
        caminho = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                               "docs/historico/listas/2026-09-09-liberacao.txt.gz")
        if not os.path.exists(caminho):
            self.skipTest("lista de setembro ausente (fica so no privado)")
        with gzip.open(caminho, "rt", encoding="utf-8") as f:
            tres = [l.strip() for l in f
                    if re.fullmatch(r"[a-z]{3}\.com\.br", l.strip())]
        self.assertGreaterEqual(len(tres), 100)
        baixos = [d for d in tres if pontuar(d, set(), set()).valor < 45]
        self.assertEqual(baixos, [])

    def test_so_o_peso_de_tres_letras_mudou(self):
        """O ajuste de 19/09/2026 subiu so esse peso; os outros ficam."""
        from garimpo.dominio import relevancia as r
        self.assertEqual(r.PESO_TRES_COM_BR, 15)
        self.assertEqual(
            (r.PESO_SIGLA, r.PESO_CURTO, r.PESO_COM_BR, r.PENA_REPETICAO,
             r.PESO_PALAVRA_PT, r.PESO_PALAVRA_EN, r.PESO_FLEXAO),
            (30, 35, 10, -10, 30, 18, 22))


class TestMarcaPeloSitePopular(unittest.TestCase):
    def test_site_popular_que_nao_e_palavra_e_risco(self):
        from garimpo.dominio.marcas import avaliar
        a = avaliar("jetbrains", sites_populares={"jetbrains": 862})
        self.assertIs(a.risco, Risco.RISCO)
        self.assertIn("862", a.motivo)

    def test_palavra_de_dicionario_vira_so_atencao(self):
        from garimpo.dominio.marcas import avaliar
        a = avaliar("boots", sites_populares={"boots": 9034},
                    e_palavra=lambda nome: nome == "boots")
        self.assertIs(a.risco, Risco.ATENCAO)

    def test_lista_fixa_continua_mandando(self):
        from garimpo.dominio.marcas import avaliar
        a = avaliar("wix", sites_populares={"wix": 625}, e_palavra=lambda n: True)
        self.assertIs(a.risco, Risco.RISCO)
        self.assertIn("marca conhecida", a.motivo)

    def test_sem_lista_nada_muda(self):
        from garimpo.dominio.marcas import avaliar
        self.assertIs(avaliar("jetbrains").risco, Risco.OK)


class TestPoolComVocabularios(unittest.TestCase):
    def test_par_simples_e_objeto_completo(self):
        from garimpo.adaptadores.dicionarios import Vocabularios
        from garimpo.dominio.relevancia import Lexico
        par = ({"custas"}, set())
        completo = Vocabularios(frozenset({"custas"}), frozenset(),
                                Lexico(), {"jetbrains": 862})
        self.assertEqual(pool.nota_de("custas.com.br", par),
                         pool.nota_de("custas.com.br", completo))
        self.assertIs(pool.marca_de("jetbrains.com.br", completo).risco, Risco.RISCO)
        self.assertIs(pool.marca_de("jetbrains.com.br", par).risco, Risco.OK)


_VOCABULARIOS_EM_DISCO = (
    "pt_palavras.txt", "pt_br.dic", "en_words.txt", "morphobr.txt",
    "pt_flexoes.txt", "wordfreq_pt.msgpack.gz", "wordfreq_en.msgpack.gz",
    "pessoas.txt", "cidades_grandes.txt", "tranco.zip")


# Todos, e nao so o primeiro: com um faltando, carregar() baixaria no meio
# da suite, e a regra "nenhum teste toca a rede" quebraria sem aviso.
@unittest.skipUnless(all(os.path.exists(os.path.join("work", f))
                         for f in _VOCABULARIOS_EM_DISCO),
                     "precisa dos vocabularios em work/ (rode o app uma vez)")
class TestSuasEscolhas(unittest.TestCase):
    """
    A ferramenta acha o que o dono achou na mao.

    As candidaturas de setembro de 2026 (CLAUDE.md) com os vocabularios de
    verdade. Todas passam do corte menos tres, anotadas abaixo com o motivo.
    Nao roda no CI: depende de ~70 MB em work/, e a suite nao toca a rede.
    """

    FICAM_DE_FORA = {
        "empregaja",   # "emprega" e verbo, nao radical de nicho
        "agroiot",     # "agro" nao esta nos radicais de nicho
        # "ggg" saiu em 19/09/2026: tres letras .com.br passaram a pesar 15
        # (PESO_TRES_COM_BR, rodada 3b), mais que a penalidade de repeticao; a
        # classe inteira fica acima do corte porque e a mais disputada
    }

    def test_candidaturas_de_setembro(self):
        from garimpo.adaptadores import dicionarios
        vocab = dicionarios.Repositorio("work").carregar()
        escolhas = (
            "peca lista vacina buscador moradias retrato ritmo praga ajude afiliar "
            "confiar redes medidas botica autismo muro perigo picante suave rumor "
            "vassoura foguete imortal apetite mentira custas gabaritos incubadora "
            "gravadora guindaste companhias albergues provedora pinacoteca "
            "irmandade tributaria aprenda estude coisas bichos chama vaca leveza "
            "honesto caravela agridoce one property sneakers hoodie handbags "
            "astrology tracker donate question option census artisan aesthetic "
            "antidote atrium barracuda bonfire lagoon quasar pendant splendid "
            "petfriendly petgourmet imoveisnovos imovelrapido creditopj creditoapp "
            "criptobanco criptopix lojaonline ofertasmega empregaja vooseguro "
            "solarfix agroiot saudeguia medicaemcasa nutripremium combustiveis "
            "con dim hal aum ars qua jeu ota urg kam koh fwd spf rdx dlc edx ggg "
            "cnd frs tpt upm hyd").split()
        abaixo = {w for w in escolhas
                  if pool.nota_de(w + ".com.br", vocab).valor < pool.NOTA_MINIMA}
        self.assertEqual(abaixo, self.FICAM_DE_FORA)


class TestDemandaCnpj(unittest.TestCase):
    """O cadastro de CNPJ como sinal de demanda, com um zip de mentira."""

    # colunas: 0 cnpj_basico, 3 matriz(1)/filial(2), 4 fantasia, 5 situacao,
    # 10 inicio, 11 cnae; o resto vazio (inclusive e-mail e telefone)
    LINHAS = [
        ("11111111", "1", "Pizzaria Bella", "02", "20240105", "5611201"),
        ("11111111", "2", "Pizzaria Bella", "02", "20240105", "5611201"),  # filial
        ("22222222", "1", "PIZZARIA BELLA LTDA", "02", "20200101", "5611201"),
        ("33333333", "1", "Salão Beleza Pura", "02", "20250301", "9602501"),
        ("44444444", "1", "Pizzaria Fechada", "08", "20100101", "5611201"),  # inativa
        ("55555555", "1", "", "02", "20230101", "4781400"),                  # sem fantasia
    ]

    def _zip(self) -> str:
        import zipfile
        f = tempfile.NamedTemporaryFile(suffix=".zip", delete=False)
        f.close()
        self.addCleanup(os.unlink, f.name)
        linhas = []
        for basico, mf, fantasia, sit, inicio, cnae in self.LINHAS:
            campos = [""] * 30
            campos[0], campos[3], campos[4] = basico, mf, fantasia
            campos[5], campos[10], campos[11] = sit, inicio, cnae
            linhas.append(";".join(f'"{c}"' for c in campos))
        with zipfile.ZipFile(f.name, "w") as z:
            z.writestr("K3241.ESTABELE", "\n".join(linhas).encode("latin-1"))
        return f.name

    def test_so_matriz_ativa(self):
        from garimpo.adaptadores import cnpj
        nomes = [m.nome_fantasia for m in cnpj.matrizes_ativas(self._zip())]
        self.assertEqual(nomes, ["Pizzaria Bella", "PIZZARIA BELLA LTDA",
                                 "Salão Beleza Pura", ""])

    def test_conta_por_empresa(self):
        """Filial nao conta de novo; LTDA e acento nao mudam o nome."""
        from garimpo.adaptadores import cnpj
        from garimpo.casos import demanda
        d = demanda.Demanda()
        d.somar(cnpj.matrizes_ativas(self._zip()))
        self.assertEqual(d.empresas, 4)
        self.assertEqual(d.palavras["pizzaria"], 2)
        self.assertEqual(d.palavras["salao"], 1)
        self.assertNotIn("ltda", d.palavras)
        self.assertEqual(d.nomes["pizzariabella"], 1)
        self.assertEqual(d.nomes["pizzariabellaltda"], 1)
        self.assertEqual(d.setores["561"]["pizzaria"], 2)

    def test_colado_vira_rotulo(self):
        from garimpo.casos.demanda import colado
        self.assertEqual(colado("Salão Beleza Pura"), "salaobelezapura")

    def test_ida_e_volta_e_cortes(self):
        from garimpo.casos import demanda
        d = demanda.Demanda(mes="2026-08")
        d.palavras.update({"pizzaria": 900, "rara": 1})
        d.nomes.update({"reidapizza": 3, "unica": 1})
        arquivo = os.path.join(tempfile.mkdtemp(), "demanda.json")
        demanda.gravar(d, arquivo)
        lido = demanda.ler(arquivo)
        self.assertEqual(lido["palavras"], {"pizzaria": 900})
        self.assertEqual(lido["nomes"], {"reidapizza": 3})
        self.assertEqual(lido["mes"], "2026-08")


class TestTodosDaRodada(unittest.TestCase):
    def _rodada(self):
        from garimpo.adaptadores.registrobr import Rodada
        return Rodada(liberacao=["custas.com.br", "lojaonline.com.br",
                                 "zzqx.net.br", "custas.com.br"],
                      elegiveis={"custas.com.br"}, em_leilao=set(),
                      inicio="2026-09-09T15:00:00-03:00",
                      fim="2026-09-16T15:00:00-03:00")

    def test_um_item_por_nome_com_nota(self):
        from garimpo.casos import todos
        dados = todos.montar(self._rodada(), ({"custas"}, set()))
        rotulos = [i[0] for i in dados["itens"]]
        self.assertEqual(rotulos, ["custas", "lojaonline", "zzqx"])  # sem repetido
        custas = dados["itens"][0]
        self.assertEqual(dados["extensoes"][custas[1]], "com.br")
        self.assertEqual(custas[2], pool.nota_de("custas.com.br", ({"custas"}, set()),
                                                 elegivel=True).valor)
        tipos = {dados["motivos"][i] for i in custas[3]}
        self.assertIn("elegível ao leilão", tipos)
        self.assertEqual(dados["marcas"][custas[4]], "OK")

    def test_risco_de_marca_vai_junto(self):
        """Busca na rodada inteira sem o risco levaria gente a nome de terceiro."""
        from garimpo.adaptadores.registrobr import Rodada
        from garimpo.casos import todos
        dados = todos.montar(Rodada(["netflix.com.br"], set(), set()), (set(), set()))
        self.assertEqual(dados["marcas"][dados["itens"][0][4]], "RISCO")

    def test_deterministico(self):
        """Mesmo conteudo, mesmo arquivo: o workflow nao comita a toa."""
        from garimpo.casos import todos
        a = json.dumps(todos.montar(self._rodada(), ({"custas"}, set())))
        b = json.dumps(todos.montar(self._rodada(), ({"custas"}, set())))
        self.assertEqual(a, b)
        self.assertNotIn("gerado_em", a)

    def test_motivo_so_o_tipo(self):
        from garimpo.casos import todos
        from garimpo.adaptadores.dicionarios import Vocabularios
        from garimpo.dominio.relevancia import Lexico
        vocab = Vocabularios(frozenset(), frozenset(),
                             Lexico(comuns=frozenset({"online"})), {})
        dados = todos.montar(self._rodada(), vocab)
        self.assertIn("composto", dados["motivos"])
        self.assertFalse(any(":" in m for m in dados["motivos"]))


class TestCategorias(unittest.TestCase):
    def test_casos_do_ramo(self):
        from garimpo.dominio.categorias import categorias_de
        self.assertIn("imoveis", categorias_de("imoveisembelem"))
        self.assertIn("alimentacao", categorias_de("pizzariabella"))
        self.assertIn("pet", categorias_de("petshopdobairro"))
        self.assertIn("pet", categorias_de("mundopet"))
        self.assertIn("beleza", categorias_de("barbeariadojoao"))
        self.assertIn("juridico", categorias_de("custas"))

    def test_raiz_curta_nao_casa_no_meio(self):
        """Senao "pet" acharia competencia, e "app" acharia happy."""
        from garimpo.dominio.categorias import categorias_de
        self.assertNotIn("pet", categorias_de("competencia"))
        self.assertNotIn("tecnologia", categorias_de("happyhour"))

    def test_palavra_que_engole_a_raiz(self):
        """Cada caso saiu errado numa amostra da rodada de setembro."""
        from garimpo.dominio.categorias import categorias_de
        casos = {
            "srpimoveis": "casa",              # movel dentro de imovel
            "mndvtransportes": "esporte",      # sport dentro de transport
            "investidorcientifico": "moda",    # vestido dentro de investidor
            "dasalesrefrigeracao": "pet",      # racao dentro de refrigeracao
            "paulocarneiro": "alimentacao",    # carne dentro de carneiro
            "mundobizarrobrasil": "construcao",  # obras dentro de robrasil
            "petruscavalcante": "pet",         # Petrus e nome, nao pet
        }
        for rotulo, errado in casos.items():
            self.assertNotIn(errado, categorias_de(rotulo), rotulo)
        # e o certo continua certo
        self.assertIn("imoveis", categorias_de("srpimoveis"))
        self.assertIn("transporte", categorias_de("mndvtransportes"))

    def test_raiz_engolida_hotfix_de_setembro(self):
        """Hotfix de 19/09/2026: cada nome saiu no ramo errado na rodada de
        09/09/2026 (site/todos.json, 125.453 nomes)."""
        from garimpo.dominio.categorias import categorias_de
        casos = {
            "fernandacunha": "beleza",         # unha dentro de cunha
            "anapaula": "educacao",            # aula dentro de paula
            "eletrobras": "construcao",        # obras dentro de eletrobras
            "petrobrasp19": "construcao",      # obras dentro de petrobras
            "eletrobrasacre": "casa",          # eletro dentro de eletrobras
            "recargadecelular": "transporte",  # carga dentro de recarga
            "terrenosportoseguro": "esporte",  # sport em s + portoseguro
            "colchoesportoalegre": "esporte",  # esport em s + portoalegre
            "domusportoes": "esporte",         # sport em s + portoes
            "bordados": "tecnologia",          # dados dentro de bordados
            "cuidados": "tecnologia",          # dados dentro de cuidados
        }
        for rotulo, errado in casos.items():
            self.assertNotIn(errado, categorias_de(rotulo), rotulo)
        # e o certo continua certo
        self.assertIn("imoveis", categorias_de("terrenosportoseguro"))
        self.assertIn("casa", categorias_de("colchoesportoalegre"))
        self.assertIn("esporte", categorias_de("abcdesportos"))
        self.assertIn("construcao", categorias_de("jasolucoesobras"))

    def test_dados_e_digital_so_valem_sozinhos(self):
        """Modificador, nao ramo: com outro ramo no nome, tecnologia sai."""
        from garimpo.dominio.categorias import categorias_de
        # dados atravessando pousada|dosul; digital de marketing digital
        self.assertEqual(categorias_de("pousadadosul"), ("turismo",))
        self.assertEqual(categorias_de("marketingdigital"), ("marketing",))
        # sozinhos, continuam tecnologia
        self.assertEqual(categorias_de("lojadigital"), ("tecnologia",))
        self.assertEqual(categorias_de("centraldedados"), ("tecnologia",))
        # raiz forte de tecnologia ao lado de outra continua valendo
        self.assertIn("tecnologia", categorias_de("techdigitalimoveis"))

    def test_nome_sem_ramo(self):
        from garimpo.dominio.categorias import categorias_de
        self.assertEqual(categorias_de("xqmjml"), ())

    def test_mascara_e_tabela_andam_juntas(self):
        from garimpo.dominio import categorias
        bits = categorias.mascara("petshop")
        nomes = [c["nome"] for i, c in enumerate(categorias.tabela()) if bits & (1 << i)]
        self.assertEqual(nomes, ["pet"])

    def test_nomes_de_pessoas(self):
        """Nome exato ou dois nomes colados; cada metade com 3+ letras."""
        from garimpo.dominio.categorias import categorias_de, mascara, ORDEM
        gente = frozenset({"adriano", "souza", "aline", "bianca", "carlos", "ana"})
        for rotulo in ("carlos", "adrianosouza", "alinebianca", "souzacarlos"):
            self.assertIn("pessoas", categorias_de(rotulo, gente), rotulo)
        for rotulo in ("carloshop", "anaxsouza", "xyzcarlos", "banana"):
            self.assertNotIn("pessoas", categorias_de(rotulo, gente), rotulo)
        # sem a lista, a categoria some em vez de quebrar
        self.assertNotIn("pessoas", categorias_de("carlos"))
        # o bit novo foi no fim: os 18 ramos antigos mantem o numero
        self.assertEqual(ORDEM[-1], "pessoas")
        self.assertEqual(mascara("carlos", gente), 1 << (len(ORDEM) - 1))

    def test_pessoas_nos_dois_json(self):
        """Os dois exportadores recebem a mesma lista e marcam o mesmo bit."""
        from garimpo.casos import todos
        from garimpo.adaptadores.registrobr import Rodada
        from garimpo.dominio.relevancia import Lexico
        gente = frozenset({"adriano", "souza"})

        class Vocab:
            lexico = Lexico(pessoas=gente)

            def __iter__(self):
                return iter((set(), set()))

        t = todos.montar(Rodada(["adrianosouza.com.br"], set(), set()), Vocab())
        c = Candidato("adrianosouza.com.br", situacao=Situacao.LIBERACAO_LIVRE,
                      candidatos=0)
        d = instantaneo.exportar([c], instantaneo.Metadados(gerado_em="x"),
                                 pessoas=gente)
        self.assertTrue(t["itens"][0][5])
        self.assertEqual(d["itens"][0][instantaneo.I_CATEGORIAS], t["itens"][0][5])

    def test_vai_para_os_dois_json(self):
        from garimpo.casos import todos
        from garimpo.adaptadores.registrobr import Rodada
        t = todos.montar(Rodada(["petshop.com.br"], set(), set()), (set(), set()))
        self.assertEqual(t["categorias"][0]["nome"], "alimentacao")
        self.assertTrue(t["itens"][0][5])
        c = Candidato("petshop.com.br", situacao=Situacao.LIBERACAO_LIVRE, candidatos=0)
        d = instantaneo.exportar([c], instantaneo.Metadados(gerado_em="x"))
        self.assertEqual(d["itens"][0][instantaneo.I_CATEGORIAS], t["itens"][0][5])


class TestQualidadeRamos(unittest.TestCase):
    """
    A amostra rotulada (tests/amostra-ramos.tsv, 450 nomes da rodada de
    09/09/2026) vira piso: nenhuma mudanca de raiz piora um ramo em silencio.
    A amostra fica no privado (nomes de gente, NAO_ATRAVESSA); no publico a
    classe e pulada. Por rotulo:
    precisao = ramos certos / ramos dados; revocacao = ramos certos / ramos do
    gabarito; cobertura = nomes com ao menos um ramo certo / nomes com ramo.
    "pessoas" nao entra (vem da lista de nomes, nao das raizes). O piso vale
    so na B de consenso: a A foi vista ao escrever o lexico do prototipo, e
    as 22 linhas em que os dois rotulos da B discordam ficam fora.
    """
    AMOSTRA = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                           "tests", "amostra-ramos.tsv")
    PISO_PRECISAO = 0.90      # B de consenso, taxonomia de 33 ramos
    PISO_PRECISAO_18 = 0.95   # B de consenso, so os 18 ramos de hoje

    @classmethod
    def setUpClass(cls):
        if not os.path.exists(cls.AMOSTRA):
            raise unittest.SkipTest(
                "amostra-ramos.tsv so existe no repositorio privado (NAO_ATRAVESSA)")
        with open(cls.AMOSTRA, encoding="utf-8") as f:
            linhas = [l.rstrip("\n").split("\t") for l in f if not l.startswith("#")]
        cab = linhas[0]
        cls.linhas = [dict(zip(cab, l)) for l in linhas[1:]]

    def _medir(self, linhas, so_18=False):
        from garimpo.dominio.categorias import categorias_de, ORDEM
        hoje = set(ORDEM) - {"pessoas"}
        dados = certos = gabarito = com_ramo = cobertos = 0
        for l in linhas:
            certo = {r for r in l["rotulo"].split(",") if r}
            if so_18:
                certo &= hoje
            dado = set(categorias_de(l["dominio"].split(".")[0])) - {"pessoas"}
            dados += len(dado)
            certos += len(dado & certo)
            gabarito += len(certo)
            com_ramo += bool(certo)
            cobertos += bool(dado & certo)
        return {"precisao": certos / dados, "revocacao": certos / gabarito,
                "cobertura": cobertos / com_ramo,
                "texto": f"precisao {certos}/{dados} = {certos / dados:.0%}, "
                         f"revocacao {certos}/{gabarito} = {certos / gabarito:.0%}, "
                         f"cobertura {cobertos}/{com_ramo} = {cobertos / com_ramo:.0%}"}

    def test_amostra_inteira_e_sem_rede(self):
        self.assertEqual(len(self.linhas), 450)
        self.assertEqual(sum(l["amostra"] == "A" for l in self.linhas), 300)
        self.assertEqual(sum(l["amostra"] == "B" for l in self.linhas), 150)
        with open(self.AMOSTRA, encoding="utf-8") as f:
            self.assertIn("rotulada por agente em 19/09/2026; B com segundo "
                          "rótulo às cegas", f.readline())

    def test_piso_de_precisao(self):
        a = [l for l in self.linhas if l["amostra"] == "A"]
        b = [l for l in self.linhas if l["amostra"] == "B"]
        consenso = [l for l in b if l["diverge"] != "s"]
        print()
        for nome, grupo in (("A (referencia, vista)", a), ("B inteira", b),
                            ("B consenso", consenso)):
            print(f"  ramos {nome}, n={len(grupo)}: {self._medir(grupo)['texto']}")
            print(f"  ramos {nome}, 18 de hoje: {self._medir(grupo, True)['texto']}")
        m = self._medir(consenso)
        self.assertGreaterEqual(m["precisao"], self.PISO_PRECISAO, m["texto"])
        m18 = self._medir(consenso, so_18=True)
        self.assertGreaterEqual(m18["precisao"], self.PISO_PRECISAO_18, m18["texto"])


class TestLembretes(unittest.TestCase):
    """O .ics servido pelo site, que o iPhone abre direto no Calendario."""

    # "agora" fixo: antes o teste dependia do relogio e viraria vermelho
    # sozinho em 17/09/2026 15h, junto com o piso da rodada de setembro.
    ANTES = datetime.datetime(2026, 9, 17, 10, 0,
                              tzinfo=datetime.timezone(datetime.timedelta(hours=-3)))
    DEPOIS = datetime.datetime(2026, 9, 18, 10, 0,
                               tzinfo=datetime.timezone(datetime.timedelta(hours=-3)))

    def test_fim_e_rodada_mais_um_dia(self):
        from garimpo.casos import lembretes
        fim = lembretes.fim_do_leilao("2026-09-16T15:00:00-03:00", self.ANTES)
        self.assertEqual(fim.isoformat(), "2026-09-17T15:00:00-03:00")
        self.assertIsNone(lembretes.fim_do_leilao(None))
        self.assertIsNone(lembretes.fim_do_leilao("lixo"))

    def test_piso_vencido_nao_vira_evento(self):
        """
        O piso e a primeira hora em que o leilao PODE fechar, nao o fim: em
        17/09/2026 groupon.com.br seguia em leilao com o piso vencido havia
        horas. Passado o piso nao ha data honesta, e servir o convite velho
        marcaria no calendario de quem confia um fim que nao aconteceu.
        """
        from garimpo.casos import lembretes
        self.assertIsNone(
            lembretes.fim_do_leilao("2026-09-16T15:00:00-03:00", self.DEPOIS))

    def test_formato_do_calendario(self):
        from garimpo.casos import lembretes
        fim = lembretes.fim_do_leilao("2026-09-16T15:00:00-03:00", self.ANTES)
        texto = lembretes.ics("vacina.com.br", fim)
        linhas = texto.split("\r\n")
        self.assertTrue(texto.endswith("\r\n"))
        self.assertIn("DTEND:20260917T180000Z", linhas)
        self.assertIn("DTSTART:20260917T173000Z", linhas)
        self.assertIn("BEGIN:VALARM", linhas)
        # RFC 5545: nenhuma linha passa de 75 bytes, acento incluso
        self.assertTrue(all(len(l.encode("utf-8")) <= 75 for l in linhas))
        # deterministico: mesma entrada, mesmo arquivo (o git nao ve diferenca)
        self.assertEqual(texto, lembretes.ics("vacina.com.br", fim))

    def test_pasta_refeita(self):
        import tempfile
        from garimpo.casos import lembretes
        fim = lembretes.fim_do_leilao("2026-09-16T15:00:00-03:00", self.ANTES)
        with tempfile.TemporaryDirectory() as d:
            pasta = os.path.join(d, "lembretes")
            self.assertEqual(lembretes.escrever(pasta, ["a.com.br", "b.com.br"], fim), 2)
            self.assertEqual(lembretes.escrever(pasta, ["b.com.br"], fim), 1)
            self.assertEqual(os.listdir(pasta), ["b.com.br.ics"])
            self.assertEqual(lembretes.escrever(pasta, ["b.com.br"], None), 0)
            self.assertFalse(os.path.exists(pasta))


class TestCompatibilidade(unittest.TestCase):
    """filtrar_lista.py continua funcionando por conta propria."""

    def test_sem_acento(self):
        self.assertEqual(sem_acento("informação"), "informacao")

    def test_separar_antigo(self):
        self.assertEqual(separar_antigo("combustiveis.com.br"),
                         ("combustiveis", "com.br"))



# --------------------------------------------------------------------------
# RDAP e "o que aconteceu com esse nome depois"
# --------------------------------------------------------------------------

# resposta real do rdap.registro.br para pneus.com.br, capturada em
# 10/09/2026 e encurtada. E o .br mais caro ja vendido em leilao (R$ 220 mil
# em 2019) e, mesmo pago ate 2029, nao resolve para lugar nenhum.
RDAP_PNEUS = {
    "handle": "pneus.com.br",
    "status": ["active"],
    "events": [
        {"eventAction": "registration", "eventDate": "2019-02-21T21:22:26Z"},
        {"eventAction": "last changed", "eventDate": "2023-04-29T14:41:33Z"},
        {"eventAction": "expiration", "eventDate": "2029-02-21T21:22:26Z"},
    ],
    "nameservers": [{"ldhName": "a.auto.dns.br"}, {"ldhName": "b.auto.dns.br"}],
    "entities": [{
        "handle": "82534819000101",
        "roles": ["registrant"],
        "publicIds": [{"type": "cnpj", "identifier": "82.534.819/0001-01"}],
        "vcardArray": ["vcard", [
            ["version", {}, "text", "4.0"],
            ["kind", {}, "text", "org"],
            ["fn", {}, "text", "SUNSET PNEUS DO BRASIL LTDA"],
        ]],
    }],
}


class TestRdap(unittest.TestCase):
    def test_interpretar_extrai_titular_e_datas(self):
        f = rdap.interpretar("pneus.com.br", RDAP_PNEUS)
        self.assertTrue(f.existe)
        self.assertEqual(f.titular, "SUNSET PNEUS DO BRASIL LTDA")
        self.assertEqual(f.documento, "82.534.819/0001-01")
        self.assertEqual(f.registrado_em, "2019-02-21T21:22:26Z")
        self.assertEqual(f.expira_em, "2029-02-21T21:22:26Z")
        self.assertEqual(f.servidores, ("a.auto.dns.br", "b.auto.dns.br"))

    def test_sem_endereco_e_em_branco(self):
        """Pago, delegado, e ainda assim nao entrega nada."""
        f = rdap.interpretar("pneus.com.br", RDAP_PNEUS, enderecos=())
        self.assertFalse(f.resolve)
        self.assertTrue(f.em_branco)
        self.assertTrue(f.estacionado)      # a.auto.dns.br e do proprio registro

    def test_com_endereco_nao_e_em_branco(self):
        f = rdap.interpretar("x.com.br", RDAP_PNEUS, enderecos=("1.2.3.4",))
        self.assertTrue(f.resolve)
        self.assertFalse(f.em_branco)

    def test_dns_proprio_nao_e_estacionado(self):
        dados = dict(RDAP_PNEUS, nameservers=[{"ldhName": "ns1.locaweb.com.br"}])
        self.assertFalse(rdap.interpretar("x.com.br", dados).estacionado)

    def test_vcard_ausente_nao_explode(self):
        """Nem toda entidade traz vcard; faltar nao pode virar excecao."""
        dados = {"entities": [{"roles": ["registrant"]}], "events": []}
        f = rdap.interpretar("x.com.br", dados)
        self.assertIsNone(f.titular)
        self.assertTrue(f.existe)

    def test_resolver_devolve_vazio_em_vez_de_excecao(self):
        """
        Nome que nao resolve e resposta, nao falha.

        O getaddrinfo e trocado em vez de consultar um nome de verdade:
        nenhum teste deste arquivo pode depender de rede.
        """
        with unittest.mock.patch("socket.getaddrinfo",
                                 side_effect=OSError("sem resposta")):
            self.assertEqual(rdap.resolver("qualquer.com.br"), ())

    def test_resolver_ordena_e_remove_repetido(self):
        infos = [(0, 0, 0, "", ("1.2.3.4", 0)), (0, 0, 0, "", ("1.2.3.4", 0)),
                 (0, 0, 0, "", ("1.1.1.1", 0))]
        with unittest.mock.patch("socket.getaddrinfo", return_value=infos):
            self.assertEqual(rdap.resolver("qualquer.com.br"),
                             ("1.1.1.1", "1.2.3.4"))


# resposta real da CDX do Internet Archive para pneus.com.br, capturada em
# 10/09/2026 e encurtada. E o registro que corrigiu a historia: entre 2019 e
# 2023 o dominio NAO estava parado, estava redirecionando.
CDX_PNEUS = [
    ["urlkey", "timestamp", "original", "mimetype", "statuscode", "digest", "length"],
    ["br,com,pneus)/", "19990125", "http://pneus.com.br/", "text/html", "200", "X", "1"],
    ["br,com,pneus)/", "20031012", "http://pneus.com.br/", "text/html", "200", "X", "1"],
    ["br,com,pneus)/", "20040118", "http://pneus.com.br/", "text/html", "403", "X", "1"],
    ["br,com,pneus)/", "20081222", "http://pneus.com.br/", "text/html", "403", "X", "1"],
    ["br,com,pneus)/", "20190502", "http://pneus.com.br/", "text/html", "301", "X", "1"],
    ["br,com,pneus)/", "20230405", "http://pneus.com.br/", "text/html", "301", "X", "1"],
]


class TestWayback(unittest.TestCase):
    def test_interpretar_monta_a_linha_do_tempo(self):
        h = wayback.interpretar("pneus.com.br", CDX_PNEUS)
        self.assertTrue(h.existe)
        self.assertEqual(h.primeira, "199901")
        self.assertEqual(h.ultima, "202304")
        self.assertEqual(len(h.capturas), 5 + 1)

    def test_teve_site_e_diferente_de_respondeu(self):
        """
        A distincao que corrigiu a afirmacao publicada: 301 nao e site, mas
        tambem nao e abandono.
        """
        h = wayback.interpretar("pneus.com.br", CDX_PNEUS)
        self.assertTrue(h.teve_site)               # houve 200 la atras
        self.assertEqual(h.ultima_viva, "202304")  # o ultimo 301 conta
        self.assertEqual(h.anos_de_site, 2)        # 1999 e 2003

    def test_sem_captura_nao_explode(self):
        h = wayback.interpretar("nunca-existiu.com.br", [])
        self.assertFalse(h.existe)
        self.assertFalse(h.teve_site)
        self.assertIsNone(h.ultima_viva)
        self.assertIn("nunca capturado", h.resumo())

    def test_le_colunas_pelo_cabecalho_e_nao_por_indice(self):
        """A CDX ja mudou de formato; ler por posicao fixa seria apostar."""
        trocado = [["statuscode", "timestamp"], ["200", "20200101"]]
        h = wayback.interpretar("x.com.br", trocado)
        self.assertEqual(h.primeira, "202001")
        self.assertTrue(h.teve_site)

    def test_cabecalho_sem_as_colunas_esperadas_vira_erro(self):
        h = wayback.interpretar("x.com.br", [["foo", "bar"], ["1", "2"]])
        self.assertIsNotNone(h.erro)


class ClienteRdapFalso:
    """Substitui o rdap.registro.br nos testes de historias."""

    def __init__(self, fichas):
        self.fichas = fichas
        self.consultados = []

    def ficha(self, dominio):
        self.consultados.append(dominio)
        return self.fichas.get(dominio, rdap.Ficha(dominio=dominio, existe=False))


class ArquivoFalso:
    """Substitui o Internet Archive nos testes de historias."""

    def __init__(self, historicos=None):
        self.historicos = historicos or {}
        self.consultados = []

    def historico(self, dominio):
        self.consultados.append(dominio)
        return self.historicos.get(dominio, wayback.Historico(dominio=dominio))


class TestHistorias(unittest.TestCase):
    def setUp(self):
        self.cliente = ClienteRdapFalso({
            "pneus.com.br": rdap.interpretar("pneus.com.br", RDAP_PNEUS),
            "ativo.com.br": rdap.Ficha(
                dominio="ativo.com.br", existe=True,
                servidores=("ns1.locaweb.com.br",), enderecos=("1.2.3.4",)),
            "parado.com.br": rdap.Ficha(
                dominio="parado.com.br", existe=True,
                servidores=("a.auto.dns.br",), enderecos=("200.160.2.95",)),
            "quebrado.com.br": rdap.Ficha(dominio="quebrado.com.br", erro="http 500"),
        })

    def investigar(self, dominios, arquivo=None):
        return historias.investigar(
            [{"dominio": d} for d in dominios], cliente=self.cliente,
            pausa=0, arquivo=arquivo)

    def test_categorias(self):
        achados = {h.dominio: h.categoria for h in self.investigar(
            ["pneus.com.br", "ativo.com.br", "parado.com.br",
             "livre.com.br", "quebrado.com.br"])}
        self.assertEqual(achados["pneus.com.br"], historias.EM_BRANCO)
        self.assertEqual(achados["ativo.com.br"], historias.ATIVO)
        self.assertEqual(achados["parado.com.br"], historias.ESTACIONADO)
        self.assertEqual(achados["livre.com.br"], historias.LIVRE)
        self.assertEqual(achados["quebrado.com.br"], historias.ERRO)

    def test_so_o_inesperado_e_notavel(self):
        """Dominio que funciona nao e historia: e o esperado."""
        por_nome = {h.dominio: h for h in self.investigar(
            ["pneus.com.br", "ativo.com.br", "parado.com.br"])}
        self.assertTrue(por_nome["pneus.com.br"].notavel)
        self.assertTrue(por_nome["parado.com.br"].notavel)
        self.assertFalse(por_nome["ativo.com.br"].notavel)

    def test_contexto_sobrevive_a_consulta(self):
        achados = historias.investigar(
            [{"dominio": "pneus.com.br", "valor": "R$ 220.000",
              "ano": "2019", "fonte": "NIC.br"}],
            cliente=self.cliente, pausa=0, arquivo=None)
        self.assertEqual(achados[0].valor, "R$ 220.000")
        self.assertIn("R$ 220.000", historias.resumir(achados))

    def test_sem_arquivo_nao_consulta_o_archive(self):
        """`arquivo=None` precisa mesmo pular a requisicao extra."""
        arquivo = ArquivoFalso()
        historias.investigar([{"dominio": "pneus.com.br"}],
                             cliente=self.cliente, pausa=0, arquivo=None)
        self.assertEqual(arquivo.consultados, [])

    def test_arquivo_distingue_morreu_de_nunca_foi_nada(self):
        arquivo = ArquivoFalso({
            "pneus.com.br": wayback.interpretar("pneus.com.br", CDX_PNEUS),
        })
        achados = self.investigar(["pneus.com.br", "ativo.com.br"],
                                  arquivo=arquivo)
        por_nome = {h.dominio: h for h in achados}
        self.assertTrue(por_nome["pneus.com.br"].ja_teve_site)
        self.assertFalse(por_nome["ativo.com.br"].ja_teve_site)
        self.assertEqual(arquivo.consultados,
                         ["pneus.com.br", "ativo.com.br"])
        # o resumo precisa contar isso, senao a descoberta nao chega a ninguem
        self.assertIn("arquivo:", historias.resumir(achados))

    def test_arquivo_fora_do_ar_nao_vira_nunca_teve_site(self):
        """14/09/2026: com o arquivo em 503, x.com.br saiu sem capturas e o site publicou isso."""
        arquivo = ArquivoFalso({
            "pneus.com.br": wayback.Historico(dominio="pneus.com.br", erro="http 503"),
        })
        achados = self.investigar(["pneus.com.br"], arquivo=arquivo)
        self.assertIn("nada a concluir", historias.resumir(achados))
        with tempfile.TemporaryDirectory() as pasta:
            caminho = os.path.join(pasta, "saida.csv")
            historias.escrever(achados, caminho)
            import csv
            linha = next(csv.DictReader(open(caminho, encoding="utf-8")))
        self.assertEqual(linha["arquivo_teve_site"], "erro")
        self.assertEqual(linha["arquivo_erro"], "http 503")

    def test_classificar_conta_tudo(self):
        contagem = historias.classificar(
            self.investigar(["pneus.com.br", "ativo.com.br"]))
        self.assertEqual(contagem[historias.EM_BRANCO], 1)
        self.assertEqual(contagem[historias.ATIVO], 1)
        self.assertEqual(contagem[historias.LIVRE], 0)

    def test_ida_e_volta_do_csv(self):
        with tempfile.TemporaryDirectory() as pasta:
            caminho = os.path.join(pasta, "saida.csv")
            historias.escrever(self.investigar(["pneus.com.br"]), caminho)
            texto = open(caminho, encoding="utf-8").read()
            self.assertIn("SUNSET PNEUS DO BRASIL LTDA", texto)
            self.assertIn(historias.EM_BRANCO, texto)



if __name__ == "__main__":
    unittest.main()


class TestPaginas(unittest.TestCase):
    """Uma URL por assunto: montagem pura, sem ler o site_modelo."""

    LAYOUT = ("<title>{{titulo}}</title>"
              "<link rel=canonical href=\"{{canonical}}\">{{jsonld}}"
              "<nav>{{nav}}</nav>{{cabecalho_extra}}{{regua}}"
              "<main class={{classe_main}}>{{miolo}}</main><footer>{{rodape}}</footer>"
              "{{scripts}}<!-- {{nome}} {{descricao}} -->")

    def fragmento(self, **extra):
        meta = {"titulo": "As regras", "descricao": "O que vale.", **extra}
        cabeca = "<!--\n" + "".join(f"{k}: {v}\n" for k, v in meta.items()) + "-->\n"
        return cabeca + '<p id="p-total-rodada">-</p><table id="tab-bonus"></table>'

    def test_le_metadados_e_corpo(self):
        from garimpo.web import paginas
        p = paginas.ler_fragmento(self.fragmento(tipo="pagina", data="2026-09-11"),
                                  "regras-do-br")
        self.assertEqual(p.titulo, "As regras")
        self.assertEqual(p.caminho, "/regras-do-br/")
        self.assertTrue(p.corpo.startswith('<p id="p-total-rodada">'))
        self.assertEqual(p.data, "2026-09-11")

    def test_metadado_obrigatorio_e_descricao_curta(self):
        from garimpo.web import paginas
        with self.assertRaises(ValueError):
            paginas.ler_fragmento("<p>sem metadados</p>", "x")
        with self.assertRaises(ValueError):
            paginas.ler_fragmento(self.fragmento(descricao="x" * 161), "x")

    def test_slug_do_arquivo(self):
        from garimpo.web import paginas
        self.assertEqual(paginas.slug_do_arquivo("ferramenta.html"), "")
        self.assertEqual(paginas.slug_do_arquivo("insights/capsula.html"), "insights/capsula")

    def test_render_tem_um_h1_e_canonical(self):
        from garimpo.web import paginas
        p = paginas.ler_fragmento(self.fragmento(), "regras-do-br")
        html = paginas.render(p, self.LAYOUT, base="https://ex.br")
        self.assertEqual(html.count("<h1"), 1)
        self.assertIn('href="https://ex.br/regras-do-br/"', html)
        # sem regra de indexacao no HTML (nem no _headers, ver abaixo)
        self.assertNotIn("robots", html)
        self.assertIn('<a class="aba" href="/regras-do-br/" aria-current="page">', html)
        self.assertNotIn('id="carimbo"', html)      # so a ferramenta tem
        self.assertIn("<title>As regras · Liberados</title>", html)

    def test_render_ferramenta(self):
        from garimpo.web import paginas
        p = paginas.ler_fragmento(self.fragmento(tipo="ferramenta", scripts="app.js"), "")
        html = paginas.render(p, self.LAYOUT, base="https://ex.br")
        self.assertIn('href="https://ex.br/"', html)
        # o h1 da raiz e a primeira coisa que se le: nunca so para leitor de tela
        self.assertIn('<h1 class="titulo-inicio">', html)
        self.assertNotIn('<h1 class="sr-apenas">', html)
        self.assertIn('id="carimbo"', html)
        self.assertIn('<script src="/app.js"></script>', html)
        self.assertIn('"@type": "WebSite"', html)

    def test_relogio_conta_ate_a_proxima_rodada(self):
        """Contagem regressiva do inicio (16/09/2026): datas pela regra, prontas no HTML."""
        from garimpo.web import paginas
        rodada = {"inicio": "2026-09-09T15:00:00-03:00", "fim": "2026-09-16T15:00:00-03:00"}
        fechada = {"gerado_em": "2026-09-17T01:00:00+00:00", "rodada": rodada}
        caixa = paginas.relogio_da_pagina(fechada)
        self.assertIn('data-alvo="2026-10-12T00:00:00-03:00"', caixa)
        self.assertIn('data-alvo="2026-10-21T15:00:00-03:00"', caixa)
        self.assertIn('<time id="relogio-quando" datetime="2026-10-14T15:00:00-03:00">'
                      "quarta-feira, 14/10/2026, às 15h", caixa)
        self.assertIn('data-marco="abre" data-alvo="2026-10-14T15:00:00-03:00" '
                      'data-rotulo="A rodada de outubro abre em"', caixa)
        self.assertIn('data-desde="2026-09-16T15:00:00-03:00"', caixa)
        self.assertEqual(caixa.count('aria-pressed="true"'), 1)
        self.assertNotIn("style=", caixa)   # a CSP bloqueia
        passos_fechada = paginas.passos_da_pagina(fechada)
        self.assertIn("Candidate-se de 14/10 a 21/10", passos_fechada)
        self.assertIn('href="/dominios/"', passos_fechada)   # achado o2: link nos passos
        # aberta: conta ate o fechamento dela e os passos ficam os do modelo
        aberta = {"gerado_em": "2026-09-12T12:00:00+00:00", "rodada": rodada}
        caixa = paginas.relogio_da_pagina(aberta)
        self.assertIn('datetime="2026-09-16T15:00:00-03:00">quarta-feira, 16/09/2026', caixa)
        self.assertIn("A rodada de setembro fecha em", caixa)
        self.assertEqual(paginas.passos_da_pagina(aberta), "")
        self.assertEqual(paginas.relogio_da_pagina({}), "")
        corpo = paginas.preencher_numeros('<div id="p-relogio"></div>', fechada)
        self.assertIn('<section class="relogio"', corpo)

    def test_toda_pagina_diz_o_que_e_o_liberado(self):
        """Quem chega pelo Google numa pagina de texto nunca viu o inicio."""
        from garimpo.web import paginas
        for tipo in ("ferramenta", "pagina"):
            p = paginas.ler_fragmento(self.fragmento(tipo=tipo), "" if tipo == "ferramenta" else "x")
            html = paginas.render(p, self.LAYOUT, base="https://ex.br")
            self.assertIn(paginas.DEFINICAO, html)
            self.assertIn('<a href="/sobre/">', html)
        org = self.do_grafo(paginas.json_ld(p, "https://ex.br"), "Organization")
        self.assertEqual(org["description"], paginas.DEFINICAO)
        # quem faz: a mesma pessoa no JSON-LD e na pagina Sobre
        self.assertEqual(org["founder"]["sameAs"], [paginas.AUTOR_LINKEDIN])
        with open(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                               "site_modelo", "conteudo", "sobre.html"), encoding="utf-8") as f:
            sobre = f.read()
        self.assertIn(paginas.AUTOR, sobre)
        self.assertIn(paginas.AUTOR_LINKEDIN, sobre)
        # a mesma definicao tambem abre o llms.txt (achado o2-site-definicao)
        self.assertIn(paginas.DEFINICAO, paginas.llms_txt([p], "https://ex.br"))
        # sobre.html complementa a definicao, nunca copia ela a mao
        # (AGENTS.md: "Mudou o produto, mude a frase ali, nunca em copia solta")
        self.assertNotIn(paginas.DEFINICAO, sobre)

    def test_rodape_leva_aos_caminhos_fixos(self):
        """O rodape e a porta fixa para /dominios/, o ciclo de vida e o
        glossario (18/09/2026): antes so "Sobre" tinha link dali, e um alvo
        de toque de pelo menos 24px."""
        from garimpo.web import paginas
        modelo = os.path.join(os.path.dirname(os.path.abspath(__file__)), "site_modelo")
        with open(os.path.join(modelo, "layout.html"), encoding="utf-8") as f:
            layout = f.read()
        paginas_carregadas = paginas.carregar(modelo)
        self.assertTrue(paginas_carregadas)
        for p in paginas_carregadas:
            with self.subTest(slug=p.slug or "/"):
                html = paginas.render(p, layout, base="https://ex.br")
                self.assertIn('<nav class="rodape-nav" aria-label="Rodapé">', html)
                for href, rotulo in paginas.CAMINHOS_RODAPE:
                    self.assertIn(f'<a href="{href}">{rotulo}</a>', html)
        css = open(os.path.join(modelo, "extra.css"), encoding="utf-8").read()
        self.assertIn(".rodape-nav a", css)
        self.assertIn("min-height: 1.5rem", css)   # 24px: alvo de toque minimo

    def test_adv_med_ind_sem_comprovacao(self):
        """.adv.br, .med.br e .ind.br sao "sem restricao" (Res. CGI.br 2008/008,
        art. 14, II e III; categorias.txt sem asterisco): nenhuma pagina pode
        dizer que exigem documento, OAB ou CRM (achado de 18/09/2026,
        docs/limitacoes-registrobr.md S17)."""
        raiz = os.path.dirname(os.path.abspath(__file__))
        pasta = os.path.join(raiz, "site_modelo", "conteudo")
        proibidas = ("OAB", "CRM", "por quem tem a profissão",
                     "que exige comprova", "que exigem comprova")
        for dirpath, _, nomes in os.walk(pasta):
            for nome in sorted(nomes):
                if not nome.endswith(".html"):
                    continue
                caminho = os.path.join(dirpath, nome)
                texto = open(caminho, encoding="utf-8").read()
                for proibida in proibidas:
                    self.assertNotIn(proibida, texto,
                                      f"{caminho}: {proibida!r}")

    @so_com("site_modelo/conteudo/extensoes-do-dominio-br.html")
    def test_extensoes_numeros_da_lista_somam(self):
        """/extensoes-do-dominio-br/ (19/09/2026): os numeros da lista de
        09/09/2026 sao escritos a mao; as 109 categorias somam o total dos
        grupos e o da resposta curta, e o titulo_busca nao repete outra pagina."""
        import re
        raiz = os.path.dirname(os.path.abspath(__file__))
        pasta = os.path.join(raiz, "site_modelo", "conteudo")
        texto = open(os.path.join(pasta, "extensoes-do-dominio-br.html"),
                     encoding="utf-8").read()
        num = lambda s: int(s.replace(".", ""))
        por_categoria = re.findall(
            r'<tr><td><code>\.[a-z0-9]+\.br</code></td><td class="num">([\d.]+)</td></tr>',
            texto)
        self.assertEqual(len(por_categoria), 109)
        total = sum(num(n) for n in por_categoria)
        grupos = re.findall(r'<tr><td>(?!Total)[A-Z][^<]*(?:<code>[^<]*</code>[^<]*)?</td>'
                            r'<td class="num">([\d.]+)</td></tr>', texto)
        self.assertEqual(len(grupos), 4)
        self.assertEqual(sum(num(n) for n in grupos), total)
        self.assertIn(f'<td>Total</td><td class="num">{total:,}</td>'.replace(",", "."), texto)
        self.assertIn(f"entraram {total:,} domínios".replace(",", "."), texto)
        # a pagina e o Mapa de intencoes: titulo_busca unico no site
        vistos = {}
        for dirpath, _, nomes in os.walk(pasta):
            for nome in nomes:
                if nome.endswith(".html"):
                    t = open(os.path.join(dirpath, nome), encoding="utf-8").read()
                    m = re.search(r"^titulo_busca: (.+)$", t, re.M)
                    if m:
                        self.assertNotIn(m.group(1), vistos, nome)
                        vistos[m.group(1)] = nome

    def test_inicio_explica_antes_dos_numeros(self):
        """A apresentacao vem antes dos cartoes, e Joias nao nasce visivel em zero."""
        with open(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                               "site_modelo", "conteudo", "ferramenta.html"),
                  encoding="utf-8") as f:
            corpo = f.read()
        self.assertLess(corpo.index('class="apresentacao"'), corpo.index('class="cartoes"'))
        self.assertIn('class="cartao destaque escondido" type="button" data-filtro="joias"', corpo)
        self.assertIn('id="fase-inicio"', corpo)

    def test_cartao_sem_competicao_zerado_some_entre_rodadas(self):
        """Relida a lista inteira, ninguem fica "fechou sem candidato": entre rodadas o cartao zerado some (19/09/2026)."""
        js = open(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                               "site_modelo", "app.js"), encoding="utf-8").read()
        trecho = js[js.index("const semComp = document.querySelector"):]
        trecho = trecho[:trecho.index("const painelCartoes")]
        # entre rodadas o cartao zerado some; com a rodada aberta, so encurta
        self.assertIn("contagem.sem_competicao === 0", trecho)
        self.assertIn("semComp.classList.toggle('escondido', fechada)", trecho)
        self.assertIn("'Nenhum agora'", trecho)
        self.assertIn("semComp.classList.remove('escondido')", trecho)
        # a cadeia de Joias tambem nao pode parar num cartao vazio
        self.assertIn("contagem.sem_competicao ? 'sem_competicao' : filtroInicial()", js)

    def test_fonte_propria_vai_ao_site_e_cabe_na_csp(self):
        """A fonte e servida pelo proprio site: a CSP e font-src 'self' e nada chama terceiro (19/09/2026)."""
        raiz = os.path.dirname(os.path.abspath(__file__))
        modelo = os.path.join(raiz, "site_modelo")
        # a pasta inteira vai para o site, com a licenca junto (exige a OFL)
        import exportar_site as exp
        self.assertIn("fontes", exp.PASTAS)
        fontes = os.path.join(modelo, "fontes")
        arquivos = os.listdir(fontes)
        self.assertIn("instrument-sans-latin.woff2", arquivos)
        self.assertIn("instrument-sans-latin-ext.woff2", arquivos)
        self.assertTrue([n for n in arquivos if n.startswith("LICENCA")], arquivos)
        css = open(os.path.join(modelo, "extra.css"), encoding="utf-8").read()
        layout = open(os.path.join(modelo, "layout.html"), encoding="utf-8").read()
        cabecalhos = open(os.path.join(modelo, "_headers"), encoding="utf-8").read()
        # todo src do @font-face aponta para /fontes/ do proprio site
        import re
        for url in re.findall(r"src: url\(\"([^\"]+)\"\)", css):
            self.assertTrue(url.startswith("/fontes/"), url)
            self.assertTrue(os.path.exists(os.path.join(modelo, url.lstrip("/"))), url)
        self.assertIn("font-src 'self'", cabecalhos)
        self.assertNotIn("fonts.googleapis.com", cabecalhos + css + layout)
        self.assertNotIn("fonts.gstatic.com", cabecalhos + css + layout)
        # o preload existe, aponta para um arquivo real e vem antes do CSS
        preload = re.search(r'<link rel="preload" href="([^"]+)" as="font"[^>]*crossorigin>', layout)
        self.assertIsNotNone(preload, "sem preload da fonte")
        self.assertTrue(os.path.exists(os.path.join(modelo, preload.group(1).lstrip("/"))))
        self.assertLess(layout.index("rel=\"preload\""), layout.index('href="/style.css"'))
        self.assertIn("/fontes/*", cabecalhos)

    def test_estilo_usa_os_tokens_de_fonte_e_raio(self):
        """Uma familia, um monoespacado e tres raios: nada de valor solto (19/09/2026)."""
        css = open(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "web", "style.css"), encoding="utf-8").read()
        for token in ("--fonte:", "--fonte-mono:", "--raio-p:", "--raio:", "--raio-g:", "--sombra:"):
            self.assertIn(token, css)
        corpo = css[css.index("body {"):]
        self.assertIn("font-family: var(--fonte);", corpo[:corpo.index("}")])
        # fora da declaracao dos tokens, ninguem mais escreve a pilha na mao
        depois = css[css.index("--fonte-mono:"):]
        depois = depois[depois.index("\n"):]
        self.assertNotIn("ui-monospace", depois)
        self.assertNotIn("-apple-system", depois)
        # raio solto so nas pilulas (999px)
        import re
        # 999px e a pilula; 0.25rem e a marca do texto selecionado; o par
        # "0 999px 999px 0" e a ponta arredondada da barra do relogio
        soltos = [v for v in re.findall(r"border-radius: ([^;]+);", css)
                  if "var(--raio" not in v
                  and v.strip() not in ("999px", "0.25rem", "0 999px 999px 0")]
        self.assertEqual([], soltos, soltos)

    def test_barra_de_filtros_e_painel_so_no_computador(self):
        """A barra vira painel no computador; no celular a altura nao muda (revertida em 18/09 por empurrar a lista)."""
        css = open(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "site_modelo", "extra.css"), encoding="utf-8").read()
        bloco = css[css.index("barra de filtros"):]
        bloco = bloco[:bloco.index("}\n}") + 3] if "}\n}" in bloco else bloco
        self.assertIn("@media (min-width: 40.0625rem)", bloco)
        self.assertIn("#controles {", bloco)
        # nada de regra para tela pequena neste bloco
        self.assertNotIn("max-width: 40rem", bloco)

    def test_link_de_parametro_nao_gasta_rastreio(self):
        """?d= e ?ramo= tem canonical e nunca sao indexadas: os links por nome levam nofollow (20/09/2026)."""
        raiz = os.path.dirname(os.path.abspath(__file__))
        ramos = open(os.path.join(raiz, "garimpo", "web", "ramos.py"), encoding="utf-8").read()
        letras = open(os.path.join(raiz, "garimpo", "web", "letras.py"), encoding="utf-8").read()
        js = open(os.path.join(raiz, "site_modelo", "app.js"), encoding="utf-8").read()
        import re
        for arquivo, texto in (("ramos.py", ramos), ("letras.py", letras)):
            for linha in texto.split("\n"):
                if "quando-volta/?d=" in linha and "<a " in linha:
                    self.assertIn('rel="nofollow"', linha, f"{arquivo}: {linha.strip()[:80]}")
            for linha in texto.split("\n"):
                if 'href="/?ramo=' in linha:
                    self.assertIn('rel="nofollow"', linha, f"{arquivo}: {linha.strip()[:80]}")
        # no navegador, todo link montado para a ficha tambem marca nofollow
        criados = len(re.findall(r"quando-volta/\?d=\$\{encodeURIComponent", js))
        marcados = len(re.findall(r"rel = 'nofollow'|rel=\"nofollow\"", js))
        self.assertGreaterEqual(marcados, criados - 1, "link de ficha sem nofollow no app.js")

    def test_toda_ordem_do_seletor_tem_ordenador(self):
        """Opcao de ordem sem ordenador cai calada na relevancia (14/09/2026: A a Z e Z a A)."""
        import re
        raiz = os.path.dirname(os.path.abspath(__file__))
        html = open(os.path.join(raiz, "site_modelo", "conteudo", "ferramenta.html"), encoding="utf-8").read()
        js = open(os.path.join(raiz, "site_modelo", "app.js"), encoding="utf-8").read()
        seletor = re.search(r'<select id="ordem">(.*?)</select>', html, re.S).group(1)
        valores = re.findall(r'value="([^"]+)"', seletor)
        self.assertIn("alfabetica_desc", valores)
        bloco = re.search(r"const ordenadores = \{(.*?)\n  \};", js, re.S).group(1)
        for v in valores:
            self.assertRegex(bloco, rf"\b{v}:", v)
        from garimpo.web import consultas
        local = open(os.path.join(raiz, "web", "index.html"), encoding="utf-8").read()
        seletor = re.search(r'<select id="ordem">(.*?)</select>', local, re.S).group(1)
        for v in re.findall(r'value="([^"]+)"', seletor):
            self.assertIn(v, consultas.ORDENS, v)

    def test_filtro_com_busca_abre_painel_sem_teclado(self):
        """14/09/2026: o campo de texto no lugar do seletor abria o teclado do
        celular ao tocar. O gatilho e botao, o painel e dialog, e no celular o
        foco vai para a lista, nao para a busca."""
        import re
        js = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "site_modelo", "app.js"),
                  encoding="utf-8").read()
        corpo = js[js.index("function tornarBuscavel"):js.index("function sincronizarBuscaveis")]
        self.assertIn("setAttribute('aria-haspopup', 'dialog')", corpo)
        self.assertIn("showModal()", corpo)
        self.assertNotIn("'combobox'", corpo)
        ramo_celular = re.search(r"if \(celular\(\)\) \{(.*?)\} else \{", corpo[corpo.index("function abrir"):], re.S).group(1)
        self.assertNotIn("busca.focus", ramo_celular)

    def _app_js(self):
        return open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "site_modelo", "app.js"),
                    encoding="utf-8").read()

    def test_filtro_de_situacao_so_tem_chaves_conhecidas(self):
        """15/09/2026: toda opcao do seletor de situacao sai de SITUACOES (ou e nao verificado)."""
        import re
        raiz = os.path.dirname(os.path.abspath(__file__))
        html = open(os.path.join(raiz, "site_modelo", "conteudo", "ferramenta.html"), encoding="utf-8").read()
        seletor = re.search(r'<select id="situacao"[^>]*>(.*?)</select>', html, re.S).group(1)
        valores = [v for v in re.findall(r'value="([^"]*)"', seletor) if v]
        js = self._app_js()
        bloco = re.search(r"const SITUACOES = \{(.*?)\n\};", js, re.S).group(1)
        conhecidas = set(re.findall(r":\s*'([a-z_]+)'", bloco)) | {"nao_verificado"}
        self.assertEqual(set(valores), conhecidas)

    def test_conferir_nao_reordena_e_filtros_contam(self):
        """15/09/2026: a conferencia ao vivo mantem a ordem da tela; aplicar reescreve as contagens."""
        js = self._app_js()
        fila = js[js.index("async function processarFila"):]
        self.assertIn("aplicar({ manterOrdem: true })", fila[:fila.index("\n}\n")])
        corpo = js[js.index("function aplicar("):js.index("// ------------------------------------------------------------------- tabela")]
        self.assertIn("pintarContagensDosFiltros(", corpo)

    def test_lista_do_link_valida_e_abrevia(self):
        """15/09/2026: ?lista= so aceita nome .br valido; .com.br vai abreviado e volta inteiro."""
        import re, shutil, json as _json
        node = shutil.which("node")
        if not node:
            self.skipTest("sem node")
        js = self._app_js()
        ler = re.search(r"function lerListaDoLink\(bruto\) \{.*?\n\}", js, re.S).group(0)
        link = re.search(r"function linkDaLista\(nomes\) \{.*?\n\}", js, re.S).group(0)
        roteiro = ("const MAXIMO_LISTA = 200; const location = {origin: 'https://ex.br'};"
                   + ler + link
                   + "const l = lerListaDoLink('cale, GRITA,meuteste.ia.br,<script>,xx..br,a.b.com,www.one,cale');"
                   + "process.stdout.write(JSON.stringify([[...l], linkDaLista(l)]));")
        saida = subprocess.run([node, "-e", roteiro], capture_output=True, text=True, check=True).stdout
        nomes, url = _json.loads(saida)
        self.assertEqual(nomes, ["cale.com.br", "grita.com.br", "meuteste.ia.br", "one.com.br"])
        self.assertEqual(url, "https://ex.br/?lista=cale,grita,meuteste.ia.br,one")
        # a lista de quem recebe o link nunca vai para o localStorage sozinha
        gravar = js[js.index("function gravarAcompanhados"):js.index("function garantirLinha")]
        self.assertNotIn("lista", gravar)

    def test_todo_parametro_do_endereco_e_lido_de_volta(self):
        """15/09/2026: o link compartilhado so reproduz a tela se todo filtro gravado no endereco e lido ao abrir."""
        import re
        js = self._app_js()
        grava = js[js.index("function parametrosDaTela"):js.index("function atualizarEndereco")]
        le = js[js.index("function lerParametros"):js.index("// ----------------------------------------------------------- rodada inteira")]
        gravados = set(re.findall(r"q\.set\('([a-z]+)'", grava)) | {"lista"}
        lidos = set(re.findall(r"q\.get\('([a-z]+)'\)", le))
        self.assertTrue(gravados, "nenhum parametro achado")
        self.assertLessEqual(gravados, lidos)

    # --- busca na rodada inteira (19/09/2026, r3-busca-rodada-inteira)

    @staticmethod
    def _busca_py(rotulos, texto):
        """O oraculo da busca: a mesma regra de app.js, em Python."""
        import unicodedata
        def norm(s):
            s = unicodedata.normalize("NFD", s.lower())
            return re.sub(r"[^a-z0-9.]", "", "".join(c for c in s if not unicodedata.combining(c)))
        t = texto.strip()
        modo = "contem"
        if re.match(r'^["“”](.*)["“”]$', t):
            modo, t = "exato", t[1:-1]
        elif t.endswith("*") and not t.startswith("*"):
            modo = "comeca"
        elif t.startswith("*") and not t.endswith("*"):
            modo = "termina"
        termo = norm(t)
        casa = {"exato": lambda r: r == termo, "comeca": lambda r: r.startswith(termo),
                "termina": lambda r: r.endswith(termo), "contem": lambda r: termo in r}[modo]
        return sorted(r for r in rotulos if casa(norm(r)))

    def _busca_js(self, dominios, textos):
        """Roda normalizarTermo/modoDaBusca/casaBusca do app.js no node; None sem node."""
        import shutil, tempfile, json as _json
        node = shutil.which("node")
        if not node:
            return None
        js = self._app_js()
        funcoes = "".join(re.search(r"function %s\(.*?\n\}" % f, js, re.S).group(0) + "\n"
                          for f in ("normalizarTermo", "modoDaBusca", "rotuloDaLinha", "casaBusca"))
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as f:
            _json.dump({"dominios": dominios, "textos": textos}, f)
            caminho = f.name
        try:
            roteiro = ("const D = 0, RN = 13;" + funcoes
                       + "const e = JSON.parse(require('fs').readFileSync(%s, 'utf8'));" % _json.dumps(caminho)
                       + "const linhas = e.dominios.map((d) => [d]); const r = {};"
                       + "for (const t of e.textos) { const q = modoDaBusca(t);"
                       + "  r[t] = linhas.filter((it) => casaBusca(it, q)).map((it) => it[D].split('.')[0]).sort(); }"
                       + "process.stdout.write(JSON.stringify(r));")
            saida = subprocess.run([node, "-e", roteiro], capture_output=True, text=True, check=True).stdout
        finally:
            os.unlink(caminho)
        return _json.loads(saida)

    def test_busca_casa_so_no_rotulo_sem_acento_e_com_modo(self):
        """19/09/2026: rotulo sem extensao, sem acento/caixa/hifen; pet*, *pet e "pet"."""
        dominios = ["pizza.com.br", "pizzaria.com.br", "xpizza.com.br", "apolo.dev.br", "devops.com.br",
                    "cafe.com.br", "cafeteria.com.br", "pet.com.br", "petshop.com.br", "superpet.com.br",
                    "pet.floripa.br", "loja.com.br"]
        textos = ["pizza", "dev", "café", "cafe", "CAFÉ", "pet*", "*pet", '"pet"', "“pet”", "pet-shop", "PET"]
        r = self._busca_js(dominios, textos)
        if r is None:
            self.skipTest("sem node")
        rotulos = [d.split(".")[0] for d in dominios]
        for t in textos:
            self.assertEqual(r[t], self._busca_py(rotulos, t), t)
        self.assertEqual(r["dev"], ["devops"])          # apolo.dev.br nao casa pela extensao
        self.assertEqual(r["café"], r["cafe"])
        self.assertEqual(r["pet*"], ["pet", "pet", "petshop"])
        self.assertEqual(r["*pet"], ["pet", "pet", "superpet"])
        self.assertEqual(r['"pet"'], ["pet", "pet"])
        self.assertEqual(r["“pet”"], r['"pet"'])
        self.assertEqual(r["pet-shop"], ["petshop"])

    def test_busca_na_rodada_de_setembro_bate_com_o_python(self):
        """19/09/2026: "pizza" na rodada de 09/09/2026 sao 188 rotulos, os mesmos no node e no Python."""
        import json as _json
        caminho = os.path.join(os.path.dirname(os.path.abspath(__file__)), "site", "todos.json")
        if not os.path.exists(caminho):
            self.skipTest("sem site/todos.json")
        t = _json.load(open(caminho, encoding="utf-8"))
        if not str((t.get("rodada") or {}).get("inicio", "")).startswith("2026-09-09"):
            self.skipTest("todos.json de outra rodada")
        dominios = [f"{r[0]}.{t['extensoes'][r[1]]}" for r in t["itens"]]
        textos = ["pizza", "dev", "café", "cafe", "pet*", "*pet", '"pet"']
        r = self._busca_js(dominios, textos)
        if r is None:
            self.skipTest("sem node")
        rotulos = [r_[0] for r_ in t["itens"]]
        for x in textos:
            self.assertEqual(r[x], self._busca_py(rotulos, x), x)
        self.assertEqual(len(r["pizza"]), 188)
        self.assertEqual(r["café"], r["cafe"])
        # "dev" no dominio inteiro pegaria as .dev.br; no rotulo, nao
        self.assertLess(len(r["dev"]), sum("dev" in d for d in dominios))

    def test_resumo_da_busca_conta_a_rodada_sem_os_filtros(self):
        """19/09/2026: com a marca em "so", "vacina" dizia "0 nomes dos 125.453"; sao 9, e 0 com o filtro."""
        import shutil, json as _json
        caminho = os.path.join(os.path.dirname(os.path.abspath(__file__)), "site", "todos.json")
        if not os.path.exists(caminho):
            self.skipTest("sem site/todos.json")
        t = _json.load(open(caminho, encoding="utf-8"))
        if not str((t.get("rodada") or {}).get("inicio", "")).startswith("2026-09-09"):
            self.skipTest("todos.json de outra rodada")
        node = shutil.which("node")
        if not node:
            self.skipTest("sem node")
        js = self._app_js()
        funcoes = "".join(re.search(r"function %s\(.*?\n\}" % f, js, re.S).group(0) + "\n"
                          for f in ("normalizarTermo", "modoDaBusca", "rotuloDaLinha", "casaBusca", "contarBusca"))
        # as linhas como carregarRodada monta: dominio, risco de marca (MK), rotulo (RN)
        roteiro = ("const D = 0, MK = 6, RN = 13;" + funcoes
                   + "const t = JSON.parse(require('fs').readFileSync(%s, 'utf8'));" % _json.dumps(caminho)
                   + "const RISCO = t.marcas.indexOf('RISCO');"
                   + "const linhas = t.itens.map(([r, e, , , risco]) => {"
                   + "  const l = [`${r}.${t.extensoes[e]}`]; l[MK] = risco === RISCO ? 2 : 0; return l; });"
                   + "const so = (it) => it[MK] === 2; const r = {};"
                   + "for (const x of ['vacina', 'brasil']) r[x] = contarBusca(linhas, modoDaBusca(x), so);"
                   + "process.stdout.write(JSON.stringify(r));")
        r = _json.loads(subprocess.run([node, "-e", roteiro], capture_output=True, text=True, check=True).stdout)
        self.assertEqual(r["vacina"], {"total": 9, "comFiltros": 0})
        self.assertEqual(r["brasil"], {"total": 1486, "comFiltros": 2})
        # a frase do resumo usa o total sem filtro; os chips, os achados com filtro
        corpo = re.search(r"function pintarResumoDaBusca\(.*?\n\}", js, re.S).group(0)
        self.assertIn("num(contagem.total)", corpo)
        self.assertNotIn("${num(achados.length)} `\n", corpo)
        self.assertIn("Com os filtros atuais", corpo)
        self.assertIn("limparFiltros", corpo)
        # a lista vazia nao diz "nenhum nome com o termo" quando e o filtro que esconde
        vazio = re.search(r"function pintarVazio\(.*?\n\}", js, re.S).group(0)
        self.assertIn("pelos filtros atuais", vazio)
        self.assertIn("limparSoFiltros", vazio)
        # limpar os filtros mantem a busca
        limpar = re.search(r"function limparSoFiltros\(.*?\n\}", js, re.S).group(0)
        self.assertNotIn("estado.busca", limpar)
        # a situacao fica fora da segunda linha: os chips a detalham e contam sem ela
        for f in ("filtrosLigados", "contagemDaBusca", "rotulosDosFiltros"):
            corpo_f = re.search(r"function %s\(.*?\n\}" % f, js, re.S).group(0)
            self.assertNotIn("situacao", corpo_f, f)

    def test_busca_baixa_a_rodada_so_no_foco_e_fica_no_topo(self):
        """19/09/2026: todos.json so no primeiro foco da busca; o campo sobe para baixo do subtitulo."""
        js = self._app_js()
        self.assertEqual(js.count("fetch('todos.json')"), 1)
        ligar = js[js.index("function ligarEventos"):js.index("async function iniciar")]
        foco = ligar[ligar.index("addEventListener('focus'"):]
        self.assertIn("carregarRodada(", foco[:foco.index("{ once: true }")])
        raiz = os.path.dirname(os.path.abspath(__file__))
        html = open(os.path.join(raiz, "site_modelo", "conteudo", "ferramenta.html"), encoding="utf-8").read()
        topo = html[html.index('class="busca-topo"'):html.index('id="fase-inicio"')]
        self.assertIn('id="busca"', topo)
        self.assertIn('href="/quando-volta/"', topo)
        self.assertLess(html.index('id="p-subtitulo"'), html.index('class="busca-topo"'))
        self.assertEqual(html.count('id="busca"'), 1)

    def test_modo_busca_recolhe_o_painel_so_por_classe(self):
        """19/09/2026: com 3 letras a lista sobe para baixo da caixa; nada sai do DOM."""
        js = self._app_js()
        raiz = os.path.dirname(os.path.abspath(__file__))
        html = open(os.path.join(raiz, "site_modelo", "conteudo", "ferramenta.html"), encoding="utf-8").read()
        css = open(os.path.join(raiz, "site_modelo", "extra.css"), encoding="utf-8").read()
        # o que se recolhe existe no modelo, e so o que fica entre a caixa e a lista
        # o bloco que recolhe: da fase ate o primeiro "{ display: none; }"
        bloco = css[css.index("body.modo-busca .fase-linha"):]
        bloco = bloco[:bloco.index("{")]
        escondidos = re.findall(r"body\.modo-busca ([.#][\w-]+)(?=[,\s{])", bloco + " ")
        self.assertIn("#p-relogio", escondidos)
        self.assertIn(".cartoes", escondidos)
        for sel in escondidos:
            marca = f'id="{sel[1:]}"' if sel[0] == "#" else sel[1:]
            self.assertIn(marca, html, sel)
        for fica in ("#p-subtitulo", ".subtitulo", ".busca-topo", "#resumo-busca", "#controles",
                     ".rolagem", "#ao-vivo", "#mudancas", "#resumo-busca-status"):
            self.assertNotIn(fica, escondidos)
        regra = css[css.index("body.modo-busca .fase-linha"):]
        self.assertIn("display: none", regra[:regra.index("}")])
        # a saida do modo esta no modelo, e o CSP segue sem atributo style
        self.assertIn('id="limpar-busca"', html)
        self.assertIn("$('#limpar-busca').addEventListener('click', limparBusca)", js)
        self.assertNotIn("style=", html)
        # o modo se decide antes da lista (o cartao de antes volta ao sair) e
        # so desliga com a caixa vazia: apagar ate 2 letras nao traz o painel
        aplicar = re.search(r"function aplicar\(.*?\n\}", js, re.S).group(0)
        self.assertLess(aplicar.index("pintarModoBusca()"), aplicar.index("let base"))
        modo = re.search(r"function pintarModoBusca\(.*?\n\}", js, re.S).group(0)
        self.assertIn("!estado.busca.trim()", modo)
        self.assertIn("estado.antesDaBusca.filtro", modo)
        self.assertIn("andarRelogio()", modo)
        # escondido, o relogio nao repinta
        andar = re.search(r"function andarRelogio\(.*?\n\}", js, re.S).group(0)
        self.assertIn("modo-busca", andar)
        # o link com ?busca= ja abre no modo, antes do JSON
        self.assertLess(js.index("document.body.classList.add('modo-busca', 'modo-busca-link')"),
                        js.index("\niniciar().catch("))
        # rev2: a linha ao vivo vazia nao deixa vao no modo, mas segue no ar
        vao = re.search(r"body\.modo-busca #ao-vivo:empty \{([^}]*)\}", css).group(1)
        self.assertIn("min-height: 0", vao)
        self.assertNotIn("display", vao)
        # rev2: so quem chega pelo link perde o subtitulo, e so no celular
        link = css[css.index("body.modo-busca.modo-busca-link #p-subtitulo"):]
        self.assertIn("display: none", link[:link.index("}")])
        self.assertLess(css.rindex("@media (max-width: 40rem)", 0, css.index("body.modo-busca.modo-busca-link #p-subtitulo")),
                        css.index("body.modo-busca.modo-busca-link #p-subtitulo"))
        self.assertNotIn("modo-busca-link", html)
        import shutil
        node = shutil.which("node")
        if not node:
            self.skipTest("sem node")
        funcoes = "".join(re.search(r"function %s\(.*?\n\}" % f, js, re.S).group(0) + "\n"
                          for f in ("normalizarTermo", "modoDaBusca", "buscaPedeModo"))
        roteiro = ("const MINIMO_BUSCA_RODADA = 3;" + funcoes
                   + "process.stdout.write(JSON.stringify(['pizza', 'pi', '\"loja\"', 'piz*', ' pi ', 'pizza']"
                   + ".map((t, i) => buscaPedeModo(t, i === 5 ? 'acompanhados' : null))));")
        r = json.loads(subprocess.run([node, "-e", roteiro], capture_output=True, text=True, check=True).stdout)
        self.assertEqual(r, [True, False, True, True, False, False])
        # rev2: entrar, limpar e entrar de novo; o aviso do modo volta a
        # ser dito na segunda busca, e a classe do link sai com o modo
        funcoes += re.search(r"function pintarModoBusca\(.*?\n\}", js, re.S).group(0) + "\n"
        roteiro = ("const MINIMO_BUSCA_RODADA = 3; const classes = new Set(['modo-busca', 'modo-busca-link']);"
                   "const document = { body: { classList: { toggle: (c, v) => (v ? classes.add(c) : classes.delete(c)),"
                   " remove: (c) => classes.delete(c) } } }; function andarRelogio() {}"
                   "const estado = { busca: 'pizza', filtro: 'sem_competicao', cartaoEscolhido: false,"
                   " modoBusca: false, antesDaBusca: null };" + funcoes
                   + "const passos = []; const olha = () => passos.push([estado.modoBusca, Boolean(estado.modoBuscaAnunciado),"
                   " classes.has('modo-busca'), classes.has('modo-busca-link')]);"
                   "pintarModoBusca(); estado.modoBuscaAnunciado = true; olha();"
                   "estado.busca = ''; pintarModoBusca(); olha();"
                   "estado.busca = 'loja'; pintarModoBusca(); olha();"
                   "process.stdout.write(JSON.stringify(passos));")
        r = json.loads(subprocess.run([node, "-e", roteiro], capture_output=True, text=True, check=True).stdout)
        self.assertEqual(r, [[True, True, True, True], [False, False, False, False], [True, False, True, False]])

    def test_campo_sem_valor_no_layout_e_erro(self):
        from garimpo.web import paginas
        p = paginas.ler_fragmento(self.fragmento(), "x")
        with self.assertRaises(ValueError):
            paginas.render(p, "{{titulo}} {{inexistente}}")

    def test_artigo_vira_article_com_jsonld(self):
        from garimpo.web import paginas
        p = paginas.ler_fragmento(self.fragmento(tipo="artigo", secao="insights",
                                                 etiqueta="Descoberta", data="2026-09-10"),
                                  "insights/x")
        html = paginas.render(p, self.LAYOUT)
        self.assertIn('<article class="insight">', html)
        self.assertIn('<p class="etiqueta">Descoberta</p>', html)
        self.assertIn('"datePublished": "2026-09-10"', html)
        self.assertIn('<a class="aba" href="/insights/" aria-current="page">', html)

    def test_faq_extrai_perguntas(self):
        from garimpo.web import paginas
        corpo = ('<div class="pergunta"><h2>Posso?</h2><p class="resposta-curta">Não.</p>'
                 "<p>Porque <em>não</em>.</p></div>")
        p = paginas.Pagina(slug="perguntas", titulo="P", descricao="D", corpo=corpo, tipo="faq")
        faq = self.do_grafo(paginas.json_ld(p), "FAQPage")
        self.assertEqual(faq["mainEntity"][0]["name"], "Posso?")
        self.assertEqual(faq["mainEntity"][0]["acceptedAnswer"]["text"], "Não. Porque não.")

    @staticmethod
    def do_grafo(bloco, tipo):
        ld = json.loads(re.search(r'<script type="application/ld\+json">(.*?)</script>',
                                  bloco, re.S).group(1))
        achados = [n for n in ld["@graph"] if n["@type"] == tipo]
        assert achados, f"sem {tipo} no @graph"
        return achados[0]

    def test_titulo_busca_vai_para_title_e_h1_fica_manchete(self):
        from garimpo.web import paginas
        p = paginas.ler_fragmento(self.fragmento(
            tipo="artigo", secao="insights", data="2026-09-10", modificado="2026-09-12",
            titulo_busca="Quais domínios .br são disputados"), "insights/x")
        html = paginas.render(p, self.LAYOUT + "{{og_tipo}}{{og_extra}}{{imagem}}",
                              base="https://ex.br")
        self.assertIn("<title>Quais domínios .br são disputados · Liberados</title>", html)
        self.assertIn("<h1>As regras</h1>", html)
        self.assertIn("article", html)
        self.assertIn('property="article:modified_time" content="2026-09-12"', html)
        self.assertIn("https://ex.br/og.png", html)
        artigo = self.do_grafo(paginas.json_ld(p, "https://ex.br"), "Article")
        self.assertEqual(artigo["dateModified"], "2026-09-12")
        self.assertEqual(artigo["datePublished"], "2026-09-10")
        migalhas = self.do_grafo(paginas.json_ld(p, "https://ex.br"), "BreadcrumbList")
        self.assertEqual([i["name"] for i in migalhas["itemListElement"]],
                         ["Início", "Insights", "Quais domínios .br são disputados"])

    def test_ferramenta_publica_dataset(self):
        from garimpo.web import paginas
        p = paginas.Pagina("", "Raiz", "d", "", tipo="ferramenta")
        dados = {"gerado_em": "2026-09-12T19:07:54+00:00",
                 "rodada": {"inicio": "2026-09-09T15:00:00-03:00",
                            "fim": "2026-09-16T15:00:00-03:00"}}
        bloco = paginas.json_ld(p, "https://ex.br", dados)
        conjunto = self.do_grafo(bloco, "Dataset")
        self.assertEqual(conjunto["distribution"][0]["contentUrl"], "https://ex.br/dados.json")
        self.assertEqual(conjunto["dateModified"], "2026-09-12T19:07:54+00:00")
        self.assertEqual(conjunto["temporalCoverage"],
                         "2026-09-09T15:00:00-03:00/2026-09-16T15:00:00-03:00")
        self.do_grafo(bloco, "WebSite")
        self.assertNotIn("BreadcrumbList", bloco)          # a raiz nao tem migalha

    def test_proxima_rodada_pela_segunda_quarta(self):
        from garimpo.web import paginas
        self.assertEqual(paginas.proxima_rodada("2026-09-09T15:00:00-03:00"), "14/10/2026")
        self.assertEqual(paginas.proxima_rodada("2026-10-14T15:00:00-03:00"), "11/11/2026")
        self.assertEqual(paginas.proxima_rodada("2026-12-09T15:00:00-03:00"), "13/01/2027")
        self.assertEqual(paginas.proxima_rodada(None), "")

    def test_faq_no_jsonld_leva_os_numeros_gravados(self):
        """O agente cita o JSON-LD: a data da proxima rodada nao pode sair como '-'."""
        from garimpo.web import paginas
        corpo = ('<div class="pergunta"><h2>Quando?</h2><p class="resposta-curta">'
                 'Em <span id="p-proxima-rodada">-</span>.</p></div>')
        p = paginas.Pagina("perguntas", "P", "D", corpo, tipo="faq")
        dados = {"rodada": {"inicio": "2026-09-09T15:00:00-03:00"}}
        faq = self.do_grafo(paginas.json_ld(p, "https://ex.br", dados), "FAQPage")
        self.assertEqual(faq["mainEntity"][0]["acceptedAnswer"]["text"], "Em 14/10/2026.")

    def test_glossario_vira_defined_term_set(self):
        from garimpo.web import paginas
        corpo = ('<dl><dt id="ticket">Ticket</dt><dd>O número do <b>pedido</b>.</dd>'
                 '<dt id="leilao">Processo competitivo</dt>\n<dd>O leilão.</dd></dl>')
        p = paginas.Pagina("glossario", "Glossário", "d", corpo, tipo="glossario")
        termos = self.do_grafo(paginas.json_ld(p, "https://ex.br"), "DefinedTermSet")
        self.assertEqual([(t["name"], t["description"]) for t in termos["hasDefinedTerm"]],
                         [("Ticket", "O número do pedido."), ("Processo competitivo", "O leilão.")])
        self.assertEqual(termos["hasDefinedTerm"][0]["url"], "https://ex.br/glossario/#ticket")

    def test_jsonld_nao_fecha_o_script(self):
        from garimpo.web import paginas
        p = paginas.Pagina("insights/x", "</script><b>", "d", "", tipo="artigo", secao="insights")
        bloco = paginas.json_ld(p, "https://ex.br")
        self.assertEqual(bloco.count("</script>"), 1)

    def test_llms_full_junta_o_texto(self):
        from garimpo.web import paginas
        ps = [paginas.Pagina("", "Raiz", "d1", "<p>app</p>", tipo="ferramenta"),
              paginas.Pagina("regras-do-br", "Regras", "d2", "<p>São <b id=\"p-total-rodada\">-</b>.</p>")]
        full = paginas.llms_full_txt(ps, {"total_rodada": 125453}, "https://ex.br")
        self.assertIn("# Regras", full)
        self.assertIn("**125.453**", full)
        self.assertNotIn("app", full.split("---", 1)[1])
        self.assertIn("https://ex.br/llms-full.txt", paginas.llms_txt(ps, "https://ex.br"))

    def test_preencher_numeros(self):
        from garimpo.web import paginas
        dados = {"total_rodada": 125453, "itens": [[1], [2]], "nao_verificados": 3,
                 "criterios": {"bonus": [{"peso": 25, "rotulo": "elegível"}],
                               "nota_minima": 45, "nichos": ["a"], "total_marcas": 160},
                 "gerado_em": "2026-09-11T23:09:33+00:00"}
        html = paginas.preencher_numeros(
            '<p id="p-total-rodada">-</p><b id="p-pool">x</b><table id="tab-bonus"></table>'
            '<span id="p-gerado">-</span>', dados)
        self.assertIn('<p id="p-total-rodada">125.453</p>', html)
        self.assertIn('<b id="p-pool">5</b>', html)
        self.assertIn("<td>elegível</td><td><strong>+25</strong></td>", html)
        self.assertIn('id="p-gerado">11/09/2026 20:09<', html)   # em Brasilia

    def test_sitemap_robots_e_llms(self):
        from garimpo.web import paginas
        ps = [paginas.Pagina("", "Raiz", "d1", "", tipo="ferramenta"),
              paginas.Pagina("insights/x", "X", "d2", "", tipo="artigo", data="2026-09-10")]
        mapa = paginas.sitemap(ps, "https://ex.br")
        self.assertIn("<loc>https://ex.br/</loc>", mapa)
        self.assertIn("<loc>https://ex.br/insights/x/</loc><lastmod>2026-09-10</lastmod>", mapa)
        self.assertIn("Sitemap: https://ex.br/sitemap.xml", paginas.robots_txt("https://ex.br"))
        llms = paginas.llms_txt(ps, "https://ex.br")
        self.assertIn("- [Raiz](https://ex.br/): d1", llms)             # a ferramenta: HTML
        self.assertIn("- [X](https://ex.br/insights/x/index.md): d2", llms)   # texto: o espelho

    def test_lastmod_usa_modificado_e_a_raiz_usa_o_build(self):
        """achado seo-tecnico:lastmod-ignora-modificado (18/09/2026): pagina
        revista depois de `data` nao pode parecer mais velha do que e, e a
        raiz (sem `data`) usa o dia do instantaneo, em horario de Brasilia."""
        from garimpo.web import paginas
        ps = [paginas.Pagina("", "Raiz", "d", "", tipo="ferramenta"),
              paginas.Pagina("x", "X", "d", "", data="2026-09-11", modificado="2026-09-18")]
        # sem `dados`: a raiz fica sem lastmod, como antes
        self.assertNotIn("https://ex.br/</loc><lastmod>", paginas.sitemap(ps, "https://ex.br"))
        dados = {"gerado_em": "2026-09-18T01:30:00+00:00"}   # 17/09 22h30 em Brasilia
        mapa = paginas.sitemap(ps, "https://ex.br", dados)
        self.assertIn("<loc>https://ex.br/</loc><lastmod>2026-09-17</lastmod>", mapa)
        self.assertIn("<loc>https://ex.br/x/</loc><lastmod>2026-09-18</lastmod>", mapa)
        self.assertIn("Conferido em 18/09/2026",
                      paginas.render(ps[1], self.LAYOUT, base="https://ex.br"))

    def test_insights_pega_a_data_mais_recente_dos_artigos(self):
        """achado seo-tecnico:lastmod-ignora-modificado: /insights/ nao tinha
        `data` nenhuma (sem lastmod no sitemap, sem "Conferido em"). O
        "Conferido em" e o lastmod usam a revisao mais recente (`modificado`);
        `data` fica com a mais antiga, para o datePublished do JSON-LD nao
        dizer que o indice nasceu no dia em que um artigo so foi revisto."""
        from garimpo.web import paginas
        artigos = [paginas.Pagina("insights/a", "A", "d", "", tipo="artigo", data="2026-09-10"),
                  paginas.Pagina("insights/b", "B", "d", "", tipo="artigo",
                                 data="2026-09-05", modificado="2026-09-17"),
                  paginas.Pagina("insights/c", "C", "d", "", tipo="artigo", data="2026-09-03")]
        indice = paginas.indice_insights(artigos, "Insights", "d")
        self.assertEqual(indice.data, "2026-09-03")           # a mais antiga
        self.assertEqual(indice.modificado, "2026-09-17")     # a mais recente
        self.assertIn("<lastmod>2026-09-17</lastmod>",
                      paginas.sitemap([indice], "https://ex.br"))
        vazio = paginas.indice_insights([], "Insights", "d")
        self.assertEqual((vazio.data, vazio.modificado), ("", ""))

    def test_html_para_markdown(self):
        from garimpo.web import paginas
        html = ("<h2>Título</h2><p>Um <strong>forte</strong> e <code>x</code>, ver "
                '<a href="/regras-do-br/">regras</a>.</p>'
                "<ul><li>um<ul><li>dentro</li></ul></li><li>dois</li></ul>"
                '<table class="tabela-doc"><tbody><tr><td><strong>A</strong></td><td>b | c</td></tr></tbody></table>'
                "<table><thead><tr><th>H1</th><th>H2</th></tr></thead><tbody><tr><td>1</td><td>2</td></tr></tbody></table>"
                "<pre><code>a &lt; b\nc</code></pre>"
                '<blockquote class="citacao">frase<cite>Fonte</cite></blockquote>'
                '<div class="aviso">cuidado</div>'
                '<span class="sr-apenas">oculto</span><button>botão</button>')
        md = paginas.html_para_markdown(html, "https://ex.br")
        self.assertIn("## Título", md)
        self.assertIn("Um **forte** e `x`, ver [regras](https://ex.br/regras-do-br/).", md)
        self.assertIn("- um\n\n  - dentro\n\n- dois", md)
        self.assertIn("|  |  |\n|---|---|\n| **A** | b \\| c |", md)
        self.assertIn("| H1 | H2 |\n|---|---|\n| 1 | 2 |", md)
        self.assertIn("```\na < b\nc\n```", md)
        self.assertIn("> frase — Fonte", md)
        self.assertIn("> cuidado", md)
        self.assertNotIn("oculto", md)
        self.assertNotIn("botão", md)

    def test_markdown_da_pagina_grava_numeros(self):
        from garimpo.web import paginas
        p = paginas.Pagina("regras-do-br", "Regras", "Desc.", '<p>São <b id="p-total-rodada">-</b> nomes.</p>',
                           data="2026-09-11")
        md = paginas.markdown_da_pagina(p, {"total_rodada": 125453}, "https://ex.br")
        self.assertTrue(md.startswith("# Regras\n\n> Desc.\n\nSão **125.453** nomes."))
        self.assertIn("Fonte: https://ex.br/regras-do-br/", md)
        self.assertIn("Conferido em 2026-09-11", md)

    def test_ancorar_da_id_estavel_a_cada_titulo(self):
        from garimpo.web import paginas
        corpo = ('<h2 id="curto">Já tem</h2><h2>Quanto custa um domínio?</h2>'
                 '<h3>Quanto custa um domínio?</h3>'
                 '<h2>Por que só <span id="p-pool">15 mil</span> nomes</h2>'
                 '<dt>sem id</dt><dt id="elegivel">Elegível</dt>')
        novo, titulos = paginas.ancorar(corpo)
        self.assertEqual([i for _, i, _ in titulos],
                         ["curto", "quanto-custa-um-dominio", "quanto-custa-um-dominio-2",
                          "por-que-so-nomes", "elegivel"])
        # o numero gravado pelo build nao entra no endereco: senao ele muda a cada rodada
        self.assertIn('<h2 id="por-que-so-nomes">', novo)
        self.assertIn("<dt>sem id</dt>", novo)
        self.assertLessEqual(len(paginas.slug_ancora("palavra " * 30)), 60)

    def test_faq_ganha_indice_links_e_url_por_pergunta(self):
        from garimpo.web import paginas
        corpo = ('<p>Intro.</p>'
                 '<div class="pergunta"><h2 id="custa">Quanto custa?</h2>'
                 '<p class="resposta-curta">Nada.</p></div>'
                 '<div class="pergunta"><h2>Chegar primeiro ajuda?</h2>'
                 '<p class="resposta-curta">Não.</p></div>')
        p = paginas.Pagina("perguntas", "P", "D", corpo, tipo="faq")
        html = paginas.render(p, self.LAYOUT, base="https://ex.br")
        self.assertLess(html.index('<nav class="indice"'), html.index('<div class="pergunta">'))
        self.assertIn('<li><a href="#chegar-primeiro-ajuda">Chegar primeiro ajuda?</a></li>', html)
        self.assertIn('<h2 id="custa"><a class="ancora" href="#custa">Quanto custa?</a></h2>', html)
        self.assertIn('<script src="/compartilhar.js"></script>', html)
        faq = self.do_grafo(paginas.json_ld(p, "https://ex.br"), "FAQPage")
        self.assertEqual([q["url"] for q in faq["mainEntity"]],
                         ["https://ex.br/perguntas/#custa",
                          "https://ex.br/perguntas/#chegar-primeiro-ajuda"])
        md = paginas.markdown_da_pagina(p, None, "https://ex.br")
        self.assertIn("## [Quanto custa?](https://ex.br/perguntas/#custa)", md)

    def test_artigo_tem_ancoras_mas_nao_indice(self):
        from garimpo.web import paginas
        corpo = "".join(f"<h2>Parte {n}</h2><p>{'texto ' * 300}</p>" for n in range(6))
        artigo = paginas.Pagina("insights/x", "X", "D", corpo, tipo="artigo", secao="insights")
        html = paginas.render(artigo, self.LAYOUT, base="https://ex.br")
        self.assertNotIn('class="indice"', html)
        self.assertIn('<a class="ancora" href="#parte-0">', html)
        pagina = paginas.Pagina("regras", "R", "D", corpo)
        self.assertIn('class="indice"', paginas.render(pagina, self.LAYOUT, base="https://ex.br"))
        self.assertNotIn("compartilhar.js", paginas.render(
            paginas.Pagina("", "Raiz", "D", "", tipo="ferramenta"), self.LAYOUT))

    def test_indice_de_insights_ordena(self):
        from garimpo.web import paginas
        a = paginas.Pagina("insights/b", "B", "db", "", tipo="artigo", ordem=2)
        b = paginas.Pagina("insights/a", "A", "da", "", tipo="artigo", ordem=1)
        idx = paginas.indice_insights([a, b], "Insights", "Sete achados.")
        self.assertLess(idx.corpo.index('href="/insights/a/"'), idx.corpo.index('href="/insights/b/"'))
        self.assertEqual(idx.caminho, "/insights/")

    def test_devs_documenta_o_formato_real_dos_json(self):
        """
        A pagina "Para devs" promete o formato dos dois JSON, e a skill e o
        MCP vao ensinar agentes a ler por ela. Documentacao de formato erra
        em silencio: o consumidor le a coluna errada e nao reclama. Entao a
        versao e o numero de colunas saem daqui do codigo, nao da memoria.
        """
        from garimpo.casos import instantaneo, todos
        caminho = os.path.join(os.path.dirname(__file__), "site_modelo",
                               "conteudo", "api-registrobr.html")
        with open(caminho, encoding="utf-8") as f:
            pagina = f.read()

        self.assertIn(f"dados.json, versão {instantaneo.VERSAO_FORMATO}", pagina)
        self.assertIn(f"todos.json, versão {todos.VERSAO}", pagina)

        # o numero de colunas descrito bate com o que o exportador emite
        colunas = instantaneo.I_CHEGADA_MAX + 1
        self.assertEqual(colunas, 13)
        self.assertIn(f"tem {colunas} posições", pagina)

        # toda situacao exportada aparece citada ou existe na tabela status
        self.assertEqual(len(instantaneo.SITUACOES), 8)
        for situacao in instantaneo.SITUACOES:
            self.assertIn(f"<code>{situacao.value}</code>", pagina)

        # o indice "ja teve site?" (arquivo/<xx>.txt): colunas descritas = lidas
        from garimpo.dominio import arquivo
        self.assertIn(f"{arquivo.COLUNAS} colunas separadas por tabulação", pagina)

    def test_chave_do_indexnow_bate_com_o_arquivo(self):
        """
        O IndexNow so aceita se https://<host>/<chave>.txt contiver a chave.

        Sao tres lugares que precisam concordar: CHAVE_INDEXNOW, o arquivo em
        site_modelo/ e o passo do workflow (via avisar_indexnow.py, que
        importa a chave em vez de copiar). Trocar um e esquecer outro da 403
        ou 422 e nada e indexado — falha silenciosa, porque o passo e
        continue-on-error de proposito.
        """
        import avisar_indexnow
        import exportar_site
        chave = exportar_site.CHAVE_INDEXNOW
        raiz = os.path.dirname(__file__)

        self.assertRegex(chave, r"^[0-9a-f]{8,128}$")
        # o arquivo existe, tem a chave e nada mais (nem quebra de linha)
        caminho = os.path.join(raiz, "site_modelo", f"{chave}.txt")
        with open(caminho, encoding="utf-8") as f:
            self.assertEqual(f.read(), chave)
        # o exportador copia o arquivo para o site
        self.assertIn(f"{chave}.txt", exportar_site.ESTATICOS)
        # avisar_indexnow.py importa a mesma chave, sem copia nova
        self.assertIs(avisar_indexnow.CHAVE_INDEXNOW, exportar_site.CHAVE_INDEXNOW)
        # e o workflow chama o script sobre o sitemap exportado
        with open(os.path.join(raiz, ".github", "workflows", "garimpo.yml"),
                  encoding="utf-8") as f:
            self.assertIn("avisar_indexnow.py site/sitemap.xml", f.read())

    def test_favicon_de_verdade(self):
        """
        O icone da marca: um cadeado aberto desenhado em paths (nao um
        emoji em data: URI, que depende da fonte de quem renderiza e nunca
        vira arquivo rastreavel para o Google).
        """
        import exportar_site
        raiz = os.path.dirname(__file__)

        with open(os.path.join(raiz, "site_modelo", "favicon.svg"), encoding="utf-8") as f:
            svg = f.read()
        self.assertNotIn("<text", svg)
        self.assertIn("<path", svg)

        with open(os.path.join(raiz, "site_modelo", "layout.html"), encoding="utf-8") as f:
            layout = f.read()
        self.assertNotIn("data:image/svg+xml", layout)
        self.assertIn('<link rel="icon" href="/favicon.svg" type="image/svg+xml">', layout)
        self.assertIn('<link rel="icon" href="/favicon-48.png" sizes="48x48">', layout)
        self.assertIn('<link rel="apple-touch-icon" href="/apple-touch-icon.png">', layout)

        # os quatro arquivos gerados por gerar_og.py estao comitados e vao
        # ao ar como estaticos
        for nome in ("favicon.svg", "favicon-48.png", "favicon.ico", "apple-touch-icon.png"):
            self.assertIn(nome, exportar_site.ESTATICOS)
            self.assertTrue(os.path.exists(os.path.join(raiz, "site_modelo", nome)), nome)

    def test_headers_do_cloudflare(self):
        """O _headers do modelo: sem noindex, uma CSP so, dentro dos limites."""
        import exportar_site
        caminho = os.path.join(os.path.dirname(__file__), "site_modelo", "_headers")
        texto = open(caminho, encoding="utf-8").read()
        regras = exportar_site.ler_cabecalhos(texto)
        nomes = [n.lower() for _, cabs in regras for n, _ in cabs]
        self.assertNotIn("x-robots-tag", nomes)
        # CSP repetida vira duas politicas somadas por virgula
        self.assertEqual(nomes.count("content-security-policy"), 1)
        self.assertLessEqual(len(regras), 100)
        # 2.000 e o limite do Cloudflare; o hash gravado no build soma ~55
        self.assertLess(max(len(l) for l in texto.splitlines()), 1900)

    def test_hash_da_csp_vai_para_o_headers(self):
        import shutil
        import tempfile
        import exportar_site
        with tempfile.TemporaryDirectory() as d:
            shutil.copy(os.path.join(os.path.dirname(__file__), "site_modelo", "_headers"), d)
            with open(os.path.join(d, "index.html"), "w", encoding="utf-8") as f:
                f.write("<html><script>tema()</script></html>")
            h = exportar_site.fixar_hash_da_csp(d)
            texto = open(os.path.join(d, "_headers"), encoding="utf-8").read()
            self.assertIn(f"script-src 'self' '{h}' https://static.cloudflareinsights.com; style-src", texto)
            # rodar de novo nao acumula hashes
            exportar_site.fixar_hash_da_csp(d)
            self.assertEqual(open(os.path.join(d, "_headers"), encoding="utf-8").read(), texto)

    def test_csp_deixa_o_web_analytics_contar(self):
        """
        O beacon do Cloudflare Web Analytics e a unica contagem de pessoas (o
        resto conta robo junto). Ele e injetado pela zona e, sem as duas
        origens na CSP, e barrado em silencio: foi o que aconteceu de 16 a
        17/09/2026, com o painel zerado.
        """
        import exportar_site
        texto = open(os.path.join(os.path.dirname(__file__), "site_modelo", "_headers"), encoding="utf-8").read()
        csp = next(v for _, cabs in exportar_site.ler_cabecalhos(texto) for n, v in cabs
                   if n.lower() == "content-security-policy")
        diretivas = {d.split()[0]: d.split()[1:] for d in csp.split(";") if d.strip()}
        self.assertIn("https://static.cloudflareinsights.com", diretivas["script-src"])
        self.assertIn("https://cloudflareinsights.com", diretivas["connect-src"])
        # e nada alem disso: nenhum curinga nem outro terceiro executando codigo
        self.assertEqual(set(diretivas["script-src"]), {"'self'", "https://static.cloudflareinsights.com"})


class TestAvisarIndexnow(unittest.TestCase):
    """
    urls_para_indexnow (18/09/2026): as 3 URLs fixas mais o que o sitemap
    marca como revisado hoje ou ontem, sem pagina de ramo e com teto.
    """

    def _sitemap(self, urls):
        entradas = "".join(
            f"<url><loc>{loc}</loc>" + (f"<lastmod>{lastmod}</lastmod>" if lastmod else "")
            + "</url>"
            for loc, lastmod in urls)
        return ('<?xml version="1.0" encoding="UTF-8"?>'
                '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
                f"{entradas}</urlset>")

    def test_ramo_de_hoje_fica_fora_insight_de_hoje_entra(self):
        import avisar_indexnow as ai
        hoje = datetime.date(2026, 9, 20)
        ontem = datetime.date(2026, 9, 19)
        sitemap = self._sitemap([
            (f"{ai.BASE}/", str(hoje)),
            (f"{ai.BASE}/dominios/pet/", str(hoje)),          # ramo: fora
            (f"{ai.BASE}/insights/capsula-do-tempo/", str(hoje)),   # entra
            (f"{ai.BASE}/insights/tres-travas/", str(ontem)),       # entra (ontem)
            (f"{ai.BASE}/insights/artigo-antigo/", "2026-08-01"),   # antigo: fora
            (f"{ai.BASE}/perguntas/", ""),                          # sem lastmod: fora
        ])
        urls = ai.urls_para_indexnow(sitemap, hoje)

        self.assertEqual(list(ai.URLS_FIXAS), [u for u in ai.URLS_FIXAS if u in urls])
        self.assertIn(f"{ai.BASE}/insights/capsula-do-tempo/", urls)
        self.assertIn(f"{ai.BASE}/insights/tres-travas/", urls)
        self.assertNotIn(f"{ai.BASE}/dominios/pet/", urls)
        self.assertNotIn(f"{ai.BASE}/insights/artigo-antigo/", urls)
        self.assertNotIn(f"{ai.BASE}/perguntas/", urls)
        # sem repeticao: a home aparece so uma vez, mesmo citada no sitemap
        self.assertEqual(urls.count(f"{ai.BASE}/"), 1)

    def test_teto_de_20(self):
        import avisar_indexnow as ai
        hoje = datetime.date(2026, 9, 20)
        sitemap = self._sitemap(
            [(f"{ai.BASE}/insights/artigo-{i}/", str(hoje)) for i in range(30)])
        urls = ai.urls_para_indexnow(sitemap, hoje)
        self.assertEqual(len(urls), 20)
        # e as 3 fixas continuam dentro do teto
        for fixa in ai.URLS_FIXAS:
            self.assertIn(fixa, urls)


# --------------------------------------------------------------------------
# Fontes oficiais do Registro.br (12/09/2026): a enumeracao do status, o
# ISAVAIL, a extensao NIC.br do RDAP e as categorias de extensao.
# Ver docs/fontes-oficiais-registrobr.md.
# --------------------------------------------------------------------------

# pacotes de avail.registro.br:43/udp, no formato capturado em 12/09/2026;
# os tickets sao sinteticos (90000000 em diante): os reais sao de
# candidatos de verdade e o RDAP ainda responde a ?ticket= de ticket
# cancelado (docs/limitacoes-registrobr.md, S15)
ISAVAIL_COOKIE = "% Copyright Nic.br\nCK 8a6e52837fc2c68f7a4a 123\n"
ISAVAIL_LEILAO = (
    "% Copyright Nic.br\nST 9 727976103\nvacina.com.br\n"
    "2026-09-26 15:00:00|2026-09-26 15:00:00|2026-09-26 15:00:00\n"
    "90000001|90000002|90000003|90000004|90000005|90000006|90000007|"
    "90000008|90000009|90000010\n")
ISAVAIL_DISPUTADO = (
    "% Copyright Nic.br\nST 7 196086054\none.com.br\n"
    "2026-09-26 15:00:00|2026-09-26 15:00:00\n"
    "90001001|90001002|90001003|90001004|90001005|90001006|90001007|"
    "90001008|90001009|90001010\n")
ISAVAIL_EQUIVALENTE = (
    "% Copyright Nic.br\nST 3 544709500\ncafé.com.br|xn--caf-dma.com.br\n"
    "Domínio já registrado sob sintaxe similar\n")
ISAVAIL_LIVRE = "% Copyright Nic.br\nST 0 745255192\nexemplolivrezz.com.br\n"
ISAVAIL_INVALIDO = "% Copyright Nic.br\nST 4 785478214\nvacina.com.br\nconsulta inválida\n"
# os quatro abaixo sao os exemplos de Protocolo-ISAVAIL.txt
ISAVAIL_REGISTRADO = (
    "% Copyright registro.br\nST 2 12345\nexample.eng.br\n"
    "2007-03-15|published|fork.example.eng.br|example.eng.br\n"
    "blog|flog|sec3|vlog|wiki\n")
ISAVAIL_AGUARDANDO = "% Copyright registro.br\nST 5 12345\nexample.com.br\n"
ISAVAIL_LIMITE = "% Copyright registro.br\nST 8\nQuery rate limit exceeded\n"
ISAVAIL_COM_TICKET = "% Copyright registro.br\nST 1 12345\nexample.com.br\n2567849|2567856\n"


class TestStatusEnumeracao(unittest.TestCase):
    """
    O status e a enumeracao do ISAVAIL, nao um bitmask.

    Regressao: lido como bits (4|1), o 5 ("aguardando processo de
    liberacao") virava LIBERACAO_LIVRE, a joia falsa por excelencia.
    """

    def test_aguardando_nao_e_joia(self):
        leitura = classificar({"status": 5, "fqdn": "travado.com.br", "exempt": False})
        self.assertIs(leitura.situacao, Situacao.AGUARDANDO_LIBERACAO)
        self.assertIsNot(leitura.situacao, Situacao.LIBERACAO_LIVRE)
        self.assertTrue(leitura.situacao.resolvida)

    def test_com_ticket_fora_da_rodada(self):
        leitura = classificar({"status": 1, "fqdn": "x.com.br", "tickets": [1, 2]})
        self.assertIs(leitura.situacao, Situacao.LIVRE_COM_TICKET)
        self.assertEqual(leitura.candidatos, 2)

    def test_indisponivel_e_fato_com_motivo(self):
        leitura = classificar({"status": 3, "fqdn": "", "fqdnace": "xn--caf-dma.com.br",
                               "reasons": ["Domínio já registrado sob sintaxe similar"]})
        self.assertIs(leitura.situacao, Situacao.INDISPONIVEL)
        self.assertTrue(leitura.situacao.resolvida)
        self.assertIn("sintaxe similar", leitura.detalhe)

    def test_consulta_invalida_e_erro(self):
        com_motivo = classificar({"status": 4, "fqdn": "x", "reasons": ["consulta inválida"]})
        self.assertIs(com_motivo.situacao, Situacao.ERRO)
        self.assertIs(classificar({"status": 4, "fqdn": "x"}).situacao, Situacao.ERRO)

    def test_oito_com_fqdn_nao_e_leilao_nem_bloqueio(self):
        self.assertIs(classificar({"status": 8, "fqdn": "x.com.br"}).situacao,
                      Situacao.ERRO)

    def test_rate_limit_em_ingles_tambem_e_bloqueio(self):
        leitura = classificar({"status": 8, "fqdn": "",
                               "reasons": ["Query rate limit exceeded"]})
        self.assertIs(leitura.situacao, Situacao.LIMITADO)

    def test_valor_fora_da_tabela(self):
        self.assertIs(classificar({"status": 12, "fqdn": "x.com.br"}).situacao,
                      Situacao.INDESCONHECIDO)

    def test_situacoes_novas_ficam_no_fim_do_instantaneo(self):
        """Os indices gravados no JSON publicado nao podem mudar."""
        self.assertEqual(instantaneo.SITUACOES[:5], (
            Situacao.LIBERACAO_LIVRE, Situacao.LIBERACAO_DISPUTADA,
            Situacao.COMPETITIVO, Situacao.LIVRE, Situacao.REGISTRADO))
        self.assertIn(Situacao.AGUARDANDO_LIBERACAO, instantaneo.SITUACOES)


class TestIsavail(unittest.TestCase):
    """O leitor do protocolo oficial, contra pacotes gravados."""

    def test_cookie(self):
        r = isavail.interpretar(ISAVAIL_COOKIE)
        self.assertTrue(r.novo_cookie)
        self.assertEqual(r.cookie, "8a6e52837fc2c68f7a4a")
        self.assertIsNone(r.status)

    def test_leilao_com_dez_tickets(self):
        r = isavail.interpretar(ISAVAIL_LEILAO)
        self.assertEqual((r.status, r.fqdn, len(r.tickets)), (9, "vacina.com.br", 10))
        self.assertEqual(r.tickets[0], 90000001)
        self.assertEqual(r.datas, ("2026-09-26 15:00:00",) * 3)
        leitura = classificar(r.payload())
        self.assertIs(leitura.situacao, Situacao.COMPETITIVO)
        self.assertEqual(leitura.candidatos, 10)

    def test_datas_nao_entram_no_payload(self):
        """12/09/2026: o ISAVAIL deu 26/09 para uma rodada que fecha 16/09."""
        p = isavail.interpretar(ISAVAIL_LEILAO).payload()
        self.assertNotIn("ends-at", p)
        self.assertNotIn("accepting-new-tickets-until", p)

    def test_disputado(self):
        leitura = classificar(isavail.interpretar(ISAVAIL_DISPUTADO).payload())
        self.assertIs(leitura.situacao, Situacao.LIBERACAO_DISPUTADA)
        self.assertEqual(leitura.candidatos, 10)

    def test_equivalente_reconhece_ace_pelo_prefixo(self):
        r = isavail.interpretar(ISAVAIL_EQUIVALENTE)
        self.assertEqual((r.status, r.fqdn, r.fqdnace),
                         (3, "café.com.br", "xn--caf-dma.com.br"))
        self.assertIn("sintaxe similar", r.mensagem)
        self.assertIs(classificar(r.payload()).situacao, Situacao.INDISPONIVEL)

    def test_livre(self):
        self.assertIs(classificar(isavail.interpretar(ISAVAIL_LIVRE).payload()).situacao,
                      Situacao.LIVRE)

    def test_registrado_exemplo_da_especificacao(self):
        r = isavail.interpretar(ISAVAIL_REGISTRADO)
        self.assertEqual(r.expira_em, "2007-03-15")
        self.assertEqual(r.publicacao, "published")
        self.assertEqual(r.servidores, ("fork.example.eng.br", "example.eng.br"))
        self.assertEqual(r.sugestoes[0], "blog.br")
        leitura = classificar(r.payload())
        self.assertIs(leitura.situacao, Situacao.REGISTRADO)
        self.assertIn("expires-at", leitura.detalhe)

    def test_aguardando_e_com_ticket(self):
        self.assertIs(classificar(isavail.interpretar(ISAVAIL_AGUARDANDO).payload()).situacao,
                      Situacao.AGUARDANDO_LIBERACAO)
        leitura = classificar(isavail.interpretar(ISAVAIL_COM_TICKET).payload())
        self.assertIs(leitura.situacao, Situacao.LIVRE_COM_TICKET)
        self.assertEqual(leitura.candidatos, 2)

    def test_limite_e_invalido(self):
        r = isavail.interpretar(ISAVAIL_LIMITE)
        self.assertEqual(r.status, 8)
        self.assertIs(classificar(r.payload()).situacao, Situacao.LIMITADO)
        self.assertIs(classificar(isavail.interpretar(ISAVAIL_INVALIDO).payload()).situacao,
                      Situacao.ERRO)

    def test_cliente_faz_a_danca_do_cookie(self):
        pacotes = [ISAVAIL_COOKIE, ISAVAIL_LIVRE]
        perguntas = []

        def enviar(p):
            perguntas.append(p)
            return pacotes.pop(0)

        cliente = isavail.Cliente(enviar=enviar)
        self.assertIs(cliente.verificar("exemplolivrezz.com.br").situacao, Situacao.LIVRE)
        self.assertEqual(len(perguntas), 2)
        self.assertTrue(perguntas[0].startswith("2 00000000000000000000 1 "))
        self.assertIn(" 8a6e52837fc2c68f7a4a ", perguntas[1])
        # a versao 1+ exige o campo "sugerir" no fim; sem ele e "consulta invalida"
        self.assertTrue(perguntas[1].endswith(" exemplolivrezz.com.br 0"))
        self.assertEqual(cliente.cookie, "8a6e52837fc2c68f7a4a")

    def test_cliente_sem_resposta_vira_erro(self):
        def enviar(p):
            raise OSError("timed out")

        leitura = isavail.Cliente(enviar=enviar).verificar("x.com.br")
        self.assertIs(leitura.situacao, Situacao.ERRO)
        self.assertIn("timed out", leitura.detalhe)


# resposta real do rdap.registro.br para pneus.com.br em 12/09/2026, a parte
# nova: a conferencia que o proprio registro faz de cada servidor de DNS
RDAP_PNEUS_NS = dict(
    RDAP_PNEUS,
    nicbr_arbitration=True,
    nameservers=[
        {"ldhName": "a.auto.dns.br", "events": [
            {"eventAction": "delegation check", "eventDate": "2026-09-04T08:10:12Z",
             "status": ["ns aa"]},
            {"eventAction": "last correct delegation check",
             "eventDate": "2026-09-04T08:10:12Z"}]},
        {"ldhName": "b.auto.dns.br", "events": [
            {"eventAction": "delegation check", "eventDate": "2026-09-04T08:10:12Z",
             "status": ["ns aa"]},
            {"eventAction": "last correct delegation check",
             "eventDate": "2026-09-04T08:10:12Z"}]},
    ],
)
# rdap.registro.br/entity/<cnpj>, 12/09/2026, sem o vcard e com o nome do
# representante trocado: esse campo nunca pode sair da resposta crua
RDAP_ENTIDADE = {
    "objectClassName": "entity", "handle": "82534819000101",
    "publicIds": [{"type": "cnpj", "identifier": "82.534.819/0001-01"}],
    "nicbr_domainCount": 166, "legalRepresentative": "Nome De Pessoa",
}


class TestRdapExtensaoNicbr(unittest.TestCase):
    def test_delegacao_conferida_pelo_registro(self):
        f = rdap.interpretar("pneus.com.br", RDAP_PNEUS_NS)
        self.assertEqual(len(f.delegacoes), 2)
        self.assertTrue(f.delegacoes[0].responde)
        self.assertFalse(f.delegacao_quebrada)
        self.assertEqual(f.delegacao_ok_em, "2026-09-04T08:10:12Z")
        self.assertTrue(f.arbitragem)
        self.assertEqual(f.servidores, ("a.auto.dns.br", "b.auto.dns.br"))
        self.assertEqual(historias.dns_segundo_o_registro(f), "ok")

    def test_delegacao_quebrada_sabe_desde_quando(self):
        dados = dict(RDAP_PNEUS_NS, nameservers=[
            {"ldhName": "ns1.morto.com.br", "events": [
                {"eventAction": "delegation check", "eventDate": "2026-09-10T00:00:00Z",
                 "status": "ns timeout"},           # a especificacao usa string
                {"eventAction": "last correct delegation check",
                 "eventDate": "2024-03-01T00:00:00Z"}]},
            {"ldhName": "ns2.morto.com.br", "events": [
                {"eventAction": "delegation check", "eventDate": "2026-09-10T00:00:00Z",
                 "status": ["ns udn"]}]},
        ])
        f = rdap.interpretar("morto.com.br", dados)
        self.assertTrue(f.delegacao_quebrada)
        self.assertEqual(f.delegacao_ok_em, "2024-03-01T00:00:00Z")
        self.assertEqual(historias.dns_segundo_o_registro(f), "quebrado")

    def test_um_servidor_bom_nao_e_quebrado(self):
        dados = dict(RDAP_PNEUS_NS)
        dados["nameservers"] = [RDAP_PNEUS_NS["nameservers"][0], {
            "ldhName": "ns2.x.com.br", "events": [
                {"eventAction": "delegation check", "eventDate": "2026-09-10T00:00:00Z",
                 "status": ["ns timeout"]}]}]
        f = rdap.interpretar("x.com.br", dados)
        self.assertFalse(f.delegacao_quebrada)
        self.assertEqual(historias.dns_segundo_o_registro(f), "parcial")

    def test_sem_conferencia_nao_afirma_nada(self):
        f = rdap.interpretar("x.com.br", RDAP_PNEUS)      # fixture sem eventos
        self.assertFalse(f.delegacao_quebrada)
        self.assertIsNone(f.delegacao_ok_em)
        self.assertIsNone(f.arbitragem)
        self.assertEqual(historias.dns_segundo_o_registro(f), "")

    def test_ordem_judicial(self):
        f = rdap.interpretar("x.com.br", dict(RDAP_PNEUS, status=["nicbr inactive court order"]))
        self.assertTrue(f.fora_do_ar_por_decisao)
        self.assertFalse(rdap.interpretar("x.com.br", RDAP_PNEUS).fora_do_ar_por_decisao)

    def test_entidade_so_conta_dominios(self):
        self.assertEqual(rdap.interpretar_entidade(RDAP_ENTIDADE), 166)
        chamadas = []

        def consulta(handle):
            chamadas.append(handle)
            return RDAP_ENTIDADE

        f = rdap.com_titular(rdap.interpretar("pneus.com.br", RDAP_PNEUS_NS), consulta)
        self.assertEqual(f.dominios_do_titular, 166)
        self.assertEqual(chamadas, ["82534819000101"])    # so digitos
        self.assertNotIn("Nome De Pessoa", repr(f))

    def test_entidade_nunca_para_cpf(self):
        chamadas = []
        # sem pontuacao de proposito: a rede de seguranca do
        # sincronizar-publico.sh barra qualquer coisa com cara de CPF
        f = rdap.Ficha("x.com.br", existe=True, documento="cpf 11 digitos")
        rdap.com_titular(f, lambda h: chamadas.append(h) or {})
        self.assertEqual(chamadas, [])

    def test_entidade_com_falha_nao_derruba(self):
        def quebra(handle):
            raise OSError("rede")

        f = rdap.com_titular(rdap.interpretar("pneus.com.br", RDAP_PNEUS_NS), quebra)
        self.assertIsNone(f.dominios_do_titular)
        self.assertTrue(f.existe)

    def test_resumo_conta_o_que_o_registro_sabe(self):
        f = rdap.Ficha("morto.com.br", existe=True, dominios_do_titular=166,
                       delegacoes=(rdap.Delegacao("ns1", "ns timeout",
                                                  "2026-09-10T00:00:00Z",
                                                  "2024-03-01T00:00:00Z"),))
        texto = historias.resumir([historias.Historia(ficha=f)])
        self.assertIn("desde 2024-03-01", texto)
        self.assertIn("166", texto)


# forma PROVAVEL de /ticket/<n>: um dominio em pendingCreate com a entidade
# do candidato. Nao conferida ao vivo em 12/09/2026 (a consulta foi barrada
# como dado pessoal); o leitor e tolerante e o tickets.py --bruto mostra o
# JSON real para ajustar.
RDAP_TICKET = {
    "objectClassName": "domain", "ldhName": "exemplo.com.br",
    "status": ["pending create"],
    "events": [{"eventAction": "registration", "eventDate": "2026-09-09T15:01:02Z"}],
    "publicIds": [{"type": "ticket", "identifier": "90000001"}],
    "entities": [{
        "objectClassName": "entity", "handle": "12345678000199",
        "roles": ["registrant"],
        "publicIds": [{"type": "cnpj", "identifier": "12.345.678/0001-99"}],
        "vcardArray": ["vcard", [["version", {}, "text", "4.0"],
                                 ["fn", {}, "text", "EMPRESA EXEMPLO LTDA"]]],
    }],
}


class TestTickets(unittest.TestCase):
    def test_interpretar_ticket(self):
        c = rdap.interpretar_ticket(90000001, RDAP_TICKET)
        self.assertEqual(c.dominio, "exemplo.com.br")
        self.assertEqual(c.nome, "EMPRESA EXEMPLO LTDA")
        self.assertEqual((c.tipo_documento, c.documento), ("cnpj", "12.345.678/0001-99"))
        self.assertEqual(c.papel, "registrant")
        self.assertEqual(c.pedido_em, "2026-09-09T15:01:02Z")
        self.assertFalse(c.pessoa_fisica)

    def test_ticket_vazio_nao_explode(self):
        c = rdap.interpretar_ticket(1, {})
        self.assertIsNone(c.nome)
        self.assertIsNone(c.dominio)

    def test_cpf_e_pessoa_fisica(self):
        dados = dict(RDAP_TICKET, entities=[{"roles": ["registrant"],
                                             "publicIds": [{"type": "cpf", "identifier": "***.456.789-**"}]}])
        self.assertTrue(rdap.interpretar_ticket(2, dados).pessoa_fisica)

    def test_tickets_py_nao_atravessa_para_o_publico(self):
        """A ferramenta de dado pessoal nunca vai para o repositorio do site."""
        caminho = os.path.join(os.path.dirname(__file__), "sincronizar-publico.sh")
        if not os.path.exists(caminho):
            # no repositorio publico o script nao existe: ele e justamente
            # um dos arquivos que a sincronizacao nao leva
            self.skipTest("sincronizar-publico.sh so existe no repositorio de trabalho")
        with open(caminho) as f:
            nao_atravessa = f.read().split("NAO_ATRAVESSA=(")[1].split(")")[0]
        self.assertIn("tickets.py", nao_atravessa)
        # anotacao pessoal do dono (candidaturas, lances): versionada so aqui
        self.assertIn("CLAUDE.md", nao_atravessa)
        # pesquisa do produto pago (fechado): a pasta inteira fica aqui
        self.assertIn("presente/", nao_atravessa)
        # planos de receita e doacao: ficam aqui ate o dono decidir publicar
        self.assertIn("monetizacao/", nao_atravessa)
        self.assertIn("work/leilao/", nao_atravessa)
        # fotos de cada rodada (candidaturas) e o guia de quem clona o privado
        self.assertIn("rodadas/", nao_atravessa)
        self.assertIn("COMECE-AQUI.md", nao_atravessa)
        # a skill fica privada ate o dono decidir onde publicar (17/09/2026):
        # ela nao tem nada do garimpo, mas publicar e decisao dele, nao do
        # script -- e o sincronizar leva tudo que nao esta nesta lista
        self.assertIn("skill/", nao_atravessa)
        # o estado da varredura (nucleo aberto, 25/09/2026): o workflow o
        # grava no privado mesmo rodando no publico, e um PR o reverteria
        self.assertIn("site/dados.json", nao_atravessa)
        self.assertIn("site/todos.json", nao_atravessa)
        self.assertIn("docs/historico/", nao_atravessa)
        # conteudo fechado: os insights, as paginas editoriais e as imagens
        self.assertIn("site_modelo/conteudo/insights/", nao_atravessa)
        self.assertIn("site_modelo/og/", nao_atravessa)
        self.assertIn("site_modelo/conteudo/perguntas.html", nao_atravessa)
        # leituras feitas fora do GitHub (19/09/2026): fora do nucleo aberto
        self.assertIn("leituras/", nao_atravessa)

    def test_sobreposicao_do_workflow_cabe_no_que_nao_atravessa(self):
        """Nucleo aberto (25/09/2026): tudo que o Garimpo busca do privado
        (sparse-checkout em garimpo.yml) tem de ser algo que o sincronizar
        nao leva ao publico; senao o mesmo arquivo existiria nos dois e o do
        privado sobrescreveria o do publico em silencio. E o inverso: o que
        o site precisa e nao atravessa tem de estar na sobreposicao, senao
        o site no ar sai sem ele."""
        raiz = os.path.dirname(__file__) or "."
        caminho = os.path.join(raiz, "sincronizar-publico.sh")
        if not os.path.exists(caminho):
            self.skipTest("sincronizar-publico.sh so existe no repositorio de trabalho")
        fechado = subprocess.run(["bash", caminho, "--listar-fechado"], cwd=raiz,
                                 capture_output=True, text=True, check=True).stdout.split()
        yml = open(os.path.join(raiz, ".github", "workflows", "garimpo.yml"), encoding="utf-8").read()
        bloco = re.search(r"sparse-checkout: \|\n((?:\s+/\S+\n)+)", yml).group(1)
        sobrepostos = [l.strip().lstrip("/") for l in bloco.splitlines() if l.strip()]
        self.assertTrue(sobrepostos)

        def coberto(caminho):
            return any(caminho == e or (e.endswith("/") and caminho.startswith(e)) for e in fechado)

        for c in sobrepostos:
            self.assertTrue(coberto(c), f"{c} e sobreposto pelo workflow mas atravessa ao publico")
        # o passo seguinte copia exatamente a mesma lista
        copia = re.search(r"for caminho in (site/dados\.json[^;]+?); do\n\s+\[ -e \"privado/", yml, re.S).group(1)
        self.assertEqual(sorted(copia.replace("\\\n", " ").split()), sorted(c.rstrip("/") for c in sobrepostos))
        # e o que o site le e nao atravessa esta na lista
        for precisa in ("site_modelo/conteudo/insights/", "site_modelo/og/", "docs/historico/",
                        "site/dados.json", "site/todos.json"):
            self.assertTrue(any(precisa.rstrip("/") == c.rstrip("/") for c in sobrepostos), precisa)

    def test_sincronizar_comita_com_noreply_do_github(self):
        """seguranca:email-do-autor-nos-commits-do-publico,
        preparacao-ops:email-no-historico-publico (rodada 1, 18/09/2026): o
        e-mail global desta maquina e pessoal (a propria rede de seguranca
        do script trata como dado pessoal), mas so olha o diff, nunca o
        autor do commit -- por isso o commit tem que forcar o noreply."""
        caminho = os.path.join(os.path.dirname(__file__), "sincronizar-publico.sh")
        if not os.path.exists(caminho):
            self.skipTest("sincronizar-publico.sh so existe no repositorio de trabalho")
        with open(caminho) as f:
            texto = f.read()
        i_commit = texto.index("commit -q -m")
        i_email = texto.index("-c user.email=142928526+dmgobbi@users.noreply.github.com")
        i_case = texto.index('case "$autor"')
        i_push = texto.index("git push -q")
        # o commit forca o noreply, e so depois dele o script confere o
        # autor gravado e aborta antes de empurrar
        self.assertTrue(i_email < i_commit < i_case < i_push,
                        (i_email, i_commit, i_case, i_push))
        self.assertIn("exit 1", texto[i_case:i_push])

    def test_pasta_em_nao_atravessa_vale_para_tudo_dentro(self):
        """Entrada terminada em / barra qualquer arquivo da pasta."""
        caminho = os.path.join(os.path.dirname(__file__), "sincronizar-publico.sh")
        if not os.path.exists(caminho):
            self.skipTest("sincronizar-publico.sh so existe no repositorio de trabalho")
        with open(caminho) as f:
            texto = f.read()
        inicio = texto.index("NAO_ATRAVESSA=(")
        fim = texto.index("\n}\n", inicio) + 3
        roteiro = texto[inicio:fim] + (
            'for f in presente/README.md presente/fontes/registrobr/contrato-epp.txt '
            'monetizacao/README.md work/leilao/relatorio.md work/leilao/tickets/a.com.br.json '
            'CLAUDE.md presentes.md docs/presente/x.md README.md; do '
            'atravessa "$f" && echo "$f"; done\n')
        saida = subprocess.run(["bash", "-c", roteiro], capture_output=True,
                               text=True, check=True).stdout.split()
        self.assertEqual(saida, ["presentes.md", "docs/presente/x.md", "README.md"])

    def test_arquivo_que_atravessa_nao_cita_ticket_real(self):
        """seguranca:tickets-reais-de-terceiros-no-git-e-no-site,
        preparacao-ops:tickets-reais-no-publico (rodada 1, 18/09/2026): um
        numero de ticket real mora so em arquivo que nao atravessa (CLAUDE.md,
        rodadas/, work/leilao/); nenhum arquivo que vai ao publico pode citar
        um desses numeros, porque `?ticket=` ainda responde para ticket
        cancelado e devolve nome e documento mascarado do candidato (S15 em
        docs/limitacoes-registrobr.md). Os tickets ficam fora deste arquivo
        de proposito: ele mesmo e um dos que atravessa. Alem de varrer o que
        fica hoje, confere contra rodadas/2026-09/tickets-reais.txt, a lista
        fixa dos tickets que ja vazaram uma vez (correcao do revisor,
        rodada 1): sem ela, um numero que saia de todo arquivo que fica
        passaria batido mesmo continuando citado num arquivo que cruza.
        """
        caminho = os.path.join(os.path.dirname(__file__), "sincronizar-publico.sh")
        if not os.path.exists(caminho):
            self.skipTest("sincronizar-publico.sh so existe no repositorio de trabalho")
        raiz = os.path.dirname(__file__) or "."
        with open(caminho) as f:
            texto = f.read()
        inicio = texto.index("NAO_ATRAVESSA=(")
        fim = texto.index("\n}\n", inicio) + 3
        roteiro = texto[inicio:fim] + (
            'git ls-files -z | while IFS= read -r -d "" f; do '
            'if atravessa "$f"; then printf 1; else printf 0; fi; '
            'printf "%s\\0" "$f"; done\n')
        saida = subprocess.run(["bash", "-c", roteiro], cwd=raiz,
                               capture_output=True, text=True, check=True).stdout
        registros = saida.split("\0")[:-1]
        cruza, fica = [], []
        for r in registros:
            (cruza if r[0] == "1" else fica).append(r[1:])

        def conteudo_de(rel):
            abs_ = os.path.join(raiz, rel)
            if not os.path.isfile(abs_):
                return None
            try:
                with open(abs_, encoding="utf-8") as fh:
                    return fh.read()
            except (UnicodeDecodeError, OSError):
                return None

        ticket_re = re.compile(r"\b3\d{7}\b")  # formato dos tickets vistos: 3xxxxxxx

        def tickets_de_ritmo(rel, c):
            """ritmo.serie so guarda o maior ticket visto por instante, sem
            dominio nem candidato (CLAUDE.md, achado seguranca:tickets-reais-
            de-terceiros-no-git-e-no-site): nao conta como ticket real."""
            if not rel.endswith(".json"):
                return set()
            try:
                d = json.loads(c)
            except ValueError:
                return set()
            serie = d.get("ritmo", {}).get("serie") if isinstance(d, dict) else None
            if not isinstance(serie, list):
                return set()
            return {str(par[1]) for par in serie
                    if isinstance(par, (list, tuple)) and len(par) == 2}

        reais = set()
        for rel in fica:
            c = conteudo_de(rel)
            if c:
                reais |= set(ticket_re.findall(c)) - tickets_de_ritmo(rel, c)
        # lista explicita (rodada 1, correcao do revisor, 18/09/2026): os
        # tickets reais tirados dos arquivos que cruzam em 78adb1d nao estao
        # mais em nenhum arquivo que fica, entao o scan acima sozinho nao os
        # pegava e o teste passava com um vazamento no ar; conferir contra
        # esta lista, alem do scan.
        lista = conteudo_de("rodadas/2026-09/tickets-reais.txt")
        self.assertIsNotNone(lista, "rodadas/2026-09/tickets-reais.txt sumiu")
        reais |= set(ticket_re.findall(lista))

        vazados = {}
        for rel in cruza:
            c = conteudo_de(rel)
            if not c:
                continue
            achados = set(ticket_re.findall(c)) & reais
            if achados:
                vazados[rel] = sorted(achados)
        self.assertEqual(vazados, {})

    def test_arquivo_que_atravessa_nao_cita_caminho_privado(self):
        """preparacao-ops:docs-publicos-citam-privado (rodada 1, 18/09/2026,
        correcao do revisor): metade do criterio original ficava faltando --
        alem do numero de ticket, nenhum arquivo que cruza para o publico
        deveria citar um CAMINHO de NAO_ATRAVESSA que nunca chega la, porque
        quem le no repositorio publico nao acha o arquivo.

        site/dados.json, site/todos.json, docs/historico/disputas.json e
        docs/historico/listas/ ficam de fora desta lista: ao contrario do
        resto de NAO_ATRAVESSA, eles chegam ao publico por outro caminho (o
        workflow do proprio repositorio publico os gera a cada execucao, ou
        o lancamento semeia o historico uma vez -- CLAUDE.md, "Repositorios
        e publicacao", docs/lancamento.md passo 5): cita-los nao e um link
        quebrado.

        So conta citacao que parece um caminho de verdade (precedida de
        espaco, aspas, crase, parenteses etc.), nunca uma que e so parte de
        um caminho maior ou de uma URL do site (`/lembretes/rodadas/...`,
        `docs/presente/x.md`): por isso o regex exige que o caractere antes
        do nome nao seja letra, digito, `_` nem `/`.

        Citacoes que ja existem e sao legitimas (o proprio arquivo
        explicando sua propria regra, uma instrucao para rodar uma
        ferramenta local, ou a proveniencia de uma decisao) ficam na lista
        de excecoes abaixo, cada uma anotada; qualquer citacao NOVA falha o
        teste, para nao reabrir o vazamento que este item fechou.
        """
        caminho = os.path.join(os.path.dirname(__file__), "sincronizar-publico.sh")
        if not os.path.exists(caminho):
            self.skipTest("sincronizar-publico.sh so existe no repositorio de trabalho")
        raiz = os.path.dirname(__file__) or "."
        with open(caminho) as f:
            texto = f.read()
        inicio = texto.index("NAO_ATRAVESSA=(")
        fim = texto.index("\n}\n", inicio) + 3
        roteiro = texto[inicio:fim] + (
            'git ls-files -z | while IFS= read -r -d "" f; do '
            'if atravessa "$f"; then printf 1; else printf 0; fi; '
            'printf "%s\\0" "$f"; done\n')
        saida = subprocess.run(["bash", "-c", roteiro], cwd=raiz,
                               capture_output=True, text=True, check=True).stdout
        registros = saida.split("\0")[:-1]
        cruza = [r[1:] for r in registros if r[0] == "1"]

        # entradas de NAO_ATRAVESSA que nunca chegam ao publico por nenhum
        # caminho (ver docstring: os quatro de dado/historico ficam de fora)
        entradas = ["CLAUDE.md", "favoritos.txt", "skill/",
                    "sincronizar-publico.sh", "tickets.py", "presente/",
                    "monetizacao/", "work/leilao/", "rodadas/",
                    "COMECE-AQUI.md", "leituras/",
                    # conteudo fechado (nucleo aberto, 25/09/2026): a
                    # pesquisa editorial e a operacao do dono
                    "docs/criterios-de-valor.md", "docs/estrategia.md",
                    "docs/historico-das-rodadas.md", "docs/leilao-ao-vivo.md",
                    "docs/marcas-e-cybersquatting.md", "docs/mercado-br-vs-eua.md",
                    "docs/pesquisa-wayback-em-escala.md", "docs/perguntas-do-publico.md",
                    "docs/consulta-ponto-com.md", "docs/lancamento.md", "docs/operacao.md",
                    "site_modelo/conteudo/insights/"]
        padroes = {e: re.compile(r"(?<![\w/])" + re.escape(e)) for e in entradas}

        excecoes = {
            # o proprio .gitignore, explicando as excecoes das suas regras
            ".gitignore": {"sincronizar-publico.sh", "work/leilao/",
                           "CLAUDE.md", "rodadas/", "presente/"},
            # o proprio teste, descrevendo a NAO_ATRAVESSA que ele confere
            "test_scripts.py": {"sincronizar-publico.sh", "tickets.py",
                                "CLAUDE.md", "work/leilao/", "rodadas/",
                                "presente/", "monetizacao/",
                                "COMECE-AQUI.md", "skill/", "favoritos.txt",
                                "leituras/",
                                "docs/criterios-de-valor.md", "docs/estrategia.md",
                                "docs/historico-das-rodadas.md", "docs/leilao-ao-vivo.md",
                                "docs/marcas-e-cybersquatting.md", "docs/mercado-br-vs-eua.md",
                                "docs/pesquisa-wayback-em-escala.md", "docs/perguntas-do-publico.md",
                                "docs/consulta-ponto-com.md", "docs/lancamento.md", "docs/operacao.md",
                                "site_modelo/conteudo/insights/"},
            # o varrer.py le leituras/casa.json se existir; no publico a
            # pasta nao existe e ele segue em silencio (19/09/2026)
            "varrer.py": {"leituras/"},
            # a rajada em casa grava e comita leituras/casa.json, e a
            # operacao ensina a roda-la (19/09/2026); no publico a rajada
            # nao tem para onde empurrar e o varrer.py segue sem a pasta
            "rajada.py": {"leituras/", "docs/operacao.md"},
            "garimpo/casos/rajada.py": {"leituras/", "docs/operacao.md"},
            "docs/operacao.md": {"CLAUDE.md", "leituras/"},
            # paths-ignore do CI: nomes de pasta como configuracao, nao
            # citacao para o leitor abrir
            ".github/workflows/testes.yml": {"monetizacao/", "presente/",
                                             "rodadas/", "leituras/"},
            # o roteiro do lancamento precisa mandar rodar o script, e cita
            # uma conferencia ja feita no privado sobre COMECE-AQUI.md
            "docs/lancamento.md": {"sincronizar-publico.sh", "COMECE-AQUI.md"},
            # proveniencia de decisao (nao instrucao para abrir o arquivo);
            # monetizacao/ ja vem anotado como "(repositorio privado)" na
            # mesma frase
            "AGENTS.md": {"CLAUDE.md", "monetizacao/", "docs/operacao.md"},
            # S10: proveniencia da checagem da revogacao, nao instrucao
            "docs/limitacoes-registrobr.md": {"presente/"},
            "README.md": {"tickets.py"},
            "agenda_do_projeto.py": {"CLAUDE.md"},
            "docs/fontes-oficiais-registrobr.md": {"tickets.py"},
            "docs/historico-das-rodadas.md": {"work/leilao/"},
            "docs/pesquisa-wayback-em-escala.md": {"CLAUDE.md"},
            "garimpo/adaptadores/rdap.py": {"tickets.py"},
            "garimpo/adaptadores/registrobr.py": {"work/leilao/"},
            "garimpo/web/letras.py": {"CLAUDE.md"},
            "site_modelo/letra.js": {"CLAUDE.md"},
            "visitas.py": {"CLAUDE.md"},
            # nucleo aberto (25/09/2026): proveniencia de decisao em
            # comentario de codigo, ou o roteiro que precisa mandar rodar
            # o script; nada e link para o leitor abrir
            ".github/workflows/garimpo.yml": {"sincronizar-publico.sh"},
            "docs/rumo.md": {"docs/operacao.md", "sincronizar-publico.sh"},
            "garimpo/dominio/historico.py": {"docs/historico-das-rodadas.md"},
            "garimpo/dominio/relevancia.py": {"docs/criterios-de-valor.md"},
            "garimpo/web/ramos.py": {"docs/perguntas-do-publico.md"},
            "site_modelo/ficha.js": {"docs/perguntas-do-publico.md"},
            "web/pontocom.js": {"docs/consulta-ponto-com.md"},
        }

        def conteudo_de(rel):
            abs_ = os.path.join(raiz, rel)
            if not os.path.isfile(abs_):
                return None
            try:
                with open(abs_, encoding="utf-8") as fh:
                    return fh.read()
            except (UnicodeDecodeError, OSError):
                return None

        vazados = {}
        for rel in cruza:
            c = conteudo_de(rel)
            if not c:
                continue
            liberado = excecoes.get(rel, set())
            achados = {e for e, p in padroes.items()
                      if e not in liberado and p.search(c)}
            if achados:
                vazados[rel] = sorted(achados)
        self.assertEqual(vazados, {})


class TestCadenciaConfiguravel(unittest.TestCase):
    """O intervalo vem do workflow; o prazo dos quentes segue a razao."""

    def setUp(self):
        from garimpo.dominio import frescor
        self.frescor = frescor
        self.antes = (frescor.INTERVALO_HORAS, frescor.PRAZOS[frescor.Classe.QUENTE])

    def tearDown(self):
        self.frescor.configurar(self.antes[0])
        self.frescor.PRAZOS[self.frescor.Classe.QUENTE] = self.antes[1]

    def test_configurar_muda_intervalo_e_prazo(self):
        self.frescor.configurar(4)
        self.assertEqual(self.frescor.INTERVALO_HORAS, 4)
        self.assertEqual(self.frescor.PRAZOS[self.frescor.Classe.QUENTE], 8)
        self.assertEqual(self.frescor.tabela()["intervalo_horas"], 4)
        quente = next(c for c in self.frescor.tabela()["classes"] if c["nome"] == "quente")
        self.assertEqual(quente["prazo_horas"], 8)

    def test_workflow_escolhe_pela_visibilidade(self):
        with open(os.path.join(os.path.dirname(__file__), ".github", "workflows", "garimpo.yml")) as f:
            wf = f.read()
        self.assertIn('cron: "3 * * * *"', wf)
        # 18/09/2026: o privado saiu do minuto 3. Dois crons no mesmo minuto
        # viram um evento so, e o `if` pulava o horario do privado.
        self.assertIn('cron: "41 2,8,14,20 * * *"', wf)
        self.assertNotIn("3 1,5,9,13,17,21", wf)
        self.assertEqual(wf.count("'41 2,8,14,20 * * *'"), 2)  # os dois do if
        self.assertIn('cron: "30 7 20 * *"', wf)
        self.assertIn("github.event.repository.private", wf)
        self.assertIn("--intervalo-horas", wf)
        self.assertIn("intervalo=6", wf)

    def test_workflow_sem_expressao_dentro_do_shell(self):
        """Input do dispatch e nome do ref entram por env, nunca colados no run:."""
        with open(os.path.join(os.path.dirname(__file__), ".github", "workflows", "garimpo.yml")) as f:
            wf = f.read()
        blocos = re.findall(r"^(\s*)run: [|>]-?\n((?:\1\s+.*\n|\s*\n)*)", wf, re.MULTILINE)
        blocos += [("", b) for b in re.findall(r"^\s*run: ([^|>].*)$", wf, re.MULTILINE)]
        self.assertTrue(blocos)
        for _, corpo in blocos:
            self.assertNotIn("${{", corpo)
        self.assertIn("^[0-9]{1,3}$", wf)
        self.assertIn('default: "3"', wf)
        self.assertIn("ref: ${{ github.ref_name }}", wf)

    def test_wrangler_com_versao_fixa_e_igual_nos_dois(self):
        raiz = os.path.dirname(__file__)
        with open(os.path.join(raiz, ".github", "workflows", "garimpo.yml")) as f:
            wf = f.read()
        with open(os.path.join(raiz, "publicar.sh")) as f:
            sh = f.read()
        no_wf = re.findall(r"wrangler@([0-9.]+)", wf)
        no_sh = re.findall(r"wrangler@([0-9.]+)", sh)
        self.assertTrue(no_wf and no_sh)
        self.assertEqual(set(no_wf), set(no_sh))
        self.assertEqual(len(set(no_wf)), 1)
        self.assertRegex(no_wf[0], r"^4\.\d+\.\d+$")


class TestAlarmeDaVarredura(unittest.TestCase):
    """conferir_frescor.py fica vermelho quando a varredura foi barrada."""

    def rodar(self, varredura, fim="2026-09-16T15:00:00-03:00"):
        import conferir_frescor
        with tempfile.TemporaryDirectory() as d:
            dados = os.path.join(d, "dados.json")
            with open(dados, "w") as f:
                json.dump({"gerado_em": "2026-09-18T05:55:50+00:00",
                           "rodada": {"inicio": "2026-09-09T15:00:00-03:00",
                                      "fim": fim},
                           "frescor": {"classes": []}, "itens": []}, f)
            caminho = os.path.join(d, "varredura.json")
            if varredura is not None:
                with open(caminho, "w") as f:
                    json.dump(varredura, f)
            with unittest.mock.patch("sys.argv", ["conferir_frescor.py", dados,
                                                  "--varredura", caminho]), \
                 unittest.mock.patch("builtins.print"):
                return conferir_frescor.main()

    def test_alvos_e_nenhum_feito_com_a_rodada_fechada(self):
        self.assertEqual(self.rodar({"alvos": 120, "feitos": 0, "erros": 0,
                                     "bloqueios": 0}), 1)

    def test_bloqueio_acende_mesmo_com_consultas_feitas(self):
        self.assertEqual(self.rodar({"alvos": 120, "feitos": 80, "erros": 0,
                                     "bloqueios": 1}), 1)
        # e com a rodada aberta tambem
        self.assertEqual(self.rodar({"alvos": 120, "feitos": 80, "erros": 0,
                                     "bloqueios": 1}, fim="2099-01-01T15:00:00-03:00"), 1)

    def test_varredura_normal_ou_sem_alvos_fica_verde(self):
        self.assertEqual(self.rodar({"alvos": 120, "feitos": 118, "erros": 2,
                                     "bloqueios": 0}), 0)
        self.assertEqual(self.rodar({"alvos": 0, "feitos": 0, "erros": 0,
                                     "bloqueios": 0}), 0)
        # rodando local, sem varredura.json: so o frescor conta
        self.assertEqual(self.rodar(None), 0)

    def test_varredura_barrada_acende_citando_o_motivo(self):
        """19/09/2026: a varredura que parou sozinha diz por que parou."""
        import conferir_frescor
        for motivo in ("bloqueio", "rede"):
            barrada = {"alvos": 120, "tentados": 10, "feitos": 0, "erros": 10,
                       "bloqueios": 0, "pulada": None, "barrada": True,
                       "motivo": motivo}
            self.assertIn(motivo, conferir_frescor.alarme_da_varredura(barrada))
            self.assertEqual(self.rodar(barrada), 1)
            self.assertEqual(self.rodar(dict(barrada, feitos=80),
                                        fim="2099-01-01T15:00:00-03:00"), 1)

    def test_varredura_pulada_antes_da_abertura_fica_verde(self):
        """18/09/2026: lista nova saiu, rodada nao abriu, nada consultado."""
        pulada = {"alvos": 0, "tentados": 0, "feitos": 0, "erros": 0,
                  "bloqueios": 0, "pulada": "antes_da_abertura"}
        self.assertEqual(self.rodar(pulada, fim="2099-01-01T15:00:00-03:00"), 0)
        self.assertEqual(self.rodar(pulada), 0)

    def test_testes_yml_um_job_so_e_cancela_a_run_velha(self):
        """Regressao da matriz que dobrava o custo em minutos do Actions."""
        with open(os.path.join(os.path.dirname(__file__), ".github", "workflows", "testes.yml")) as f:
            wf = f.read()
        self.assertNotIn("strategy:", wf)
        self.assertIn("cancel-in-progress: true", wf)
        self.assertIn("group: testes-${{ github.ref }}", wf)
        # site_modelo/** e docs/historico/*.json tem de continuar disparando
        # a run: o ignore e so para texto que nenhum teste le.
        ignorados = re.findall(r'^\s*-\s*"([^"]+)"', wf, re.MULTILINE)
        self.assertTrue(ignorados)
        self.assertNotIn("site_modelo/**", ignorados)
        self.assertNotIn("docs/historico/*.json", ignorados)


class TestRitmo(unittest.TestCase):
    """Os tickets sao um contador global: a serie vira curva e estimativa."""

    H = 3600
    SERIE = [(0, 1000), (4 * 3600, 1400), (8 * 3600, 2200)]

    def test_registrar_so_avanca(self):
        from garimpo.dominio import ritmo
        s = ritmo.registrar([], 10, 100)
        s = ritmo.registrar(s, 20, 90)          # menor: nao acrescenta nada
        s = ritmo.registrar(s, 15, 150)
        s = ritmo.registrar(s, 12, 200)         # instante que nao avanca e corrigido
        self.assertEqual(s, [(10, 100), (15, 150), (15, 200)])

    def test_estimar_interpola(self):
        from garimpo.dominio import ritmo
        self.assertEqual(ritmo.estimar(self.SERIE, 1200), 2 * self.H)
        self.assertEqual(ritmo.estimar(self.SERIE, 1000), 0)
        self.assertEqual(ritmo.estimar(self.SERIE, 500), 0)     # antes: o limite
        self.assertIsNone(ritmo.estimar(self.SERIE, 9999))      # ainda nao visto
        self.assertIsNone(ritmo.estimar([], 1))

    def test_emitidos_e_por_hora(self):
        from garimpo.dominio import ritmo
        self.assertEqual(ritmo.emitidos(self.SERIE, 1000), 1201)
        self.assertIsNone(ritmo.emitidos(self.SERIE, None))
        # ultimas 4 h: de 1400 a 2200 em 4 h
        self.assertAlmostEqual(ritmo.por_hora(self.SERIE, 8 * self.H, 4 * self.H), 200)
        self.assertIsNone(ritmo.por_hora(self.SERIE[:1], 8 * self.H))
        # cinco pontos em sete minutos (a primeira execucao real): a subida e
        # descoberta de nomes, nao emissao; taxa nenhuma e melhor que 872 mil/h
        mesma_execucao = [(0, 1000), (100, 1500), (200, 2200), (300, 3000), (420, 3100)]
        self.assertIsNone(ritmo.por_hora(mesma_execucao, 420))
        r = ritmo.resumo(self.SERIE, 1000, 8 * self.H)
        self.assertEqual((r["emitidos"], r["pontos"]), (1201, 3))

    def test_por_hora_ignora_descoberta_dentro_da_execucao(self):
        # a serie publicada em 13/09/2026: saiu 2.289/h, o certo e ~267/h
        from datetime import datetime, timezone
        from garimpo.dominio import ritmo

        def t(txt):
            return int(datetime.strptime(txt, "%d %H:%M:%S").replace(
                year=2026, month=9, tzinfo=timezone.utc).timestamp())
        serie = [(t("12 17:44:51"), 32163208), (t("12 17:45:07"), 32164997),
                 (t("12 17:45:24"), 32179031), (t("12 17:45:43"), 32180685),
                 (t("12 17:46:08"), 32181871), (t("12 19:02:39"), 32181952),
                 (t("12 19:39:15"), 32182245), (t("12 19:39:26"), 32182353),
                 (t("12 19:57:32"), 32182458), (t("13 02:56:21"), 32183938),
                 (t("13 02:58:25"), 32184329)]
        self.assertEqual(len(ritmo.por_execucao(serie)), 3)
        self.assertAlmostEqual(ritmo.por_hora(serie, t("13 02:58:25")), 267, delta=1)

    def test_leitura_carrega_tickets_e_corte(self):
        leitura = classificar(LIBERACAO_DISPUTADA)
        self.assertEqual(leitura.tickets, (30001101, 30001102))
        self.assertFalse(leitura.cortado)
        dez = dict(LIBERACAO_DISPUTADA, tickets=list(range(1, 11)))
        self.assertTrue(classificar(dez).cortado)

    def test_repositorio_anota_ritmo_e_exporta_chegada(self):
        from garimpo.dominio import ritmo
        repo = Repositorio(":memory:")
        repo.gravar_pool([Candidato("a.com.br", nota=70), Candidato("b.com.br", nota=60)])
        repo.gravar_leitura("a.com.br", Leitura(Situacao.LIBERACAO_DISPUTADA, 2, "",
                                                 7, (1000, 1200)), epoch=100)
        repo.gravar_leitura("b.com.br", Leitura(Situacao.LIBERACAO_DISPUTADA, 2, "",
                                                 7, (1100, 2000)), epoch=200)
        # ticket menor visto depois nao acrescenta ponto
        repo.gravar_leitura("a.com.br", Leitura(Situacao.LIBERACAO_DISPUTADA, 2, "",
                                                 7, (1000, 1200)), epoch=300)
        self.assertEqual(repo.serie_ritmo(), [(100, 1200), (200, 2000)])
        self.assertEqual(repo.ticket_primeiro(), 1000)
        a = repo.um("a.com.br")
        self.assertEqual((a.ticket_min, a.ticket_max), (1000, 1200))

        meta = instantaneo.Metadados(gerado_em="2026-09-12T00:00:00+00:00")
        dados = instantaneo.exportar(repo.verificados(), meta,
                                     serie=repo.serie_ritmo(),
                                     primeiro=repo.ticket_primeiro(), agora_epoch=400)
        item = next(i for i in dados["itens"] if i[0] == "b.com.br")
        # 1100 esta entre 1200 (t=100)... nao: 1100 < 1200, o primeiro ponto
        self.assertEqual(item[instantaneo.I_CHEGADA_MIN], 100)
        self.assertEqual(item[instantaneo.I_CHEGADA_MAX], 200)
        self.assertEqual(dados["ritmo"]["emitidos"], 1001)
        self.assertEqual(dados["ritmo"]["serie"], [[100, 1200], [200, 2000]])
        # os numeros de ticket nao saem no item
        self.assertNotIn(1200, item)
        self.assertNotIn(2000, item)

        # restaurar num banco novo repoe a serie e a chegada estimada
        novo = Repositorio(":memory:")
        novo.gravar_pool([Candidato("b.com.br", nota=60)])
        novo.restaurar(instantaneo.candidatos_de(dados))
        novo.restaurar_ritmo(*instantaneo.ritmo_de(dados))
        self.assertEqual(novo.serie_ritmo(), [(100, 1200), (200, 2000)])
        self.assertEqual(novo.ticket_primeiro(), 1000)
        self.assertEqual(novo.um("b.com.br").chegada_min, 100)
        # e uma rodada nova zera tudo
        novo.esquecer_leituras()
        self.assertEqual(novo.serie_ritmo(), [])
        self.assertIsNone(novo.ticket_primeiro())

    def test_instantaneo_antigo_sem_chegada(self):
        """Item com 11 posicoes (v5 de antes de 12/09) continua legivel."""
        dados = {"status": ["LIBERACAO_LIVRE"], "marcas": ["OK"], "motivos": [],
                 "gerado_em": "2026-09-11T00:00:00+00:00",
                 "itens": [["x.com.br", 0, 0, 50, 1, [], 0, 0, 0, 0, 0]]}
        c = instantaneo.candidatos_de(dados)[0]
        self.assertIsNone(c.chegada_min)
        self.assertEqual(instantaneo.ritmo_de(dados), ([], None))


class TestRecontagem(unittest.TestCase):
    """Com 10 tickets no avail, a varredura pergunta ao RDAP uma vez."""

    def _repo(self):
        repo = Repositorio(":memory:")
        repo.gravar_pool([Candidato("dez.com.br", nota=70), Candidato("dois.com.br", nota=70)])
        return repo

    def test_reconta_so_quem_bateu_no_corte(self):
        repo = self._repo()
        cliente = ClienteFalso({
            "dez.com.br": Leitura(Situacao.LIBERACAO_DISPUTADA, 10, "ends-at=x", 7,
                                  tuple(range(1, 11))),
            "dois.com.br": Leitura(Situacao.LIBERACAO_DISPUTADA, 2, "", 7, (1, 2)),
        })
        contados = []

        def contador(dominio):
            contados.append(dominio)
            return 67

        v = Varredura(cliente, repo, contador=contador)
        v.PAUSA_RDAP = 0
        v.executar(["dez.com.br", "dois.com.br"], pausa=0)
        self.assertEqual(contados, ["dez.com.br"])
        self.assertEqual(repo.um("dez.com.br").candidatos, 67)
        self.assertIn("rdap=67", repo.um("dez.com.br").detalhe)
        self.assertEqual(repo.um("dois.com.br").candidatos, 2)

    def test_erro_no_rdap_desliga_ate_a_proxima_execucao(self):
        repo = self._repo()
        repo.gravar_pool([Candidato("outro.com.br", nota=70)])
        dez = Leitura(Situacao.LIBERACAO_DISPUTADA, 10, "", 7, tuple(range(1, 11)))
        cliente = ClienteFalso({"dez.com.br": dez, "outro.com.br": dez})
        chamadas = []

        def contador(dominio):
            chamadas.append(dominio)
            raise OSError("429")

        v = Varredura(cliente, repo, contador=contador)
        v.PAUSA_RDAP = 0
        v.executar(["dez.com.br", "outro.com.br"], pausa=0)
        self.assertEqual(chamadas, ["dez.com.br"])      # parou no primeiro erro
        self.assertEqual(repo.um("dez.com.br").candidatos, 10)

    def test_sem_contador_nada_muda(self):
        repo = self._repo()
        dez = Leitura(Situacao.LIBERACAO_DISPUTADA, 10, "", 7, tuple(range(1, 11)))
        Varredura(ClienteFalso({"dez.com.br": dez}), repo).executar(["dez.com.br"], pausa=0)
        self.assertEqual(repo.um("dez.com.br").candidatos, 10)


class TestSinaisDoDesfecho(unittest.TestCase):
    def test_cruza_veredito_com_faixas(self):
        import sinais_do_desfecho as sd
        desfecho = [
            {"dominio": "curto.com.br", "leitura": sd.OCULTO},
            {"dominio": "outrocurto.com.br", "leitura": sd.ZERO},
            {"dominio": "aindanarodada.com.br", "leitura": "ainda na rodada ou travado"},
        ]
        antes = {
            "curto.com.br": {"nota": 85, "elegivel": True, "motivos": ["palavra em português"]},
            "outrocurto.com.br": {"nota": 55, "elegivel": False, "motivos": ["nicho: x"]},
        }
        t = sd.cruzar(desfecho, antes)
        self.assertEqual({k: t["todos"][k] for k in ("n", "ocultos", "taxa")},
                         {"n": 2, "ocultos": 1, "taxa": 0.5})
        self.assertEqual(t["nota 80+"]["taxa"], 1.0)
        self.assertEqual(t["não elegível"]["ocultos"], 0)
        self.assertIn("extensão genérica", t)
        self.assertIn("nicho comercial", t)
        rel = sd.relatorio(t)
        self.assertIn("2 nomes", rel)
        self.assertNotIn("| nota 80+", rel)     # menos de 5: nao entra na tabela

    def test_taxa_ponderada_pela_amostra(self):
        """16/09/2026: a faixa sorteada em 1 de 10 pesa 10 na taxa geral."""
        import sinais_do_desfecho as sd
        desfecho = [
            {"dominio": "alto.com.br", "leitura": sd.OCULTO, "peso": "1"},
            {"dominio": "baixo.com.br", "leitura": sd.ZERO, "peso": "10"},
        ]
        antes = {"alto.com.br": {"nota": 85, "elegivel": False, "motivos": []},
                 "baixo.com.br": {"nota": 30, "elegivel": False, "motivos": []}}
        t = sd.cruzar(desfecho, antes)
        self.assertEqual((t["todos"]["n"], t["todos"]["ocultos"]), (2, 1))
        self.assertAlmostEqual(t["todos"]["taxa"], 1 / 11)

    def test_amostra_por_faixa_do_desfecho(self):
        """16/09/2026: 15.736 nomes nao cabem em 90 min; sorteio por faixa com peso."""
        import desfecho
        from garimpo.adaptadores.repositorio import Candidato
        alvos = ([Candidato(f"b{i:04d}.com.br", nota=30) for i in range(1000)]
                 + [Candidato(f"a{i}.com.br", nota=85) for i in range(3)])
        escolhidos, pesos = desfecho.amostrar(alvos, 50)
        self.assertEqual(len(escolhidos), 53)
        self.assertEqual({c.dominio for c in escolhidos if c.nota == 85},
                         {"a0.com.br", "a1.com.br", "a2.com.br"})
        self.assertEqual(pesos["a0.com.br"], 1.0)
        self.assertEqual({pesos[c.dominio] for c in escolhidos if c.nota == 30}, {20.0})
        # semente fixa: a mesma amostra em toda execucao
        self.assertEqual([c.dominio for c in escolhidos],
                         [c.dominio for c in desfecho.amostrar(alvos, 50)[0]])
        todos, pesos = desfecho.amostrar(alvos, 0)
        self.assertEqual((len(todos), set(pesos.values())), (1003, {1.0}))

    def test_itens_do_instantaneo(self):
        import sinais_do_desfecho as sd
        dados = {"motivos": ["a", "b"], "itens": [["x.com.br", 0, 0, 70, 1, [1], 0]]}
        self.assertEqual(sd.itens_do_instantaneo(dados)["x.com.br"],
                         {"nota": 70, "elegivel": True, "motivos": ["b"]})


class TestExtensoes(unittest.TestCase):
    """Quem pode registrar em cada extensao, pelo TLDs.php oficial."""

    def test_categorias(self):
        self.assertEqual(extensoes.categoria("com.br"), extensoes.GENERICA)
        self.assertEqual(extensoes.categoria("adv.br"), extensoes.PROFISSIONAL)
        self.assertEqual(extensoes.categoria("ind.br"), extensoes.EMPRESA)
        self.assertEqual(extensoes.categoria("rio.br"), extensoes.CIDADE)
        self.assertEqual(extensoes.categoria("blog.br"), extensoes.PESSOA)
        self.assertEqual(extensoes.categoria("org.br"), extensoes.RESTRITA)
        self.assertEqual(extensoes.categoria("br"), extensoes.RESTRITA)
        self.assertEqual(extensoes.categoria("naoexiste.br"), extensoes.DESCONHECIDA)

    def test_restrita(self):
        self.assertFalse(extensoes.restrita("app.br"))
        self.assertFalse(extensoes.restrita("sampa.br"))
        self.assertTrue(extensoes.restrita("med.br"))
        self.assertTrue(extensoes.restrita("tur.br"))
        # sem comprovacao da profissao (ajuda 2.6 do Registro.br, 18/09/2026)
        self.assertIn("só CPF", extensoes.quem_registra("med.br"))
        self.assertNotIn("conselho", extensoes.quem_registra("med.br"))

    def test_toda_extensao_frequente_da_rodada_esta_catalogada(self):
        """As 50 mais comuns na lista de setembro de 2026."""
        vistas = """com net app adv org ia tec dev ind art blog eng eco med agr
            tur srv tv log ong imb api inf seg arq pro social rio adm etc eti
            psc esp xyz cnt vet bsb vlog mus far wiki sorocaba floripa cim rec
            poa bio curitiba flog campinas""".split()
        faltam = [e for e in vistas if extensoes.categoria(e + ".br") == extensoes.DESCONHECIDA]
        self.assertEqual(faltam, [])

    def test_nota_rotula_extensao_restrita_sem_mudar_o_peso(self):
        restrita = pontuar("advogado.adv.br", {"advogado"}, set())
        livre = pontuar("advogado.art.br", {"advogado"}, set())   # generica, sem bonus
        self.assertTrue(any(m.startswith("extensão restrita") for m in restrita.motivos))
        self.assertFalse(any(m.startswith("extensão restrita") for m in livre.motivos))
        self.assertEqual(restrita.valor, livre.valor)


# --------------------------------------------------------------------------
# serie historica das rodadas (Internet Archive)
# --------------------------------------------------------------------------
from datetime import date as _date
from garimpo.dominio import historico
from garimpo.web import graficos


def _lista(inicio, gerado, nomes, fim=True, cabecalho_latin1=False):
    linhas = [f"# Processo de liberação no período de {inicio}T15:00:00-03:00 a {inicio}T15:00:00-03:00",
              "# Mais informações em https://registro.br/dominio/processo-de-liberacao/",
              f"# Arquivo gerado em {gerado}"] + list(nomes)
    if fim:
        linhas.append("# Fim do arquivo")
    return "\n".join(linhas)


def _rodadas(por_mes: dict) -> dict:
    """{'2020-01': ['a.com.br', ...]} -> rodadas agrupadas, dia 8 de cada mes."""
    copias = [historico.ler_lista(_lista(f"{m}-08", f"{m}-06T10:00:00", n)) for m, n in por_mes.items()]
    return historico.agrupar_por_rodada(copias)


class TestHistoricoLeitura(unittest.TestCase):
    def test_latin1_e_cabecalho(self):
        bruto = _lista("2019-03-13", "2019-03-11T10:00:00", ["café.com.br", "Loja.com.br"]).encode("latin-1")
        c = historico.ler_lista(historico.decodificar(bruto))
        self.assertEqual(c.inicio, _date(2019, 3, 13))
        self.assertEqual(c.nomes, ("café.com.br", "loja.com.br"))
        self.assertTrue(c.completa)

    def test_mesma_rodada_em_dois_dias_vira_uma_so(self):
        """digest diferente nao e rodada diferente: vale a copia gerada por ultimo"""
        a = historico.ler_lista(_lista("2020-01-08", "2020-01-06T10:00:00", ["a.com.br"]))
        b = historico.ler_lista(_lista("2020-01-08", "2020-01-07T10:00:00", ["a.com.br", "b.com.br"]))
        rodadas = historico.agrupar_por_rodada([b, a])
        self.assertEqual(len(rodadas), 1)
        self.assertEqual(rodadas[_date(2020, 1, 8)].total_linhas, 2)

    def test_copia_truncada_e_descartada(self):
        truncada = historico.ler_lista(_lista("2020-01-08", "2020-01-06T10:00:00", ["a.com.br"], fim=False))
        self.assertEqual(historico.agrupar_por_rodada([truncada]), {})


class TestHistoricoSeries(unittest.TestCase):
    def setUp(self):
        self.r = _rodadas({
            "2020-01": ["trava.com.br", "x.com.br"],
            "2020-02": ["trava.com.br", "volta.com.br"],
            "2020-03": ["trava.com.br"],
            "2020-04": ["trava.com.br", "volta.com.br"],
            # 2020-05 sem copia
            "2020-06": ["volta.com.br"],
        })

    def test_intervalo_so_entre_meses_seguidos(self):
        s = historico.serie_de_tamanho(self.r)
        self.assertIsNone(s[0]["intervalo_dias"])
        self.assertEqual(s[1]["intervalo_dias"], 31)
        self.assertIsNone(s[-1]["intervalo_dias"], "junho vem depois de um mes sem copia")

    def test_sequencia_de_quatro_rodadas(self):
        seqs = {(n, k) for n, _, k in historico.sequencias(self.r)}
        self.assertIn(("trava.com.br", 4), seqs)
        self.assertIn(("x.com.br", 1), seqs)

    def test_episodios_nao_contam_mes_sem_copia_como_volta(self):
        ep = historico.episodios(self.r)
        self.assertEqual(ep["trava.com.br"], 1)
        # volta: jan nao, fev sim, mar nao, abr sim, jun sim (a rodada capturada anterior, abr, tinha o nome)
        self.assertEqual(ep["volta.com.br"], 2)

    def test_origem_dos_elegiveis_nas_tres_anteriores(self):
        lib = _rodadas({"2020-01": ["a.com.br", "b.com.br"], "2020-02": ["a.com.br", "b.com.br"],
                        "2020-03": ["a.com.br", "b.com.br"], "2020-04": ["a.com.br", "b.com.br"],
                        "2020-05": ["a.com.br", "b.com.br", "novo.com.br"]})
        ele = _rodadas({"2020-05": ["a.com.br", "novo.com.br"]})
        (linha,) = historico.origem_dos_elegiveis(lib, ele)
        self.assertEqual((linha["elegiveis"], linha["nas_3_anteriores"], linha["nas_4_anteriores"]), (2, 1, 1))


class TestHistoricoTermos(unittest.TestCase):
    def test_casamento_ancorado_evita_colisao(self):
        regras = historico.compilar_termos()
        self.assertTrue(historico.casa("vacinacovid19", regras["covid"]))
        self.assertFalse(historico.casa("ecovida", regras["covid"]), "covid no meio de ecovida")
        self.assertTrue(historico.casa("bitcoinbrasil", regras["cripto"]))
        self.assertFalse(historico.casa("criptografia", regras["cripto"]))
        self.assertFalse(historico.casa("alphabet", regras["apostas"]))
        self.assertFalse(historico.casa("zukunft", regras["NFT"]))


class TestGraficos(unittest.TestCase):
    def test_svg_respeita_a_csp_e_tem_dica(self):
        svg = graficos.colunas_no_tempo(
            [(_date(2020, 1, 8), 100, "g-s1", "jan: 100"), (_date(2020, 3, 8), 50, "g-s0", "mar <50>")], "t")
        self.assertNotIn("style=", svg, "CSP style-src 'self' bloqueia atributo style")
        self.assertIn("<title>jan: 100</title>", svg)
        self.assertIn("mar &lt;50&gt;", svg)
        self.assertEqual(svg.count("<path"), 2)

    def test_figura_leva_tabela_e_fonte(self):
        fig = graficos.figura("<svg></svg>", "Legenda.", "arquivo", graficos.tabela(["a", "b"], [[1, 2]], {1}))
        self.assertIn("<figcaption>Legenda.", fig)
        self.assertIn('<td class="num">2</td>', fig)
        self.assertIn("<details>", fig)

    def test_numeros_em_portugues(self):
        self.assertEqual(graficos.num(1234567), "1.234.567")
        self.assertEqual(graficos.compacto(163544), "164 mil")
        self.assertEqual(graficos.compacto(1500000), "1,5 mi")


class TestPaginaComGraficoEImagem(unittest.TestCase):
    def test_markdown_ignora_svg_e_mantem_tabela(self):
        from garimpo.web import paginas
        fig = graficos.figura(graficos.colunas([("a", 1, "g-s1", "a: 1")], "t"), "Legenda.", "fonte",
                              graficos.tabela(["x", "y"], [["a", 1]]),
                              [("g-s1", "5 semanas"), ("g-s0", "4 semanas")])
        md = paginas.html_para_markdown("<p>Antes.</p>" + fig)
        self.assertIn("5 semanas · 4 semanas", md, "itens da chave de cores colados")
        self.assertNotIn("<path", md)
        self.assertNotIn("a: 1", md, "texto de dica do SVG vazou para o Markdown")
        self.assertIn("| x | y |", md)
        self.assertIn("Legenda.", md)

    def test_imagem_propria_vai_para_og_e_json_ld(self):
        from garimpo.web import paginas
        texto = ("<!--\ntitulo: T\ndescricao: D\ntipo: artigo\nsecao: insights\n"
                 "data: 2026-09-13\nimagem: og/x.png\n-->\n<p>c</p>")
        p = paginas.ler_fragmento(texto, "insights/x")
        layout = "{{titulo}}{{descricao}}{{canonical}}{{nome}}{{nav}}{{classe_main}}{{cabecalho_extra}}{{regua}}{{miolo}}{{rodape}}{{jsonld}}{{og_tipo}}{{og_extra}}{{imagem}}{{scripts}}{{alternativo}}"
        html = paginas.render(p, layout, {}, "https://ex.br")
        self.assertIn("https://ex.br/og/x.png", html)
        self.assertNotIn("https://ex.br/og.png", html)


class TestPaginaDados(unittest.TestCase):
    """A aba Dados: numeros vivos do instantaneo e nenhum digito escrito a mao."""

    DADOS = {
        "status": ["LIBERACAO_LIVRE", "LIBERACAO_DISPUTADA", "COMPETITIVO"],
        "marcas": ["OK", "ATENCAO", "RISCO"],
        "itens": [
            ["a.com.br", 1, 2, 90, 0, [], 0, 0, 0, 0, 0, 0, 0],
            ["b.com.br", 1, 3, 90, 0, [], 0, 0, 0, 0, 0, 0, 0],
            ["marca.com.br", 1, 40, 90, 0, [], 2, 0, 0, 0, 0, 0, 0],
            ["c.com.br", 1, 12, 90, 0, [], 0, 0, 0, 0, 0, 0, 0],
            ["d.com.br", 0, 0, 90, 0, [], 0, 0, 0, 0, 0, 0, 0],
            ["e.com.br", 2, 3, 90, 1, [], 0, 1, 0, 0, 0, 0, 0],
        ],
    }

    def test_navegacao_tem_dados(self):
        from garimpo.web import paginas
        self.assertIn(("dados", "Dados"), paginas.NAVEGACAO)

    def test_grafico_de_candidatos(self):
        fig = graficos.figura_candidatos(self.DADOS)
        self.assertIn("Dos 4 nomes disputados, 50% têm só 2 ou 3", fig)
        self.assertIn("<td>10+</td><td class=\"num\">2</td>", fig)
        self.assertEqual(graficos.figura_candidatos({"status": ["LIVRE"], "itens": []}), "")

    def test_numeros_vivos_e_ranking_sem_marca(self):
        from garimpo.web import paginas
        molde = ('<strong id="p-disputados">-</strong><span id="p-verificados">-</span>'
                 '<div id="p-fig-candidatos"><p>espera</p></div><ol id="p-mais-disputados"><li>x</li></ol>')
        html = paginas.preencher_numeros(molde, self.DADOS)
        self.assertIn('<strong id="p-disputados">4</strong>', html)
        self.assertIn('<span id="p-verificados">6</span>', html)
        self.assertIn("<figure", html)
        self.assertNotIn("marca.com.br", html)
        self.assertLess(html.index("c.com.br"), html.index("b.com.br"))

    def test_fragmento_sem_digito_a_mao(self):
        import re
        texto = open(os.path.join(os.path.dirname(__file__), "site_modelo", "conteudo", "dados.html"),
                     encoding="utf-8").read()
        texto = re.sub(r"<!--.*?-->", "", texto, flags=re.S)
        texto = re.sub(r"<figure.*?</figure>", "", texto, flags=re.S)
        texto = re.sub(r'(<(\w+)[^>]*\bid="[hp]-[^"]*"[^>]*>).*?(</\2>)', "", texto, flags=re.S)
        texto = re.sub(r"<[^>]+>", " ", texto)
        soltos = re.findall(r"\S*\d\S*", texto.replace("º", ""))
        soltos = [s for s in soltos if not re.fullmatch(r"\d", s)]   # 1º mes, 4º mes
        self.assertEqual(soltos, [], "numero escrito a mao na pagina Dados")

    DISPUTAS = {"rodadas": {"2026-09-09": {
        "fim": "2026-09-16T15:00:00-03:00", "na_lista": 1000, "conferidos": 200,
        "nomes": {"a.com.br": [2, 0], "b.com.br": [3, 2], "c.com.br": [12, 0],
                  "marca.com.br": [40, 2], "fora.com.br": [50, 0]}}}}
    MOLDE = ('<section id="p-rodada"><h2 id="este-mes">A lista deste mês</h2>'
             '<p>A lista aberta. Estes números se atualizam.</p>'
             '<strong id="p-disputados">-</strong></section>')

    def _com(self, gerado_em: str, inicio: str = "2026-09-09T15:00:00-03:00",
             fim: str = "2026-09-16T15:00:00-03:00") -> dict:
        return dict(self.DADOS, gerado_em=gerado_em, rodada={"inicio": inicio, "fim": fim})

    def test_rodada_fechada_vem_da_base_e_nao_do_instantaneo(self):
        # 17/09/2026: depois do fechamento o instantaneo so via 4 disputados
        # (os que sobraram); a base guardava 311
        from garimpo.web import paginas
        html = paginas.preencher_numeros(self.MOLDE, self._com("2026-09-18T01:00:00+00:00"),
                                         self.DISPUTAS)
        self.assertIn("Como terminou a rodada de setembro de 2026", html)
        self.assertNotIn("aberta.", html)
        self.assertNotIn("se atualizam", html)
        self.assertIn(">5</strong> nomes tiveram duas ou mais", html)
        self.assertIn("2,5% dos 200", html)
        self.assertIn(">2</strong> foram a leilão", html)
        self.assertIn(">3</strong> travaram", html)
        self.assertIn("abre em 14/10/2026", html)
        # ranking: do mais pedido, sem marca, e sem nome que o instantaneo nao confere
        self.assertLess(html.index("c.com.br</code>: 12 pedidos (travou, volta em outubro)"),
                        html.index("b.com.br</code>: 3 pedidos (foi a leilão)"))
        self.assertNotIn("marca.com.br</code>", html)
        self.assertNotIn("fora.com.br</code>", html)
        # marca.com.br (40) e fora.com.br (50) passam do ultimo da lista (b, 3)
        self.assertIn("fora os que parecem marca", html)
        self.assertIn("2 nomes com mais pedidos que o último", html)
        self.assertIn("<figure", html)

    def test_rodada_aberta_fica_com_o_bloco_vivo(self):
        from garimpo.web import paginas
        html = paginas.preencher_numeros(self.MOLDE, self._com("2026-09-12T12:00:00+00:00"),
                                         self.DISPUTAS)
        self.assertIn("A lista deste mês", html)
        self.assertIn('<strong id="p-disputados">4</strong>', html)

    def test_lista_nova_antes_de_abrir_mostra_a_rodada_anterior(self):
        # 12/10 a 14/10: o instantaneo ja e de outubro, a base ainda nao
        from garimpo.web import paginas
        dados = self._com("2026-10-13T12:00:00+00:00", "2026-10-14T15:00:00-03:00",
                          "2026-10-21T15:00:00-03:00")
        html = paginas.preencher_numeros(self.MOLDE, dados, self.DISPUTAS)
        self.assertIn("Como terminou a rodada de setembro de 2026", html)

    def test_rodada_fechada_sem_base_nao_inventa_numero(self):
        from garimpo.web import paginas
        html = paginas.preencher_numeros(self.MOLDE, self._com("2026-09-18T01:00:00+00:00"), {})
        self.assertIn("A rodada está fechada", html)
        self.assertNotIn("se atualizam", html)

    def test_ranking_reavalia_marca_mesmo_com_risco_gravado_desatualizado(self):
        """achado produto-ceo:ranking-marca-no-titulo (S18): a varredura que
        gravou o instantaneo e anterior a lista fixa de hoje, e o h3 promete
        "fora os que parecem marca" sem depender de uma nova varredura."""
        from garimpo.web import paginas
        dados = dict(self.DADOS, itens=self.DADOS["itens"] + [
            ["brasiltelecom.com.br", 1, 35, 90, 0, [], 0, 0, 0, 0, 0, 0, 0]])  # marca[0]="OK", gravado antes do fix
        disputas = {"rodadas": {"2026-09-09": dict(
            self.DISPUTAS["rodadas"]["2026-09-09"],
            nomes=dict(self.DISPUTAS["rodadas"]["2026-09-09"]["nomes"],
                      **{"brasiltelecom.com.br": [35, 0]}))}}
        html = paginas.rodada_da_pagina(
            dict(dados, gerado_em="2026-09-18T01:00:00+00:00",
                rodada={"inicio": "2026-09-09T15:00:00-03:00", "fim": "2026-09-16T15:00:00-03:00"}),
            disputas)
        self.assertNotIn("brasiltelecom.com.br</code>", html)
        # brasiltelecom (35) some da lista; o "ficaram de fora" sobe em 1
        self.assertIn("3 nomes com mais pedidos que o último", html)

    def test_json_ld_da_pagina_dados_tem_dataset(self):
        from garimpo.web import paginas
        p = paginas.ler_fragmento("<!--\ntitulo: T\ndescricao: D\ntipo: pagina\n-->\n<p>c</p>", "dados")
        ld = paginas.json_ld(p, "https://ex.br")
        self.assertIn("https://ex.br/dados/historico/rodadas.json", ld)
        self.assertIn("https://ex.br/dados/historico/disputas.json", ld)
        self.assertIn('"Dataset"', ld)


@so_com("site_modelo/conteudo/regras-do-br.html")
class TestRegrasOficiaisDoBr(unittest.TestCase):
    """
    o1-site-regras-oficiais (18/09/2026): a reserva "depois de 6 processos"
    foi revogada pela Res. CGI.br 2017/031; quem deu o numero de travas
    exigidas antes do leilao foi o NIC.br, em 2017, nao a resolucao.
    """

    def _ler(self, *partes):
        caminho = os.path.join(os.path.dirname(__file__), "site_modelo",
                                "conteudo", *partes)
        with open(caminho, encoding="utf-8") as f:
            return f.read()

    def test_regra_de_6_processos_so_como_historia(self):
        pagina = self._ler("regras-do-br.html")
        # nao pode dar a reserva automatica como regra vigente
        self.assertNotIn("Depois de 6 processos, o nome vira reservado", pagina)
        self.assertIn("revogou", pagina)
        self.assertIn("2017/031", pagina)
        # a mensagem de erro citada e a literal da especificacao (sem acento)
        pagina_uma_linha = re.sub(r"\s+", " ", pagina)
        self.assertIn(
            "Dominio nao disponivel para registro por ter participado de "
            "mais de 6 (seis) processos de liberacao consecutivos",
            pagina_uma_linha)

    def test_flag1_marca_sem_efeito_hoje(self):
        pagina = self._ler("regras-do-br.html")
        self.assertIn("provedor de serviços", pagina)
        self.assertNotIn("provedor de hospedagem", pagina)
        # a preferencia (nao a flag em si) e o que acabou; a citacao da
        # flag1 e a literal da especificacao (sem acento)
        pagina_uma_linha = re.sub(r"\s+", " ", pagina)
        self.assertIn(
            "indica que a entidade e detentora de marca registrada do "
            "nome de dominio", pagina_uma_linha)
        self.assertNotIn("já não tem efeito", pagina)

    def test_nicbr_deu_o_numero_de_travas_em_2017(self):
        for arquivo in ("regras-do-br.html", "glossario.html", "perguntas.html"):
            pagina = self._ler(arquivo)
            self.assertNotIn("A regra oficial não diz quantas", pagina)
            self.assertNotIn("regra oficial não dá o número", pagina)
        insight = self._ler("insights", "tres-travas-e-leilao.html")
        insight_uma_linha = re.sub(r"\s+", " ", insight)
        self.assertIn("3 processos sem que um novo titular seja apontado",
                       insight_uma_linha)
        self.assertIn("Rubens Kuhl", insight)
        self.assertIn("nic.br/noticia", insight)

    def test_regras_do_br_sem_acento_faltando(self):
        pagina = self._ler("regras-do-br.html")
        # trechos fora de citacao literal do protocolo (essas ficam sem
        # acento de proposito: mensagens da especificacao EPP, citadas ao
        # pe da letra)
        sem_citacoes = re.sub(r'"[^"]*"', "", pagina)
        for errado, certo in [
            ("quem estava la antes", "quem estava lá antes"),
            ("esse periodo", "esse período"),
            ("seguinte as 15h", "seguinte às 15h"),
            ("O menor lance e ", "O menor lance é "),
            ("A oferta e <strong>vinculante", "A oferta é <strong>vinculante"),
            ("ela\n    alcanca", "ela\n    alcança"),
            ("prova ma-fe", "prova má-fé"),
            ("maioria esta na rodada", "maioria está na rodada"),
            ("que da a situação", "que dá a situação"),
            ("0,87 req/s</td><td>comecam falhas",
             "0,87 req/s</td><td>começam falhas"),
            ("sequencial e lenta:\n    e o que separa",
             "sequencial e lenta:\n    é o que separa"),
        ]:
            self.assertNotIn(errado, sem_citacoes, f"acento faltando: {certo!r}")

    def test_reserva_continua_como_origem_pois_a_pagina_oficial_diz_isso(self):
        # achado de rodada 1 pedia tirar "reserva" da frase de abertura; a
        # pagina oficial (processo-de-liberacao, dump de 17/09/2026) lista
        # "ou que tenham sido reservados" como uma das origens, entao a
        # frase foi mantida e citada, nao apagada.
        pagina = self._ler("regras-do-br.html")
        self.assertIn("tenham sido reservados", pagina)
        self.assertIn("/perguntas/#como-entra-na-lista", pagina)

    def test_total_da_rodada_nao_fica_preso_a_um_mes(self):
        # bug de classe: um numero escrito a mao (ex.: "na de setembro de
        # 2026 foram") ao lado do id preenchido pelo build envelhece
        # sozinho em outubro; o total tem que vir só do id
        pagina = self._ler("regras-do-br.html")
        self.assertNotIn("na de setembro de 2026 foram", pagina)
        self.assertIn('id="p-rodada-inicio2"', pagina)
        self.assertIn('id="p-total-rodada"', pagina)

    def test_como_ler_a_tabela_tem_os_selos_da_rodada_fechada(self):
        pagina = self._ler("regras-do-br.html")
        for selo in ("fechou sem candidato", "travou",
                     "volta na próxima rodada", "espera a próxima rodada",
                     "pedido pendente"):
            self.assertIn(selo, pagina)
        self.assertIn("/glossario/#nome-travado", pagina)

    def test_regras_do_br_abre_com_resposta_citavel(self):
        # o2-site-respostas-citaveis (18/09/2026): a pagina nao pode abrir
        # falando de si mesma; as duas primeiras frases sao o que uma IA
        # extrai como resumo.
        pagina = self._ler("regras-do-br.html")
        self.assertIn('<p class="entrada">', pagina)
        entrada = re.search(r'<p class="entrada">(.*?)</p>', pagina, re.S).group(1)
        self.assertNotIn("Esta página descreve", entrada)
        self.assertIn("processo de liberação de domínios", entrada)
        self.assertIn("costuma", entrada)
        # nao repete o texto literal do resumo de /perguntas/
        self.assertNotIn(
            "A rodada costuma começar na segunda quarta-feira do mês, às "
            "15h de Brasília, e dura 7 dias", entrada)


@so_com("site_modelo/conteudo/glossario.html")
class TestGlossarioDefineCongeladoEExpirado(unittest.TestCase):
    """
    o2-site-respostas-citaveis (18/09/2026): o glossario (que vira
    DefinedTermSet) nao definia "domínio congelado" nem "expirado", os
    termos que o publico digita e que estao no title de /quando-volta/.
    """

    def _ler_glossario(self):
        caminho = os.path.join(os.path.dirname(__file__), "site_modelo",
                                "conteudo", "glossario.html")
        with open(caminho, encoding="utf-8") as f:
            return f.read()

    def test_dois_termos_novos_com_links_para_ciclo_e_quando_volta(self):
        pagina = self._ler_glossario()
        for termo in ("dominio-congelado", "dominio-expirado"):
            bloco = re.search(rf'<dt id="{termo}">.*?</dd>', pagina, re.S)
            self.assertIsNotNone(bloco, f"falta o termo {termo}")
            self.assertIn("/quando-volta/#congelado", bloco.group(0))
            self.assertIn("/ciclo-de-vida-do-dominio-br/", bloco.group(0))

    def test_definicoes_concordam_com_a_tabela_do_ciclo(self):
        # o Registro.br nao publica quanto tempo o dominio fica congelado
        pagina = self._ler_glossario()
        congelado = re.search(r'<dt id="dominio-congelado">.*?</dd>',
                               pagina, re.S).group(0)
        self.assertIn("não publica quanto tempo", congelado)
        self.assertIn("inactive", congelado)

    def test_nenhum_id_existente_muda(self):
        pagina = self._ler_glossario()
        ids = re.findall(r'<dt id="([^"]+)">', pagina)
        for antigo in ("processo-de-liberacao", "rodada", "candidatura",
                       "limite-de-candidaturas", "ticket", "candidato-oculto",
                       "nome-travado", "elegivel", "processo-competitivo",
                       "oferta-vinculante", "dominio-liberado", "anuidade",
                       "cancelamento", "aguardando-liberacao",
                       "dominio-equivalente", "extensao-restrita", "rdap",
                       "saci-adm", "registro-br", "nota-de-relevancia",
                       "joia"):
            self.assertIn(antigo, ids)
        self.assertIn("dominio-congelado", ids)
        self.assertIn("dominio-expirado", ids)

    def test_defined_term_set_ganha_os_dois_termos(self):
        from garimpo.web import paginas
        pagina = self._ler_glossario()
        corpo = re.search(r"<dl.*?</dl>", pagina, re.S).group(0)
        termos = {i: t for i, t, _ in paginas.termos_do_glossario(corpo)}
        self.assertEqual(termos["dominio-congelado"], "Domínio congelado")
        self.assertEqual(termos["dominio-expirado"],
                          "Domínio expirado (vencido)")


@so_com("site_modelo/conteudo/ciclo-de-vida-do-dominio-br.html")
class TestCicloDeVidaCitaFaqOficial(unittest.TestCase):
    """
    o2-site-respostas-citaveis (18/09/2026): o ciclo de vida nao trazia a
    frase oficial sobre o que acontece se o dono nao pagar.
    """

    def test_cita_a_pergunta_1_4_com_fonte(self):
        caminho = os.path.join(os.path.dirname(__file__), "site_modelo",
                                "conteudo", "ciclo-de-vida-do-dominio-br.html")
        with open(caminho, encoding="utf-8") as f:
            pagina = f.read()
        pagina_uma_linha = re.sub(r"\s+", " ", pagina)
        self.assertIn(
            "O seu domínio será congelado e após um período liberado para "
            "novo registro, de acordo com as regras do processo de "
            "liberação.", pagina_uma_linha)
        self.assertIn("pagamento-de-dominio", pagina)
        self.assertIn("1.4", pagina)


@so_com("site_modelo/conteudo/perguntas.html")
class TestPerguntasComTextoLiteralDaBusca(unittest.TestCase):
    """
    o2-site-perguntas-literais (18/09/2026): tres perguntas em perguntas.html
    citam ao pe da letra as mensagens que a busca do Registro.br mostra
    (bundle publico IsAvail, conferido em 17/09/2026), porque quem le a frase
    no site do Registro.br copia ela para o Google.
    """

    FRASES = (
        'O que significa "Domínio disponível para candidaturas no processo '
        'de liberação" no Registro.br?',
        'O que significa "Domínio está aguardando o início do processo de '
        'liberação" no Registro.br?',
        'O que significa "Domínio em processo de liberação competitivo" no '
        'Registro.br?',
    )

    def _ler(self, *partes):
        caminho = os.path.join(os.path.dirname(__file__), "site_modelo",
                                "conteudo", *partes)
        with open(caminho, encoding="utf-8") as f:
            return f.read()

    def test_tres_ids_fixos_com_a_pergunta_literal(self):
        pagina = self._ler("perguntas.html")
        for id_, frase in zip(
            ("disponivel-para-candidaturas", "aguardando-inicio",
             "processo-competitivo-mensagem"), self.FRASES):
            self.assertIn(f'id="{id_}">{frase}', pagina)

    def test_faqpage_ganha_as_tres_perguntas(self):
        from garimpo.web import paginas
        p = paginas.ler_fragmento(self._ler("perguntas.html"), "perguntas")
        bloco = paginas.json_ld(p, "https://ex.br")
        ld = json.loads(re.search(
            r'<script type="application/ld\+json">(.*?)</script>',
            bloco, re.S).group(1))
        faq = next(n for n in ld["@graph"] if n["@type"] == "FAQPage")
        nomes = [q["name"] for q in faq["mainEntity"]]
        for frase in self.FRASES:
            self.assertIn(frase, nomes)

    def test_nenhuma_outra_pagina_repete_esses_h2(self):
        raiz = os.path.join(os.path.dirname(__file__), "site_modelo", "conteudo")
        for atual, _, arquivos in os.walk(raiz):
            for nome in arquivos:
                if not nome.endswith(".html") or nome == "perguntas.html":
                    continue
                with open(os.path.join(atual, nome), encoding="utf-8") as f:
                    conteudo = f.read()
                for frase in self.FRASES:
                    self.assertNotIn(frase, conteudo,
                                      f"{nome} repete o h2 {frase!r}")

    def test_resposta_curta_sem_div_aninhado_antes_do_fechamento(self):
        pagina = self._ler("perguntas.html")
        for id_ in ("disponivel-para-candidaturas", "aguardando-inicio",
                    "processo-competitivo-mensagem"):
            trecho = pagina.split(f'id="{id_}"')[1].split("</div>")[0]
            self.assertNotIn("<div", trecho)

    def test_disponivel_para_candidaturas_cobre_as_duas_ocorrencias(self):
        """
        A frase e o titulo do resultado com a rodada aberta (sem data) e
        tambem um aviso com "a partir de <data>" antes dela abrir (bundle
        IsAvail, funcao Z e o template do titulo `available===2`). Rodada 2
        do revisor corrigiu uma resposta que so cobria a segunda ocorrencia.
        """
        pagina = self._ler("perguntas.html")
        resposta = pagina.split('id="disponivel-para-candidaturas"')[1].split(
            '<p class="resposta-curta">')[1].split("</p>")[0]
        self.assertIn("a partir de", resposta)
        self.assertIn("rodada aberta", resposta)

    def test_aguardando_inicio_nao_afirma_sem_ressalva(self):
        """A resposta-curta nao pode voltar a dizer soh 'o nome travou': o
        caso medido (S16) e um entre os que mostram essa mensagem."""
        pagina = self._ler("perguntas.html")
        resposta = pagina.split('id="aguardando-inicio"')[1].split(
            '<p class="resposta-curta">')[1].split("</p>")[0]
        self.assertIn("caso conferido", resposta)


class TestCalendario(unittest.TestCase):
    """As datas da rodada pela regra, e a previsao de volta (S14)."""

    def test_segunda_quarta_as_15h(self):
        from garimpo.dominio import calendario as c
        self.assertEqual(c.abertura(2026, 9).isoformat(), "2026-09-09T15:00:00-03:00")
        self.assertEqual(c.abertura(2026, 10).isoformat(), "2026-10-14T15:00:00-03:00")
        self.assertEqual(c.abertura(2026, 11).isoformat(), "2026-11-11T15:00:00-03:00")
        # mes que comeca numa quarta: a segunda quarta e o dia 8
        self.assertEqual(c.abertura(2025, 1).day, 8)
        abre = c.abertura(2026, 10)
        self.assertEqual(c.saida_da_lista(abre).isoformat(), "2026-10-12")
        self.assertEqual(c.fechamento(abre).isoformat(), "2026-10-21T15:00:00-03:00")

    def test_proxima_abertura_e_estrita(self):
        from garimpo.dominio import calendario as c
        abre = c.abertura(2026, 9)
        self.assertEqual(c.proxima_abertura(abre).month, 10)
        um_minuto_antes = abre - __import__("datetime").timedelta(minutes=1)
        self.assertEqual(c.proxima_abertura(um_minuto_antes), abre)
        self.assertEqual(c.mes_seguinte(c.abertura(2026, 12)).isoformat(), "2027-01-13T15:00:00-03:00")

    def test_previsao_de_volta_bate_com_a_publicada(self):
        # insight dos bumerangues: galoegolo.com.br vence 15/07/2026 e deve
        # voltar na rodada de 09/12/2026
        from garimpo.dominio import calendario as c
        provavel, seguinte = c.previsao_de_volta(_date(2026, 7, 15))
        self.assertEqual(provavel.date().isoformat(), "2026-12-09")
        self.assertEqual(seguinte.date().isoformat(), "2027-01-13")

    def test_aberturas_para_o_navegador(self):
        from garimpo.dominio import calendario as c
        datas = c.aberturas(_date(2026, 9, 14), 1, 2)
        self.assertEqual(datas, ["2026-08-12", "2026-09-09", "2026-10-14", "2026-11-11"])

    def test_pagina_recebe_o_calendario_do_instantaneo(self):
        from garimpo.web import paginas
        dados = {"gerado_em": "2026-09-14T03:00:00+00:00", "itens": [],
                 "rodada": {"inicio": "2026-09-09T15:00:00-03:00", "fim": "2026-09-16T15:00:00-03:00"}}
        html = paginas.preencher_numeros('<script type="application/json" id="p-calendario">{}</script>', dados)
        corpo = re.search(r">(.*)</script>", html).group(1)
        cal = json.loads(corpo)
        self.assertIn("2026-10-14", cal["aberturas"])
        self.assertEqual(cal["meses_ate_a_lista"], 5)
        self.assertEqual(cal["dias_lista_antes"], 2)
        self.assertEqual([d.date().isoformat() for d in paginas.rodadas_para_lembrete(dados, 2)],
                         ["2026-10-14", "2026-11-11"])
        self.assertEqual(paginas.proxima_rodada("2026-09-09T15:00:00-03:00"), "14/10/2026")


class TestPassagens(unittest.TestCase):
    """O indice da ficha: fatia por hash, igual no Python e no navegador."""

    def test_hash_conhecido(self):
        from garimpo.dominio import passagens
        # vetores de referencia do FNV-1a de 32 bits
        self.assertEqual(passagens.fnv1a32(""), 0x811C9DC5)
        self.assertEqual(passagens.fnv1a32("a"), 0xE40C292C)
        self.assertEqual(passagens.fatia("A.com.br "), passagens.fatia("a.com.br"))

    def test_mesmo_hash_no_ficha_js(self):
        import shutil
        from garimpo.dominio import passagens
        node = shutil.which("node")
        if not node:
            self.skipTest("sem node")
        js = open(os.path.join(os.path.dirname(__file__), "site_modelo", "ficha.js"), encoding="utf-8").read()
        funcao = re.search(r"function fnv1a32\(texto\) \{.*?\n  \}", js, re.S).group(0)
        nomes = ["galoegolo.com.br", "café.com.br", "xn--caf-dma.com.br", "a"]
        saida = subprocess.run([node, "-e", funcao + f"; for (const n of {json.dumps(nomes)}) process.stdout.write(String(fnv1a32(n)) + ' ')"],
                               capture_output=True, text=True, check=True).stdout.split()
        self.assertEqual([int(x) for x in saida], [passagens.fnv1a32(n) for n in nomes])

    def test_montar_so_quem_passou_duas_vezes(self):
        from garimpo.dominio import passagens
        rod = {
            _date(2026, 7, 8): historico.Rodada(_date(2026, 7, 8), None, "", frozenset({"a.com.br", "b.com.br"})),
            _date(2026, 8, 12): historico.Rodada(_date(2026, 8, 12), None, "", frozenset({"a.com.br"})),
            _date(2026, 9, 9): historico.Rodada(_date(2026, 9, 9), None, "", frozenset({"a.com.br", "c.com.br"})),
        }
        datas, fatias = passagens.montar(rod)
        self.assertEqual(datas, ["2026-07-08", "2026-08-12", "2026-09-09"])
        linhas = [l for ls in fatias.values() for l in ls]
        self.assertEqual(linhas, ["a.com.br\t0,1,2"])
        self.assertIn(passagens.fatia("a.com.br"), fatias)

    def test_marca_a_rodada_em_que_era_elegivel(self):
        from garimpo.dominio import passagens
        d = [_date(2026, 7, 8), _date(2026, 8, 12), _date(2026, 9, 9)]
        rod = {x: historico.Rodada(x, None, "", frozenset({"a.com.br"})) for x in d}
        ele = {d[2]: historico.Rodada(d[2], None, "", frozenset({"a.com.br"}))}
        datas, fatias = passagens.montar(rod, elegiveis=ele)
        self.assertEqual([l for ls in fatias.values() for l in ls], ["a.com.br\t0,1,2e"])
        # sem copia da lista de elegiveis, "nao era" e "nao sabemos" se separam aqui
        self.assertEqual(passagens.com_elegiveis(datas, ele), [2])

    def test_ficha_le_o_rdap_depois_do_fechamento(self):
        """16/09/2026: nome travado e leilao com a rodada fechada nao sao 'registrado'."""
        import shutil
        node = shutil.which("node")
        if not node:
            self.skipTest("sem node")
        js = open(os.path.join(os.path.dirname(__file__), "site_modelo", "ficha.js"), encoding="utf-8").read()
        funcao = re.search(r"function classificar\(res, exibe\) \{.*?\n  \}", js, re.S).group(0)
        vazio = {"objectClassName": "domain", "handle": "one.com.br", "ldhName": "one.com.br"}
        leilao = {"objectClassName": "domain", "status": ["pending create"],
                  "publicIds": [{"type": "ticket", "identifier": "1"}, {"type": "ticket", "identifier": "2"}]}
        casos = [
            {"status": 200, "recurso": "release-process-waiting", "json": vazio},
            {"status": 200, "recurso": "competitive-release-process-closed;date=2026-09-16T18:00:00Z", "json": leilao},
            {"status": 200, "recurso": "competitive-release-process-running;date=2026-09-16T18:00:00Z", "json": leilao},
            {"status": 200, "recurso": "release-process-running;date=2026-09-16T18:00:00Z", "json": leilao},
            {"status": 200, "recurso": "release-process-closed;date=2026-09-16T18:00:00Z", "json": leilao},
        ]
        saida = subprocess.run([node, "-e", "const foraDaRegra = () => false;" + funcao
                                + f"; for (const c of {json.dumps(casos)}) console.log(JSON.stringify(classificar(c, '')))"],
                               capture_output=True, text=True, check=True).stdout.splitlines()
        r = [json.loads(l) for l in saida]
        self.assertEqual(r[0]["tipo"], "travado")
        self.assertEqual((r[1]["tipo"], r[1]["tickets"], r[1]["fim"]), ("leilao", 2, "2026-09-16T18:00:00.000Z"))
        self.assertEqual(r[2]["tipo"], "leilao")
        self.assertEqual(r[3]["tipo"], "rodada")
        # rodada normal fechada nao foi vista: nao vira "rodada aberta"
        self.assertEqual(r[4]["tipo"], "pendente")

    def test_conferencia_ao_vivo_le_o_rdap_depois_do_fechamento(self):
        """16/09/2026: o app nao chama de REGISTRADO um nome travado nem um leilao fechado."""
        import shutil
        node = shutil.which("node")
        if not node:
            self.skipTest("sem node")
        js = open(os.path.join(os.path.dirname(__file__), "site_modelo", "app.js"), encoding="utf-8").read()
        funcao = re.search(r"async function consultarRdap\(dominio\) \{.*?\n\}", js, re.S).group(0)
        # 18/09/2026: consultarRdap delega a window.Disputa.consultar (disputa.js), que ja
        # devolve {status, recurso, json}; so essa fronteira precisa de mock aqui.
        roteiro = (funcao + """
const respostas = {
  'one.com.br': [200, 'release-process-waiting', {objectClassName: 'domain'}],
  'vacina.com.br': [200, 'competitive-release-process-closed;date=2026-09-16T18:00:00Z',
                    {objectClassName: 'domain', publicIds: [{type: 'ticket'}, {type: 'ticket'}]}],
  'liberados.com.br': [200, '', {objectClassName: 'domain', status: ['active']}],
};
globalThis.window = { Disputa: { consultar: async (caminho) => {
  const [status, recurso, json] = respostas[caminho.replace('domain/', '')];
  return { status, recurso, json };
} } };
(async () => { for (const d of Object.keys(respostas)) console.log(JSON.stringify(await consultarRdap(d))); })();
""")
        saida = subprocess.run([node, "-e", roteiro], capture_output=True, text=True, check=True).stdout.splitlines()
        r = [json.loads(l) for l in saida]
        self.assertEqual(r[0], {"situacao": "AGUARDANDO_LIBERACAO", "candidatos": 0})
        self.assertEqual(r[1], {"situacao": "COMPETITIVO", "candidatos": 2})
        self.assertEqual(r[2]["situacao"], "REGISTRADO")

    def test_sequencia_da_ficha(self):
        """Tres travas seguidas: leilao. Mes sem lista guardada nao prova ausencia."""
        import shutil
        node = shutil.which("node")
        if not node:
            self.skipTest("sem node")
        js = open(os.path.join(os.path.dirname(__file__), "site_modelo", "ficha.js"), encoding="utf-8").read()
        funcao = re.search(r"function sequencia\(rodadas, linha, mes, naLista\) \{.*?\n  \}", js, re.S).group(0)
        jul_a_set = ["2026-07-08", "2026-08-12", "2026-09-09"]
        sem_julho = ["2026-06-10", "2026-08-12", "2026-09-09"]
        casos = [
            (jul_a_set, "0,1,2", "2026-09", True),     # terceira trava: leilao
            (jul_a_set, "1,2", "2026-09", True),       # segunda: rodada normal, falta uma
            (jul_a_set, None, "2026-09", True),        # primeira vez (fora do indice, set indexado)
            (sem_julho, "1,2", "2026-09", True),       # julho sem copia: incerta
            (jul_a_set, None, "2026-10", True),        # outubro fora do indice: set nao prova nada
            (["2026-08-12", "2026-09-09"], "0e,1", "2026-09", True),   # elegivel em ago: +3
            (jul_a_set, None, "2026-09", False),       # nem na lista
            (["2026-08-12", "2026-09-09"], "0,1e", "2026-09", True),   # elegivel agora: jul provado
        ]
        saida = subprocess.run([node, "-e", funcao + f"; for (const c of {json.dumps(casos)}) "
                                "console.log(JSON.stringify(sequencia(...c)))"],
                               capture_output=True, text=True, check=True).stdout.splitlines()
        r = [json.loads(l) for l in saida]
        self.assertEqual((r[0]["seguidas"], r[0]["proxima"]), (3, "leilao"))
        self.assertEqual((r[1]["seguidas"], r[1]["proxima"], r[1]["faltam"], r[1]["piso"]), (2, "rodada", 1, False))
        self.assertEqual((r[2]["seguidas"], r[2]["proxima"], r[2]["faltam"]), (1, "rodada", 2))
        self.assertEqual((r[3]["proxima"], r[3]["falta"]), ("incerta", {"mes": "2026-07", "motivo": "sem-copia"}))
        # o que falta no indice e outubro, a rodada de agora, e nao setembro
        self.assertEqual((r[4]["proxima"], r[4]["falta"]), ("incerta", {"mes": "2026-10", "motivo": "indice"}))
        self.assertEqual((r[5]["seguidas"], r[5]["proxima"], r[5]["piso"]), (5, "leilao", True))
        self.assertEqual(r[6]["proxima"], "nenhuma")
        self.assertEqual((r[7]["seguidas"], r[7]["proxima"]), (4, "leilao"))


class TestArquivoDasRodadas(unittest.TestCase):
    """A base propria: listas guardadas uma vez e contagem que so cresce."""

    @staticmethod
    def _dados(itens, inicio="2026-09-09T15:00:00-03:00", gerado="2026-09-10T00:00:00+00:00"):
        return {"rodada": {"inicio": inicio, "fim": "2026-09-16T15:00:00-03:00"},
                "gerado_em": gerado, "total_rodada": 125453,
                "status": [s.value for s in instantaneo.SITUACOES], "itens": itens}

    @staticmethod
    def _item(nome, situacao, candidatos, elegivel=0, em_leilao=0):
        return [nome, instantaneo.SITUACOES.index(situacao), candidatos, 50, elegivel, [], 0,
                em_leilao, 0, 0, 0, 0, 0]

    def test_acumula_o_maior_e_a_fase_mais_adiantada(self):
        from garimpo.casos import arquivo_das_rodadas as arq
        s = Situacao
        base = arq.acumular(None, self._dados([
            self._item("a.com.br", s.LIBERACAO_DISPUTADA, 3),
            self._item("b.com.br", s.LIBERACAO_LIVRE, 0),            # sem disputa: fora
            self._item("c.com.br", s.COMPETITIVO, 2, elegivel=1, em_leilao=1),
        ]))
        # depois da rodada a varredura ve o nome sem candidato: a contagem nao cai
        base = arq.acumular(base, self._dados([
            self._item("a.com.br", s.AGUARDANDO_LIBERACAO, 0),
            self._item("c.com.br", s.COMPETITIVO, 5, elegivel=1, em_leilao=1),
        ], gerado="2026-09-17T00:00:00+00:00"))
        rodada = base["rodadas"]["2026-09-09"]
        self.assertEqual(rodada["nomes"], {"a.com.br": [3, 0], "c.com.br": [5, 2]})
        self.assertEqual((rodada["conferidos"], rodada["na_lista"]), (3, 125453))
        self.assertEqual(json.loads(arq.serializar(base)), base)
        texto = json.dumps(base)
        self.assertNotIn("ticket_", texto)

    def test_nada_mudou_nada_grava(self):
        from garimpo.casos import arquivo_das_rodadas as arq
        dados = self._dados([self._item("a.com.br", Situacao.LIBERACAO_DISPUTADA, 2)])
        with tempfile.TemporaryDirectory() as d:
            caminho = os.path.join(d, "disputas.json")
            self.assertTrue(arq.atualizar_disputas(caminho, dados))
            self.assertFalse(arq.atualizar_disputas(caminho, dict(dados, gerado_em="2026-09-11T00:00:00+00:00")))

    def test_lista_guardada_uma_vez_e_so_completa(self):
        import gzip
        from garimpo.casos import arquivo_das_rodadas as arq
        cabecalho = ("# Processo de liberação no período de 2026-10-14T15:00:00-03:00 a 2026-10-21T15:00:00-03:00\n"
                     "# Arquivo gerado em 2026-10-12T10:00:00-03:00\n")
        with tempfile.TemporaryDirectory() as d:
            trabalho, pasta = os.path.join(d, "work"), os.path.join(d, "listas")
            os.makedirs(trabalho)
            with open(os.path.join(trabalho, "liberacao.txt"), "w", encoding="utf-8") as f:
                f.write(cabecalho + "a.com.br\n")                    # truncada: sem fim
            with open(os.path.join(trabalho, "competitivo.txt"), "w", encoding="utf-8") as f:
                f.write(cabecalho + "b.com.br\n# Fim do arquivo\n")
            self.assertEqual([os.path.basename(c) for c in arq.guardar_listas(trabalho, pasta)],
                             ["2026-10-14-elegiveis.txt.gz"])
            with open(os.path.join(trabalho, "liberacao.txt"), "a", encoding="utf-8") as f:
                f.write("# Fim do arquivo\n")
            self.assertEqual([os.path.basename(c) for c in arq.guardar_listas(trabalho, pasta)],
                             ["2026-10-14-liberacao.txt.gz"])
            self.assertEqual(arq.guardar_listas(trabalho, pasta), [])
            with open(os.path.join(pasta, "2026-10-14-liberacao.txt.gz"), "rb") as f:
                bruto = f.read()
            self.assertEqual(gzip.decompress(bruto).decode("utf-8").splitlines()[2], "a.com.br")
            self.assertEqual(bruto, arq.gzip_estavel(cabecalho + "a.com.br\n# Fim do arquivo\n"))


class TestLembretesDeRodada(unittest.TestCase):
    """O .ics da proxima rodada, que sobrevive quando nao ha leilao."""

    def test_dois_eventos_deterministicos(self):
        from garimpo.casos import lembretes
        from garimpo.dominio import calendario
        texto = lembretes.ics_da_rodada(calendario.abertura(2026, 10))
        linhas = texto.split("\r\n")
        self.assertIn("DTSTART;VALUE=DATE:20261012", linhas)
        self.assertIn("DTSTART:20261014T180000Z", linhas)
        self.assertEqual(texto.count("BEGIN:VEVENT"), 2)
        self.assertTrue(all(len(l.encode("utf-8")) <= 75 for l in linhas))
        self.assertEqual(texto, lembretes.ics_da_rodada(calendario.abertura(2026, 10)))

    def test_rodadas_depois_da_pasta_refeita(self):
        import tempfile
        from garimpo.casos import lembretes
        from garimpo.dominio import calendario
        with tempfile.TemporaryDirectory() as d:
            pasta = os.path.join(d, "lembretes")
            lembretes.escrever(pasta, [], None)          # sem leilao: apaga a pasta
            n = lembretes.escrever_rodadas(pasta, [calendario.abertura(2026, 10),
                                                   calendario.abertura(2026, 11)])
            self.assertEqual(n, 2)
            self.assertEqual(sorted(os.listdir(os.path.join(pasta, "rodadas"))),
                             ["2026-10-14.ics", "2026-11-11.ics"])


class TestConferenciaAoVivo(unittest.TestCase):
    """app.js: nao reconferir ao vivo quem acabou de ser conferido (18/09/2026, o1)."""

    def test_recente_conferido_respeita_rever_minutos(self):
        import shutil
        node = shutil.which("node")
        if not node:
            self.skipTest("sem node")
        js = open(os.path.join(os.path.dirname(__file__), "site_modelo", "app.js"), encoding="utf-8").read()
        # o indice de VF no array compacto e a janela de REVER_MINUTOS, exatamente como app.js declara
        vf = int(re.search(r"const D = 0, SS = 1, C = 2, N = 3, E = 4, M = 5, MK = 6, EL = 7, VF = (\d+)", js).group(1))
        rever = int(re.search(r"const REVER_MINUTOS = (\d+);", js).group(1))
        funcao = re.search(r"function recenteConferido\(it\) \{.*?\n\}", js, re.S).group(0)
        roteiro = (f"const VF = {vf}; const REVER_MINUTOS = {rever};"
                   + "const agoraSeg = () => 1000000;" + funcao + """
const it = (vf) => { const a = []; a[VF] = vf; return a; };
process.stdout.write(JSON.stringify([
  recenteConferido(it(1000000 - 60)),             // 1 min atras: recente
  recenteConferido(it(1000000 - REVER_MINUTOS * 60 + 1)),  // dentro da janela, por 1s
  recenteConferido(it(1000000 - REVER_MINUTOS * 60)),      // no limite: nao e mais recente
  recenteConferido(it(1000000 - REVER_MINUTOS * 60 - 1)),  // passou da janela
  recenteConferido(it(0)),                          // nunca conferido (VF ausente)
  recenteConferido(it(undefined)),
]));""")
        saida = subprocess.run([node, "-e", roteiro], capture_output=True, text=True, check=True).stdout
        self.assertEqual(json.loads(saida), [True, True, False, False, False, False])

    def test_etiqueta_elegivel_conta_o_desfecho_com_a_rodada_fechada(self):
        """25/09/2026: 'elegivel' num nome ja registrado, rodada fechada, era
        lido como 'ainda em leilao, da para entrar'. Fechada, o registrado
        ganha 'leilao encerrado' (sem a cor de convite) e os outros nada; o
        motivo 'elegivel ao leilao' vira 'foi a leilao' na mesma linha."""
        import shutil
        node = shutil.which("node")
        if not node:
            self.skipTest("sem node")
        js = open(os.path.join(os.path.dirname(__file__), "site_modelo", "app.js"), encoding="utf-8").read()
        etiqueta = re.search(r"function etiquetaElegivel\(it\) \{.*?\n\}", js, re.S).group(0)
        motivo = re.search(r"function motivoDaLinha\(it, motivo\) \{.*?\n\}", js, re.S).group(0)
        roteiro = f"""
const SS = 1, E = 4;
const iLeilao = 0, iRegistrado = 1, iLivre = 2;
let fechada = false;
const rodadaFechada = () => fechada;
{etiqueta}
{motivo}
const linha = (ss, e) => {{ const it = []; it[SS] = ss; it[E] = e; return it; }};
const r = [];
r.push(etiquetaElegivel(linha(iLivre, 1)));          // aberta: convite
r.push(etiquetaElegivel(linha(iLeilao, 1)));         // aberta, em leilao: nada
fechada = true;
r.push(etiquetaElegivel(linha(iRegistrado, 1)));     // fechada: desfecho
r.push(etiquetaElegivel(linha(iLivre, 1)));          // fechada, nao registrado: nada
r.push(etiquetaElegivel(linha(iRegistrado, 0)));     // nao elegivel: nada
r.push(motivoDaLinha(linha(iRegistrado, 1), 'elegível ao leilão'));
r.push(motivoDaLinha(linha(iLivre, 1), 'elegível ao leilão'));
r.push(motivoDaLinha(linha(iRegistrado, 1), 'nome curto'));
process.stdout.write(JSON.stringify(r));
"""
        saida = subprocess.run([node, "-e", roteiro], capture_output=True, text=True, check=True).stdout
        aberta, em_leilao, registrado, livre, nao_elegivel, m1, m2, m3 = json.loads(saida)
        self.assertIn(">elegível<", aberta)
        self.assertNotIn("encerrado", aberta)
        self.assertEqual(em_leilao, "")
        self.assertIn('class="pilula-elegivel encerrado"', registrado)
        self.assertIn(">leilão encerrado<", registrado)
        self.assertNotIn(">elegível<", registrado)
        self.assertEqual(livre, "")
        self.assertEqual(nao_elegivel, "")
        self.assertEqual(m1, "foi a leilão")
        self.assertEqual(m2, "elegível ao leilão")
        self.assertEqual(m3, "nome curto")
        css = open(os.path.join(os.path.dirname(__file__), "web", "style.css"), encoding="utf-8").read()
        self.assertIn(".pilula-elegivel.encerrado {", css)

    def test_conferir_ao_abrir_pula_quem_e_recente_mas_nao_a_lista_compartilhada(self):
        js = open(os.path.join(os.path.dirname(__file__), "site_modelo", "app.js"), encoding="utf-8").read()
        corpo = re.search(r"function conferirAoAbrir\(\) \{.*?\n\}", js, re.S).group(0)
        self.assertIn(".filter((it) => !recenteConferido(it))", corpo)
        # a lista compartilhada (?lista=) fica fora do filtro: quem abriu o link quer o numero fresco
        linha_compartilhada = next(l for l in corpo.splitlines() if "compartilhada =" in l)
        self.assertNotIn("recenteConferido", linha_compartilhada)

    def test_localstorage_ate_recente_conferido_a_cadeia_inteira(self):
        # o1, criterio 2: nao basta o predicado isolado. O bug real era a
        # cadeia localStorage -> lerConferidos -> restaurarConferido -> it[VF]
        # -> recenteConferido nunca se encontrarem numa pagina recem-aberta
        # (estado.aoVivo, em memoria, some a cada load; quem sobrevive e o
        # localStorage). Roda as 3 funcoes reais do app.js encadeadas, com um
        # localStorage falso: e o mais perto de "abrir a inicial de novo" que
        # da para fazer sem navegador e sem tocar o Registro.br.
        import shutil
        node = shutil.which("node")
        if not node:
            self.skipTest("sem node")
        js = open(os.path.join(os.path.dirname(__file__), "site_modelo", "app.js"), encoding="utf-8").read()
        d_idx, ss_idx, vf_idx, el_idx = 0, 1, 8, 7
        assert re.search(r"const D = 0, SS = 1, C = 2, N = 3, E = 4, M = 5, MK = 6, EL = 7, VF = 8, CL = 9", js)
        rever = int(re.search(r"const REVER_MINUTOS = (\d+);", js).group(1))
        chave = re.search(r"const CHAVE_CONFERIDOS = '([^']+)';", js).group(1)
        validade = re.search(r"const VALIDADE_CONFERIDO = ([^;]+);", js).group(1)
        ler_conferidos = re.search(r"function lerConferidos\(\) \{.*?\n\}", js, re.S).group(0)
        restaurar_conferido = re.search(r"function restaurarConferido\(it\) \{.*?\n\}", js, re.S).group(0)
        recente_conferido = re.search(r"function recenteConferido\(it\) \{.*?\n\}", js, re.S).group(0)
        roteiro = f"""
const D = {d_idx}, SS = {ss_idx}, C = 2, VF = {vf_idx}, EL = {el_idx};
const REVER_MINUTOS = {rever};
const CHAVE_CONFERIDOS = {json.dumps(chave)};
const VALIDADE_CONFERIDO = {validade};
const agoraSeg = () => 2000000;
const estado = {{ dados: {{ status: ['LIVRE', 'REGISTRADO'] }}, conferidos: new Map(), doNavegador: new Set() }};
const localStorage = {{
  _v: {{}},
  getItem(k) {{ return Object.prototype.hasOwnProperty.call(this._v, k) ? this._v[k] : null; }},
  setItem(k, v) {{ this._v[k] = v; }},
}};
// uma conferencia feita 3 min atras, guardada no aparelho na visita anterior
localStorage.setItem(CHAVE_CONFERIDOS, JSON.stringify({{ 'ex.com.br': {{ s: 'LIVRE', c: 0, t: 2000000 - 180 }} }}));
{ler_conferidos}
{restaurar_conferido}
{recente_conferido}
estado.conferidos = lerConferidos();          // como no boot: le o localStorage
const it = []; it[D] = 'ex.com.br'; it[SS] = 0; it[VF] = 0; it[EL] = 0;
restaurarConferido(it);                       // como no boot: aplica a cada linha
process.stdout.write(JSON.stringify({{ tamanho: estado.conferidos.size, vf: it[VF], recente: recenteConferido(it) }}));
"""
        saida = subprocess.run([node, "-e", roteiro], capture_output=True, text=True, check=True).stdout
        r = json.loads(saida)
        self.assertEqual(r["tamanho"], 1)             # lerConferidos aceitou o registro
        self.assertEqual(r["vf"], 2000000 - 180)       # restaurarConferido propagou o carimbo
        self.assertTrue(r["recente"])                  # e recenteConferido reconhece: nao reconfere

    def test_conferencia_nao_duplica_a_mensagem_do_bloqueio(self):
        # o1, criterio 3: com window.Disputa bloqueado, e.message ja e "Não deu
        # para conferir agora...", e o prefixo generico ("A conferência
        # parou:") duplicaria a frase e deixaria ".." no meio.
        import shutil
        node = shutil.which("node")
        if not node:
            self.skipTest("sem node")
        js = open(os.path.join(os.path.dirname(__file__), "site_modelo", "app.js"), encoding="utf-8").read()
        processar = re.search(r"async function processarFila\(\) \{.*?\n\}", js, re.S).group(0)
        catch = re.search(r"\} catch \(e\) \{.*?\n    \}", processar, re.S).group(0)
        # bloqueado: e.message ja e a mensagem completa, sem o prefixo generico
        for bloqueado, tem_prefixo_generico in ((True, False), (False, True)):
            roteiro = f"""
let fila = {{}};
let avisado = null;
const avisar = (t) => {{ avisado = t; }};
const window = {{ Disputa: {{ bloqueado: () => {str(bloqueado).lower()} }} }};
const erroLancado = {{ message: 'Não deu para conferir agora; tente de novo em 5 min.' }};
try {{ throw erroLancado; {catch}
process.stdout.write(JSON.stringify(avisado));
"""
            saida = subprocess.run([node, "-e", roteiro], capture_output=True, text=True, check=True).stdout
            avisado = json.loads(saida)
            self.assertEqual(avisado.startswith("A conferência parou:"), tem_prefixo_generico)
            if not tem_prefixo_generico:      # bloqueado: a frase pronta ja termina em ".", sem duplicar
                self.assertNotIn("..", avisado)


class TestFicha(unittest.TestCase):
    """A pagina /quando-volta/: navegacao, espelho sem formulario, scripts."""

    def test_aba_e_espelho(self):
        from garimpo.web import paginas
        self.assertIn(("quando-volta", "Quando volta"), paginas.NAVEGACAO)
        modelo = os.path.join(os.path.dirname(__file__), "site_modelo")
        pagina = next(p for p in paginas.carregar(modelo) if p.slug == "quando-volta")
        self.assertEqual(pagina.scripts, ("disputa.js", "agenda.js", "ficha.js"))
        md = paginas.markdown_da_pagina(pagina, {})
        self.assertNotIn("Consultar", md)             # o formulario nao vira texto
        self.assertIn("/quando-volta/?d=nome.com.br", md)

    def test_ficha_nunca_le_dado_pessoal_alem_do_nome(self):
        js = open(os.path.join(os.path.dirname(__file__), "site_modelo", "ficha.js"), encoding="utf-8").read()
        codigo = "\n".join(l for l in js.splitlines() if not l.strip().startswith(("*", "//", "/*")))
        for proibido in ("legalRepresentative", "publicIds.find", "email", "adr"):
            self.assertNotIn(proibido, codigo)

    def test_nome_fora_da_regra_nao_e_livre(self):
        # a.com.br responde 404 no RDAP como um nome livre, mas e "Dominio invalido"
        import shutil
        node = shutil.which("node")
        if not node:
            self.skipTest("sem node")
        js = open(os.path.join(os.path.dirname(__file__), "site_modelo", "ficha.js"), encoding="utf-8").read()
        funcao = re.search(r"function foraDaRegra\(exibe\) \{.*?\n  \}", js, re.S).group(0)
        nomes = ["a.com.br", "ab.com.br", "123.com.br", "2a.com.br", "é.com.br", "café.com.br",
                 "a" * 26 + ".com.br", "a" * 27 + ".com.br"]
        saida = subprocess.run([node, "-e", funcao + f"; process.stdout.write(JSON.stringify({json.dumps(nomes)}.map(foraDaRegra)))"],
                               capture_output=True, text=True, check=True).stdout
        self.assertEqual(json.loads(saida), [True, False, True, False, True, False, False, True])

    def test_ancora_nao_vira_consulta(self):
        # 18/09/2026: /quando-volta/#travou consultava o RDAP de "travou.com.br" (F-bug).
        # So ?d= pede consulta; o hash fica so para os ids das secoes (compartilhar.js).
        js = open(os.path.join(os.path.dirname(__file__), "site_modelo", "ficha.js"), encoding="utf-8").read()
        self.assertNotIn("location.hash", js)
        pedido = re.search(r"const pedido = .*?;", js, re.S).group(0)
        self.assertEqual(pedido, "const pedido = new URLSearchParams(location.search).get('d');")


class TestSeuNome(unittest.TestCase):
    """/seu-nome/ (19/09/2026, r3-seu-nome): ate tres .com.br do nome, pela ficha, com pausa."""

    RAIZ = os.path.dirname(os.path.abspath(__file__))

    def node(self, roteiro):
        import shutil
        node = shutil.which("node")
        if not node:
            self.skipTest("sem node")
        # relogio falso: setTimeout avanca o relogio e dispara na hora, entao
        # as pausas de 2,5 s viram numeros e o teste nao espera nada. fetch
        # falso anota toda URL (nenhuma pode ser do RDAP: essa passa so por
        # Disputa.consultar, que conta as chamadas e o instante de cada uma)
        preparo = """
let t = 1e12;
Date.now = () => t;
globalThis.setTimeout = (fn, ms) => { t += Math.max(0, ms || 0); Promise.resolve().then(fn); return 0; };
globalThis.clearTimeout = () => {};
globalThis.window = globalThis;
const urls = [];
globalThis.fetch = async (url) => { urls.push(String(url)); return { ok: false, status: 404, text: async () => '', json: async () => null }; };
globalThis.document = { querySelector: () => null, addEventListener: () => {} };
globalThis.location = { search: '', origin: 'https://liberados.com.br' };
globalThis.history = { replaceState: () => {} };
const chamadas = [];
window.Disputa = { consultar: async (c) => { chamadas.push([c, t]); return { status: 404, recurso: '', json: null }; },
                   bloqueado: () => false };
const fs = require('fs');
for (const f of ['site_modelo/ficha.js', 'site_modelo/seu-nome.js']) (0, eval)(fs.readFileSync(f, 'utf8'));
const alvo = () => ({ dataset: {}, innerHTML: '', querySelector: () => null });
"""
        return subprocess.run([node, "-e", preparo + roteiro], capture_output=True, text=True,
                              check=True, cwd=self.RAIZ).stdout

    def test_candidatos(self):
        casos = ["Maria Silva", "João da Conceição", "Ana Maria dos Santos", "Li", "a", "", "   ",
                 "mariasilva.com.br", "Zé 123", "SILVA silva", "João Silva Filho",
                 "Pedro Souza Júnior", "Ana Costa Neta", "Carlos Neto", "José da Silva Jr."]
        saida = self.node(f"console.log(JSON.stringify({json.dumps(casos)}.map(SeuNome.candidatos)))")
        r = dict(zip(casos, json.loads(saida)))
        self.assertEqual(r["Maria Silva"], ["mariasilva.com.br", "silva.com.br", "maria.com.br"])
        self.assertEqual(r["João da Conceição"], ["joaoconceicao.com.br", "conceicao.com.br", "joao.com.br"])
        self.assertEqual(r["Ana Maria dos Santos"], ["anasantos.com.br", "santos.com.br", "ana.com.br"])
        self.assertEqual(r["Li"], ["li.com.br"])
        self.assertEqual((r["a"], r[""], r["   "]), ([], [], []))
        self.assertEqual(r["mariasilva.com.br"], ["mariasilva.com.br"])
        # so numeros nao vale como rotulo do .br
        self.assertEqual(r["Zé 123"], ["ze123.com.br", "ze.com.br"])
        self.assertEqual(r["SILVA silva"], ["silvasilva.com.br", "silva.com.br"])
        # Filho, Junior, Neto no fim nao sao sobrenome; com dois nomes so, sao
        self.assertEqual(r["João Silva Filho"], ["joaosilva.com.br", "silva.com.br", "joao.com.br"])
        self.assertEqual(r["Pedro Souza Júnior"], ["pedrosouza.com.br", "souza.com.br", "pedro.com.br"])
        self.assertEqual(r["Ana Costa Neta"], ["anacosta.com.br", "costa.com.br", "ana.com.br"])
        self.assertEqual(r["Carlos Neto"], ["carlosneto.com.br", "neto.com.br", "carlos.com.br"])
        self.assertEqual(r["José da Silva Jr."], ["josesilva.com.br", "silva.com.br", "jose.com.br"])

    def test_maria_silva_tres_consultas_em_sequencia_com_pausa(self):
        saida = self.node("""
(async () => {
  const nomes = SeuNome.candidatos('Maria Silva');
  const alvos = nomes.map(alvo);
  await SeuNome.conferirTodos(nomes, { conferir: (n, i) => Ficha.conferir(n, n, alvos[i]) });
  await new Promise((r) => setImmediate(r));
  console.log(JSON.stringify({ nomes, chamadas, urls, cartoes: alvos.map((a) => a.innerHTML) }));
})();
""")
        r = json.loads(saida)
        self.assertEqual([c for c, _ in r["chamadas"]],
                         ["domain/mariasilva.com.br", "domain/silva.com.br", "domain/maria.com.br"])
        instantes = [t for _, t in r["chamadas"]]
        self.assertTrue(all(b - a >= 2000 for a, b in zip(instantes, instantes[1:])), instantes)
        self.assertFalse([u for u in r["urls"] if "rdap" in u])
        for nome, cartao in zip(r["nomes"], r["cartoes"]):
            self.assertIn(f"<code>{nome}</code> está livre agora", cartao)

    def test_fora_do_indice_nunca_vira_nunca(self):
        # o indice de passagens so guarda quem passou 2 vezes ou mais: fora dele e
        # "no maximo uma vez", ou "a primeira vez" se a rodada de agora ja esta nele
        saida = self.node("""
globalThis.fetch = async (url) => {
  urls.push(String(url));
  if (String(url).endsWith('rodadas.json')) {
    return { ok: true, json: async () => ({ fatias: 256, rodadas: ['2017-09-13', '2026-08-12', '2026-09-09'] }) };
  }
  return { ok: true, status: 200, text: async () => 'outro.com.br\\t0,1\\n', json: async () => null };
};
const respostas = {
  'domain/livre.com.br': { status: 404, recurso: '', json: null },
  'domain/a.com.br': { status: 404, recurso: '', json: null },
  'domain/narodada.com.br': { status: 200, recurso: 'release-process-running;date=2026-09-16T18:00:00Z',
                              json: { objectClassName: 'domain', status: ['pending create'] } },
};
window.Disputa.consultar = async (c) => respostas[c];
const comBlocos = () => { const b = {}; return { dataset: {}, innerHTML: '',
  querySelector: (s) => (b[s] = b[s] || { innerHTML: '' }), blocos: b }; };
(async () => {
  const saida = {};
  for (const nome of ['livre.com.br', 'narodada.com.br', 'a.com.br']) {
    const a = comBlocos();
    await Ficha.conferir(nome, nome, a);
    for (let i = 0; i < 20; i += 1) await new Promise((r) => setImmediate(r));
    saida[nome] = a.blocos['.ficha-passagens'].innerHTML;
  }
  console.log(JSON.stringify(saida));
})();
""")
        r = json.loads(saida)
        self.assertIn("no máximo uma vez", r["livre.com.br"])
        self.assertIn("3 listas de que temos cópia, desde 2017", r["livre.com.br"])
        self.assertIn("primeira vez que ele aparece na lista", r["narodada.com.br"])
        # nome fora da regra (1 letra): "nao pode ser registrado", sem historico de rodadas
        self.assertEqual(r["a.com.br"], "")
        for texto in r.values():
            self.assertNotIn("nunca", texto.lower())

    def test_bloqueio_para_a_fila(self):
        # depois de um 429, disputa.js bloqueia por 5 min: os nomes que faltam nao sao consultados
        saida = self.node("""
(async () => {
  let n = 0;
  await SeuNome.conferirTodos(['a.com.br', 'b.com.br', 'c.com.br'], {
    conferir: async () => { n += 1; throw new Error('limite'); },
    aoErro: () => false });
  process.stdout.write(String(n));
})();
""")
        self.assertEqual(saida.strip(), "1")

    def test_nada_guardado_e_n_na_url(self):
        js = open(os.path.join(self.RAIZ, "site_modelo", "seu-nome.js"), encoding="utf-8").read()
        codigo = "\n".join(l for l in js.splitlines() if not l.strip().startswith(("*", "//", "/*")))
        for proibido in ("localStorage", "sessionStorage", "fetch(", "XMLHttpRequest", "sendBeacon", "cookie"):
            self.assertNotIn(proibido, codigo)
        self.assertIn("new URLSearchParams(location.search).get('n')", js)
        self.assertNotIn("location.hash", js)

    @so_com("site_modelo/conteudo/perguntas.html")
    def test_pagina(self):
        import exportar_site
        from garimpo.web import paginas
        modelo = os.path.join(self.RAIZ, "site_modelo")
        todas = paginas.carregar(modelo)
        pagina = next(p for p in todas if p.slug == "seu-nome")
        # ficha.js antes: seu-nome.js usa window.Ficha
        self.assertEqual(pagina.scripts, ("disputa.js", "agenda.js", "ficha.js", "seu-nome.js"))
        self.assertIn("seu-nome.js", exportar_site.ESTATICOS)
        self.assertTrue(os.path.exists(os.path.join(modelo, pagina.imagem)))
        self.assertIn('id="p-calendario"', pagina.corpo)
        self.assertIn("https://liberados.com.br/seu-nome/", paginas.sitemap(todas))
        self.assertIn("https://liberados.com.br/seu-nome/", paginas.llms_txt(todas))
        self.assertNotIn("processo de liberação", pagina.titulo_aba.lower())
        # o titulo de busca nao repete o de nenhuma outra pagina (mapa de intencoes)
        outros = {p.titulo_aba.lower() for p in todas if p.slug != "seu-nome"}
        self.assertNotIn(pagina.titulo_aba.lower(), outros)
        # nada comercial: nem o domínio de presente, nem revenda
        for proibido in ("presente", "revenda", "afiliado", "/onde-registrar"):
            self.assertNotIn(proibido, pagina.corpo.lower())

    def test_portas(self):
        ferramenta = open(os.path.join(self.RAIZ, "site_modelo", "conteudo", "ferramenta.html"),
                          encoding="utf-8").read()
        self.assertIn('href="/seu-nome/"', ferramenta)
        ramos = open(os.path.join(self.RAIZ, "garimpo", "web", "ramos.py"), encoding="utf-8").read()
        self.assertIn('href="/seu-nome/"', ramos)


@so_com("site_modelo/conteudo/quem-e-o-dono-do-dominio.html")
class TestQuemEODono(unittest.TestCase):
    """/quem-e-o-dono-do-dominio/ (19/09/2026, r3-quem-e-o-dono): a mesma ficha
    de /quando-volta/, sem consulta nova e sem dado pessoal alem do nome."""

    RAIZ = os.path.dirname(os.path.abspath(__file__))

    def test_pagina(self):
        from garimpo.web import paginas
        modelo = os.path.join(self.RAIZ, "site_modelo")
        todas = paginas.carregar(modelo)
        pagina = next(p for p in todas if p.slug == "quem-e-o-dono-do-dominio")
        # a ferramenta e a ficha: mesmos scripts, um formulario, calendario do build
        self.assertEqual(pagina.scripts, ("disputa.js", "agenda.js", "ficha.js"))
        self.assertEqual(pagina.corpo.count('id="ficha-form"'), 1)
        self.assertIn('id="p-calendario"', pagina.corpo)
        # nenhuma consulta propria ao RDAP e nada de representante legal
        for proibido in ("rdap.registro.br", "legalRepresentative", "<script>", "style="):
            self.assertNotIn(proibido, pagina.corpo)
        # FAQPage com as oito perguntas, cada uma com resposta curta
        self.assertEqual(pagina.corpo.count('<div class="pergunta">'), 8)
        self.assertEqual(pagina.corpo.count('class="resposta-curta"'), 8)
        self.assertIn("https://liberados.com.br/quem-e-o-dono-do-dominio/", paginas.sitemap(todas))
        self.assertIn("https://liberados.com.br/quem-e-o-dono-do-dominio/", paginas.llms_txt(todas))
        self.assertNotIn("processo de liberação", pagina.titulo_aba.lower())
        outros = {p.titulo_aba.lower() for p in todas if p.slug != pagina.slug}
        self.assertNotIn(pagina.titulo_aba.lower(), outros)
        # a pergunta de comprar vira ponteiro para ca (sem canibalizar)
        comprar = next(p for p in todas if p.slug == "comprar-dominio-que-ja-tem-dono")
        self.assertIn('href="/quem-e-o-dono-do-dominio/"', comprar.corpo)

    def test_link_da_estimativa_vale_fora_da_quando_volta(self):
        # a ficha roda em outras paginas: ancora relativa quebraria aqui
        js = open(os.path.join(self.RAIZ, "site_modelo", "ficha.js"), encoding="utf-8").read()
        self.assertNotIn('href="#quanto-tempo"', js)
        self.assertIn('href="/quando-volta/#quanto-tempo"', js)


class TestDisputa(unittest.TestCase):
    """Quem disputa (web/disputa.js): 429 com pausa de 5 min, /entity/ a parte, trocar de nome no meio da carga."""

    RAIZ = os.path.dirname(__file__)

    def node(self, roteiro, respostas=None, extra=""):
        import shutil
        node = shutil.which("node")
        if not node:
            self.skipTest("sem node")
        # DOM minimo: um <dialog> unico com os ids fixos que disputa.js usa
        # (nunca um parser de HTML de verdade: o innerHTML do template e
        # ignorado, e cada id vira um elemento a parte, pre-criado).
        preparo = """
const vm = require('vm');
const fs = require('fs');
const chamadas = [];
const respostas = RESPOSTAS;
function elFactory() {
  const listeners = {};
  return {
    _text: '', _html: '', hidden: false, disabled: false, className: '',
    get textContent() { return this._text; }, set textContent(v) { this._text = v; },
    get innerHTML() { return this._html; }, set innerHTML(v) { this._html = v; },
    setAttribute() {},
    addEventListener(ev, fn) { (listeners[ev] = listeners[ev] || []).push(fn); },
  };
}
let dlg = null;
function makeDialog() {
  const elems = {};
  ['disputa-titulo', 'disputa-resumo', 'disputa-caixa', 'disputa-corpo', 'disputa-status', 'disputa-mais', 'disputa-fechar']
    .forEach((id) => { elems[id] = elFactory(); });
  const d = elFactory();
  d.open = false;
  d.showModal = function () { this.open = true; };
  d.close = function () { this.open = false; };
  d.querySelector = (sel) => { const m = /^#([\\w-]+)$/.exec(sel); return m ? elems[m[1]] : null; };
  return d;
}
const doc = {
  createElement(tag) { if (tag === 'dialog') { dlg = makeDialog(); return dlg; } return elFactory(); },
  body: { appendChild() {} },
  addEventListener() {},
};
const ctx = {
  console, Promise, Map, Set, String, Date, Array, Object, JSON, Math,
  encodeURIComponent, decodeURIComponent,
  // PAUSA real (2,5 s) viraria um teste lento sem mudar o que se prova aqui
  setTimeout: (fn, ms) => setTimeout(fn, ms > 20 ? 3 : ms), clearTimeout,
  document: doc,
  fetch: async (url) => {
    chamadas.push(url);
    const caminho = url.replace('https://rdap.registro.br/', '');
    const def = respostas[caminho];
    if (!def) return { status: 404, ok: false, headers: { get: () => null }, json: async () => null };
    const [status, cabecalhos, corpo] = def;
    return {
      status, ok: status >= 200 && status < 300,
      headers: { get: (k) => (cabecalhos && cabecalhos[(k || '').toLowerCase()]) || null },
      json: async () => corpo,
    };
  },
};
ctx.window = ctx;
vm.createContext(ctx);
vm.runInContext(fs.readFileSync(ARQUIVO, 'utf8'), ctx);
vm.runInContext(EXTRA, ctx);
const D = ctx.Disputa;
// funcoes extras (de outro arquivo, ex. consultarRdap do app.js) rodam
// DENTRO do contexto sandboxado tambem, para 'window' resolver la: expostas
// aqui so como atalho para o roteiro do teste (que roda no node de fora).
const consultarRdap = ctx.consultarRdap;
const dialogo = () => dlg;
const esperarAte = async (pred, tentativas) => {
  for (let i = 0; i < (tentativas || 400); i++) {
    if (pred()) return true;
    await new Promise((r) => setTimeout(r, 3));
  }
  return false;
};
(async () => {
""".replace("ARQUIVO", json.dumps(os.path.join(self.RAIZ, "web", "disputa.js")))
        preparo = preparo.replace("RESPOSTAS", json.dumps(respostas or {})).replace("EXTRA", json.dumps(extra))
        p = subprocess.run([node, "-e", preparo + roteiro + "\n})();"], capture_output=True, text=True)
        if p.returncode != 0:
            self.fail(p.stderr)
        return json.loads(p.stdout)

    def test_429_no_domain_bloqueia_5_min_e_e_a_mesma_mensagem_da_conferencia(self):
        # o1, criterio 3: um 429 no /domain/ (aqui, o de "quem disputa") bloqueia
        # tambem consultarRdap (app.js), que usa a mesma window.Disputa.consultar
        app_js = open(os.path.join(self.RAIZ, "site_modelo", "app.js"), encoding="utf-8").read()
        consultar_rdap = re.search(r"async function consultarRdap\(dominio\) \{.*?\n\}", app_js, re.S).group(0)
        respostas = {
            "domain/a.com.br": [429, {"nicbr-rate-limit-exceeded": "true"}, None],
            "domain/b.com.br": [200, {"nicbr-resource": ""}, {"objectClassName": "domain", "status": ["active"]}],
        }
        r = self.node("""
let erro1 = null;
try { await D.consultar('domain/a.com.br'); } catch (e) { erro1 = e.message; }
let erro2 = null;
try { await consultarRdap('b.com.br'); } catch (e) { erro2 = e.message; }
process.stdout.write(JSON.stringify({
  erro1, erro2, bloqueado: D.bloqueado(), mensagem: D.mensagemBloqueio(), chamadas,
}));
""", respostas, extra=consultar_rdap)
        self.assertEqual(r["erro1"], "Não deu para conferir agora; tente de novo em 5 min.")
        self.assertEqual(r["erro2"], r["erro1"])          # mesma mensagem em consultarRdap
        self.assertEqual(r["mensagem"], r["erro1"])
        self.assertTrue(r["bloqueado"])
        # a 2a chamada nem saiu: nenhuma consulta nova ao RDAP durante o bloqueio
        self.assertEqual(r["chamadas"], ["https://rdap.registro.br/domain/a.com.br"])

    def test_429_no_entity_nao_bloqueia_o_domain_e_pula_so_o_resto_do_lote(self):
        # F-bug de 18/09: um 429 no /entity/ (de UM candidato CNPJ) esvaziava a
        # lista inteira e travava os tickets seguintes. Doc1 e cnpj (429 na
        # entidade), doc2 tambem e cnpj (a entidade dele tem de ser pulada,
        # sem tentar), doc3 e cpf (nunca pede /entity/).
        respostas = {
            "domain/x.com.br": [200, {}, {"publicIds": [
                {"type": "ticket", "identifier": "1"}, {"type": "ticket", "identifier": "2"},
                {"type": "ticket", "identifier": "3"}]}],
            "domain/x.com.br?ticket=1": [200, {}, {
                "entities": [{"roles": ["registrant"], "publicIds": [{"type": "cnpj", "identifier": "11.111.111/0001-11"}],
                             "vcardArray": ["vcard", [["fn", {}, "text", "Empresa Um"]]]}],
                "events": [{"eventAction": "registration", "eventDate": "2026-09-01T00:00:00Z"}]}],
            "entity/11111111000111": [429, {"nicbr-rate-limit-exceeded": "true"}, None],
            "domain/x.com.br?ticket=2": [200, {}, {
                "entities": [{"roles": ["registrant"], "publicIds": [{"type": "cnpj", "identifier": "22.222.222/0001-22"}],
                             "vcardArray": ["vcard", [["fn", {}, "text", "Empresa Dois"]]]}],
                "events": [{"eventAction": "registration", "eventDate": "2026-09-02T00:00:00Z"}]}],
            "entity/22222222000122": [200, {}, {"nicbr_domainCount": 9}],   # nunca deveria ser chamado
            "domain/x.com.br?ticket=3": [200, {}, {
                "entities": [{"roles": ["registrant"], "publicIds": [{"type": "cpf", "identifier": "123.***.***-00"}],
                             "vcardArray": ["vcard", [["fn", {}, "text", "Fulano De Tal"]]]}],
                "events": [{"eventAction": "registration", "eventDate": "2026-09-03T00:00:00Z"}]}],
        }
        r = self.node("""
D.abrir('x.com.br');
await esperarAte(() => dialogo().querySelector('#disputa-status').textContent.endsWith('lidos.'));
process.stdout.write(JSON.stringify({
  status: dialogo().querySelector('#disputa-status').textContent,
  corpo: dialogo().querySelector('#disputa-corpo').innerHTML,
  chamadas, bloqueado: D.bloqueado(),
}));
""", respostas)
        self.assertEqual(r["status"], "todos lidos.")     # os 3 tickets, nao so o 1o
        for esperado in ("Empresa Um", "Empresa Dois", "Fulano De Tal"):
            self.assertIn(esperado, r["corpo"])
        self.assertNotIn("…", r["corpo"])                 # nenhuma linha ficou pendente
        self.assertIn("https://rdap.registro.br/entity/11111111000111", r["chamadas"])
        # a entidade do ticket 2 foi pulada: so uma consulta a /entity/ no lote
        self.assertNotIn("https://rdap.registro.br/entity/22222222000122", r["chamadas"])
        self.assertEqual(sum(1 for c in r["chamadas"] if "/entity/" in c), 1)
        # um 429 so no /entity/ (endpoint bem mais restrito) nao bloqueia o /domain/
        self.assertFalse(r["bloqueado"])

    def test_trocar_de_nome_durante_a_carga_mostra_so_o_segundo(self):
        # F-bug de 18/09: abrir b.com.br enquanto a.com.br ainda carregava
        # pintava os candidatos de a por cima do titulo de b, e b nunca
        # carregava. abrir() e sincrono ate o 1o await de carregar(), entao
        # duas chamadas seguidas (sem esperar) reproduzem a corrida de
        # verdade: quando a 2a roda, ocupado ja esta true por causa da 1a.
        respostas = {
            "domain/a.com.br": [200, {}, {"publicIds": [{"type": "ticket", "identifier": "1"}]}],
            "domain/a.com.br?ticket=1": [200, {}, {
                "entities": [{"roles": ["registrant"], "publicIds": [{"type": "cpf", "identifier": "1.***-00"}],
                             "vcardArray": ["vcard", [["fn", {}, "text", "Nao Deveria Aparecer"]]]}]}],
            "domain/b.com.br": [200, {}, {"publicIds": []}],
        }
        r = self.node("""
D.abrir('a.com.br');
D.abrir('b.com.br');
await esperarAte(() => /nenhum ticket/.test(dialogo().querySelector('#disputa-status').textContent));
process.stdout.write(JSON.stringify({
  titulo: dialogo().querySelector('#disputa-titulo').textContent,
  status: dialogo().querySelector('#disputa-status').textContent,
  corpo: dialogo().querySelector('#disputa-corpo').innerHTML,
  chamadas,
}));
""", respostas)
        self.assertEqual(r["titulo"], "Quem disputa b.com.br")
        self.assertEqual(r["status"], "nenhum ticket visível para este nome.")
        self.assertNotIn("Nao Deveria Aparecer", r["corpo"])
        self.assertIn("https://rdap.registro.br/domain/a.com.br", r["chamadas"])
        self.assertIn("https://rdap.registro.br/domain/b.com.br", r["chamadas"])
        # a corrida corta a.com.br assim que b.com.br e aberto: nunca busca o ticket dele
        self.assertNotIn("https://rdap.registro.br/domain/a.com.br?ticket=1", r["chamadas"])

    # 19/09/2026, cagada.com.br: a lista dizia "pedido pendente, 1 candidato"
    # (leitura de 3 dias antes); o painel dizia "nenhum ticket visivel" e
    # mostrava "carregar mais 0". A resposta registrada e a real daquele dia.
    ROTEIRO_ABRIR = """
D.abrir(NOME, 'há 3 d');
await esperarAte(() => /\\.$/.test(dialogo().querySelector('#disputa-status').textContent));
const q = (id) => dialogo().querySelector('#' + id);
process.stdout.write(JSON.stringify({
  status: q('disputa-status').textContent, resumo: q('disputa-resumo').textContent,
  corpo: q('disputa-corpo').innerHTML, caixaOculta: q('disputa-caixa').hidden,
  maisOculto: q('disputa-mais').hidden, mais: q('disputa-mais').textContent, chamadas,
}));
"""

    def abrir(self, nome, respostas):
        return self.node(self.ROTEIRO_ABRIR.replace("NOME", json.dumps(nome)), respostas)

    def test_registrado_sem_ticket_explica_com_a_data_do_registro(self):
        r = self.abrir("cagada.com.br", {"domain/cagada.com.br": [200, {}, {
            "objectClassName": "domain", "ldhName": "cagada.com.br",
            "events": [{"eventAction": "registration", "eventDate": "2026-09-16T18:23:14Z"}],
            "entities": [{"roles": ["registrant"]}, {"roles": ["technical"]}]}]})
        self.assertEqual(r["status"], "Este nome já está registrado (o RDAP dá 16/09/2026, 15:23 como data "
                                      "do registro) e o RDAP não lista mais o ticket do pedido. O número da lista "
                                      "é de uma leitura feita há 3 d.")
        self.assertTrue(r["maisOculto"])
        self.assertNotIn("carregar mais 0", r["mais"])
        self.assertTrue(r["caixaOculta"])                 # sem tabela so com cabecalho
        self.assertEqual(r["chamadas"], ["https://rdap.registro.br/domain/cagada.com.br"])

    def test_pedido_pendente_mostra_o_candidato(self):
        r = self.abrir("p.com.br", {
            "domain/p.com.br": [200, {}, {"objectClassName": "domain", "status": ["pending create"],
                                          "publicIds": [{"type": "ticket", "identifier": "32300001"}]}],
            "domain/p.com.br?ticket=32300001": [200, {}, {
                "entities": [{"roles": ["registrant"], "publicIds": [{"type": "cpf", "identifier": "123.***.***-00"}],
                             "vcardArray": ["vcard", [["fn", {}, "text", "Fulano Exemplo"]]]}],
                "events": [{"eventAction": "registration", "eventDate": "2026-09-16T17:00:00Z"}]}],
        })
        self.assertEqual(r["status"], "todos lidos.")
        self.assertIn("Fulano Exemplo", r["corpo"])
        self.assertFalse(r["caixaOculta"])
        self.assertTrue(r["maisOculto"])
        # pedido comum: o ticket unico aparece, entao a frase da rodada nao cabe
        self.assertEqual(r["resumo"], "1 ticket visível, do primeiro ao último.")

    def test_404_diz_que_esta_livre(self):
        r = self.abrir("sumiu.com.br", {})
        self.assertTrue(r["status"].startswith("Este nome está livre agora"))
        self.assertIn("leitura feita há 3 d", r["status"])
        self.assertTrue(r["maisOculto"])

    def test_travado_e_rodada_sem_ticket(self):
        r = self.abrir("t.com.br", {"domain/t.com.br": [200, {"nicbr-resource": "release-process-waiting"},
                                                        {"objectClassName": "domain"}]})
        self.assertTrue(r["status"].startswith("Este nome travou e espera a próxima rodada"))
        r = self.abrir("r.com.br", {"domain/r.com.br": [200, {"nicbr-resource": "release-process-running;date=x"},
                                                        {"objectClassName": "domain", "status": ["pending create"]}]})
        self.assertIn("zero aqui pode ser um", r["status"])

    def test_carregar_mais_escondido_vence_o_css(self):
        # .conferir (extra.css) e inline-block e vencia o [hidden] do navegador
        css = open(os.path.join(self.RAIZ, "web", "style.css"), encoding="utf-8").read()
        self.assertIn(".dialogo-disputa [hidden] { display: none; }", css)

    def test_contagem_da_lista_leva_a_idade_da_leitura(self):
        js = open(os.path.join(self.RAIZ, "site_modelo", "app.js"), encoding="utf-8").read()
        funcao = re.search(r"function competindo\(it\) \{.*?\n\}", js, re.S).group(0)
        # todo numero de candidatos (0, >=2 e n) sai com a idade ao lado
        self.assertEqual(funcao.count("${idade}") + funcao.count(") + idade;"), 4)
        self.assertIn("'1 candidato'", funcao)
        self.assertIn(".idade-contagem", open(os.path.join(self.RAIZ, "site_modelo", "extra.css"), encoding="utf-8").read())


class TestPontoCom(unittest.TestCase):
    """O .com do mesmo nome (web/pontocom.js, 15/09/2026): interruptor, lote e ficha, tudo no navegador."""

    RAIZ = os.path.dirname(__file__)
    # respostas reais de 15/09/2026, so com os campos que o modulo le (e, no
    # titular, com e-mail e telefone de proposito: nao podem sair)
    VERISIGN = {
        "objectClassName": "domain", "ldhName": "VACINA.COM",
        "links": [{"rel": "self", "href": "https://rdap.verisign.com/com/v1/domain/vacina.com"},
                  {"rel": "related", "href": "https://rdap.godaddy.com/v1/domain/VACINA.COM"}],
        "status": ["client delete prohibited", "client renew prohibited",
                   "client transfer prohibited", "client update prohibited"],
        "events": [{"eventAction": "registration", "eventDate": "2002-05-13T18:30:01Z"},
                   {"eventAction": "expiration", "eventDate": "2027-05-13T18:30:01Z"},
                   {"eventAction": "last changed", "eventDate": "2026-04-15T14:41:40Z"}],
        "entities": [{"objectClassName": "entity", "roles": ["registrar"],
                      "publicIds": [{"type": "IANA Registrar ID", "identifier": "146"}],
                      "vcardArray": ["vcard", [["version", {}, "text", "4.0"],
                                               ["fn", {}, "text", "GoDaddy.com, LLC"]]]}],
        "nameservers": [{"ldhName": "DAMAO.NS.GIANTPANDA.COM"}, {"ldhName": "YANGGUANG.NS.GIANTPANDA.COM"}],
    }
    PRIVADO = {"entities": [{"roles": ["registrant"], "vcardArray": ["vcard", [
        ["fn", {}, "text", "Registration Private"], ["org", {}, "text", "Domains By Proxy, LLC"],
        ["adr", {"cc": "US"}, "text", ["", "", "", "Tempe", "Arizona", "85281", ""]],
        ["tel", {"type": "voice"}, "uri", "tel:+1.4806242599"]]]}]}
    AMAZON = {"entities": [{"roles": ["registrant"], "vcardArray": ["vcard", [
        ["fn", {}, "text", "Hostmaster, Amazon Legal Dept."], ["org", {}, "text", "Amazon Technologies, Inc."],
        ["adr", {}, "text", ["P.O. Box 8102", "", "", "Reno", "NV", "89507", "US"]],
        ["email", {}, "text", "hostmaster@amazon.com"], ["tel", {}, "uri", "tel:+1.2062664064"]]]}]}
    HUGE = {"entities": [{"roles": ["registrant"], "vcardArray": ["vcard", [
        ["fn", {}, "text", "Domain Admin / This Domain is For Sale"], ["org", {}, "text", "HugeDomains.com"]]]}]}

    def js(self):
        return open(os.path.join(self.RAIZ, "web", "pontocom.js"), encoding="utf-8").read()

    def node(self, roteiro, respostas=None, pilulas=None):
        import shutil
        node = shutil.which("node")
        if not node:
            self.skipTest("sem node")
        # o modulo roda num contexto com o minimo de navegador: fetch de
        # mentira (respostas por URL, e conta as chamadas), DOM vazio, sem
        # localStorage (como numa aba que o bloqueia). `pilulas` (fqdns do
        # .com) simula quem esta na tela para [data-com]; o roteiro dispara
        # o MutationObserver de verdade chamando `disparar()`.
        preparo = """
const vm = require('vm');
const fs = require('fs');
const chamadas = [];
const classes = [];
const respostas = RESPOSTAS;
const pilulas = PILULAS.map((f) => ({ dataset: { com: f }, nodeType: 1,
  matches: (sel) => sel === '[data-com]', querySelector: () => null }));
let observador = null;
const disparar = () => observador && observador([{ addedNodes: pilulas }]);
const ctx = {
  URL, Promise, Map, Set, String, Date, Array, Object, JSON, Math, Intl, console, setTimeout, clearTimeout,
  CSS: { escape: (s) => s },
  MutationObserver: class { constructor(cb) { observador = cb; } observe() {} },
  document: {
    addEventListener() {},
    querySelectorAll: (sel) => sel === '[data-com]' ? pilulas : [],
    querySelector: () => null, activeElement: null,
    createElement: () => ({ setAttribute() {}, addEventListener() {} }),
    documentElement: { classList: { toggle: (c, v) => classes.push([c, v]) } },
    body: { appendChild() {} },
  },
  fetch: async (url) => {
    chamadas.push(url);
    const nome = url.split('/').pop().toLowerCase();
    const [status, json] = respostas[nome] || [404, null];
    return { status, json: async () => json };
  },
};
ctx.window = ctx;
vm.createContext(ctx);
vm.runInContext(fs.readFileSync(ARQUIVO, 'utf8'), ctx);
const P = ctx.PontoCom;
(async () => {
""".replace("ARQUIVO", json.dumps(os.path.join(self.RAIZ, "web", "pontocom.js")))
        preparo = preparo.replace("RESPOSTAS", json.dumps(respostas or {})).replace("PILULAS", json.dumps(pilulas or []))
        saida = subprocess.run([node, "-e", preparo + roteiro + "\n})();"],
                               capture_output=True, text=True, check=True).stdout
        return json.loads(saida)

    def test_rotulo_serve_para_toda_extensao_br(self):
        r = self.node("process.stdout.write(JSON.stringify(['vacina.com.br', 'Vacina.app.br', "
                      "'nome.sorocaba.br', 'café.com.br', '-x.com.br', '', 'a_b.com.br'].map(P.rotulo)));")
        self.assertEqual(r, ["vacina", "vacina", "nome", "xn--caf-dma", "", "", ""])

    def test_ler_a_resposta_da_verisign(self):
        venda = dict(self.VERISIGN, nameservers=[{"ldhName": "NS1.AFTERNIC.COM"}])
        caindo = dict(venda, status=["redemption period"])
        parado = dict(self.VERISIGN, nameservers=[{"ldhName": "NS1.PARKINGCREW.NET"}])
        r = self.node(f"""
process.stdout.write(JSON.stringify([
  P.ler(404, null), P.ler(200, {json.dumps(self.VERISIGN)}), P.ler(200, {json.dumps(venda)}),
  P.ler(200, {json.dumps(caindo)}).estado, P.ler(200, {{ objectClassName: 'error' }}).estado,
  P.ler(200, {json.dumps(parado)}),
]));""")
        self.assertEqual(r[0], {"estado": "livre"})
        self.assertEqual(r[1], {
            "estado": "com_dono", "desde": "2002-05-13T18:30:01Z", "expira": "2027-05-13T18:30:01Z",
            "alterado": "2026-04-15T14:41:40Z", "registrador": "GoDaddy.com, LLC", "iana": "146",
            "situacoes": self.VERISIGN["status"],
            "servidores": ["damao.ns.giantpanda.com", "yangguang.ns.giantpanda.com"],
            "vitrine": "", "estacionamento": "",
            "ficha": "https://rdap.godaddy.com/v1/domain/VACINA.COM"})
        self.assertEqual((r[2]["estado"], r[2]["vitrine"]), ("a_venda", "Afternic"))
        # vencido manda mais que vitrine: o nome esta caindo
        self.assertEqual(r[3], "caindo")
        self.assertEqual(r[4], "erro")
        # estacionamento nao e venda: continua "tem dono"
        self.assertEqual((r[5]["estado"], r[5]["estacionamento"]), ("com_dono", "ParkingCrew"))

    def test_dono_so_nome_organizacao_e_pais(self):
        r = self.node(f"""
process.stdout.write(JSON.stringify([
  P.lerTitular({json.dumps(self.PRIVADO)}), P.lerTitular({json.dumps(self.AMAZON)}),
  P.lerTitular({json.dumps(self.HUGE)}), P.lerTitular({{ entities: [] }}),
]));""")
        self.assertEqual(r[0], {"encontrado": True, "nome": "", "organizacao": "Domains By Proxy, LLC",
                                "pais": "US", "oculto": True, "aVenda": False})
        self.assertEqual(r[1], {"encontrado": True, "nome": "Hostmaster, Amazon Legal Dept.",
                                "organizacao": "Amazon Technologies, Inc.", "pais": "US",
                                "oculto": False, "aVenda": False})
        self.assertTrue(r[2]["aVenda"])
        self.assertFalse(r[3]["encontrado"])
        saida = json.dumps(r)
        for proibido in ("hostmaster@amazon.com", "4806242599", "2062664064", "Reno", "Tempe", "85281"):
            self.assertNotIn(proibido, saida)

    def test_so_consulta_registrador_da_lista(self):
        r = self.node("""process.stdout.write(JSON.stringify([
  'https://rdap.godaddy.com/v1/domain/X.COM', 'https://dreamhost.rdap.tucows.com/domain/x.com',
  'https://rdap.godaddy.com.mal.example/v1/domain/x.com', 'http://rdap.godaddy.com/v1/domain/x.com',
  'https://rdap.hosting.kr/domain/x.com', 'nao e url',
].map(P.permitido)));""")
        self.assertEqual(r, [True, True, False, False, False, False])

    def test_travas_em_portugues(self):
        r = self.node("""process.stdout.write(JSON.stringify([
  P.travas(['client transfer prohibited', 'client delete prohibited']),
  P.travas(['server delete prohibited', 'server transfer prohibited']),
  P.travas(['redemption period']), P.travas(['active']),
]));""")
        self.assertEqual(r[0], ["travas comuns do registrador contra transferência sem autorização"])
        self.assertEqual(r[1], ["travado pelo próprio registro do .com"])
        self.assertIn("prazo de resgate", r[2][0])
        self.assertEqual(r[3], ["ativo, sem travas"])

    def test_lote_uma_consulta_por_nome_para_no_429_e_resume(self):
        respostas = {"vacina.com": [200, self.VERISIGN], "cheio.com": [429, None],
                     "venda.com": [200, dict(self.VERISIGN, nameservers=[{"ldhName": "ns1.afternic.com"}])]}
        r = self.node("""
const primeiro = await P.conferirLote(['vacina.com', 'livre.com', 'vacina.com', 'venda.com']);
const texto = P.textoDoResumo(P.resumo(['vacina.com', 'livre.com', 'venda.com']));
chamadas.length = 0;
const segundo = await P.conferirLote(['vacina.com', 'cheio.com', 'a.com', 'b.com', 'c.com', 'd.com']);
process.stdout.write(JSON.stringify({ primeiro, texto, segundo, chamadas,
  pilula: P.botao('vacina.app.br'), livre: P.botao('livre.com.br'), desligado: classes }));""", respostas)
        self.assertEqual(r["primeiro"], {"total": 3, "feitos": 3, "parou": "", "cancelado": False})
        self.assertEqual(r["texto"], "3 nomes conferidos: 1 com .com livre (livre.com); 1 parece à venda.")
        # o que ja estava no cache nao e consultado de novo; o 429 para o lote
        self.assertNotIn("https://rdap.verisign.com/com/v1/domain/vacina.com", r["chamadas"])
        self.assertTrue(r["segundo"]["parou"].startswith("o registro do .com pediu uma pausa"))
        self.assertLess(len(r["chamadas"]), 5)
        self.assertIn(".com tem dono", r["pilula"])
        self.assertIn('data-com="vacina.com"', r["pilula"])
        self.assertIn("pontocom-livre", r["livre"])
        # sem nada guardado, o interruptor nasce desligado
        self.assertEqual(r["desligado"], [["com-ligado", False]])

    def test_erro_nao_vira_laco_pelo_observer(self):
        # F7, achado de 18/09/2026 (harness em work/revisao/js-bugs/harness_pontocom.html,
        # 6 pilulas: 10 consultas/s sem fim). Erro na Verisign (ou rede caida)
        # repinta a pilula, o MutationObserver acorda -- e antes do hotfix
        # isso reconsultava o lote inteiro sem fim, nome a nome (PARALELO=2
        # e menor que o lote, entao o resto nunca tentado reaparecia em
        # "faltam" a cada disparo). O observer nunca deve refazer nem quem
        # deu erro nem o resto do lote que parou nele; so alternar() (acao
        # explicita) refaz.
        nomes = ["a.com", "b.com", "c.com", "d.com", "e.com", "f.com"]
        respostas = {n: [500, None] for n in nomes}
        r = self.node("""
P.alternar();                       // liga: 1o lote, para no 1o erro (PARALELO=2)
await new Promise((r) => setTimeout(r, 200));
const depoisDeLigar = chamadas.length;
disparar(); disparar(); disparar(); // observer acordando repetido (repintar em laco)
await new Promise((r) => setTimeout(r, 500));
const depoisDoObservador = chamadas.length;
P.alternar(); P.alternar();         // desliga e religa: acao explicita
await new Promise((r) => setTimeout(r, 200));
const depoisDeReligar = chamadas.length;
process.stdout.write(JSON.stringify({ depoisDeLigar, depoisDoObservador, depoisDeReligar }));
""", respostas, pilulas=nomes)
        self.assertEqual(r["depoisDeLigar"], 2)
        # o observer nao reconsulta quem deu erro nem o resto do lote que parou: nenhuma chamada nova
        self.assertEqual(r["depoisDoObservador"], 2)
        # religar e uma acao de quem olha: reconsulta (novo lote, para de novo no 1o erro)
        self.assertEqual(r["depoisDeReligar"], 4)

    def test_toda_origem_consultada_esta_na_csp(self):
        js = self.js()
        origens = set(re.findall(r"'(https://[^'/]+)", re.search(r"const REGISTRADORES = \[(.*?)\];", js, re.S).group(1)))
        origens.add(re.search(r"const REGISTRO = '(https://[^/']+)/", js).group(1))
        self.assertGreater(len(origens), 20)
        import exportar_site
        texto = open(os.path.join(self.RAIZ, "site_modelo", "_headers"), encoding="utf-8").read()
        csp = next(v for _, cabs in exportar_site.ler_cabecalhos(texto) for n, v in cabs
                   if n.lower() == "content-security-policy")
        connect = set(re.search(r"connect-src ([^;]*)", csp).group(1).split())
        self.assertLessEqual(origens, connect)

    def test_nunca_le_contato_do_dono(self):
        codigo = "\n".join(l for l in self.js().splitlines() if not l.strip().startswith(("*", "//", "/*")))
        for proibido in ("'email'", "'tel'", "legalRepresentative", "publicIds.find((p) => p.type === 'cpf"):
            self.assertNotIn(proibido, codigo)
        # do adr so sai o codigo do pais
        titular = codigo[codigo.index("function lerTitular"):codigo.index("function travas")]
        self.assertNotRegex(titular, r"adr\[3\]\[[0-5]\]")

    def test_interruptor_na_lista_e_no_app_local(self):
        from garimpo.web import paginas
        modelo = os.path.join(self.RAIZ, "site_modelo")
        ferramenta = next(p for p in paginas.carregar(modelo) if p.tipo == "ferramenta")
        self.assertIn("pontocom.js", ferramenta.scripts)
        self.assertLess(ferramenta.scripts.index("pontocom.js"), ferramenta.scripts.index("app.js"))
        import exportar_site
        self.assertIn("pontocom.js", exportar_site.COMPARTILHADOS)
        for pagina in (os.path.join(modelo, "conteudo", "ferramenta.html"), os.path.join(self.RAIZ, "web", "index.html")):
            html = open(pagina, encoding="utf-8").read()
            self.assertRegex(html, r'data-pontocom-alternar aria-pressed="false"')
            self.assertIn("data-pontocom-status", html)
        self.assertIn('src="/static/pontocom.js"', open(os.path.join(self.RAIZ, "web", "index.html"), encoding="utf-8").read())
        for app in (("site_modelo", "app.js"), ("web", "app.js")):
            self.assertIn("window.PontoCom.botao(", open(os.path.join(self.RAIZ, *app), encoding="utf-8").read())
        css = open(os.path.join(self.RAIZ, "web", "style.css"), encoding="utf-8").read()
        self.assertIn(":root:not(.com-ligado) .pontocom { display: none; }", css)


@so_com("site_modelo/imagens/letras")
class TestPaginasDasLetras(unittest.TestCase):
    """/insights/dominios-de-uma-letra/<letra>-com-br/: 26 paginas, 8 indexaveis."""

    MODELO = os.path.join(os.path.dirname(__file__), "site_modelo")

    def test_vinte_e_seis_com_oito_indexaveis(self):
        from garimpo.web import letras, paginas
        lista = [paginas.Pagina(**c) for c in letras.paginas(self.MODELO)]
        self.assertEqual(len(lista), 26)
        self.assertEqual("".join(p.slug[-8] for p in lista if p.indexavel), "behnpsxz")
        for p in lista:
            self.assertTrue(p.slug.startswith("insights/dominios-de-uma-letra/"))
            self.assertLessEqual(len(p.descricao), 160)
            self.assertNotEqual(p.tipo, "artigo")          # fora do indice de insights
            self.assertIn('aria-current="page"', p.corpo)  # a faixa das 26 letras
        mapa = paginas.sitemap(lista, "https://ex.br")
        self.assertIn("/x-com-br/", mapa)
        self.assertNotIn("/a-com-br/", mapa)
        self.assertNotIn("/a-com-br/", paginas.llms_full_txt(lista, {}, "https://ex.br"))
        self.assertIn('href="/insights/" aria-current="page"', paginas.navegacao(lista[0]))
        # so as cinco que existem consultam o dono no navegador
        self.assertEqual("".join(p.slug[-8] for p in lista if "letra.js" in p.scripts), "bensx")

    def test_toda_tela_existe_e_tem_tamanho(self):
        from garimpo.web import letras
        usadas = set()
        for c in letras.paginas(self.MODELO):
            for img in re.findall(r"<img [^>]*>", c["corpo"]):
                src = re.search(r'src="/imagens/letras/([^"]+)"', img).group(1)
                self.assertTrue(os.path.exists(os.path.join(self.MODELO, "imagens", "letras", src)), src)
                for attr in ("width=", "height=", "alt=", 'loading="lazy"'):
                    self.assertIn(attr, img)
                usadas.add(src)
        self.assertEqual(usadas, set(os.listdir(os.path.join(self.MODELO, "imagens", "letras"))))

    def test_letra_js_nunca_le_dado_pessoal_alem_do_nome(self):
        js = open(os.path.join(self.MODELO, "letra.js"), encoding="utf-8").read()
        codigo = "\n".join(l for l in js.splitlines() if not l.strip().startswith(("*", "//", "/*")))
        for proibido in ("legalRepresentative", "publicIds", "email", "adr", "innerHTML = nome"):
            self.assertNotIn(proibido, codigo)
        self.assertIn("letra.js", open(os.path.join(os.path.dirname(__file__), "exportar_site.py"), encoding="utf-8").read())


class TestInicioEntreRodadas(unittest.TestCase):
    """A pagina inicial leva o calendario e o cartao de quem volta na proxima."""

    def test_calendario_e_cartao_na_ferramenta(self):
        from garimpo.web import paginas
        modelo = os.path.join(os.path.dirname(__file__), "site_modelo")
        inicio = next(p for p in paginas.carregar(modelo) if p.slug == "")
        self.assertIn("agenda.js", inicio.scripts)
        layout = open(os.path.join(modelo, "layout.html"), encoding="utf-8").read()
        dados = {"gerado_em": "2026-09-17T12:00:00+00:00", "itens": [],
                 "rodada": {"inicio": "2026-09-09T15:00:00-03:00", "fim": "2026-09-16T15:00:00-03:00"}}
        html = paginas.render(inicio, layout, dados)
        cal = json.loads(re.search(r'id="p-calendario">(.*?)</script>', html).group(1))
        self.assertIn("2026-10-14", cal["aberturas"])
        self.assertIn('data-filtro="aguardando"', html)
        self.assertIn('id="lembrar-rodada"', html)
        # o script de tema continua sendo o primeiro <script> sem atributo (hash da CSP)
        self.assertIn("localStorage", re.search(r"<script>(.*?)</script>", html, re.S).group(1))


class TestPaginasPorRamo(unittest.TestCase):
    """/dominios/<ramo>/: texto pela fase, marca fora, pagina rala com noindex."""

    STATUS = ["LIBERACAO_LIVRE", "LIBERACAO_DISPUTADA", "COMPETITIVO", "LIVRE",
              "REGISTRADO", "AGUARDANDO_LIBERACAO", "INDISPONIVEL", "LIVRE_COM_TICKET"]

    def dados(self, gerado, n_pet=12):
        cats = [{"nome": "pet", "rotulo": "Pet"}, {"nome": "saude", "rotulo": "Saúde"}]
        itens = []
        for i in range(n_pet):
            itens.append([f"pet{i:02d}.com.br", 0, 0, 60 - i, 0, [], 0, 0, 0, 0, 1, 0, 0])
        itens.append(["petdisputa.com.br", 1, 3, 90, 0, [], 0, 0, 0, 0, 1, 0, 0])
        itens.append(["petmarca.com.br", 0, 0, 99, 0, [], 2, 0, 0, 0, 1, 0, 0])       # marca: fora
        itens.append(["petdono.com.br", 4, 0, 98, 0, [], 0, 0, 0, 0, 1, 0, 0])        # registrado: fora
        itens.append(["saude1.com.br", 0, 0, 70, 0, [], 0, 0, 0, 0, 2, 0, 0])
        return {"gerado_em": gerado, "status": self.STATUS, "categorias": cats,
                "motivos": [], "total_rodada": 1000, "itens": itens,
                "rodada": {"inicio": "2026-09-09T15:00:00-03:00", "fim": "2026-09-16T15:00:00-03:00"}}

    TODOS = {"extensoes": ["com.br"], "motivos": [],
             "itens": [["pet", 0, 50, [], 0, 1], ["petx", 0, 50, [], 0, 1], ["saude", 0, 50, [], 0, 2]]}

    def pagina(self, campos, slug):
        return next(c for c in campos if c["slug"] == slug)

    def test_rodada_aberta(self):
        from garimpo.web import ramos
        campos = ramos.paginas(self.dados("2026-09-14T12:00:00+00:00"), self.TODOS)
        pet = self.pagina(campos, "dominios/pet")
        self.assertTrue(pet["indexavel"])
        self.assertIn("<strong>2</strong> domínios .br de pet, de 1.000 da lista", pet["corpo"])
        self.assertIn("12 estavam sem candidato visível, 1 disputados", pet["corpo"])
        self.assertIn("3 candidatos", pet["corpo"])
        self.assertNotIn("petmarca", pet["corpo"])
        self.assertNotIn("petdono", pet["corpo"])
        self.assertIn('href="/?ramo=pet"', pet["corpo"])
        self.assertLessEqual(len(pet["descricao"]), 160)
        self.assertIn("setembro de 2026", pet["titulo_busca"])
        # saude tem um nome so: fica de pe, sem indexar, e fora da lista de outros ramos
        saude = self.pagina(campos, "dominios/saude")
        self.assertFalse(saude["indexavel"])
        self.assertNotIn("/dominios/saude/", pet["corpo"])

    def test_rodada_fechada_fala_do_que_sobrou(self):
        from garimpo.web import ramos
        campos = ramos.paginas(self.dados("2026-09-18T12:00:00+00:00"), self.TODOS)
        pet = self.pagina(campos, "dominios/pet")
        self.assertIn("A rodada fechou", pet["corpo"])
        self.assertIn("fechou sem candidato visível", pet["corpo"])
        self.assertIn("travou: volta na rodada de 14/10", pet["corpo"])
        self.assertIn("foi a leilão", ramos.situacao(["x.com.br", 2, 2, 1, 1, [], 0, 1, 0, 0, 0],
                                                     self.dados("2026-09-18T12:00:00+00:00"),
                                                     ramos.fase_de(self.dados("2026-09-18T12:00:00+00:00")))[1])

    def test_sitemap_e_llms_pulam_pagina_rala(self):
        from garimpo.web import paginas, ramos
        lista = [paginas.Pagina(**c) for c in ramos.paginas(self.dados("2026-09-14T12:00:00+00:00"), self.TODOS)]
        mapa = paginas.sitemap(lista, "https://ex.br")
        self.assertIn("https://ex.br/dominios/pet/", mapa)
        self.assertNotIn("https://ex.br/dominios/saude/", mapa)
        self.assertNotIn("dominios/saude", paginas.llms_txt(lista, "https://ex.br"))
        layout = open(os.path.join(os.path.dirname(__file__), "site_modelo", "layout.html"), encoding="utf-8").read()
        rala = next(p for p in lista if p.slug == "dominios/saude")
        self.assertIn('content="noindex, follow"', paginas.render(rala, layout, {}))
        pet = next(p for p in lista if p.slug == "dominios/pet")
        html = paginas.render(pet, layout, self.dados("2026-09-14T12:00:00+00:00"))
        self.assertNotIn("noindex", html)
        self.assertIn('"ItemList"', html)
        self.assertIn('<a class="aba" href="/" aria-current="page">', html)


class TestPagina404(unittest.TestCase):
    """
    18/09/2026 (seo-tecnico:404-vazio): endereco que nao existe (ex.: as
    URLs /products/... que o Google ainda conhece da loja que usou o
    dominio antes) tinha corpo vazio, porque wrangler.jsonc dizia
    not_found_handling "none" e nao havia 404.html nenhum para servir.
    """

    def test_conteudo_da_pagina(self):
        from garimpo.web import paginas
        erro = paginas.pagina_404()
        self.assertFalse(erro.indexavel)
        self.assertLessEqual(len(erro.descricao), 160)
        layout = open(os.path.join(os.path.dirname(__file__), "site_modelo", "layout.html"),
                      encoding="utf-8").read()
        html = paginas.render(erro, layout, {}, base="https://ex.br")
        self.assertIn("<h1>Esta página não existe</h1>", html)
        self.assertIn('content="noindex, follow"', html)
        self.assertIn('href="/perguntas/"', html)
        self.assertIn('href="/sobre/"', html)
        self.assertIn('id="ficha-404-nome"', html)
        self.assertIn('<script src="/erro404.js"></script>', html)
        # sem method/action: a CSP tem form-action 'none' (site_modelo/_headers),
        # um <form> de verdade nunca submeteria; erro404.js e que navega
        self.assertNotIn("action=", html)

    def test_gerar_escreve_404_html_na_raiz_e_wrangler_serve(self):
        """
        Amarra as duas metades do achado: o arquivo que paginas.gerar() grava
        e a configuracao que manda o Cloudflare servi-lo (sem as duas juntas,
        not_found_handling "none" ignora um 404.html que exista sozinho, e
        "404-page" sem o arquivo so faria o Cloudflare recusar publicar).
        """
        from garimpo.web import paginas
        raiz = os.path.dirname(__file__)
        modelo = os.path.join(raiz, "site_modelo")
        dados = {
            "gerado_em": "2026-09-18T12:00:00+00:00",
            "status": ["LIBERACAO_LIVRE", "LIBERACAO_DISPUTADA", "COMPETITIVO", "LIVRE",
                       "REGISTRADO", "AGUARDANDO_LIBERACAO", "INDISPONIVEL", "LIVRE_COM_TICKET"],
            "categorias": [], "motivos": [], "total_rodada": 0, "itens": [],
            "rodada": {"inicio": "2026-09-09T15:00:00-03:00", "fim": "2026-09-16T15:00:00-03:00"},
        }
        with tempfile.TemporaryDirectory() as destino:
            escritos = paginas.gerar(modelo, destino, dados)
            caminho = os.path.join(destino, "404.html")
            self.assertIn(caminho, escritos)
            texto = open(caminho, encoding="utf-8").read()
            self.assertIn("Esta página não existe", texto)
            self.assertIn('content="noindex, follow"', texto)
            # nao entra no sitemap nem no llms.txt: 404.html nunca e citado
            self.assertNotIn("/404", open(os.path.join(destino, "sitemap.xml"), encoding="utf-8").read())
            self.assertNotIn("/404", open(os.path.join(destino, "llms.txt"), encoding="utf-8").read())
        wrangler = open(os.path.join(raiz, "wrangler.jsonc"), encoding="utf-8").read()
        sem_comentarios = re.sub(r"(?m)^\s*//.*$", "", wrangler)
        config = json.loads(sem_comentarios)
        self.assertEqual(config["assets"]["not_found_handling"], "404-page")


class TestNavegacaoNoCelular(unittest.TestCase):
    """
    18/09/2026 (o2-site-cabecalho-navegacao): a aba ativa ficava fora da
    tela em 5 das 8 secoes a 390px, um link para um trecho abria com o
    titulo escondido sob o cabecalho fixo (768 a 1279px), Shift+Tab podia
    deixar o foco coberto (WCAG 2.4.11) e nao havia "Pular para o
    conteudo".
    """

    def setUp(self):
        self.raiz = os.path.dirname(__file__)
        self.modelo = os.path.join(self.raiz, "site_modelo")
        self.tema_js = open(os.path.join(self.modelo, "tema.js"), encoding="utf-8").read()
        self.extra_css = open(os.path.join(self.modelo, "extra.css"), encoding="utf-8").read()
        self.layout = open(os.path.join(self.modelo, "layout.html"), encoding="utf-8").read()
        self.style_css = open(os.path.join(self.raiz, "web", "style.css"), encoding="utf-8").read()

    def test_pular_para_o_conteudo_e_primeiro_filho_do_body(self):
        from garimpo.web import paginas
        inicio = next(p for p in paginas.carregar(self.modelo) if p.slug == "")
        html = paginas.render(inicio, self.layout, {}, base="https://ex.br")
        corpo = html.split("<body>", 1)[1]
        # o link de pular vem antes de qualquer outro elemento visivel, e
        # main leva tabindex para receber o foco quando o link e ativado
        self.assertLess(corpo.index('class="pular"'), corpo.index("<header>"))
        self.assertIn('href="#conteudo"', corpo)
        self.assertIn('<main id="conteudo" tabindex="-1"', html)

    def test_pular_nao_mexe_no_script_inline_do_head(self):
        # o hash da CSP e calculado sobre o script inline do <head>: a
        # correcao deste item so mexe no <body>
        cabeca, resto = self.layout.split("<body>", 1)
        self.assertIn("localStorage.getItem(\"tema\")", cabeca)
        self.assertNotIn("pular", cabeca)

    def test_tema_js_rola_a_aba_ativa_mesmo_sem_botao_de_tema(self):
        # o script tem de rodar mesmo em paginas sem #btn-tema (nenhuma
        # hoje, mas o guard "if (!botao) return" barrava tudo que vinha
        # depois dele); a rolagem e a altura do cabecalho ficam antes
        antes_do_guard = self.tema_js.split("if (!botao) return;")[0]
        self.assertIn('aria-current="page"', antes_do_guard)
        self.assertIn("scrollLeft", antes_do_guard)
        self.assertIn("--altura-cabecalho", antes_do_guard)
        self.assertIn("ResizeObserver", antes_do_guard)

    def test_seta_das_abas_fora_da_faixa_e_so_no_celular(self):
        # personas de 19/09/2026: a mascara sozinha nao avisava que as abas
        # continuam. A seta nasce antes do guard (roda em toda pagina), fica
        # fora da faixa (a mascara a esfumaria e um filho a mais tiraria o
        # :last-child da ultima aba) e some no fim da faixa, com folga de
        # 1px para scrollLeft fracionario
        antes_do_guard = self.tema_js.split("if (!botao) return;")[0]
        self.assertIn("abas-seta", antes_do_guard)
        self.assertIn("insertAdjacentElement('afterend'", antes_do_guard)
        self.assertIn("faixa.scrollLeft + faixa.clientWidth < faixa.scrollWidth - 1", antes_do_guard)
        self.assertNotIn(".style.", antes_do_guard.split("abas-seta", 1)[1].split("Publica a altura")[0])
        # escondida fora do celular; visivel so dentro do bloco de ate 64rem
        self.assertIn(".abas-seta { display: none; }", self.extra_css)
        bloco = self.extra_css.split(".abas-seta { display: none; }", 1)[1]
        self.assertTrue(bloco.lstrip().startswith("@media (max-width: 63.999rem)"))

    def test_extra_css_publica_scroll_padding_e_mascara_da_faixa(self):
        self.assertIn("scroll-padding-top: calc(var(--altura-cabecalho, 7rem)", self.extra_css)
        # a mascara e o padding-inline-end tem de usar o mesmo valor: com
        # 2.5rem de mascara contra 2rem de padding, o degrade cai dentro do
        # texto da ultima aba em vez de cair so no padding reservado
        mascara = re.search(r"mask-image: linear-gradient\(90deg, #000 calc\(100% - ([\d.]+rem)\)", self.extra_css)
        padding = re.search(r"padding-inline-end: ([\d.]+rem);", self.extra_css)
        self.assertIsNotNone(mascara)
        self.assertIsNotNone(padding)
        self.assertEqual(mascara.group(1), padding.group(1))
        self.assertIn("scroll-padding-inline-end: " + padding.group(1), self.extra_css)
        self.assertIn(".aba:last-child { scroll-snap-align: end; }", self.extra_css)
        # as duas margens (scroll-padding do html e scroll-margin do titulo)
        # nao podem voltar a somar 5.5rem + 7rem: o titulo ficaria coberto
        self.assertNotIn("scroll-margin-top: 5.5rem", self.extra_css)

    def test_style_css_tem_o_link_de_pular(self):
        self.assertIn(".pular {", self.style_css)
        self.assertIn(".pular:focus { top:", self.style_css)


class TestEnsaioDasFases(unittest.TestCase):
    """
    18/09/2026: a virada de outubro ensaiada em cinco instantes, no build e no
    app.js. Antes, de 12/10 a 14/10 as 15h, o inicio dizia "Rodada aberta", os
    ramos "candidatar-se e de graca ate 21/10" e a FAQ "a proxima e em 11/11".

    Os dados imitam o estado real: na virada o varrer.py esquece as leituras e
    nao consulta antes da abertura, entao a lista chega sem nenhuma leitura e a
    primeira so vem com o Garimpo seguinte a abertura.
    """

    STATUS = TestPaginasPorRamo.STATUS
    RODADA = {"inicio": "2026-10-14T15:00:00-03:00", "fim": "2026-10-21T15:00:00-03:00"}
    # instante, fase no build, fase no app.js, proxima rodada, com leitura?
    INSTANTES = [
        ("2026-10-12T09:00:00-03:00", "lista", "lista", "14/10/2026", False),
        ("2026-10-14T14:59:00-03:00", "lista", "lista", "14/10/2026", True),
        ("2026-10-14T15:01:00-03:00", "aberta", "aberta", "11/11/2026", False),
        ("2026-10-21T16:00:00-03:00", "fechada", "assentando", "11/11/2026", True),
        ("2026-10-22T12:00:00-03:00", "fechada", "assentando", "11/11/2026", True),
    ]
    FRASE_INICIO = ("A lista da rodada de outubro saiu: as candidaturas abrem em 14/10, às 15h, "
                    "e vão até 21/10, às 15h (horário de Brasília).")
    FRASE_RAMOS = ("A lista de outubro saiu; as candidaturas abrem em 14/10 às 15h e vão até "
                   "21/10 às 15h")
    TODOS = {"extensoes": ["com.br"], "motivos": [], "marcas": ["OK", "ATENCAO", "RISCO"],
             "itens": [[f"pet{i:02d}", 0, 70 - i, [], 0, 1] for i in range(14)]
             + [["petmarca", 0, 99, [], 2, 1]]}

    def dados(self, agora, com_leitura):
        itens = []
        if com_leitura:
            # 14/10 14h59: leitura de antes da abertura (status 5) nao vale nada;
            # depois do fim, o que sobrou
            situacao = 5 if agora < self.RODADA["inicio"] else 0
            itens = [[f"pet{i:02d}.com.br", situacao, 0, 70 - i, 0, [], 0, 0, 0, 0, 1, 0, 0]
                     for i in range(12)]
        return {"gerado_em": datetime.datetime.fromisoformat(agora).astimezone(
                    datetime.timezone.utc).isoformat(),
                "status": self.STATUS, "categorias": [{"nome": "pet", "rotulo": "Pet"}],
                "motivos": [], "total_rodada": 1000, "total_elegiveis": 0,
                "nao_verificados": 1000 - len(itens), "itens": itens, "rodada": dict(self.RODADA)}

    def test_build_nos_cinco_instantes(self):
        from garimpo.web import paginas, ramos
        modelo = os.path.join(os.path.dirname(__file__), "site_modelo")
        layout = open(os.path.join(modelo, "layout.html"), encoding="utf-8").read()
        inicio = next(p for p in paginas.carregar(modelo) if p.slug == "")
        for agora, fase, _, proxima, com_leitura in self.INSTANTES:
            with self.subTest(agora=agora):
                d = self.dados(agora, com_leitura)
                self.assertEqual(paginas.fase_da_rodada(d), fase)
                self.assertIn(f">{proxima}<", paginas.preencher_numeros(
                    '<span id="p-proxima-rodada">-</span>', d))
                html = paginas.render(inicio, layout, d)
                linha = re.search(r'id="fase-inicio">(.*?)</p>', html, re.S).group(1)
                passos = paginas.passos_da_pagina(d)
                pet = next(c for c in ramos.paginas(d, self.TODOS) if c["slug"] == "dominios/pet")
                self.assertNotIn("Conferimos 0", pet["corpo"])
                self.assertNotIn("petmarca", pet["corpo"])
                self.assertTrue(pet["indexavel"])
                if fase == "lista":
                    self.assertEqual(linha, self.FRASE_INICIO)
                    self.assertIn("Candidate-se de 14/10, 15h, a 21/10, 15h", passos)
                    self.assertIn('href="/dominios/"', passos)   # achado o2: link nos passos
                    self.assertIn(self.FRASE_RAMOS, pet["corpo"])
                    self.assertIn("a conferência de quem já pediu cada nome começa com a rodada, "
                                  "em 14/10, às 15h", pet["corpo"])
                    self.assertIn("a conferir a partir de 14/10", pet["corpo"])
                    # 15 na lista (a marca conta), 14 listados
                    self.assertIn("<strong>15</strong> domínios .br de pet", pet["corpo"])
                    self.assertIn("Ver os 14 na lista", pet["corpo"])
                    self.assertIn("a conferência de quem já pediu cada nome começa com a rodada, "
                                  "em 14/10, às 15h", html)
                    for errado in ("Rodada aberta", "Candidaturas ainda valem", "andidate-se agora",
                                   "até o fim da rodada", "Candidatar-se é de graça até",
                                   "estavam sem candidato visível", "Situação na última leitura"):
                        self.assertNotIn(errado, html + pet["corpo"])
                elif fase == "aberta":
                    self.assertIn("Rodada atual: de", linha)
                    self.assertEqual(passos, "")
                    # os passos ficam os do modelo (ferramenta.html), que ja
                    # linka /dominios/ no primeiro: achado o2, sem precisar
                    # de passos_da_pagina tambem preencher a aberta
                    passos_html = re.search(r'<ol class="passos"[^>]*>(.*?)</ol>', html, re.S).group(1)
                    self.assertIn('href="/dominios/"', passos_html)
                    # abriu e a primeira leitura ainda nao chegou: a lista, sem "0"
                    self.assertIn("Candidatar-se é de graça até 21/10/2026", pet["corpo"])
                    self.assertIn("a conferência de quem já pediu cada nome começou com a rodada, "
                                  "em 14/10, às 15h, e a primeira leitura chega nas próximas "
                                  "horas.</p>", pet["corpo"])
                    self.assertNotIn(self.FRASE_RAMOS, pet["corpo"])
                    # sem nenhum nome conferido: nem "sem concorrente a vista" no
                    # inicio, nem "leitura ate" no indice dos ramos
                    sub = re.search(r'id="p-subtitulo">(.*?)</p>', html, re.S).group(1)
                    self.assertNotIn("sem concorrente à vista", sub)
                    self.assertIn("começou com a rodada, em 14/10, às 15h; a primeira leitura "
                                  "chega nas próximas horas", sub)
                    indice = next(c for c in ramos.paginas(d, self.TODOS) if c["slug"] == "dominios")
                    self.assertNotIn("leitura até", indice["corpo"])
                    self.assertIn("a primeira leitura chega nas próximas horas", indice["corpo"])
                else:
                    self.assertIn("Candidate-se de 11/11 a 18/11", passos)
                    self.assertIn('href="/dominios/"', passos)   # achado o2: link nos passos
                    self.assertIn("A rodada fechou", pet["corpo"])
                    self.assertNotIn(self.FRASE_RAMOS, pet["corpo"])

    def _app_js(self):
        return open(os.path.join(os.path.dirname(__file__), "site_modelo", "app.js"),
                    encoding="utf-8").read()

    def test_app_js_nos_cinco_instantes(self):
        """O mesmo ensaio no faseDaRodada, em dois fusos: a frase e sempre a de Brasilia."""
        import shutil
        node = shutil.which("node")
        if not node:
            self.skipTest("sem node")
        js = self._app_js()
        trechos = [re.search(r"const FUSO = .*?;", js).group(0),
                   re.search(r"function horaCurta\(d\) \{.*?\n\}", js, re.S).group(0),
                   re.search(r"const MESES_EXTENSO = \[.*?\];", js, re.S).group(0),
                   re.search(r"const HORAS_DE_AVISO.*?\nfunction faseDaRodada.*?\n\}", js, re.S).group(0)]
        instantes = [a for a, *_ in self.INSTANTES]
        roteiro = "\n".join(trechos) + (
            f"\nfor (const a of {json.dumps(instantes)}) console.log(JSON.stringify("
            f"faseDaRodada({json.dumps(self.RODADA['inicio'])}, {json.dumps(self.RODADA['fim'])}, new Date(a))));")
        for fuso in ("America/Sao_Paulo", "America/Manaus", "Europe/Lisbon"):
            with self.subTest(fuso=fuso):
                saida = subprocess.run([node, "-e", roteiro], capture_output=True, text=True, check=True,
                                       env={**os.environ, "TZ": fuso}).stdout.splitlines()
                r = [json.loads(l) for l in saida]
                self.assertEqual([x["fase"] for x in r], [f for _, _, f, _, _ in self.INSTANTES])
                self.assertEqual(r[0]["completo"], self.FRASE_INICIO)
                self.assertEqual(r[1]["curto"], "abre em 14/10")
                self.assertEqual((r[2]["dia"], r[2]["hora"]), ("21/10", "15:00"))
                self.assertIn("(horário de Brasília)", r[2]["completo"])

    def test_app_js_so_aceita_agora_na_previa_e_para_o_relogio(self):
        js = self._app_js()
        desvio = js[js.index("const DESVIO_DO_RELOGIO"):js.index("const agoraMs")]
        self.assertIn("['127.0.0.1', 'localhost'].includes(location.hostname)", desvio)
        # depois do ultimo marco o relogio para de vez
        tique = js[js.index("function tiqueDoRelogio"):js.index("function pararRelogio")]
        self.assertIn("relogio.alvo = null;", tique)
        andar = js[js.index("function andarRelogio"):js.index("function iniciarRelogio")]
        self.assertIn("if (!relogio.alvo) return;", andar[andar.index("tiqueDoRelogio();"):])
        # nenhum "new Date()" sem argumento sobra nas contas de fase e relogio
        for nome in ("function rodadaFechada", "function proximaAberturaDoCalendario",
                     "function pintarBotaoDaRodada", "function marcoPadrao"):
            corpo = js[js.index(nome):]
            corpo = corpo[:corpo.index("\n}\n")]
            self.assertNotIn("new Date()", corpo)
            self.assertNotIn("Date.now()", corpo)


class TestArquivoDoDominio(unittest.TestCase):
    """
    O indice "este dominio ja teve site?" (garimpo/dominio/arquivo.py).

    O caso de teste e o pneus.com.br de verdade, lido do sparkline em
    18/09/2026: e a historia que custou duas correcoes a este repositorio, e
    se o indice a errar, erra tudo.
    """

    # recorte fiel do sparkline do pneus.com.br: 1999 serviu pagina, 2019
    # redirecionou (maio, o mes em que passou a apontar para sunset-tires)
    PNEUS = {"years": {"1999": [1, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0],
                       "2019": [0, 0, 0, 0, 1, 0, 0, 0, 0, 0, 0, 0]},
             "status": {"1999": "244444444444", "2019": "444434444444"}}

    def test_le_so_os_meses_com_captura(self):
        """
        A letra "4" de enchimento nos meses vazios NAO e erro: sem o filtro
        por `years`, o pneus.com.br viraria 22 meses de 404 inventados.
        """
        from garimpo.dominio import arquivo
        r = arquivo.de_sparkline("pneus.com.br", self.PNEUS)
        self.assertEqual((r.primeira, r.ultima), ("199901", "201905"))
        self.assertEqual(r.capturas, 2)
        self.assertEqual(r.servindo, 1)          # jan/1999
        self.assertEqual(r.redirecionando, 1)    # mai/2019
        self.assertEqual(r.estado, arquivo.SERVIU)

    def test_tres_estados(self):
        from garimpo.dominio import arquivo
        nada = arquivo.de_sparkline("x.com.br", {"years": {}, "status": {}})
        self.assertEqual(nada.estado, arquivo.NUNCA)
        so_redir = arquivo.de_sparkline("y.com.br", {
            "years": {"2020": [1] + [0] * 11}, "status": {"2020": "3" + "4" * 11}})
        self.assertEqual(so_redir.estado, arquivo.REDIRECIONOU)

    def test_linha_vai_e_volta(self):
        from garimpo.dominio import arquivo
        r = arquivo.de_sparkline("pneus.com.br", self.PNEUS, "20260918")
        self.assertEqual(arquivo.ler_linha(arquivo.linha(r)), r)
        self.assertIsNone(arquivo.ler_linha("lixo"))
        self.assertIsNone(arquivo.ler_linha("a\tb\tc\tnao-numero\t0\t0\tx"))

    def test_mesma_fatia_das_passagens(self):
        """O navegador acha as duas coisas pelo mesmo hash, ja escrito em JS."""
        from garimpo.dominio import arquivo, passagens
        r = arquivo.de_sparkline("pneus.com.br", self.PNEUS)
        (chave,) = arquivo.agrupar([r]).keys()
        self.assertEqual(chave, passagens.fatia("pneus.com.br"))

    def test_cdx_da_o_mesmo_numero(self):
        """A queda para a CDX nao pode mudar a resposta."""
        from garimpo.adaptadores.wayback import Captura
        from garimpo.dominio import arquivo
        capturas = [Captura("199901", "200"), Captura("201905", "301")]
        via_cdx = arquivo.de_capturas("pneus.com.br", capturas)
        via_spark = arquivo.de_sparkline("pneus.com.br", self.PNEUS)
        self.assertEqual(via_cdx, via_spark)

    def test_bloqueio_e_recusa_de_conexao_tambem(self):
        """F9: o Internet Archive barra recusando a conexao, nao com 429."""
        import urllib.error
        from garimpo.adaptadores import wayback
        self.assertTrue(wayback._e_bloqueio(
            OSError("<urlopen error [Errno 111] Connection refused>")))
        self.assertTrue(wayback._e_bloqueio(
            OSError("_ssl.c:993: The handshake operation timed out")))
        self.assertTrue(wayback._e_bloqueio(
            urllib.error.HTTPError("u", 429, "x", None, None)))
        self.assertFalse(wayback._e_bloqueio(
            urllib.error.HTTPError("u", 503, "x", None, None)))

    @so_com("arquivar_wayback.py")
    def test_coleta_recusa_rodar_no_actions(self):
        """Do runner o IP e compartilhado e barrado (F9): a coleta e local."""
        import subprocess
        import sys
        saida = subprocess.run(
            [sys.executable, "arquivar_wayback.py"],
            cwd=os.path.dirname(os.path.abspath(__file__)),
            env={**os.environ, "GITHUB_ACTIONS": "true"},
            capture_output=True, text=True)
        self.assertEqual(saida.returncode, 3)
        self.assertIn("F9", saida.stderr)


@so_com("docs/operacao.md")
class TestOperacao(unittest.TestCase):
    """docs/operacao.md pode ir ao publico: sem ticket, leilao, e-mail ou nome."""

    def setUp(self):
        caminho = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                               "docs", "operacao.md")
        with open(caminho, encoding="utf-8") as f:
            self.texto = f.read()

    def test_tem_as_quatro_partes(self):
        for titulo in ("Republicar", "Reverter", "Congelamento",
                       "Checklist do dia da lista"):
            self.assertIn(titulo, self.texto)

    def test_checklist_do_dia_da_lista_cobre_o_que_a_agenda_promete(self):
        # agenda_do_projeto.py copia esta secao para o issue do dia da
        # lista; se um desses sumir daqui, o issue tambem perde
        checklist = self.texto[self.texto.index("Checklist do dia da lista"):]
        for trecho in ("minutos=3", "gerado_em", "#fase-inicio",
                       "historico_listas.py passagens", "avail",
                       "22/10"):
            self.assertIn(trecho, checklist)

    def test_congelamento_cobre_os_arquivos_da_varredura_e_das_fases(self):
        for arquivo in ("varrer.py", "exportar_site.py",
                        ".github/workflows/garimpo.yml",
                        "garimpo/dominio/calendario.py",
                        "garimpo/dominio/frescor.py",
                        "garimpo/adaptadores/registrobr.py",
                        "garimpo/web/ramos.py", "site_modelo/app.js"):
            self.assertIn(arquivo, self.texto)
        for nome in ("passos_da_pagina", "subtitulo_da_pagina",
                     "relogio_da_pagina"):
            self.assertIn(nome, self.texto)

    def test_sem_dado_pessoal_nem_valor_de_leilao(self):
        # e-mail: nunca um endereco. O "@" tambem aparece pinando a versao
        # do pacote (ex.: "wrangler@4.134.0"), que nao e email: tira esse
        # formato antes de procurar.
        sem_versao_pinada = re.sub(r"\w+@\d+\.\d+\.\d+", "", self.texto)
        self.assertIsNone(re.search(r"[\w.+-]+@[\w-]+\.[\w.-]+", sem_versao_pinada),
                          "parece um endereco de e-mail")
        self.assertNotIn("R$", self.texto)  # valor de leilao nunca e publico
        # numero de ticket: sequencia de 6+ digitos seguidos (o maior ticket
        # real tem 8); datas, horas, cron e a versao do wrangler ficam
        # todos abaixo disso
        self.assertIsNone(re.search(r"\d{6,}", self.texto),
                          "parece um numero de ticket")
        for nome in ("vacina.com.br", "hostmaster"):
            self.assertNotIn(nome, self.texto)


@so_com("agenda_do_projeto.py")
class TestAgenda(unittest.TestCase):
    """agenda_do_projeto.py: um lembrete por evento, so leitura, so calendario.py e datas fixas."""

    def test_janela_de_9_dias_a_partir_de_uma_data_forcada(self):
        # o mesmo exemplo do criterio: forcar 05/10/2026 tem de mostrar so
        # a lista (12/10) e a abertura (14/10) da rodada de outubro
        import agenda_do_projeto as ag
        evs = ag.eventos(_date(2026, 10, 5), 9)
        self.assertEqual([e.data.isoformat() for e in evs],
                         ["2026-10-12", "2026-10-14"])
        self.assertIn("Lista de outubro", evs[0].titulo)
        self.assertIn("12/10", evs[0].titulo)
        self.assertIn("Rodada de outubro abre", evs[1].titulo)
        self.assertIn("14/10", evs[1].titulo)

    def test_fechamento_traz_o_desfecho_embutido(self):
        import agenda_do_projeto as ag
        evs = ag.eventos(_date(2026, 10, 15), 9)
        self.assertEqual([e.data.isoformat() for e in evs],
                         ["2026-10-21", "2026-10-22"])
        self.assertIn("fecha em 21/10", evs[0].titulo)
        self.assertIn("desfecho", evs[0].corpo.lower())
        self.assertIn("modo=desfecho", evs[0].corpo)
        self.assertIn("Revisao de metricas pos-rodada", evs[1].titulo)

    def test_datas_fixas_de_2026(self):
        import agenda_do_projeto as ag
        self.assertEqual([e.titulo for e in ag.eventos(_date(2026, 9, 25), 9)],
                         ["Revisao de metricas em 01/10"])
        self.assertEqual([e.titulo for e in ag.eventos(_date(2026, 12, 1), 9)],
                         ["Lista de dezembro sai em 07/12 (segunda)",
                          "Bumerangues na lista de 07/12",
                          "Rodada de dezembro abre em 09/12 as 15h"])
        self.assertEqual([e.titulo for e in ag.eventos(_date(2026, 12, 10), 9)],
                         ["Rodada de dezembro fecha em 16/12 as 15h; desfecho ~18h",
                          "Token do Cloudflare expira em 17/12"])

    def test_janela_vazia_nao_quebra(self):
        import agenda_do_projeto as ag
        self.assertEqual(ag.eventos(_date(2026, 10, 25), 3), [])

    def test_titulos_sao_unicos_por_mes_para_nao_duplicar_issue(self):
        # o titulo e a chave de dedup em abrir_issues(): duas rodadas
        # diferentes nunca podem gerar o mesmo titulo
        import agenda_do_projeto as ag
        titulos = [e.titulo for e in ag.eventos(_date(2026, 9, 1), 120)]
        self.assertEqual(len(titulos), len(set(titulos)))

    def test_checklist_do_dia_da_lista_para_no_proximo_titulo(self):
        import agenda_do_projeto as ag
        checklist = ag._checklist_dia_da_lista()
        self.assertIn("minutos=3", checklist)
        self.assertIn("22/10", checklist)
        self.assertNotIn("## ", checklist)  # nao vazou para a secao seguinte

    def test_cli_seco_imprime_sem_abrir_issue(self):
        import sys
        saida = subprocess.run(
            [sys.executable, "agenda_do_projeto.py", "--seco",
             "--data", "2026-10-05"],
            cwd=os.path.dirname(os.path.abspath(__file__)),
            capture_output=True, text=True)
        self.assertEqual(saida.returncode, 0, saida.stderr)
        self.assertIn("2026-10-12", saida.stdout)
        self.assertIn("2026-10-14", saida.stdout)
        # --seco nunca chega a abrir_issues(), entao nunca chama o gh
        # (que nem existe no ambiente de teste)
        self.assertNotIn("aberto:", saida.stdout)

    def test_workflow_agenda_e_so_no_privado_e_sem_cloudflare(self):
        caminho = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                               ".github", "workflows", "visitas.yml")
        with open(caminho) as f:
            wf = f.read()
        self.assertIn("cron: \"0 11 * * 1\"", wf)  # cadencia do job resumo, inalterada
        m = re.search(r"\n  agenda:\n(.*?)(?=\n  \w+:\n|\Z)", wf, re.DOTALL)
        self.assertIsNotNone(m, "job agenda nao encontrado em visitas.yml")
        job = m.group(1)
        self.assertIn("github.event.repository.private", job)
        self.assertNotIn("CLOUDFLARE", job)
        self.assertIn("gh label create agenda", job)
        self.assertIn("agenda_do_projeto.py", job)
        # sem isso, um `gh issue create` que falha some atras do `tee` e o
        # job sai verde sem abrir issue nenhum
        self.assertIn("shell: bash", job)
        for entrada in ("seco:", "data:"):
            self.assertIn(entrada, wf)

    def test_workflow_inputs_nao_colados_no_shell(self):
        """Input do dispatch entra por env, nunca colado direto no run: (mesma regra do garimpo.yml)."""
        caminho = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                               ".github", "workflows", "visitas.yml")
        with open(caminho) as f:
            wf = f.read()
        blocos = re.findall(r"^(\s*)run: [|>]-?\n((?:\1\s+.*\n|\s*\n)*)", wf, re.MULTILINE)
        blocos += [("", b) for b in re.findall(r"^\s*run: ([^|>].*)$", wf, re.MULTILINE)]
        self.assertTrue(blocos)
        for _, corpo in blocos:
            self.assertNotIn("${{ inputs.", corpo)


@so_com("visitas.py")
class TestVisitasPlacar(unittest.TestCase):
    """
    visitas.py --placar (achado produto-ceo:placar-de-metricas, 18/09/2026):
    cinco linhas para o issue semanal, sem consulta nova ao Registro.br e sem
    rede nos testes (GraphQL e `gh` sao trocados por resposta falsa).
    """

    CRED = {"CLOUDFLARE_API_TOKEN": "t", "CLOUDFLARE_ACCOUNT_ID": "a",
            "CLOUDFLARE_ZONE_ID": "z"}

    def _placar(self, resposta_placar, resposta_lembretes, saida_gh, dias=7):
        import visitas
        respostas = iter([resposta_placar, resposta_lembretes])
        original = visitas._runs_garimpo_privado  # antes do patch, senao recursao infinita
        buf = io.StringIO()
        with unittest.mock.patch.object(
                visitas, "consultar",
                side_effect=lambda cred, query, variaveis: next(respostas)), \
             unittest.mock.patch.object(
                visitas, "_runs_garimpo_privado",
                side_effect=lambda dias, **kw: original(
                    dias, _saida=saida_gh,
                    _agora=datetime.datetime(2026, 9, 18, 21, 0, tzinfo=datetime.timezone.utc))), \
             contextlib.redirect_stdout(buf):
            visitas.placar(self.CRED, dias)
        return buf.getvalue()

    def test_cron_privado_bate_com_o_garimpo_yml(self):
        """A string de cron da o numero de horarios por dia
        (HORARIOS_POR_DIA_PRIVADO), o denominador das "previstas" no
        placar: tem de concordar com garimpo.yml, ou a fracao sai errada."""
        import visitas
        caminho = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                               ".github", "workflows", "garimpo.yml")
        with open(caminho) as f:
            wf = f.read()
        self.assertIn(f'cron: "{visitas.CRON_GARIMPO_PRIVADO}"', wf)
        self.assertEqual(visitas.HORARIOS_POR_DIA_PRIVADO, 4)

    def test_cinco_linhas_com_resposta_falsa(self):
        resposta_placar = {
            "visitas": [{"sum": {"visits": 140}}],
            "origens": [
                {"sum": {"visits": 5}, "dimensions": {"refererHost": "www.perplexity.ai"}},
                {"sum": {"visits": 3}, "dimensions": {"refererHost": "chatgpt.com"}},
                {"sum": {"visits": 50}, "dimensions": {"refererHost": "google.com"}},
                {"sum": {"visits": 0}, "dimensions": {"refererHost": None}},
            ],
        }
        resposta_lembretes = {"total": [{"count": 3}]}
        saida_gh = lambda: json.dumps([
            {"conclusion": "success", "createdAt": "2026-09-18T02:41:07Z"},    # privado, sucesso
            {"conclusion": "failure", "createdAt": "2026-09-17T20:41:03Z"},    # privado, falhou
            {"conclusion": "success", "createdAt": "2026-09-18T17:52:25Z"},    # privado, atrasado 71 min: conta
            {"conclusion": "skipped", "createdAt": "2026-09-18T09:03:11Z"},    # publico: o `if` pula, fora
        ])
        saida = self._placar(resposta_placar, resposta_lembretes, saida_gh)

        self.assertIn("## Placar,", saida)
        self.assertIn("140", saida)          # pessoas
        self.assertIn("8 visitas", saida)    # perplexity (5) + chatgpt (3), google e None fora
        self.assertIn("3 pedidos a /lembretes/*.ics", saida)
        self.assertIn("2 de 28 previstas", saida)   # so as runs de sucesso contam
        self.assertRegex(saida, r"Proxima lista:\*\* \d{2}/\d{2}/\d{4}")
        self.assertNotIn("R$", saida)   # nenhuma linha do placar toca valor de leilao

    def test_gh_falhando_nao_derruba_o_placar(self):
        resposta_placar = {"visitas": [{"sum": {"visits": 0}}], "origens": []}
        resposta_lembretes = {"total": [{"count": 0}]}
        def saida_gh():
            raise RuntimeError("gh: nao autenticado")
        saida = self._placar(resposta_placar, resposta_lembretes, saida_gh)
        self.assertIn("nao conferido", saida)

    def test_runs_garimpo_ignora_json_invalido(self):
        import visitas
        self.assertIsNone(visitas._runs_garimpo_privado(
            7, _saida=lambda: "isso nao e json"))

    def test_limite_do_gh_run_list_cresce_com_os_dias(self):
        """O cron publico dispara de hora em hora mesmo saindo "skipped" no
        privado: uma semana cheia soma ate 24*7 + 4*7 = 196 runs `schedule`.
        Um `--limit` fixo (100, a versao anterior) cobriria uns 3,5 dias e a
        contagem ficaria abaixo do real sem aviso nenhum -- por isso o
        `--limit` pedido de verdade ao `gh` tem de escalar com `dias`."""
        import visitas
        capturado = {}

        def falso_run(argv, **kw):
            capturado["argv"] = argv
            return unittest.mock.Mock(stdout="[]")

        with unittest.mock.patch.object(visitas.subprocess, "run", side_effect=falso_run):
            visitas._runs_garimpo_privado(7)
            self.assertIn("--limit", capturado["argv"])
            i = capturado["argv"].index("--limit")
            self.assertEqual(capturado["argv"][i + 1], "300")

            visitas._runs_garimpo_privado(30)
            i = capturado["argv"].index("--limit")
            self.assertEqual(capturado["argv"][i + 1], "900")

    def test_workflow_chama_placar_antes_de_pessoas(self):
        caminho = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                               ".github", "workflows", "visitas.yml")
        with open(caminho) as f:
            wf = f.read()
        self.assertLess(wf.index("visitas.py --placar"),
                        wf.index("visitas.py --pessoas"))

    def test_workflow_tem_permissao_actions_read(self):
        """`gh run list` (linha "Garimpo rodou o previsto") le
        /actions/workflows e /actions/runs; sem `actions: read` em
        `permissions` a leitura falha e a falha e silenciosa (o job so
        conta "nao conferido"), entao o teste amarra o arquivo."""
        caminho = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                               ".github", "workflows", "visitas.yml")
        with open(caminho) as f:
            wf = f.read()
        bloco = wf[wf.index("permissions:"):wf.index("jobs:")]
        self.assertIn("actions: read", bloco)


@so_com("site_modelo/conteudo/insights")
class TestNumerosComDataEDenominador(unittest.TestCase):
    """
    o1-site-numeros-com-data (18/09/2026): sete números errados achados na
    rodada 1 (one.com.br "com 73" sem dizer que é retrato de 12/09; o total
    125.457 conta as 4 linhas de cabeçalho da lista, os nomes são 125.453;
    "Quanto vale" dizia que quase todos saem com um candidato, é o
    contrário; a mediana/moda de 2017 é só da primeira rodada; os R$ 98 mi
    são um fundo na FAPESP, não a anuidade; o ticket ficou inativo no mesmo
    dia do fechamento; e os R$ 220 mil do pneus.com.br apareciam sem fonte,
    com a única fonte achada nomeando outro arrematante).
    """

    ARQUIVOS = (
        ("perguntas.html",),
        ("insights", "quais-nomes-sao-disputados.html"),
        ("insights", "nomes-curtos-sobrando.html"),
        ("insights", "brasil-vs-eua.html"),
        ("api-registrobr.html",),
        ("insights", "quanto-vale-um-dominio-com-br.html"),
        ("regras-do-br.html",),
        ("insights", "o-numero-do-ticket.html"),
        ("insights", "dominio-mais-caro-do-brasil.html"),
    )

    def _ler(self, *partes):
        caminho = os.path.join(os.path.dirname(__file__), "site_modelo",
                                "conteudo", *partes)
        with open(caminho, encoding="utf-8") as f:
            return f.read()

    def _uma_linha(self, *partes):
        # normaliza a quebra de linha do HTML fonte (indentacao de 78 col.),
        # senao um assertIn positivo quebra sozinho quando o texto reflui
        return re.sub(r"\s+", " ", self._ler(*partes))

    def test_total_da_rodada_e_125453_em_todo_lugar(self):
        # a lista tem 4 linhas de cabeçalho (# ...); 125.457 - 4 = 125.453
        for partes in self.ARQUIVOS:
            pagina = self._ler(*partes)
            self.assertNotIn("125.457", pagina, f"{partes}: ainda tem 125.457")
            self.assertNotIn("125457", pagina, f"{partes}: ainda tem 125457")
        self.assertIn("125.453", self._uma_linha("insights", "nomes-curtos-sobrando.html"))
        self.assertIn("125.453", self._uma_linha("insights", "brasil-vs-eua.html"))
        self.assertIn("125.453", self._uma_linha("api-registrobr.html"))

    def test_one_com_br_tem_as_duas_leituras_com_data(self):
        perguntas = self._ler("perguntas.html")
        perguntas_uma_linha = self._uma_linha("perguntas.html")
        self.assertNotIn("com 73.", perguntas)
        self.assertIn("73 candidatos visíveis em 12/09/2026", perguntas_uma_linha)
        self.assertIn("119", perguntas)
        self.assertIn("16/09/2026", perguntas)
        self.assertIn("/dados/#mais-pedidos", perguntas)
        # nunca cita o e-mail do Registro.br nem candidatura de ninguem
        self.assertNotIn("e-mail", perguntas.split('id="mais-disputados"')[1].split("</div>")[0])
        insight = self._uma_linha("insights", "quais-nomes-sao-disputados.html")
        self.assertIn("73 concorrentes em 12/09/2026, no meio da rodada", insight)
        self.assertIn("Candidatos em 12/09/2026, no meio da rodada", insight)

    def test_quanto_vale_quase_todos_ficam_sem_candidato(self):
        pagina = self._ler("insights", "quanto-vale-um-dominio-com-br.html")
        uma_linha = self._uma_linha("insights", "quanto-vale-um-dominio-com-br.html")
        self.assertNotIn("quase todos saem por esse preço, com um único candidato",
                          uma_linha)
        self.assertIn("quase todos voltam ao espaço livre", uma_linha)
        self.assertIn("94 em cada 100", uma_linha)
        self.assertIn("1.359", pagina)  # amostra do desfecho, nao da memoria
        self.assertIn("15.736", pagina)  # denominador
        self.assertIn("escolhidos pela nota", pagina)
        self.assertIn("a partir de dois", uma_linha)

    def test_numeros_de_2017_sao_so_da_primeira_rodada(self):
        for partes in (
            ("insights", "quanto-vale-um-dominio-com-br.html"),
            ("perguntas.html",),
            ("regras-do-br.html",),
            ("api-registrobr.html",),
        ):
            pagina = self._ler(*partes)
            self.assertNotIn("Nas primeiras rodadas", pagina, partes)
            self.assertNotIn("das primeiras rodadas", pagina, partes)
            self.assertNotIn("primeiras rodadas do processo competitivo",
                              pagina, partes)
            self.assertNotIn("primeiras rodadas, em 2017", pagina, partes)
            self.assertIn("primeira rodada", self._uma_linha(*partes), partes)
            self.assertIn("2017", pagina, partes)
        quanto_vale = self._ler("insights", "quanto-vale-um-dominio-com-br.html")
        self.assertIn("R$ 80 mil", quanto_vale)
        self.assertIn("dez/2017", quanto_vale)
        self.assertNotIn("recorde de três letras", quanto_vale)

    def test_r98_milhoes_e_fundo_da_fapesp_nao_a_anuidade(self):
        pagina = self._ler("insights", "brasil-vs-eua.html")
        self.assertIn("FAPESP", pagina)
        self.assertIn("1998", pagina)
        self.assertIn("2005", pagina)
        self.assertIn("04/09/2023", pagina)
        # o aviso nao pode ligar a anuidade de hoje aos centros de IA
        aviso = re.sub(r"\s+", " ",
                        pagina.split('<div class="aviso">')[-1].split("</div>")[0])
        self.assertNotIn("centro de pesquisa em IA", aviso)
        self.assertIn("NIC.br", aviso)

    def test_ticket_inativo_no_mesmo_dia_do_fechamento(self):
        pagina = self._ler("insights", "o-numero-do-ticket.html")
        uma_linha = self._uma_linha("insights", "o-numero-do-ticket.html")
        self.assertNotIn("um dia depois do fim da rodada", uma_linha)
        self.assertIn("no mesmo dia do fechamento da rodada de setembro", uma_linha)

    def test_pneus_arrematante_tem_fonte_e_nao_e_o_titular_de_hoje(self):
        pagina = self._ler("insights", "dominio-mais-caro-do-brasil.html")
        uma_linha = self._uma_linha("insights", "dominio-mais-caro-do-brasil.html")
        self.assertNotIn(
            "<strong>fev/2019</strong></td><td>a SUNSET PNEUS DO BRASIL LTDA "
            "arremata", uma_linha)
        self.assertIn("Angels Investimentos", pagina)
        self.assertIn("Bolsa de Domínios", uma_linha)
        self.assertIn("SUNSET PNEUS DO BRASIL LTDA", pagina)  # titular de hoje, via RDAP
        self.assertNotIn("até hoje o valor mais alto já pago por um domínio brasileiro",
                          uma_linha)
        self.assertIn("maior valor de leilão já", uma_linha)

    def test_pneus_valor_tem_atribuicao_segundo_e_data(self):
        # revisao pedida pelo revisor em 18/09/2026: nas paginas que citam os
        # R$ 220 mil so de passagem, a fonte e a data tem que aparecer junto
        # ("segundo <fonte>, <data>"), nao so em dominio-mais-caro-do-brasil
        for partes in (
            ("perguntas.html",),
            ("regras-do-br.html",),
            ("insights", "quanto-vale-um-dominio-com-br.html"),
        ):
            uma_linha = self._uma_linha(*partes)
            self.assertIn("220 mil", uma_linha, partes)
            self.assertIn("Bolsa de Domínios", uma_linha, partes)
            self.assertIn("18/09/2020", uma_linha, partes)
            self.assertIn("22/09/2020", uma_linha, partes)
        dm = self._uma_linha("insights", "dominio-mais-caro-do-brasil.html")
        self.assertNotIn("chegou à imprensa", dm)
        self.assertIn(
            'href="https://www.nic.br/noticia/na-midia/'
            'dominio-pneus-com-br-e-vendido-no-leilao-do-registro-br-por-r-220-mil/"',
            dm)

    def test_docs_mercado_br_vs_eua_pneus_nao_afirma_o_arrematante(self):
        # o mesmo erro corrigido no site (o1-site-numeros-com-data) estava
        # repetido neste doc, que vai ao repositorio publico
        caminho = os.path.join(os.path.dirname(__file__), "docs",
                                "mercado-br-vs-eua.md")
        with open(caminho, encoding="utf-8") as f:
            texto = f.read()
        self.assertNotIn(
            "a SUNSET PNEUS DO BRASIL LTDA arremata por R$ 220 mil", texto)
        self.assertIn("Angels Investimentos", texto)
        self.assertIn("Bolsa de Domínios", texto)
        self.assertIn("SUNSET PNEUS DO BRASIL LTDA", texto)  # titular de hoje, via RDAP

    def test_nenhum_valor_de_leilao_de_vacina_com_br(self):
        base = os.path.join(os.path.dirname(__file__), "site_modelo", "conteudo")
        for raiz, _dirs, arquivos in os.walk(base):
            for nome in arquivos:
                if not nome.endswith(".html"):
                    continue
                caminho = os.path.join(raiz, nome)
                with open(caminho, encoding="utf-8") as f:
                    texto = re.sub(r"\s+", " ", f.read())
                trecho = re.search(r".{0,80}vacina\.com\.br.{0,120}", texto,
                                    re.DOTALL)
                if trecho:
                    self.assertNotRegex(trecho.group(0), r"R\$\s*[\d.]+",
                                         f"{caminho}: valor de leilão perto de vacina.com.br")


def _contraste(cor1, cor2):
    """Razao de contraste WCAG entre duas cores #rgb ou #rrggbb."""
    def luminancia(cor):
        cor = cor.lstrip("#")
        if len(cor) == 3:
            cor = "".join(c * 2 for c in cor)
        r, g, b = (int(cor[i:i + 2], 16) / 255 for i in (0, 2, 4))
        canal = lambda c: c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4
        return 0.2126 * canal(r) + 0.7152 * canal(g) + 0.0722 * canal(b)
    l1, l2 = sorted((luminancia(cor1), luminancia(cor2)), reverse=True)
    return (l1 + 0.05) / (l2 + 0.05)


class TestContrasteNoEscuro(unittest.TestCase):
    """
    18/09/2026 (o2-site-contraste): no escuro, --azul vira claro (#7fb0f7)
    e os botoes principais, os passos 1-2-3, a letra atual e os botoes da
    ficha continuavam com `color: #fff`, dando 2,2:1 contra o WCAG pedir
    4,5:1. A borda dos campos (--borda) tambem so dava 1,3:1 contra o
    fundo. --sobre-azul e --borda-campo resolvem os dois.
    """

    def setUp(self):
        self.raiz = os.path.dirname(__file__)
        self.style_css = open(os.path.join(self.raiz, "web", "style.css"), encoding="utf-8").read()
        self.extra_css = open(os.path.join(self.raiz, "site_modelo", "extra.css"), encoding="utf-8").read()

    def _token(self, bloco, nome):
        m = re.search(re.escape(nome) + r":\s*(#[0-9a-fA-F]{3,6})", bloco)
        self.assertIsNotNone(m, f"{nome} nao encontrado no bloco")
        return m.group(1)

    def test_sobre_azul_e_borda_campo_tem_contraste_nos_tres_blocos(self):
        # :root (claro), o media prefers-color-scheme e o data-tema=escuro:
        # os dois blocos escuros tem de concordar, senao o sistema e a
        # escolha manual do tema divergem (AGENTS.md, os dois blocos
        # existem de proposito e precisam repetir os mesmos valores)
        raiz = self.style_css.split(":root {", 1)[1].split("\n}", 1)[0]
        escuro_sistema = self.style_css.split(
            '@media (prefers-color-scheme: dark) {', 1)[1].split("\n  }", 1)[0]
        escuro_manual = self.style_css.split(
            ':root[data-tema="escuro"] {', 1)[1].split("\n}", 1)[0]
        for nome, bloco in (("claro", raiz), ("escuro (sistema)", escuro_sistema),
                             ("escuro (data-tema)", escuro_manual)):
            azul = self._token(bloco, "--azul")
            sobre_azul = self._token(bloco, "--sobre-azul")
            papel = self._token(bloco if "--papel" in bloco else raiz, "--papel")
            borda_campo = self._token(bloco, "--borda-campo")
            self.assertGreaterEqual(_contraste(sobre_azul, azul), 4.5,
                                     f"--sobre-azul sobre --azul no {nome}")
            self.assertGreaterEqual(_contraste(borda_campo, papel), 3.0,
                                     f"--borda-campo sobre --papel no {nome}")
        self.assertEqual(self._token(escuro_sistema, "--sobre-azul"),
                          self._token(escuro_manual, "--sobre-azul"))
        self.assertEqual(self._token(escuro_sistema, "--borda-campo"),
                          self._token(escuro_manual, "--borda-campo"))

    def test_nenhum_fff_fixo_sobre_azul(self):
        # o unico color: #fff que pode sobrar e o do button.perigo (sem
        # uso no site, comentado); nenhum outro par com background/border
        # var(--azul) pode voltar a usar #fff fixo em vez de --sobre-azul
        for css, nome in ((self.style_css, "style.css"), (self.extra_css, "extra.css")):
            for m in re.finditer(r"\{[^{}]*var\(--azul\)[^{}]*\}", css):
                regra = m.group(0)
                if "perigo" in css[max(0, m.start() - 40):m.start()]:
                    continue
                self.assertNotIn("color: #fff", regra,
                                  f"{nome}: {regra!r} ainda usa #fff fixo sobre --azul")

    @so_com("site_modelo/conteudo/insights")
    def test_aviso_nota_destaque_existe_e_perigo_so_sobra_pro_risco_de_verdade(self):
        self.assertIn(".aviso.nota-destaque {", self.extra_css)
        conteudo = os.path.join(self.raiz, "site_modelo", "conteudo")
        arquivos_com_nota = [
            "perguntas.html", "como-selecionamos.html",
            os.path.join("insights", "genericos-que-viraram-cemiterio.html"),
            os.path.join("insights", "o-candidato-que-nao-aparece.html"),
        ]
        for rel in arquivos_com_nota:
            texto = open(os.path.join(conteudo, rel), encoding="utf-8").read()
            self.assertIn('class="aviso nota-destaque"', texto, rel)

    def test_piso_de_doze_px_nos_textos_pequenos_da_lista(self):
        for nome, css in (
            (".selo", self.style_css), (".pilula-elegivel", self.style_css),
            ("button.pontocom", self.style_css), (".cartao .ajuda", self.style_css),
            (".idade", self.extra_css), (".conferir", self.extra_css),
            (".etiqueta", self.extra_css),
        ):
            bloco = re.search(re.escape(nome) + r"\s*\{([^}]*)\}", css)
            self.assertIsNotNone(bloco, nome)
            tamanho = re.search(r"font-size:\s*([\d.]+)rem", bloco.group(1))
            self.assertIsNotNone(tamanho, nome)
            self.assertGreaterEqual(float(tamanho.group(1)), 0.75, nome)


class TestTextosDeDivulgacao(unittest.TestCase):
    """monetizacao/lancamento-textos.md (r3-textos-de-divulgacao, 19/09/2026):
    abre com o aviso, sem valor em reais, sem numero de ticket e sem
    "codigo aberto" antes da secao que so vale com o repositorio publico.
    Pula no publico, onde monetizacao/ nao atravessa."""

    CAMINHO = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                           "monetizacao", "lancamento-textos.md")

    def setUp(self):
        if not os.path.isfile(self.CAMINHO):
            self.skipTest("monetizacao/ fica no privado")
        with open(self.CAMINHO, encoding="utf-8") as f:
            self.texto = f.read()

    def test_abre_com_nao_postar_sem_o_dono(self):
        self.assertTrue(self.texto.lstrip("* ").lower().startswith("não postar sem o dono"))

    def test_sem_reais_nem_ticket(self):
        self.assertNotIn("R$", self.texto)
        self.assertIsNone(re.search(r"\b\d{8}\b", self.texto))

    def test_codigo_aberto_so_na_condicao_do_repositorio(self):
        corte = self.texto.index("## Só depois de o repositório público existir")
        antes = re.sub(r"\s+", " ", self.texto[:corte]).lower()
        self.assertNotIn("código aberto", antes)
        self.assertNotIn("git clone", antes)

    def test_regras_como_o_site_diz(self):
        # Revisao de 19/09: o limite vai de 3 a 200 (3 e so o minimo) e tres
        # travas dao elegibilidade ao leilao, que so abre se dois pedirem.
        corrido = re.sub(r"\s*\n>?\s*", " ", self.texto)
        self.assertNotIn("até três", corrido)
        self.assertNotIn("seguidas vai a leilão", corrido)
        self.assertIn("vai de 3 a 200", corrido)
        self.assertIn("fica elegível ao leilão na quarta", corrido)

    def test_quatro_textos_com_o_lema(self):
        partes = re.split(r"^## ", self.texto, flags=re.M)
        textos = [p for p in partes if re.match(r"[1-4]\. ", p)]
        self.assertEqual(len(textos), 4)
        for p in textos:
            self.assertIn("Todo mês, domínio bom volta.", re.sub(r"\s*\n>?\s*", " ", p), p[:30])
