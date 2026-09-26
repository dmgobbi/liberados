/*
 * Lembrete na agenda de quem usa: Google Agenda, Outlook e Calendario da
 * Apple. Um modulo so para o fim do leilao (app.js), a proxima rodada
 * (pagina inicial) e a volta prevista de um dominio (ficha.js).
 *
 * Por que tres caminhos, e nessa ordem (decidido em 11/09/2026 com o
 * lembrete do leilao, que morava no app.js): .ics montado aqui (blob) so
 * baixa, e no celular vira arquivo perdido nos downloads. Google e Outlook
 * abrem o evento pronto por link. No iPhone e no Mac o que funciona e o
 * .ics SERVIDO pelo site com Content-Type text/calendar (_headers), que
 * o Safari abre na tela "Adicionar ao Calendario"; o blob fica de reserva
 * para quando nao ha arquivo servido.
 *
 *   Agenda.abrir({
 *     cabecalho, texto, nota,          // o que o dialogo diz
 *     titulo, detalhes, inicio, fim,   // o evento (Date)
 *     url, alarmeMinutos, uid,
 *     servido,                          // caminho de um .ics do site, se houver
 *     arquivo,                          // nome do .ics de reserva
 *   })
 *
 * O dialogo e criado na primeira vez, com as classes que o leilao ja usava
 * (.dialogo, .opcoes-lembrete).
 */
(function () {
  'use strict';

  let dialogo = null;

  const utc = (d) => d.toISOString().replace(/[-:]/g, '').replace(/\.\d{3}/, '');

  function eApple() {
    return /iPhone|iPad|iPod|Macintosh/.test(navigator.userAgent);
  }

  function montar() {
    if (dialogo) return dialogo;
    dialogo = document.createElement('dialog');
    dialogo.className = 'dialogo';
    dialogo.setAttribute('aria-labelledby', 'agenda-titulo');
    // o corpo separado da borda do <dialog> e o que permite fechar tocando
    // fora: o clique no fundo cai no proprio <dialog>, nunca no corpo
    dialogo.innerHTML = '<div class="dialogo-corpo">'
      + '<h2 id="agenda-titulo"></h2><p id="agenda-texto"></p>'
      + '<div id="agenda-opcoes" class="opcoes-lembrete"></div>'
      + '<p id="agenda-nota" class="nota-lembrete"></p>'
      + '<button type="button" class="discreto" id="agenda-fechar">Fechar</button></div>';
    document.body.appendChild(dialogo);
    dialogo.querySelector('#agenda-fechar').addEventListener('click', () => dialogo.close());
    dialogo.addEventListener('click', (e) => { if (e.target === dialogo) dialogo.close(); });
    return dialogo;
  }

  function opcao(titulo, detalhe, href, extra = {}) {
    const a = document.createElement(href ? 'a' : 'button');
    a.className = 'opcao';
    if (href) {
      a.href = href;
      if (extra.novaAba) { a.target = '_blank'; a.rel = 'noopener noreferrer'; }
    } else {
      a.type = 'button';
      a.addEventListener('click', extra.aoClicar);
    }
    const forte = document.createElement('strong');
    forte.textContent = titulo;
    const fraco = document.createElement('span');
    fraco.textContent = detalhe;
    a.append(forte, fraco);
    return a;
  }

  /** O texto do .ics (RFC 5545), com alarme. */
  function ics(ev) {
    const texto = (s) => String(s).replace(/[\\,;]/g, (c) => '\\' + c).replace(/\n/g, '\\n');
    const linhas = [
      'BEGIN:VCALENDAR', 'VERSION:2.0', 'PRODID:-//liberado//agenda//PT',
      'CALSCALE:GREGORIAN', 'METHOD:PUBLISH', 'BEGIN:VEVENT',
      `UID:${ev.uid || utc(ev.inicio)}@liberado`,
      `DTSTAMP:${utc(new Date())}`,
      `DTSTART:${utc(ev.inicio)}`, `DTEND:${utc(ev.fim)}`,
      'SUMMARY:' + texto(ev.titulo),
      'DESCRIPTION:' + texto(ev.detalhes || ''),
    ];
    if (ev.url) linhas.push('URL:' + ev.url);
    linhas.push('BEGIN:VALARM', 'ACTION:DISPLAY', `TRIGGER:-PT${ev.alarmeMinutos || 15}M`,
                'DESCRIPTION:' + texto(ev.titulo), 'END:VALARM', 'END:VEVENT', 'END:VCALENDAR');
    // ate 75 bytes por linha; a continuacao comeca com espaco. Corta por
    // bytes UTF-8 sem partir caractere ao meio (acento ocupa 2 bytes).
    const codificador = new TextEncoder();
    const dobrar = (linha) => {
      const pedacos = [];
      let atual = '', limite = 75;
      for (const c of linha) {
        if (codificador.encode(atual + c).length > limite) {
          pedacos.push(atual);
          atual = '';
          limite = 74;
        }
        atual += c;
      }
      pedacos.push(atual);
      return pedacos.join('\r\n ');
    };
    return linhas.map(dobrar).join('\r\n') + '\r\n';
  }

  function baixar(ev) {
    const blob = new Blob([ics(ev)], { type: 'text/calendar;charset=utf-8' });
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = ev.arquivo || 'lembrete.ics';
    a.click();
    URL.revokeObjectURL(a.href);
  }

  function abrir(ev) {
    const d = montar();
    const detalhes = ev.detalhes + (ev.url ? ` ${ev.url}` : '');
    const google = 'https://calendar.google.com/calendar/render?' + new URLSearchParams({
      action: 'TEMPLATE', text: ev.titulo, details: detalhes,
      dates: `${utc(ev.inicio)}/${utc(ev.fim)}`,
    });
    const outlook = 'https://outlook.live.com/calendar/0/deeplink/compose?' + new URLSearchParams({
      path: '/calendar/action/compose', rru: 'addevent', subject: ev.titulo, body: detalhes,
      startdt: ev.inicio.toISOString(), enddt: ev.fim.toISOString(),
    });
    const opcoes = {
      google: opcao('Google Agenda', 'Abre o evento pronto; é só salvar', google, { novaAba: true }),
      apple: ev.servido
        ? opcao('Calendário do iPhone ou Mac', 'Abre a tela de adicionar ao Calendário, com alarme',
                ev.servido)
        : opcao('Arquivo de calendário (.ics)', 'Para Calendário da Apple e outros apps',
                null, { aoClicar: () => baixar(ev) }),
      outlook: opcao('Outlook', 'Outlook.com, Hotmail ou Microsoft 365', outlook, { novaAba: true }),
    };
    const ordem = eApple() ? ['apple', 'google', 'outlook'] : ['google', 'outlook', 'apple'];
    d.querySelector('#agenda-titulo').textContent = ev.cabecalho || ev.titulo;
    d.querySelector('#agenda-texto').textContent = ev.texto || '';
    const nota = d.querySelector('#agenda-nota');
    nota.textContent = ev.nota || '';
    nota.hidden = !ev.nota;
    d.querySelector('#agenda-opcoes').replaceChildren(...ordem.map((k) => opcoes[k]));
    d.showModal();
  }

  window.Agenda = { abrir, ics, baixar };
})();
