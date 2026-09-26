/*
 * Quem disputa um nome: os candidatos por tras de cada ticket.
 *
 * E a mesma consulta que a busca do Registro.br faz quando alguem clica num
 * ticket, feita aqui no navegador de quem esta olhando (o RDAP responde com
 * CORS aberto), sob demanda, com a cota de consultas do proprio IP. Nada
 * passa pelo servidor do site e nada e guardado alem desta aba.
 *
 * O que sai por ticket, conferido ao vivo em 12/09/2026:
 *   - `events[registration]`: o instante exato em que o ticket foi emitido
 *   - a entidade `registrant`: nome (vcard fn) e documento mascarado
 *     (publicIds: cpf ou cnpj)
 *   - para CNPJ, uma consulta a mais em /entity/<cnpj> traz
 *     `nicbr_domainCount`, quantos dominios a empresa tem
 *
 * Ritmo: uma consulta por vez, 2,5 s entre elas, dez tickets por vez. O RDAP
 * expoe o cabecalho Nicbr-Rate-Limit-Exceeded (visto em 12/09/2026); um 429
 * no /domain/ bloqueia consultas novas por 5 min (18/09/2026, a mesma cota
 * do IP que a conferencia ao vivo e a ficha usam por cima de consultar()). O
 * /entity/ e mais restrito e um 429 ali so pula a entidade do resto do lote,
 * sem bloquear o /domain/.
 *
 * Usado pelo site (site_modelo) e pelo app local (web): os dois so precisam
 * de um botao com data-disputa="<dominio>" e deste arquivo.
 */
