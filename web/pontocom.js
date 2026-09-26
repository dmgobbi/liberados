/*
 * O .com do mesmo nome (15/09/2026, plano em docs/consulta-ponto-com.md).
 *
 * Para quem acha um nome bom, ter o .com.br e o .com juntos vale mais que
 * cada um sozinho. O dado ja e publico; aqui ele fica ao lado do outro. E
 * informacao, nao funil: sem registrador escolhido, sem afiliado.
 *
 * Tres pecas:
 *   - um interruptor na barra da lista ([data-pontocom-alternar]), desligado
 *     por padrao. Ligado, confere o .com de todos os nomes da pagina (o
 *     lote) e fecha com o resumo: quantos .com livres, quantos a venda;
 *   - uma pilula por linha (PontoCom.botao), escondida pelo CSS enquanto o
 *     interruptor esta desligado;
 *   - a ficha do .com, um dialogo como o de "quem disputa": registrador,
 *     datas, travas, servidores de nome (e se parecem vitrine de venda) e,
 *     buscado so ao abrir, o dono como o registrador publica.
 *
 * A regra de desenho e a do disputa.js: a consulta sai do navegador de quem
 * olha, so quando a pessoa pede (ligar o interruptor ou abrir a ficha). Nada
 * passa pelo servidor do site, nada vai para o git, a varredura nunca
 * consulta.
 *
 * Medido em 15/09/2026 (docs/limitacoes-registrobr.md, F7):
 *   - RDAP da Verisign com CORS aberto; 404 e nome sem dono; reservado da
 *     Verisign responde 200. 200 consultas seguidas (100 em fila, 100 com
 *     4 em paralelo) sem nenhum 429 e sem cabecalho de limite.
 *   - 391 de 400 nomes do topo da lista tinham o .com registrado: o valor
 *     do lote e a excecao, por isso o resumo nomeia os livres.
 *   - A Verisign e "thin": o dono mora no RDAP do registrador (o link
 *     `related`). A CSP so deixa consultar os da lista REGISTRADORES, que
 *     cobriam 159 de 192 .com registrados de uma amostra da lista.
 *
 * Do dono sai so o nome ou a organizacao e o pais, o que qualquer WHOIS
 * mostra. E-mail, telefone e endereco nunca (um teste confere).
 *
 * Usado pelo site (site_modelo) e pelo app local (web): os dois chamam
 * PontoCom.botao(dominio) na linha e poem o interruptor na barra.
 */
