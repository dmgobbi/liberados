/*
 * O quadro "hoje" das paginas de cada letra (/insights/dominios-de-uma-letra/x-com-br/),
 * 15/09/2026.
 *
 * Quem e o dono de x.com.br hoje sai do RDAP do Registro.br, consultado
 * DAQUI, do navegador de quem olha (Disputa.consultar, em disputa.js), uma
 * consulta ao abrir a pagina. O nome do titular e o que a busca do
 * Registro.br mostra a qualquer um; ele nunca fica no HTML nem no git
 * (CLAUDE.md, "Dado publico pode ir ao site"). Documento, endereco, e-mail e
 * legalRepresentative nunca.
 *
 * Sem JavaScript, ou se a consulta falhar, fica o texto do build, que manda
 * para a ficha Quando volta.
 */
(function () {
  'use strict';

  const FUSO = 'America/Sao_Paulo';
  const esc = (v) => String(v ?? '').replace(/[&<>"']/g, (c) => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  const dia = (s) => {
    const d = s ? new Date(s) : null;
    return d && !isNaN(d) ? d.toLocaleDateString('pt-BR', { timeZone: FUSO,
      day: '2-digit', month: '2-digit', year: 'numeric' }) : '';
  };

  function desenhar(alvo, nome, res) {
    const agora = new Date().toLocaleString('pt-BR', { timeZone: FUSO, day: '2-digit',
      month: '2-digit', year: 'numeric', hour: '2-digit', minute: '2-digit' });
    const fonte = `<p class="ficha-nota">Consultado agora (${esc(agora)}) no RDAP do Registro.br, `
      + 'pelo seu navegador. Nada disso fica guardado no Liberados.</p>';
    if (res.status === 404) {
      alvo.innerHTML = `<p><code>${esc(nome)}</code> <strong>não existe mais</strong> no Registro.br. `
        + 'Pela regra dos 2 a 26 caracteres, não pode ser registrado de novo.</p>' + fonte;
      return;
    }
    const j = res.json || {};
    const ev = {};
    for (const e of j.events || []) ev[e.eventAction] = e.eventDate;
    const entidade = (j.entities || []).find((e) => (e.roles || []).includes('registrant'));
    const campos = ((entidade || {}).vcardArray || [])[1] || [];
    const fn = campos.find((c) => Array.isArray(c) && c[0] === 'fn');
    const status = (j.status || []).map((s) => String(s).toLowerCase());
    const vencido = ev.expiration && new Date(ev.expiration) < new Date();
    const situacao = status.includes('inactive') ? 'congelado: venceu e saiu do ar'
      : vencido ? 'vencido, ainda não pago' : 'ativo';
    const linhas = [
      fn && fn[3] ? `<li>Titular: <strong>${esc(fn[3])}</strong></li>` : '',
      ev.registration ? `<li>Registrado em ${esc(dia(ev.registration))}</li>` : '',
      ev.expiration ? `<li>Pago até <strong>${esc(dia(ev.expiration))}</strong></li>` : '',
      `<li>Situação: ${esc(situacao)}</li>`,
    ].join('');
    alvo.innerHTML = `<ul class="letra-hoje">${linhas}</ul>${fonte}`;
  }

  async function iniciar() {
    const alvo = document.querySelector('[data-letra-hoje]');
    if (!alvo || !window.Disputa || !window.Disputa.consultar) return;
    const nome = alvo.dataset.letraHoje;
    try {
      desenhar(alvo, nome, await window.Disputa.consultar('domain/' + encodeURIComponent(nome)));
    } catch (e) {
      alvo.innerHTML = `<p>Não deu para consultar o Registro.br agora (${esc(e.message)}). `
        + `Veja na <a href="/quando-volta/?d=${encodeURIComponent(nome)}">ficha Quando volta</a>.</p>`;
    }
  }

  iniciar();
})();