(function () {
  'use strict';

  const RDAP = 'https://rdap.registro.br/';
  const PAUSA = 2500;
  const LOTE = 10;
  // Depois de um 429 no /domain/, nenhuma consulta nova por 5 min: e a cota
  // do IP, compartilhada com a conferencia ao vivo (app.js) e a ficha
  // (ficha.js), as duas por cima desta funcao. O /entity/ e "bem mais
  // restrito" (comentario acima) e um 429 ali nao prova que o /domain/
  // tambem esta no limite, entao ele NAO entra neste bloqueio global
  // (ver candidato()).
  const BLOQUEIO = 5 * 60 * 1000;
  const CHAVE_BLOQUEIO = 'disputa_bloqueado_ate';
  // sessionStorage, nao localStorage: some com a aba, como o resto da
  // consulta (cabecalho do arquivo), mas sobrevive a um F5 -- sem isto, dar
  // reload logo depois de um 429 zerava o bloqueio e reabria a rajada bem no
  // momento em que o Registro.br pediu para parar.
  let bloqueadoAte = (() => {
    try {
      const v = Number(sessionStorage.getItem(CHAVE_BLOQUEIO));
      return Number.isFinite(v) ? v : 0;
    } catch (e) { return 0; }         // aba anonima ou storage bloqueado
  })();

  const cache = new Map();          // dominio -> { tickets, candidatos: Map }
  let dialogo = null;
  let aberto = null;                // dominio na tela
  let lidoAberto = '';              // idade da leitura da lista, do botao que abriu
  let ocupado = false;
  let pendente = false;             // abriram outro nome enquanto este carregava
  let reativarAgendado = false;     // ja tem um setTimeout para repintar quando o bloqueio passar

  const esc = (v) => String(v ?? '').replace(/[&<>"']/g, (c) => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  const esperar = (ms) => new Promise((r) => setTimeout(r, ms));

  function restanteBloqueio() {
    return Math.max(0, bloqueadoAte - Date.now());
  }

  function bloqueado() {
    return restanteBloqueio() > 0;
  }

  function mensagemBloqueio() {
    const min = Math.max(1, Math.ceil(restanteBloqueio() / 60000));
    return `Não deu para conferir agora; tente de novo em ${min} min.`;
  }

  function registrarBloqueio() {
    bloqueadoAte = Date.now() + BLOQUEIO;
    try { sessionStorage.setItem(CHAVE_BLOQUEIO, String(bloqueadoAte)); } catch (e) { /* vale so nesta execucao */ }
  }

  function hora(iso) {
    if (!iso) return '';
    const d = new Date(iso);
    if (isNaN(d)) return '';
    return d.toLocaleString('pt-BR', {
      timeZone: 'America/Sao_Paulo', day: '2-digit', month: '2-digit',
      hour: '2-digit', minute: '2-digit', second: '2-digit' });
  }

  /**
   * Uma consulta ao RDAP: status HTTP, o cabecalho Nicbr-Resource (em que
   * processo o nome esta) e o JSON. 404 volta como resposta, nao como erro:
   * para a ficha (ficha.js) ele quer dizer "livre".
   */
  async function consultar(caminho) {
    if (bloqueado()) throw new Error(mensagemBloqueio());
    let r;
    try {
      r = await fetch(RDAP + caminho, {
        credentials: 'omit', cache: 'no-store', referrerPolicy: 'no-referrer',
        headers: { Accept: 'application/rdap+json' } });
    } catch (e) {
      throw new Error('o Registro.br não respondeu');
    }
    if (r.status === 429 || r.headers.get('nicbr-rate-limit-exceeded')) {
      if (!caminho.startsWith('entity/')) registrarBloqueio();
      throw new Error(caminho.startsWith('entity/')
        ? 'limite de consultas do Registro.br atingido; espere alguns minutos'
        : mensagemBloqueio());
    }
    const recurso = r.headers.get('nicbr-resource') || '';
    if (r.status === 404) return { status: 404, recurso, json: null };
    if (!r.ok) throw new Error(`o Registro.br respondeu ${r.status}`);
    return { status: r.status, recurso, json: await r.json() };
  }

  async function buscar(caminho) {
    return (await consultar(caminho)).json;
  }

  function vcard(entidade) {
    const campos = ((entidade || {}).vcardArray || [])[1] || [];
    const saida = {};
    for (const c of campos) if (Array.isArray(c) && c.length >= 4) saida[c[0]] = c[3];
    return saida;
  }

  function candidatoDe(json) {
    const entidades = (json && json.entities) || [];
    const ent = entidades.find((e) => (e.roles || []).includes('registrant')) || entidades[0] || {};
    const pid = (ent.publicIds || [])[0] || {};
    const ev = ((json && json.events) || []).find((e) => e.eventAction === 'registration') || {};
    return {
      nome: vcard(ent).fn || '',
      tipo: (pid.type || '').toLowerCase(),
      documento: pid.identifier || '',
      quando: ev.eventDate || '',
      dominios: null,
    };
  }

  function dataComAno(iso) {
    if (!iso) return '';
    const d = new Date(iso);
    if (isNaN(d)) return '';
    return d.toLocaleString('pt-BR', {
      timeZone: 'America/Sao_Paulo', day: '2-digit', month: '2-digit',
      year: 'numeric', hour: '2-digit', minute: '2-digit' });
  }

  /**
   * O nome inteiro, numa consulta: os tickets e, para quando nao ha nenhum,
   * a fase em que o RDAP o poe. A ordem dos cabecalhos e a de consultarRdap
   * (site_modelo/app.js), repetida aqui de proposito: la a funcao e testada
   * isolada, so com window.Disputa.consultar.
   *
   * 19/09/2026, cagada.com.br: a lista dizia "pedido pendente, 1 candidato"
   * (leitura de 3 dias antes) e o RDAP ja dava o nome registrado, sem
   * publicIds, so com o evento `registration`. Pedido concluido, ticket
   * some; o painel precisa dizer isso em vez de ficar vazio.
   */
  async function lerNome(dominio) {
    const r = await consultar('domain/' + encodeURIComponent(dominio));
    const json = r.json || {};
    const tickets = (json.publicIds || [])
      .filter((p) => p && p.type === 'ticket' && /^\d+$/.test(String(p.identifier)))
      .map((p) => Number(p.identifier))
      .sort((a, b) => a - b);
    const recurso = r.recurso || '';
    const status = json.status || [];
    const ev = (json.events || []).find((e) => e.eventAction === 'registration') || {};
    let fase = 'desconhecida';
    if (r.status === 404) fase = 'livre';
    else if (recurso.startsWith('competitive-release-process-')) fase = 'leilao';
    else if (recurso.startsWith('release-process-waiting')) fase = 'travado';
    else if (recurso.startsWith('release-process-running')) fase = 'rodada';
    else if (tickets.length || status.includes('pending create')) fase = 'pendente';
    else if (ev.eventDate || (json.objectClassName === 'domain' && status.length)) fase = 'registrado';
    return { tickets, fase, registro: ev.eventDate || '' };
  }

  /**
   * O que dizer quando o RDAP nao lista ticket nenhum. `lido` e a leitura da
   * lista (texto como "há 3 d", do botao que abriu o painel), para a pessoa
   * ver que o numero dela era antigo, e nao que o painel falhou.
   */
  function semTicket(info, lido) {
    const antes = lido ? ` O número da lista é de uma leitura feita ${lido}.` : '';
    switch (info.fase) {
      case 'registrado': {
        const quando = dataComAno(info.registro);
        // `registration` e a hora do pedido, nao a da conclusao (S16: o de
        // liberados.com.br marca 12h39 e o Pix foi 12h42), por isso "o RDAP da"
        return 'Este nome já está registrado'
          + (quando ? ` (o RDAP dá ${quando} como data do registro)` : '')
          + ' e o RDAP não lista mais o ticket do pedido.' + antes;
      }
      case 'livre':
        return 'Este nome está livre agora: o RDAP não tem pedido nem registro dele.' + antes;
      case 'travado':
        return 'Este nome travou e espera a próxima rodada; depois do fechamento o RDAP '
          + 'não lista mais os tickets.' + antes;
      case 'rodada':
        return 'Nenhum candidato visível agora. Com um só, o Registro.br não lista ninguém: '
          + 'zero aqui pode ser um.';
      case 'pendente':
        return 'Há um pedido pendente, mas o RDAP não mostra o ticket dele.' + antes;
      default:
        return 'nenhum ticket visível para este nome.';
    }
  }

  /**
   * `lote.pularEntidade`: depois de um 429 no /entity/ (endpoint bem mais
   * restrito, ver PAUSA acima), os proximos candidatos do MESMO lote pulam
   * so a consulta de entidade; nome e documento, que ja vieram do
   * /domain/?ticket=, continuam aparecendo (F-bug de 18/09: um 429 ali
   * esvaziava a lista inteira e travava o resto dos tickets).
   */
  async function candidato(dominio, ticket, lote) {
    const json = await buscar('domain/' + encodeURIComponent(dominio) + '?ticket=' + ticket);
    const c = candidatoDe(json);
    if (c.tipo === 'cnpj' && !lote.pularEntidade) {
      const digitos = c.documento.replace(/\D/g, '');
      if (digitos.length === 14) {
        await esperar(PAUSA);
        try {
          const ent = await buscar('entity/' + digitos);
          if (ent && typeof ent.nicbr_domainCount === 'number') c.dominios = ent.nicbr_domainCount;
        } catch (e) {
          lote.pularEntidade = true;
        }
      }
    }
    return c;
  }

  // ------------------------------------------------------------ interface

  function montar() {
    if (dialogo) return dialogo;
    dialogo = document.createElement('dialog');
    dialogo.className = 'dialogo dialogo-disputa';
    dialogo.setAttribute('aria-labelledby', 'disputa-titulo');
    dialogo.innerHTML = `
      <div class="dialogo-corpo">
        <h2 id="disputa-titulo">Quem disputa</h2>
        <p id="disputa-resumo" class="disputa-resumo"></p>
        <div class="rolagem" id="disputa-caixa" hidden>
          <table class="disputa-tabela" role="table">
            <thead><tr role="row">
              <th scope="col">#</th><th scope="col">Pedido em</th>
              <th scope="col">Candidato</th><th scope="col">Documento</th>
              <th scope="col" class="num">Domínios</th>
            </tr></thead>
            <tbody id="disputa-corpo"></tbody>
          </table>
        </div>
        <p id="disputa-status" class="disputa-status" aria-live="polite"></p>
        <p class="disputa-nota">Consulta feita pelo seu navegador direto no RDAP do
          Registro.br, o mesmo dado da busca oficial. Dez por vez, para respeitar o
          limite por IP. Pessoa física aparece com o CPF mascarado, como lá.</p>
        <div class="disputa-acoes">
          <button type="button" id="disputa-mais" class="conferir">carregar mais 10</button>
          <button type="button" id="disputa-fechar" class="discreto">Fechar</button>
        </div>
      </div>`;
    document.body.appendChild(dialogo);
    dialogo.addEventListener('click', (e) => { if (e.target === dialogo) dialogo.close(); });
    dialogo.querySelector('#disputa-fechar').addEventListener('click', () => dialogo.close());
    dialogo.querySelector('#disputa-mais').addEventListener('click', () => carregar(aberto));
    return dialogo;
  }

  function linha(ticket, c) {
    if (!c) {
      return `<tr role="row"><td role="cell">${ticket}</td><td role="cell" colspan="4" class="disputa-pendente">…</td></tr>`;
    }
    const tipo = c.tipo ? c.tipo.toUpperCase() + ' ' : '';
    const dominios = c.dominios === null || c.dominios === undefined ? '' : String(c.dominios);
    return `<tr role="row">
      <td role="cell">${ticket}</td>
      <td role="cell">${esc(hora(c.quando))}</td>
      <td role="cell">${esc(c.nome || '?')}</td>
      <td role="cell">${esc(tipo + c.documento)}</td>
      <td role="cell" class="num">${esc(dominios)}</td>
    </tr>`;
  }

  // So desenha o nome que esta na tela agora: abrir outro nome enquanto este
  // carregava nao pode pintar os candidatos do primeiro por cima do titulo
  // do segundo (F-bug de 18/09).
  function pintar(dominio) {
    if (dominio !== aberto) return;
    const d = montar();
    const info = cache.get(dominio) || { tickets: [], candidatos: new Map() };
    d.querySelector('#disputa-titulo').textContent = `Quem disputa ${dominio}`;
    const n = info.tickets.length;
    // "candidato unico nao aparece" e regra da rodada (liberacao); num pedido
    // comum pendente o ticket unico aparece, e a frase contradizia o "1"
    const naRodada = info.fase === 'rodada' || info.fase === 'leilao';
    d.querySelector('#disputa-resumo').textContent = n
      ? `${n} ${n === 1 ? 'ticket visível' : 'tickets visíveis'}, do primeiro ao último.`
        + (naRodada ? ' Candidato único não aparece: com um só, o Registro.br não lista ninguém.' : '')
      : '';
    const feitos = info.tickets.filter((t) => info.candidatos.has(t));
    d.querySelector('#disputa-corpo').innerHTML =
      feitos.map((t) => linha(t, info.candidatos.get(t))).join('');
    // tabela so com linha: cabecalho sozinho parecia resultado vazio
    d.querySelector('#disputa-caixa').hidden = feitos.length === 0;
    const faltam = n - feitos.length;
    const mais = d.querySelector('#disputa-mais');
    // nunca "carregar mais 0" (19/09/2026): o botao so existe com o que carregar
    mais.hidden = faltam <= 0 || ocupado;
    mais.disabled = bloqueado();
    if (faltam > 0) mais.textContent = `carregar mais ${Math.min(LOTE, faltam)}`;
    mais.title = bloqueado() ? mensagemBloqueio() : '';
    // sem isto, o botao ficava desabilitado para sempre depois do bloqueio:
    // nada mais chama pintar() enquanto ninguem interage com o dialogo
    if (bloqueado() && !reativarAgendado) {
      reativarAgendado = true;
      // 'aberto', nao 'dominio': se trocou de nome enquanto o timer esperava,
      // repinta o nome atual, senao o "carregar mais" dele fica preso
      setTimeout(() => { reativarAgendado = false; pintar(aberto); }, restanteBloqueio() + 200);
    }
  }

  function status(texto, dominio) {
    if (dialogo && dominio === aberto) dialogo.querySelector('#disputa-status').textContent = texto;
  }

  async function carregar(dominio) {
    if (ocupado) { pendente = true; return; }
    ocupado = true;
    pintar(dominio);
    try {
      let info = cache.get(dominio);
      if (!info) {
        status('listando os tickets…', dominio);
        info = Object.assign(await lerNome(dominio), { candidatos: new Map() });
        cache.set(dominio, info);
        pintar(dominio);
        if (dominio !== aberto || !dialogo.open) return;
        if (!info.tickets.length) {
          status(semTicket(info, lidoAberto), dominio);
          return;
        }
        await esperar(PAUSA);
      }
      if (dominio !== aberto || !dialogo.open) return;
      if (!info.tickets.length) {
        status(semTicket(info, lidoAberto), dominio);
        return;
      }
      const pendentes = info.tickets.filter((t) => !info.candidatos.has(t)).slice(0, LOTE);
      const lote = { pularEntidade: false };
      for (let i = 0; i < pendentes.length; i++) {
        if (dominio !== aberto || !dialogo.open) return;
        const t = pendentes[i];
        status(`consultando ${i + 1} de ${pendentes.length}… (${info.candidatos.size} de ${info.tickets.length} já lidos)`, dominio);
        info.candidatos.set(t, await candidato(dominio, t, lote));
        pintar(dominio);
        if (dominio !== aberto || !dialogo.open) return;
        if (i + 1 < pendentes.length) await esperar(PAUSA);
      }
      const restam = info.tickets.length - info.candidatos.size;
      status(restam ? `${info.candidatos.size} de ${info.tickets.length} lidos.` : 'todos lidos.', dominio);
    } catch (e) {
      status(`parou: ${e.message}`, dominio);
    } finally {
      ocupado = false;
      pintar(dominio);
      // so continua sozinho se o pedido pendente era de OUTRO nome (troca de
      // nome no meio da carga); um duplo toque no mesmo nome nao deve puxar
      // mais 10 tickets sem que a pessoa tenha pedido "carregar mais"
      const trocouDeNome = pendente && aberto !== dominio;
      pendente = false;
      if (trocouDeNome) carregar(aberto);
    }
  }

  function abrir(dominio, lido) {
    aberto = dominio;
    lidoAberto = lido || '';
    const d = montar();
    pintar(dominio);
    status('', dominio);
    if (!d.open) d.showModal();
    carregar(dominio);
  }

  document.addEventListener('click', (e) => {
    const botao = e.target.closest('[data-disputa]');
    if (!botao) return;
    e.preventDefault();
    abrir(botao.dataset.disputa, botao.dataset.lido);
  });

  // Duas pessoas, 12x12, traco na cor do texto: diz "tem gente aqui, toque
  // para ver" sem ocupar uma segunda linha na tabela.
  const ICONE = '<svg class="icone-disputa" viewBox="0 0 16 16" aria-hidden="true" focusable="false">'
    + '<circle cx="6" cy="5" r="2.5"/><path d="M1.5 14c0-2.8 2-4.5 4.5-4.5s4.5 1.7 4.5 4.5"/>'
    + '<circle cx="11.5" cy="5.5" r="2"/><path d="M11 9.6c2 .2 3.5 1.8 3.5 4.4"/></svg>';

  /**
   * A contagem de candidatos que abre a lista de quem disputa. Um elemento
   * so: o numero continua sendo o numero (mesma pilula, mesmas classes de
   * cor e borda), e passa a ser clicavel. `classe` e a classe de nivel
   * (competindo-pouco, competindo-muito); `falado` e o texto para leitor
   * de tela sobre a contagem; `titulo` e um complemento opcional; `lido` e
   * a idade da leitura ("há 3 d"), que o painel repete quando o RDAP ja nao
   * mostra ticket.
   */
  function contagem(dominio, n, classe, falado, titulo, lido) {
    const extra = titulo ? ` ${titulo}.` : '';
    const dataLido = lido ? ` data-lido="${esc(lido)}"` : '';
    return `<button type="button" class="competindo ${classe} competindo-botao"`
      + ` data-disputa="${esc(dominio)}"${dataLido} title="Ver quem disputa ${esc(dominio)}.${esc(extra)}">`
      + `${esc(n)}${ICONE}`
      + `<span class="sr-apenas"> ${esc(falado)}; ver quem disputa</span></button>`;
  }

  window.Disputa = { abrir, contagem, consultar, bloqueado, mensagemBloqueio, restanteBloqueio };
})();
