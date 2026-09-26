"""
Lembrete do fim de cada leilao, como arquivo de calendario servido pelo site.

Por que arquivo servido, e nao gerado no navegador: o .ics montado em
JavaScript (blob) so baixa. No celular isso vira um arquivo perdido na pasta
de downloads, que ninguem abre. O mesmo .ics vindo de uma URL com
Content-Type text/calendar e aberto pelo Safari do iPhone direto na tela
"Adicionar ao Calendario". Para Android e computador a pagina oferece antes o
link do Google Agenda e do Outlook, que nao precisam de arquivo nenhum.

Todo leilao desta rodada termina no mesmo instante (fim da rodada + 24 h),
entao um arquivo por nome em leilao, gerado junto com o dados.json.
DETERMINISTICO (DTSTAMP = o proprio fim): o conteudo so muda quando o prazo
muda.

Desde 14/09/2026 tambem um arquivo por RODADA FUTURA, em lembretes/rodadas/:
o dia em que a lista sai e a hora em que a rodada abre. E o que a pagina
inicial oferece entre rodadas e o que a ficha "quando esse dominio volta?"
oferece no iPhone (o nome consultado vai no link do Google e do Outlook; no
arquivo servido vai so a rodada, que e igual para todo mundo).
"""

from __future__ import annotations

import os
import shutil
from datetime import datetime, timedelta, timezone

from ..dominio import calendario

MINUTOS_ANTES = 30        # o evento cobre a meia hora final
AVISO_MINUTOS = 15        # e o alarme toca 15 min antes dela comecar
PAINEL = "https://registro.br/painel/dominios/processo-competitivo/"


def fim_do_leilao(fim_da_rodada: str | None,
                  agora: datetime | None = None) -> datetime | None:
    """
    O PISO do leilao: a primeira hora em que ele pode fechar. Nunca o fim.

    Candidatura vale ate o fim da rodada, e a regra garante "pelo menos"
    24 h so de ofertas depois disso. Nao existe fonte publica da hora em que
    um leilao fecha: o `date=` do RDAP e o `ends-at` do avail sao os dois o
    fim da RODADA (conferido em 17/09/2026). No mesmo dia, groupon.com.br
    seguia em leilao com este piso vencido havia horas.

    Passado o piso nao ha data honesta para colocar num convite, e devolver
    None faz `escrever()` apagar a pasta em vez de servir evento morto.
    """
    if not fim_da_rodada:
        return None
    try:
        fim = datetime.fromisoformat(fim_da_rodada)
    except ValueError:
        return None
    if fim.tzinfo is None:
        fim = fim.replace(tzinfo=timezone(timedelta(hours=-3)))
    piso = fim + timedelta(hours=24)
    if piso <= (agora or datetime.now(timezone.utc)):
        return None
    return piso


def _utc(quando: datetime) -> str:
    return quando.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _texto(s: str) -> str:
    return s.replace("\\", "\\\\").replace(",", "\\,").replace(";", "\\;")


def _dobrar(linha: str) -> str:
    """RFC 5545: ate 75 bytes por linha, sem partir caractere UTF-8 ao meio."""
    pedacos, atual, limite = [], "", 75
    for c in linha:
        if len((atual + c).encode("utf-8")) > limite:
            pedacos.append(atual)
            atual, limite = "", 74          # o espaco da continuacao conta
        atual += c
    pedacos.append(atual)
    return "\r\n ".join(pedacos)


def ics(dominio: str, fim: datetime) -> str:
    inicio = fim - timedelta(minutes=MINUTOS_ANTES)
    hora = fim.astimezone(timezone(timedelta(hours=-3))).strftime("%d/%m às %Hh%M")
    descricao = "\\n".join(_texto(s) for s in (
        f"Não termina antes de {hora} (horário de Brasília); pode ir além.",
        "O Registro.br não publica a hora em que cada leilão fecha.",
        "Lance nos 10 minutos finais prorroga por mais 10.",
        "O Registro.br não avisa quando cobrem o seu lance.",
        "Oferta é vinculante: pagar em até 15 dias.",
    ))
    linhas = [
        "BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//garimpo-br//leilao//PT",
        "CALSCALE:GREGORIAN", "METHOD:PUBLISH", "BEGIN:VEVENT",
        f"UID:leilao-{dominio}-{_utc(fim)}@garimpo-br",
        f"DTSTAMP:{_utc(fim)}",
        f"DTSTART:{_utc(inicio)}", f"DTEND:{_utc(fim)}",
        "SUMMARY:" + _texto(f"Leilão de {dominio}: pode fechar a partir daqui"),
        "DESCRIPTION:" + descricao,
        f"URL:{PAINEL}",
        "BEGIN:VALARM", "ACTION:DISPLAY", f"TRIGGER:-PT{AVISO_MINUTOS}M",
        "DESCRIPTION:" + _texto(f"Leilão de {dominio} pode fechar a partir de agora"),
        "END:VALARM", "END:VEVENT", "END:VCALENDAR",
    ]
    return "\r\n".join(_dobrar(l) for l in linhas) + "\r\n"