(function () {
  'use strict';

  // Bootstrap RDAP da IANA (data.iana.org/rdap/dns.json), 15/09/2026.
  const REGISTRO = 'https://rdap.verisign.com/com/v1/';
  const TLD = 'com';

  // RDAP dos registradores que a ficha pode consultar. Cada origem precisa
  // estar no connect-src de site_modelo/_headers (um teste confere). Da
  // lista de registradores da IANA (registrar-ids), os de mais .com na
  // amostra, com CORS aberto numa resposta 200 conferido em 15/09/2026. Fora de proposito:
  // Domain Guardians (manda o cabecalho CORS duplicado e o navegador recusa)
  // e Aliyun (responde ao navegador com uma pagina antirrobo).
  const REGISTRADORES = [
    'https://rdap.godaddy.com', 'https://rdap.wildwestdomains.com',
    'https://rdap.uniregistrar.com', 'https://rdap.brandsight.com',
    'https://rdap.networksolutions.com', 'https://rdap.snapnames.com', 'https://rdap.web.com',
    'https://*.rdap.tucows.com', 'https://rdap.namecheap.com', 'https://rdap.spaceship.com',
    'https://rdap.squarespace.domains', 'https://rdap.cloudflare.com', 'https://rdap.hostinger.com',
    'https://rdap.ionos.com', 'https://rdap.dynadot.com', 'https://rdap.namesilo.com',
    'https://cart-before.porkbun.horse', 'https://namerdap.systems', 'https://rdap.markmonitor.com',
    'https://rdap.cscglobal.com', 'https://rdap.registrar.amazon.com', 'https://rdap.namebright.com',
    'https://rdapserver.net', 'https://rdap.gandi.net', 'https://rdap.ovh.com',
    'https://rdap.fabulous.com', 'https://rdap.yoursrs.com',
    'https://rdap.rrpproxy.net', 'https://rdap.wix.com', 'https://rdap.virtualcloudmanager.com',
    'https://rdap-whois.epik.com',
  ];

  // Servidores de nome de vitrines de venda: o nome aponta para la e a
  // pagina do dominio mostra o preco. Heuristica, dita como tal na ficha.
  const VITRINES = {
    'afternic.com': 'Afternic', 'namefind.com': 'NameFind (GoDaddy)',
    'uniregistrymarket.link': 'Uniregistry Market', 'dan.com': 'Dan.com',
    'undeveloped.com': 'Dan.com', 'atom.com': 'Atom', 'squadhelp.com': 'Atom',
    'brandbucket.com': 'BrandBucket', 'eftydns.com': 'Efty', 'hugedomains.com': 'HugeDomains',
    'sedoparking.com': 'Sedo', 'namepros-dns.com': 'NamePros', 'namepros-dns.is': 'NamePros',
  };
  // Estacionamento: pagina de anuncios, sem site. Nao quer dizer a venda. So
  // os que se apresentam como estacionamento; DNS de registrador que tambem
  // hospeda site (NameBright, GiantPanda) fica de fora.
  const ESTACIONAMENTOS = {
    'abovedomains.com': 'Above.com', 'parkingcrew.net': 'ParkingCrew', 'parklogic.com': 'ParkLogic',
    'bodis.com': 'Bodis', 'fabulous.com': 'Fabulous', 'dns-expired.com': 'página de domínio vencido',
  };

  // RFC 8056: o fim do ciclo de um nome gTLD (30 dias de resgate e 5 de exclusao).
  const CAINDO = ['redemption period', 'pending restore', 'pending delete'];
  const PRIVACIDADE = /privacy|privacidad|proxy|redacted|withheld|registration private|not disclosed|data protected|gdpr|masked|anonymi|on behalf of/i;
  const A_VENDA = /for sale|hugedomains/i;

  const PARALELO = 2;
  const VALIDADE = 12 * 3600 * 1000;       // o resultado guardado no aparelho vale 12 h
  const CHAVE_LIGADO = 'pontocom:ligado';
  const CHAVE_CACHE = 'pontocom:v1';

  const estados = new Map();      // "nome.com" -> Estado | Promise<Estado>
  const titulares = new Map();    // "nome.com" -> Titular | Promise<Titular>
  let geracao = 0;                // muda quando um lote e cancelado
  let lote = null;                // { fqdns: Set } do lote em andamento
  let parado = null;              // Set dos fqdns de um lote que parou num erro
  let dialogo = null;
  let aberto = null;              // o .com cuja ficha esta na tela

  const esc = (v) => String(v ?? '').replace(/[&<>"']/g, (c) => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));

  function lerArmazenado(chave) {
    try { return localStorage.getItem(chave); } catch (e) { return null; }
  }
  function gravarArmazenado(chave, valor) {
    try { localStorage.setItem(chave, valor); } catch (e) { /* aba privada: fica so na memoria */ }
  }

  // ------------------------------------------------------------- dominio

  /**
   * O rotulo da esquerda, como o registro do .com o entende: minusculo, em
   * punycode se tiver acento (o URL do navegador converte), ou '' se nao
   * servir de nome. "Vacina.app.br" -> "vacina"; "café.com.br" -> "xn--caf-dma".
   */
  function rotulo(dominio) {
    const bruto = String(dominio || '').trim().toLowerCase().split('.')[0];
    if (!bruto) return '';
    let host;
    try {
      host = new URL(`http://${bruto}.${TLD}`).hostname;
    } catch (e) {
      return '';
    }
    const nome = host.slice(0, -(TLD.length + 1));
    return /^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$/.test(nome) ? nome : '';
  }

  /** O sufixo de dois rotulos de um servidor de nome: "ns1.afternic.com" -> "afternic.com". */
  const sufixo = (host) => String(host || '').toLowerCase().split('.').slice(-2).join('.');

  /** O link da Verisign para o RDAP do registrador pode ser consultado (esta na CSP)? */
  function permitido(url) {
    let u;
    try { u = new URL(url); } catch (e) { return false; }
    if (u.protocol !== 'https:') return false;
    return REGISTRADORES.some((origem) => {
      const host = origem.slice('https://'.length);
      return host.startsWith('*.') ? u.hostname.endsWith(host.slice(1)) : u.hostname === host;
    });
  }

  /**
   * A resposta da Verisign traduzida. Funcao pura: recebe o codigo HTTP e o
   * JSON, devolve o Estado. Da entidade so saem o nome e o numero IANA do
   * registrador.
   */
  function ler(status, json) {
    if (status === 404) return { estado: 'livre' };
    if (status !== 200 || !json || json.objectClassName !== 'domain') {
      return { estado: 'erro', mensagem: 'resposta inesperada do registro do .com' };
    }
    const eventos = {};
    for (const e of json.events || []) eventos[e.eventAction] = e.eventDate;
    const registrador = (json.entities || []).find((e) => (e.roles || []).includes('registrar')) || {};
    const campos = (registrador.vcardArray || [])[1] || [];
    const fn = campos.find((c) => Array.isArray(c) && c[0] === 'fn');
    const iana = (registrador.publicIds || []).find((p) => /iana/i.test(p.type || ''));
    const situacoes = (json.status || []).map((s) => String(s).toLowerCase());
    const servidores = (json.nameservers || []).map((n) => String(n.ldhName || '').toLowerCase()).filter(Boolean);
    const vitrine = servidores.map((s) => VITRINES[sufixo(s)]).find(Boolean) || '';
    const estacionamento = servidores.map((s) => ESTACIONAMENTOS[sufixo(s)]).find(Boolean) || '';
    const ficha = ((json.links || []).find((l) => l.rel === 'related') || {}).href || '';
    let estado = 'com_dono';
    if (situacoes.some((s) => CAINDO.includes(s))) estado = 'caindo';
    else if (vitrine) estado = 'a_venda';
    return {
      estado,
      desde: eventos.registration || '',
      expira: eventos.expiration || '',
      alterado: eventos['last changed'] || '',
      registrador: fn ? String(fn[3]) : '',
      iana: iana ? String(iana.identifier) : '',
      situacoes,
      servidores,
      vitrine,
      estacionamento,
      ficha,
    };
  }

  /**
   * O dono, do RDAP do registrador: nome ou organizacao e o pais, e se e um
   * servico de privacidade. Funcao pura. Do vCard so se leem fn, org e o
   * codigo do pais do adr; o resto do vCard nao e lido.
   */
  function lerTitular(json) {
    const entidade = ((json && json.entities) || []).find((e) => (e.roles || []).includes('registrant'));
    if (!entidade) return { encontrado: false, motivo: 'sem' };
    const campos = ((entidade.vcardArray || [])[1] || []).filter(Array.isArray);
    const texto = (nome) => {
      const c = campos.find((x) => x[0] === nome);
      const v = c ? c[3] : '';
      return String(Array.isArray(v) ? v.filter(Boolean).join(', ') : v || '').trim();
    };
    const adr = campos.find((x) => x[0] === 'adr');
    let pais = adr && adr[1] && typeof adr[1].cc === 'string' ? adr[1].cc : '';
    if (!pais && adr && Array.isArray(adr[3])) pais = String(adr[3][adr[3].length - 1] || '');
    pais = /^[A-Za-z]{2}$/.test(pais) ? pais.toUpperCase() : '';
    const nome = texto('fn');
    const organizacao = texto('org');
    const junto = `${nome} ${organizacao}`;
    return {
      encontrado: true,
      nome: PRIVACIDADE.test(nome) ? '' : nome,
      organizacao,
      pais,
      oculto: PRIVACIDADE.test(junto) || (!nome && !organizacao),
      aVenda: A_VENDA.test(junto),
    };
  }

  /** As travas e prazos do EPP, ditos em portugues. */
  function travas(situacoes) {
    const s = new Set(situacoes || []);
    const tem = (prefixo) => [...s].some((x) => x.startsWith(prefixo) && x.endsWith('prohibited'));
    const frases = [];
    if (s.has('redemption period')) frases.push('venceu e está no prazo de resgate (30 dias); se ninguém resgatar, é apagado');
    if (s.has('pending restore')) frases.push('o dono está resgatando depois de vencer');
    if (s.has('pending delete')) frases.push('sendo apagado; fica livre em até 5 dias');
    if (s.has('auto renew period')) frases.push('venceu há pouco e foi renovado automaticamente; o registrador ainda pode desfazer');
    if (s.has('add period')) frases.push('registrado há menos de 5 dias');
    if (s.has('client hold') || s.has('server hold')) frases.push('suspenso: não funciona na internet');
    if (s.has('pending transfer')) frases.push('mudando de registrador agora');
    if (tem('server ')) frases.push('travado pelo próprio registro do .com');
    if (tem('client ')) frases.push('travas comuns do registrador contra transferência sem autorização');
    if (!frases.length && (s.has('active') || s.has('ok'))) frases.push('ativo, sem travas');
    return frases;
  }

  /** O que ja se sabe dos `fqdns`, contado do cache. */
  function resumo(fqdns) {
    const r = { total: 0, livres: [], caindo: [], aVenda: 0, comDono: 0, erros: 0 };
    for (const f of new Set(fqdns)) {
      const e = estados.get(f);
      if (!e || e instanceof Promise) continue;
      r.total++;
      if (e.estado === 'livre') r.livres.push(f);
      else if (e.estado === 'caindo') r.caindo.push(f);
      else if (e.estado === 'a_venda') r.aVenda++;
      else if (e.estado === 'com_dono') r.comDono++;
      else r.erros++;
    }
    return r;
  }

  function textoDoResumo(r) {
    const lista = (xs) => xs.slice(0, 5).join(', ') + (xs.length > 5 ? ` e mais ${xs.length - 5}` : '');
    const partes = [r.livres.length ? `${r.livres.length} com .com livre (${lista(r.livres)})` : 'nenhum .com livre'];
    if (r.caindo.length) partes.push(`${r.caindo.length} caindo (${lista(r.caindo)})`);
    if (r.aVenda) partes.push(`${r.aVenda} ${r.aVenda === 1 ? 'parece' : 'parecem'} à venda`);
    return `${r.total} ${r.total === 1 ? 'nome conferido' : 'nomes conferidos'}: ${partes.join('; ')}.`;
  }

  // ----------------------------------------------------------- adaptador

  async function buscarJson(url) {
    let r;
    try {
      r = await fetch(url, { credentials: 'omit', cache: 'no-store', referrerPolicy: 'no-referrer',
        headers: { Accept: 'application/rdap+json' } });
    } catch (e) {
      return { status: 0, json: null };
    }
    if (r.status !== 200) return { status: r.status, json: null };
    try {
      return { status: 200, json: await r.json() };
    } catch (e) {
      return { status: -1, json: null };
    }
  }

  async function consultar(fqdn) {
    const { status, json } = await buscarJson(`${REGISTRO}domain/${encodeURIComponent(fqdn)}`);
    if (status === 0) return { estado: 'erro', mensagem: 'o registro do .com não respondeu' };
    if (status === 429) return { estado: 'erro', mensagem: 'o registro do .com pediu uma pausa; espere alguns minutos' };
    if (status !== 200 && status !== 404) return { estado: 'erro', mensagem: `o registro do .com respondeu ${status}` };
    return ler(status, json);
  }

  // ---------------------------------------------------------------- cache

  function carregarCache() {
    let bruto;
    try { bruto = JSON.parse(lerArmazenado(CHAVE_CACHE) || '{}'); } catch (e) { bruto = {}; }
    const agora = Date.now();
    for (const [f, v] of Object.entries(bruto || {})) {
      if (v && v.e && v.e.estado !== 'erro' && agora - v.t < VALIDADE) {
        estados.set(f, Object.assign(v.e, { quando: v.t }));
      }
    }
  }

  let gravacao = null;
  function gravarCache() {
    clearTimeout(gravacao);
    gravacao = setTimeout(() => {
      const agora = Date.now();
      const itens = [...estados.entries()]
        .filter(([, e]) => e && !(e instanceof Promise) && e.estado !== 'erro' && agora - e.quando < VALIDADE)
        .sort((a, b) => b[1].quando - a[1].quando)
        .slice(0, 3000);
      const saida = {};
      for (const [f, e] of itens) {
        const { quando, ...resto } = e;
        saida[f] = { t: quando, e: resto };
      }
      gravarArmazenado(CHAVE_CACHE, JSON.stringify(saida));
    }, 800);
  }

  // ---------------------------------------------------------- consultas

  /** O .com de `fqdn`, do cache ou da Verisign; dois pedidos iguais, uma consulta. */
  function conferir(fqdn) {
    const atual = estados.get(fqdn);
    if (atual && (atual instanceof Promise || atual.estado !== 'erro')) return Promise.resolve(atual);
    const pedido = consultar(fqdn).then((e) => {
      e.quando = Date.now();
      estados.set(fqdn, e);
      repintar(fqdn);
      if (e.estado !== 'erro') gravarCache();
      return e;
    });
    estados.set(fqdn, pedido);
    repintar(fqdn);
    return pedido;
  }

  /**
   * Confere `fqdns` com PARALELO consultas por vez e para no primeiro erro:
   * o limite nao e publicado. `aoAvancar(feitos, total)` conta o progresso.
   * Um lote novo, ou desligar o interruptor, cancela o anterior.
   */
  async function conferirLote(fqdns, aoAvancar) {
    const execucao = ++geracao;
    const fila = [...new Set(fqdns)].filter((f) => {
      const e = estados.get(f);
      return !e || e.estado === 'erro';
    });
    let proximo = 0;
    let feitos = 0;
    let parou = '';
    async function trabalhador() {
      while (proximo < fila.length && !parou && execucao === geracao) {
        const e = await conferir(fila[proximo++]);
        feitos++;
        if (e.estado === 'erro') parou = e.mensagem;
        if (aoAvancar && execucao === geracao) aoAvancar(feitos, fila.length);
      }
    }
    await Promise.all(Array.from({ length: PARALELO }, trabalhador));
    return { total: fila.length, feitos, parou, cancelado: execucao !== geracao };
  }

  /** O dono de `fqdn`, do RDAP do registrador; so quando a ficha abre. */
  function conferirTitular(fqdn, estado) {
    if (titulares.has(fqdn)) return Promise.resolve(titulares.get(fqdn));
    if (!estado.ficha || !permitido(estado.ficha)) {
      const t = { encontrado: false, motivo: 'fora' };
      titulares.set(fqdn, t);
      return Promise.resolve(t);
    }
    const pedido = buscarJson(estado.ficha).then(({ status, json }) => {
      const t = status === 200 ? lerTitular(json)
        : { encontrado: false, motivo: status === 429 ? 'pausa' : 'falhou' };
      titulares.set(fqdn, t);
      return t;
    });
    titulares.set(fqdn, pedido);
    return pedido;
  }

  // ----------------------------------------------------------- interface

  const dia = (iso) => {
    const d = iso ? new Date(iso) : null;
    return d && !isNaN(d) ? d.toLocaleDateString('pt-BR', { timeZone: 'UTC' }) : '';
  };
  const idade = (iso) => {
    const d = iso ? new Date(iso) : null;
    if (!d || isNaN(d)) return '';
    const n = Math.floor((Date.now() - d.getTime()) / (365.25 * 86400000));
    return n >= 1 ? ` (há ${n} ${n === 1 ? 'ano' : 'anos'})` : '';
  };
  let nomesDePais = null;
  const pais = (cc) => {
    try {
      nomesDePais = nomesDePais || new Intl.DisplayNames(['pt-BR'], { type: 'region' });
      return nomesDePais.of(cc) || cc;
    } catch (e) {
      return cc;
    }
  };

  const ROTULOS = {
    espera: ['.com…', 'o .com ainda não foi conferido'],
    livre: ['✓ .com livre', 'o .com não tem dono'],
    a_venda: ['.com à venda', 'o .com tem dono e parece à venda'],
    com_dono: ['.com tem dono', 'o .com tem dono'],
    caindo: ['↓ .com caindo', 'o .com venceu e está sendo apagado'],
    erro: ['.com ?', 'não deu para conferir o .com'],
  };

  /**
   * A pilula de `dominio`: o estado do .com, que abre a ficha. Sempre
   * desenhada; o CSS a esconde enquanto o interruptor esta desligado. So le
   * o cache; quem consulta e o lote ou a ficha.
   */
  function botao(dominio) {
    const nome = rotulo(dominio);
    if (!nome) return '';
    const fqdn = `${nome}.${TLD}`;
    const e = estados.get(fqdn);
    const chave = !e || e instanceof Promise ? 'espera' : e.estado;
    const [texto, falado] = ROTULOS[chave];
    return `<button type="button" class="pontocom pontocom-${chave}" data-com="${esc(fqdn)}"`
      + ` title="${esc(`${fqdn}: ${falado}. Toque para ver a ficha.`)}">${esc(texto)}`
      + `<span class="sr-apenas">: ${esc(falado)}; abrir a ficha de ${esc(fqdn)}</span></button>`;
  }

  /** Troca, no lugar, toda pilula daquele nome; o foco vai junto. */
  function repintar(fqdn) {
    const seletor = `[data-com="${CSS.escape(fqdn)}"]`;
    const ativo = document.activeElement;
    const tinhaFoco = Boolean(ativo && ativo.matches && ativo.matches(seletor));
    for (const el of document.querySelectorAll(seletor)) {
      const molde = document.createElement('template');
      molde.innerHTML = botao(fqdn).trim();
      el.replaceWith(molde.content);
    }
    if (tinhaFoco) {
      const novo = document.querySelector(seletor);
      if (novo) novo.focus();
    }
    if (aberto === fqdn) pintarFicha();
  }

  // ---- interruptor e lote

  let ligado = lerArmazenado(CHAVE_LIGADO) === '1';

  function status(texto) {
    for (const el of document.querySelectorAll('[data-pontocom-status]')) el.textContent = texto;
  }

  function pintarInterruptor() {
    document.documentElement.classList.toggle('com-ligado', ligado);
    for (const el of document.querySelectorAll('[data-pontocom-alternar]')) {
      el.setAttribute('aria-pressed', String(ligado));
    }
  }

  /** Os .com das pilulas que estao na pagina agora, na ordem da tela. */
  const naTela = () => [...new Set([...document.querySelectorAll('[data-com]')].map((el) => el.dataset.com))];

  /**
   * Sozinha (o MutationObserver chama assim), varrer() so confere quem
   * nunca foi tentado: nunca reabre um erro nem o resto do lote que parou
   * nele. `forcarErros` refaz tambem esses dois -- so passa true quem age
   * de proposito (alternar o interruptor). Sem isso, repintar() troca a
   * pilula do erro, o observer acorda, chama varrer() de novo e o mesmo
   * lote e reconsultado sem fim (F7, achado de 18/09/2026); `parado` guarda
   * o lote inteiro (nao so quem chegou a ser consultado: PARALELO e menor
   * que o lote, e o resto reapareceria em "faltam" a cada disparo).
   */
  async function varrer(forcarErros) {
    if (!ligado) return;
    const fqdns = naTela();
    if (!fqdns.length) return;
    if (forcarErros) parado = null;
    const faltam = fqdns.filter((f) => {
      if (parado && parado.has(f)) return false;
      const e = estados.get(f);
      return forcarErros ? (!e || e.estado === 'erro') : !e;
    });
    if (!faltam.length) {
      if (!lote && !parado) status(textoDoResumo(resumo(fqdns)));
      return;
    }
    if (lote && faltam.every((f) => lote.fqdns.has(f))) return;
    const meu = { fqdns: new Set(faltam) };
    lote = meu;
    status(`conferindo o .com de ${faltam.length} ${faltam.length === 1 ? 'nome' : 'nomes'}…`);
    const r = await conferirLote(faltam, (feitos, total) => status(`conferindo o .com: ${feitos} de ${total}…`));
    if (lote === meu) lote = null;
    if (r.cancelado) return;
    if (r.parou) parado = new Set([...(parado || []), ...meu.fqdns]);
    const final = textoDoResumo(resumo(naTela()));
    status(r.parou ? `Parou: ${r.parou}. ${final}` : final);
  }

  function alternar() {
    ligado = !ligado;
    gravarArmazenado(CHAVE_LIGADO, ligado ? '1' : '0');
    pintarInterruptor();
    if (ligado) {
      varrer(true);
    } else {
      geracao++;
      lote = null;
      parado = null;
      status('');
    }
  }

  // A tabela e redesenhada a cada filtro, pagina ou busca: com o interruptor
  // ligado, o lote segue o que esta na tela.
  let agendado = null;
  new MutationObserver((mudancas) => {
    if (!ligado) return;
    const chegouPilula = mudancas.some((m) => [...m.addedNodes].some((n) => n.nodeType === 1
      && (n.matches('[data-com]') || n.querySelector('[data-com]'))));
    if (!chegouPilula) return;
    clearTimeout(agendado);
    agendado = setTimeout(varrer, 150);
  }).observe(document.body, { childList: true, subtree: true });

  // ---- a ficha

  function montar() {
    if (dialogo) return dialogo;
    dialogo = document.createElement('dialog');
    dialogo.className = 'dialogo dialogo-disputa dialogo-pontocom';
    dialogo.setAttribute('aria-labelledby', 'pontocom-titulo');
    dialogo.innerHTML = `
      <div class="dialogo-corpo">
        <h2 id="pontocom-titulo"></h2>
        <p id="pontocom-resumo" class="pontocom-resumo"></p>
        <dl id="pontocom-ficha" class="pontocom-ficha"></dl>
        <p id="pontocom-status" class="disputa-status" aria-live="polite"></p>
        <p class="disputa-nota">Consulta feita pelo seu navegador no RDAP da Verisign, que
          opera o .com, e no do registrador do nome. Do dono aparecem só o nome e o país,
          como em qualquer WHOIS; e-mail, telefone e endereço não.</p>
        <div class="disputa-acoes" id="pontocom-acoes"></div>
      </div>`;
    document.body.appendChild(dialogo);
    dialogo.addEventListener('click', (ev) => {
      if (ev.target === dialogo || ev.target.closest('[data-pontocom-fechar]')) dialogo.close();
      else if (ev.target.closest('[data-pontocom-tentar]')) abrir(aberto);
    });
    dialogo.addEventListener('close', () => { aberto = null; });
    return dialogo;
  }

  const pendente = (texto) => `<span class="disputa-pendente">${esc(texto)}</span>`;
  const linhaDaFicha = (termo, valor) => (valor ? `<dt>${esc(termo)}</dt><dd>${valor}</dd>` : '');

  function textoDoDono(t) {
    if (!t) return '';
    if (t instanceof Promise) return pendente('consultando o registrador…');
    if (!t.encontrado) {
      return pendente({
        fora: 'o registrador deste nome não abre a consulta ao navegador',
        pausa: 'o registrador pediu uma pausa; tente em alguns minutos',
      }[t.motivo] || 'o registrador não mostrou o dono');
    }
    if (t.oculto) {
      return 'oculto por um serviço de privacidade' + (t.organizacao ? ` ${pendente(`(${t.organizacao})`)}` : '');
    }
    return [...new Set([t.nome, t.organizacao].filter(Boolean))].map(esc).join(' · ');
  }

  function pintarFicha() {
    const fqdn = aberto;
    if (!fqdn || !dialogo) return;
    const e = estados.get(fqdn);
    const t = titulares.get(fqdn);
    const titular = t && !(t instanceof Promise) ? t : null;
    const resumoEl = dialogo.querySelector('#pontocom-resumo');
    const fichaEl = dialogo.querySelector('#pontocom-ficha');
    const statusEl = dialogo.querySelector('#pontocom-status');
    dialogo.querySelector('#pontocom-titulo').textContent = fqdn;
    const acoes = [];
    let resumoHtml = '';
    let fichaHtml = '';
    let statusTexto = '';

    if (!e || e instanceof Promise) {
      statusTexto = `consultando ${fqdn} no registro do .com…`;
    } else if (e.estado === 'erro') {
      statusTexto = `Não deu para conferir: ${e.mensagem}.`;
      acoes.push('<button type="button" class="conferir" data-pontocom-tentar>tentar de novo</button>');
    } else if (e.estado === 'livre') {
      resumoHtml = `<strong>Ninguém registrou ${esc(fqdn)}.</strong> Dá para registrar hoje, em qualquer registrador de .com.`;
    } else {
      resumoHtml = {
        a_venda: `<strong>Tem dono e parece à venda:</strong> aponta para a vitrine ${esc(e.vitrine)}. `
          + `O preço, quando há, aparece na página do próprio ${esc(fqdn)}.`,
        caindo: '<strong>Venceu e está sendo apagado.</strong> Se o dono não resgatar, fica livre em até cerca de 35 dias.',
        com_dono: '<strong>Tem dono.</strong>',
      }[e.estado];
      if (titular && titular.aVenda && e.estado !== 'a_venda') resumoHtml += ' O registro do dono diz que está à venda.';
      let leitura = '';
      if (e.vitrine) leitura = ` ${pendente(`(vitrine de venda: ${e.vitrine})`)}`;
      else if (e.estacionamento) leitura = ` ${pendente(`(estacionado: ${e.estacionamento}, sem site próprio)`)}`;
      fichaHtml = [
        linhaDaFicha('Dono', textoDoDono(t)),
        linhaDaFicha('País do dono', titular && titular.pais ? esc(pais(titular.pais)) : ''),
        linhaDaFicha('Registrador', esc(e.registrador) + (e.iana ? ` ${pendente(`(IANA ${e.iana})`)}` : '')),
        linhaDaFicha('Registrado em', e.desde ? esc(dia(e.desde) + idade(e.desde)) : ''),
        linhaDaFicha('Vence em', esc(dia(e.expira))),
        linhaDaFicha('Última alteração', esc(dia(e.alterado))),
        linhaDaFicha('Situação', travas(e.situacoes).map(esc).join('; ')),
        linhaDaFicha('Servidores de nome', e.servidores.length
          ? e.servidores.map(esc).join(', ') + leitura
          : 'nenhum: o nome não aponta para lugar nenhum'),
      ].join('');
      acoes.push(`<a class="botao-link" href="http://${esc(fqdn)}/" target="_blank" rel="noopener noreferrer nofollow">abrir ${esc(fqdn)}</a>`);
      acoes.push(`<a class="botao-link" href="https://web.archive.org/web/*/${esc(fqdn)}" target="_blank" rel="noopener noreferrer nofollow">histórico no Wayback</a>`);
    }
    acoes.push('<button type="button" class="discreto" data-pontocom-fechar>Fechar</button>');
    resumoEl.innerHTML = resumoHtml;
    fichaEl.innerHTML = fichaHtml;
    statusEl.textContent = statusTexto;
    dialogo.querySelector('#pontocom-acoes').innerHTML = acoes.join('');
  }

  async function abrir(fqdn) {
    aberto = fqdn;
    const d = montar();
    pintarFicha();
    if (!d.open) d.showModal();
    const e = await conferir(fqdn);
    if (aberto !== fqdn) return;
    pintarFicha();
    if (e.estado === 'livre' || e.estado === 'erro') return;
    const pedido = conferirTitular(fqdn, e);
    pintarFicha();
    await pedido;
    if (aberto === fqdn) pintarFicha();
  }

  document.addEventListener('click', (ev) => {
    const pilula = ev.target.closest('button[data-com]');
    if (pilula) {
      ev.preventDefault();
      abrir(pilula.dataset.com);
    } else if (ev.target.closest('[data-pontocom-alternar]')) {
      ev.preventDefault();
      alternar();
    }
  });

  carregarCache();
  pintarInterruptor();
  if (ligado) setTimeout(varrer, 0);

  window.PontoCom = {
    botao, abrir, conferir, conferirLote, alternar,
    rotulo, ler, lerTitular, permitido, travas, resumo, textoDoResumo,
  };
})();