def escrever(diretorio: str, dominios, fim: datetime | None) -> int:
    """Refaz a pasta inteira: leilao que acabou nao deixa arquivo velho."""
    shutil.rmtree(diretorio, ignore_errors=True)
    if fim is None:
        return 0
    os.makedirs(diretorio, exist_ok=True)
    total = 0
    for dominio in sorted(set(dominios)):
        with open(os.path.join(diretorio, f"{dominio}.ics"), "w",
                  encoding="utf-8", newline="") as f:
            f.write(ics(dominio, fim))
        total += 1
    return total


MESES = ("janeiro fevereiro março abril maio junho julho agosto setembro "
         "outubro novembro dezembro").split()
PROCESSO = "https://registro.br/dominio/processo-de-liberacao/"


def ics_da_rodada(abre: datetime) -> str:
    """Dois eventos: o dia em que a lista sai (dia inteiro) e a abertura."""
    lista = calendario.saida_da_lista(abre)
    fecha = calendario.fechamento(abre)
    mes = MESES[abre.month - 1]
    ate = fecha.astimezone(calendario.BRASILIA).strftime("%d/%m às %Hh")
    dia = lista.strftime("%Y%m%d")
    dia_seguinte = (lista + timedelta(days=1)).strftime("%Y%m%d")
    carimbo = _utc(abre)
    linhas = [
        "BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//liberado//rodada//PT",
        "CALSCALE:GREGORIAN", "METHOD:PUBLISH",
        "BEGIN:VEVENT",
        f"UID:lista-{abre.date().isoformat()}@liberado",
        f"DTSTAMP:{carimbo}",
        f"DTSTART;VALUE=DATE:{dia}", f"DTEND;VALUE=DATE:{dia_seguinte}",
        "SUMMARY:" + _texto(f"Sai a lista da rodada de liberação de {mes}"),
        "DESCRIPTION:" + "\\n".join(_texto(t) for t in (
            "O Registro.br publica os domínios .br que voltam ao mercado.",
            "A rodada abre dois dias depois, às 15h de Brasília.",
            "Data pela regra da segunda quarta-feira; feriado pode mudar.")),
        f"URL:{PROCESSO}",
        "END:VEVENT",
        "BEGIN:VEVENT",
        f"UID:rodada-{abre.date().isoformat()}@liberado",
        f"DTSTAMP:{carimbo}",
        f"DTSTART:{_utc(abre)}", f"DTEND:{_utc(abre + timedelta(minutes=30))}",
        "SUMMARY:" + _texto(f"Rodada de liberação de {mes} abre às 15h"),
        "DESCRIPTION:" + "\\n".join(_texto(t) for t in (
            f"Candidaturas de graça até {ate} (horário de Brasília).",
            "Se só você pedir o nome, ele é seu pela anuidade.")),
        f"URL:{PROCESSO}",
        "BEGIN:VALARM", "ACTION:DISPLAY", f"TRIGGER:-PT{AVISO_MINUTOS}M",
        "DESCRIPTION:" + _texto(f"A rodada de liberação de {mes} abre às 15h"),
        "END:VALARM", "END:VEVENT", "END:VCALENDAR",
    ]
    return "\r\n".join(_dobrar(l) for l in linhas) + "\r\n"


def escrever_rodadas(diretorio: str, aberturas) -> int:
    """
    Um .ics por rodada futura, em lembretes/rodadas/AAAA-MM-DD.ics. Chamar
    DEPOIS de escrever(), que apaga a pasta lembretes/ inteira.
    """
    pasta = os.path.join(diretorio, "rodadas")
    shutil.rmtree(pasta, ignore_errors=True)
    os.makedirs(pasta, exist_ok=True)
    total = 0
    for abre in aberturas:
        with open(os.path.join(pasta, f"{abre.date().isoformat()}.ics"), "w",
                  encoding="utf-8", newline="") as f:
            f.write(ics_da_rodada(abre))
        total += 1
    return total
