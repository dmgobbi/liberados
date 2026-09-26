'use strict';

const $ = (s) => document.querySelector(s);
// Quantos nomes por pagina (14/09/2026). Sem "todos": sem competicao passa
// de 15 mil linhas e a rodada inteira de 125 mil, o que trava o celular.
const TAMANHOS_PAGINA = [25, 50, 100, 250, 500];
const CHAVE_POR_PAGINA = 'por_pagina';

// indices do json compacto (ver garimpo/casos/instantaneo.py): [dominio,
// status, candidatos, nota, elegivel, motivos[], marca, em_leilao,
// verificado_em em segundos UTC, classe de frescor]
const D = 0, SS = 1, C = 2, N = 3, E = 4, M = 5, MK = 6, EL = 7, VF = 8, CL = 9;
// 12/09/2026: quando o primeiro concorrente chegou e quando o ultimo visivel
// chegou (epoch, 0 = desconhecido), estimados pelo ritmo da rodada
const CH1 = 11, CH2 = 12;
const CT = 10;   // categorias de negocio, em bits (dominio/categorias.py)
// 19/09/2026: o rotulo normalizado para a busca, calculado uma vez por linha
// (fica so na memoria; nada serializa a linha inteira)
const RN = 13;
// A partir de quantas letras a busca olha a rodada inteira (r3-busca-rodada-inteira)
const MINIMO_BUSCA_RODADA = 3;

const estado = {
  dados: null,
  filtro: null,           // escolhido por filtroInicial(): o primeiro que tem o que mostrar
  busca: '',
  ordem: 'nota',
  extensao: '',
  categoria: '',          // indice do bit, como texto; '' = todos os ramos
  marca: '',              // '' todas; 'sem' esconde risco; 'so' apenas possivel marca
  situacao: '',           // '' todas; chave de SITUACOES (so em lista que mistura)
  lista: new Set(),       // lista compartilhada por link (?lista=); nunca gravada
  pagina: 0,
  porPagina: 100,
  atual: [],
  porDominio: new Map(),
  aoVivo: new Set(),      // conferidos agora, neste navegador
  conferidos: new Map(),  // dominio -> {s, c, t}: conferido neste aparelho, guardado
  doNavegador: new Set(), // linhas cuja leitura veio do guardado, nao do servidor
  retidos: new Map(),     // dominio -> {texto, fora}: mudou ao conferir, fica na lista
  conferindo: null,       // o que esta sendo consultado neste instante
  acompanhados: new Map(),  // dominio -> ultima situacao vista, so neste aparelho
  mudancas: new Map(),    // dominio -> {de, texto}: uma linha por nome
  lembretesServidos: new Set(),  // leiloes com .ics gerado pelo exportador
  modoBusca: false,       // body.modo-busca: so caixa, resumo, filtros e lista
  antesDaBusca: null,     // {filtro, cartaoEscolhido} de quando o modo ligou
};

// os indices de status dependem da ordem em exportar_site.py
let iSemComp, iDisputado, iLeilao, iLivre, iRegistrado, iAguardando;

const NOMES_FILTRO = {
  joias: 'Joias',
  sem_competicao: 'Sem competição',
  disputados: 'Disputados',
  leilao: 'Em leilão',
  elegiveis: 'Elegíveis ao leilão',
  livres: 'Livres para registro imediato',
  todos: 'Todos consultados',
  rodada: 'Toda a rodada (fora do pool: não verificados)',
  acompanhados: 'Acompanhando',
  aguardando: 'Voltam na próxima rodada',
  lista: 'Lista compartilhada',
};

// Cartoes sem .ajuda propria (a lista compartilhada nao tem cartao)
const EXPLICA_FILTRO = {
  lista: 'Domínios que alguém compartilhou com você por link. A estrela '
       + 'acompanha no seu aparelho; nada desta lista é guardado sem você pedir.',
};

// Listas em que as situacoes se misturam: so nelas aparece o filtro de
// situacao (15/09/2026, pedido do dono para os salvos)
const LISTAS_MISTAS = new Set(['acompanhados', 'todos', 'rodada', 'elegiveis', 'lista']);

// status do JSON -> chave do filtro de situacao
const SITUACOES = {
  LIBERACAO_LIVRE: 'sem_competicao',
  LIBERACAO_DISPUTADA: 'disputado',
  LIVRE_COM_TICKET: 'disputado',
  COMPETITIVO: 'leilao',
  LIVRE: 'livre',
  AGUARDANDO_LIBERACAO: 'aguardando',
  REGISTRADO: 'registrado',
  INDISPONIVEL: 'registrado',
};

// Ao abrir, o primeiro destes que tem o que mostrar. Joias e o melhor
// cartao, mas passa a maior parte da rodada vazio: todo elegivel entra em
// leilao em ~30 h. Abrir numa lista vazia dava a impressao de site quebrado.
const PREFERENCIA = ['joias', 'sem_competicao', 'disputados', 'leilao', 'todos'];
// Com a rodada fechada (14/09/2026) o que interessa e o que da para fazer
// agora: registrar o que ficou livre, ou esperar o que travou.
// "elegiveis" no lugar de "leilao": fechada a rodada, "Em leilao" esvazia
// conforme a varredura reclassifica, e "Foram a leilao" (os elegiveis) e a
// lista estavel da rodada.
const PREFERENCIA_FECHADA = ['livres', 'aguardando', 'sem_competicao', 'elegiveis', 'todos'];

// Nome da rodada que nao esta no instantaneo: so nota, sem situacao
const NAO_VERIFICADO = -1;

const FILTROS = {
  joias: (it) => it[E] === 1 && it[SS] === iSemComp,
  sem_competicao: (it) => it[SS] === iSemComp,
  disputados: (it) => it[SS] === iDisputado,
  leilao: (it) => it[SS] === iLeilao,
  elegiveis: (it) => it[E] === 1,
  livres: (it) => it[SS] === iLivre,
  todos: (it) => it[SS] !== NAO_VERIFICADO,
  rodada: () => true,
  acompanhados: (it) => estado.acompanhados.has(it[D]),
  lista: (it) => estado.lista.has(it[D]),
  // Travou: status 5 do ISAVAIL, ou disputado (2+ tickets) lido antes do
  // fechamento de um nome que nao e elegivel. Ticket nao se cancela (S3) e
  // dois ou mais no fim travam o nome (regra oficial, S12), entao a leitura
  // antiga ja diz o desfecho; elegivel vai a leilao e fica de fora.
  aguardando: (it) => it[SS] === iAguardando
    || (rodadaFechada() && it[SS] === iDisputado && it[E] !== 1),
};

// --------------------------------------------------------------- utilidades

/** Nada dos dados entra no DOM sem passar por aqui (SEC-01). */
function esc(valor) {
  return String(valor ?? '').replace(/[&<>"']/g, (c) => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
  }[c]));
}

function extensaoDe(dominio) {
  const p = dominio.indexOf('.');
  return p === -1 ? '' : dominio.slice(p + 1);
}

// As datas do site sao as do Registro.br, em horario de Brasilia, qualquer
// que seja o fuso de quem olha (18/09/2026: em Manaus a rodada "fechava as 14:00")
const FUSO = 'America/Sao_Paulo';

function formatarData(iso) {
  if (!iso) return '-';
  const d = new Date(iso);
  if (isNaN(d)) return iso;
  return d.toLocaleString('pt-BR', {
    day: '2-digit', month: '2-digit', year: 'numeric',
    hour: '2-digit', minute: '2-digit', timeZone: FUSO,
  });
}

function formatarDataCurta(iso) {
  if (!iso) return '-';
  const d = new Date(iso);
  if (isNaN(d)) return iso;
  return d.toLocaleDateString('pt-BR', { timeZone: FUSO }) + ' ' +
    d.toLocaleTimeString('pt-BR', { hour: '2-digit', minute: '2-digit', timeZone: FUSO });
}

/** "15h" ou "15h30", em horario de Brasilia. */
function horaCurta(d) {
  const [h, m] = d.toLocaleTimeString('pt-BR',
    { hour: '2-digit', minute: '2-digit', timeZone: FUSO }).split(':');
  return m === '00' ? `${Number(h)}h` : `${Number(h)}h${m}`;
}

/*
 * O relogio da pagina. Na previa local, ?agora=<ISO> poe a pagina num
 * instante qualquer para ensaiar as fases da rodada (18/09/2026); o relogio
 * continua andando a partir dali. No ar o parametro nao vale.
 */
const DESVIO_DO_RELOGIO = (() => {
  try {
    if (!['127.0.0.1', 'localhost'].includes(location.hostname)) return 0;
    const pedido = new URLSearchParams(location.search).get('agora');
    const quando = pedido ? new Date(pedido).getTime() : NaN;
    return isNaN(quando) ? 0 : quando - Date.now();
  } catch (e) {
    return 0;
  }
})();
const agoraMs = () => Date.now() + DESVIO_DO_RELOGIO;
const agoraDaPagina = () => new Date(agoraMs());

function num(n) {
  return n.toLocaleString('pt-BR');
}

const agoraSeg = () => Math.floor(Date.now() / 1000);

function idadeTexto(segundos) {
  if (segundos < 90) return 'agora';
  const min = Math.round(segundos / 60);
  if (min < 60) return `há ${min} min`;
  const horas = Math.round(segundos / 3600);
  if (horas < 48) return `há ${horas} h`;
  return `há ${Math.round(segundos / 86400)} d`;
}

/**
 * Idade da linha e se ela passou do prazo prometido para a classe dela.
 *
 * O prazo vem do JSON (dominio/frescor.py), nao daqui: a regra mora num
 * lugar so. A comparacao e estrita (idade > prazo), a mesma do alarme.
 */
function frescorDe(it) {
  if (estado.aoVivo.has(it[D])) return { aoVivo: true };
  if (!it[VF]) return null;
  const idade = Math.max(0, agoraSeg() - it[VF]);
  const classes = (estado.dados.frescor || {}).classes || [];
  const prazo = classes[it[CL]] && classes[it[CL]].prazo_horas;
  return {
    idade,
    vencido: Boolean(prazo) && idade > prazo * 3600,
    navegador: estado.doNavegador.has(it[D]),
  };
}

// -------------------------------------------------------------------- busca

/*
 * A busca (19/09/2026). Casa so no rotulo, sem a extensao: antes
 * it[D].includes fazia "dev" achar apolo.dev.br. Sem acento, caixa, hifen
 * nem espaco, dos dois lados: "Café" acha cafe, "pet-shop" acha petshop.
 * O modo vai no proprio texto, e por isso no ?busca= do link: "pet*" comeca
 * com, "*pet" termina com, "pet" entre aspas e o nome exato. Com ponto
 * ("pizza.com.br", "*.dev.br") compara o dominio inteiro.
 */
function normalizarTermo(texto) {
  return String(texto || '').toLowerCase().normalize('NFD')
    .replace(/[̀-ͯ]/g, '').replace(/[^a-z0-9.]/g, '');
}

function modoDaBusca(texto) {
  let t = String(texto || '').trim().replace(/^www\./i, '');
  let modo = 'contem';
  const aspas = /^["“”](.*)["“”]$/.exec(t);
  if (aspas) {
    modo = 'exato';
    t = aspas[1];
  } else if (t.endsWith('*') && !t.startsWith('*')) {
    modo = 'comeca';
  } else if (t.startsWith('*') && !t.endsWith('*')) {
    modo = 'termina';
  }
  // o que sobra do texto, para a ficha: sem aspas nem asterisco
  const bruto = t.replace(/["“”*]/g, '').trim().toLowerCase().replace(/^www\./, '');
  const termo = normalizarTermo(bruto);
  return { termo, modo, bruto, dominio: termo.includes('.') };
}

function rotuloDaLinha(it) {
  if (it[RN] === undefined) {
    const p = it[D].indexOf('.');
    it[RN] = normalizarTermo(p === -1 ? it[D] : it[D].slice(0, p));
  }
  return it[RN];
}

function casaBusca(it, q) {
  const alvo = q.dominio ? rotuloDaLinha(it) + it[D].slice(it[D].indexOf('.')) : rotuloDaLinha(it);
  if (q.modo === 'exato') return alvo === q.termo;
  if (q.modo === 'comeca') return alvo.startsWith(q.termo);
  if (q.modo === 'termina') return alvo.endsWith(q.termo);
  return alvo.includes(q.termo);
}

/**
 * A busca olha a rodada inteira? Com 3 letras ou mais, enquanto a pessoa
 * nao escolheu um cartao: quem digita "pizza" quer os nomes da rodada com a
 * palavra, nao so os do cartao que abriu sozinho.
 */
function buscaNaRodada() {
  if (estado.cartaoEscolhido || ['acompanhados', 'lista'].includes(estado.filtro)) return false;
  return modoDaBusca(estado.busca).termo.length >= MINIMO_BUSCA_RODADA;
}

/*
 * O modo busca (19/09/2026). Com 3 letras ou mais, a fase, o relogio, os
 * passos e os cartoes se recolhem (extra.css, body.modo-busca) e resumo,
 * filtros e lista ficam logo abaixo da caixa: a 390 px a primeira linha
 * estava 1.640 px abaixo do campo. Liga nas 3 letras e so desliga com a
 * caixa vazia: apagar ate 2 letras nao traz o painel de volta a cada tecla.
 * O limite e o da busca na rodada, mas nao buscaNaRodada(): o toque num chip
 * escolhe um cartao e o painel nao pode voltar no meio da busca. Fica de
 * fora em Acompanhando e na lista compartilhada, que nao tem resumo.
 */
function buscaPedeModo(texto, filtro) {
  return modoDaBusca(texto).termo.length >= MINIMO_BUSCA_RODADA
    && !['acompanhados', 'lista'].includes(filtro);
}

/** Liga ou desliga o modo; ao sair, volta o cartao de antes da busca. */
function pintarModoBusca() {
  const antes = estado.modoBusca;
  if (!estado.busca.trim() || ['acompanhados', 'lista'].includes(estado.filtro)) {
    estado.modoBusca = false;
  } else if (buscaPedeModo(estado.busca, estado.filtro)) {
    estado.modoBusca = true;
  }
  // sempre: a classe pode ter entrado antes do JSON, pelo endereco
  document.body.classList.toggle('modo-busca', estado.modoBusca);
  if (!estado.modoBusca) document.body.classList.remove('modo-busca-link');
  if (antes === estado.modoBusca) return;
  // fora do modo, a proxima entrada e anunciada de novo: o resumo sai cedo
  // com a caixa vazia e nao chegaria a zerar isso
  if (!estado.modoBusca) estado.modoBuscaAnunciado = false;
  if (estado.modoBusca) {
    estado.antesDaBusca = { filtro: estado.filtro, cartaoEscolhido: estado.cartaoEscolhido };
  } else if (estado.antesDaBusca && !['acompanhados', 'lista'].includes(estado.filtro)) {
    // o chip escolhido dentro da busca era filtro da busca, nao do painel
    estado.filtro = estado.antesDaBusca.filtro;
    estado.cartaoEscolhido = estado.antesDaBusca.cartaoEscolhido;
    estado.antesDaBusca = null;
  }
  andarRelogio();   // escondido, o relogio para; de volta, anda de novo
}

/** A caixa vazia: o painel volta, com o cartao de antes e os filtros da pessoa. */
function limparBusca() {
  estado.busca = '';
  $('#busca').value = '';
  estado.pagina = 0;
  aplicar();
  const st = $('#resumo-busca-status');
  if (st) st.textContent = 'Busca limpa: de volta ao início da página.';
  $('#busca').focus({ preventScroll: true });
}

/** O cartao que a lista mostra: "Toda a rodada" enquanto a busca olha a rodada. */
function filtroEfetivo() {
  return buscaNaRodada() ? 'rodada' : estado.filtro;
}

// ------------------------------------------------------------------ filtros

/** Chave de SITUACOES de uma linha, para o filtro e a contagem. */
function situacaoDe(it) {
  if (it[SS] === NAO_VERIFICADO) return 'nao_verificado';
  return SITUACOES[estado.dados.status[it[SS]]] || 'registrado';
}

/**
 * `manterOrdem`: quem chama e a conferencia ao vivo, nao a pessoa. A linha
 * conferida muda o numero no lugar e so troca de posicao quando a pessoa
 * mexe na lista (filtro, ordem, busca) ou recarrega (15/09/2026: com a ordem
 * por candidatos, o nome pulava para outra pagina logo depois do clique).
 */
function aplicar({ manterOrdem = false, aosPoucos = false } = {}) {
  const { dados } = estado;
  // antes de tudo: ao sair do modo busca o cartao de antes volta a mandar
  pintarModoBusca();
  const q = modoDaBusca(estado.busca);
  const naRodada = buscaNaRodada();
  const teste = naRodada ? FILTROS.rodada : (FILTROS[estado.filtro] || FILTROS.todos);
  // "toda a rodada" (ou a busca de 3 letras sem cartao escolhido) olha a
  // lista inteira; acompanhados e a lista compartilhada podem ter nome de
  // fora do instantaneo; o resto, so nele
  let base = dados.itens;
  if ((estado.filtro === 'rodada' || naRodada) && estado.rodada) base = estado.rodada;
  if (estado.filtro === 'acompanhados') {
    base = [...estado.acompanhados.keys()].map(garantirLinha);
  }
  if (estado.filtro === 'lista') base = [...estado.lista].map(garantirLinha);
  // quem marcou a estrela (ou mandou a lista) escolheu ver: marca nao esconde
  const filtrarMarca = estado.filtro !== 'acompanhados' && estado.filtro !== 'lista';

  const mista = naRodada || LISTAS_MISTAS.has(estado.filtro);
  $('#situacao').classList.toggle('escondido', !mista);
  if (!mista && estado.situacao) {
    estado.situacao = '';
    $('#situacao').value = '';
  }

  // Uma passada so: a lista e as contagens de cada filtro. A contagem de um
  // filtro respeita todos os OUTROS (cartao, busca, marca e os demais
  // seletores), mas nao ele mesmo; senao escolher .com.br zeraria as outras
  // extensoes (15/09/2026: os numeros ficavam os da lista inteira).
  const porExt = new Map();
  const porCat = [];
  const porSit = new Map();
  const cat = estado.categoria === '' ? -1 : Number(estado.categoria);
  const itens = [];
  // na busca pela rodada inteira, os achados antes da situacao: os chips do
  // resumo contam em cima deles. O total sem filtro (contagemDaBusca) faz a
  // passada propria, porque a base deste laco pode ser so o cartao
  const casados = naRodada && estado.rodada ? [] : null;
  for (const it of base) {
    // conferido nesta lista e mudou: fica, com o marcador, ate a proxima
    // troca de lista. Sumir em silencio parecia bug (ver anotarMudanca).
    if (!teste(it) && !estado.retidos.has(it[D])) continue;
    if (q.termo && !casaBusca(it, q)) continue;
    if (filtrarMarca && !passaMarca(it)) continue;
    const ext = extensaoDe(it[D]);
    const bits = it[CT] || 0;
    const sit = situacaoDe(it);
    const okExt = !estado.extensao || ext === estado.extensao;
    const okCat = cat < 0 || Boolean(bits & (1 << cat));
    const okSit = !estado.situacao || sit === estado.situacao;
    if (okCat && okSit) porExt.set(ext, (porExt.get(ext) || 0) + 1);
    if (okExt && okSit) {
      for (let b = bits, i = 0; b; b >>>= 1, i++) if (b & 1) porCat[i] = (porCat[i] || 0) + 1;
    }
    if (okExt && okCat) porSit.set(sit, (porSit.get(sit) || 0) + 1);
    if (casados && okExt && okCat) casados.push(it);
    if (okExt && okCat && okSit) itens.push(it);
  }
  pintarContagensDosFiltros(porExt, porCat, porSit);

  const ordenadores = {
    nota: (a, b) => b[N] - a[N] || a[D].length - b[D].length ||
                    a[D].localeCompare(b[D]),
    // nao verificado (null) vai para o fim nas duas direcoes: null - numero
    // da NaN e embaralha a ordenacao inteira
    menos_candidatos: (a, b) => (a[C] ?? 1e9) - (b[C] ?? 1e9) || b[N] - a[N],
    candidatos: (a, b) => (b[C] ?? -1) - (a[C] ?? -1) || b[N] - a[N],
    tamanho: (a, b) => a[D].length - b[D].length || b[N] - a[N],
    alfabetica: (a, b) => a[D].localeCompare(b[D]),
    alfabetica_desc: (a, b) => b[D].localeCompare(a[D]),
  };
  itens.sort(ordenadores[estado.ordem] || ordenadores.nota);
  if (manterOrdem && estado.atual.length) {
    // sort estavel: quem ja estava na tela fica onde estava; quem entrou
    // agora vai para o fim, na ordem pedida
    const pos = new Map(estado.atual.map((it, i) => [it, i]));
    itens.sort((a, b) => (pos.get(a) ?? Infinity) - (pos.get(b) ?? Infinity));
  }

  estado.atual = itens;
  // antes da tabela: a lista vazia tambem precisa saber se foi filtro
  estado.contagemBusca = contagemDaBusca(q);
  if (!manterOrdem) atualizarEndereco();
  estado.pagina = Math.min(estado.pagina,
                           Math.max(0, Math.ceil(itens.length / estado.porPagina) - 1));
  pintarTabela({ aosPoucos });
  pintarResumoDaBusca(q, casados);
}

// ------------------------------------------------------------------- tabela

const SELOS = {
  LIBERACAO_LIVRE: ['sem_competicao', 'sem competição'],
  LIBERACAO_DISPUTADA: ['disputado', 'disputado'],
  COMPETITIVO: ['leilao', 'leilão aberto'],
  LIVRE: ['livre', 'livre agora'],
  REGISTRADO: ['registrado', 'registrado'],
  // enumeracao oficial do ISAVAIL (12/09/2026): status 5, 3 e 1
  AGUARDANDO_LIBERACAO: ['registrado', 'espera a próxima rodada'],
  INDISPONIVEL: ['registrado', 'indisponível'],
  LIVRE_COM_TICKET: ['disputado', 'pedido pendente'],
};

// Com a rodada fechada, as leituras da rodada sao historia: "sem competicao"
// ja nao convida a se candidatar, e "disputado" ja travou.
const SELOS_FECHADA = {
  LIBERACAO_LIVRE: ['sem_competicao', 'fechou sem candidato'],
  LIBERACAO_DISPUTADA: ['disputado', 'travou'],
  AGUARDANDO_LIBERACAO: ['disputado', 'volta na próxima rodada'],
};
// Nao existe selo de "leilao encerrado" por relogio. COMPETITIVO quer dizer
// que o nome estava na ultima lista-competicao.txt lida, ou seja, o leilao
// dele acontece AGORA, mesmo com a rodada fechada — leilao nao acaba junto
// com a rodada (L5, medido em 17/09/2026).
//
// A lista manda nos DOIS sentidos, e e o que sustenta este selo:
// aplicar_lista_de_leiloes() promove quem entrou e
// encerrar_leiloes_fora_da_lista() apaga a leitura de quem saiu
// (garimpo/adaptadores/repositorio.py), entao o nome volta para a fila e o
// proximo avail diz se foi registrado ou se travou. Sem a segunda metade,
// "leilao aberto" sobrevivia dias a um leilao ja resolvido.

function selo(it) {
  if (it[SS] === NAO_VERIFICADO) {
    return '<span class="selo nao-verificado">não verificado</span>';
  }
  const nome = estado.dados.status[it[SS]];
  const fechada = rodadaFechada() && SELOS_FECHADA[nome];
  const [cls, rotulo] = fechada || SELOS[nome] || ['desconhecido', nome];
  return `<span class="selo ${cls}">${esc(rotulo)}</span>`;
}

/**
 * A cor nao pode carregar sozinha o significado (A11Y-04): cada nivel tem
 * forma propria no CSS e um texto so para leitor de tela.
 */
function competindo(it) {
  if (it[SS] === NAO_VERIFICADO) {
    return '<span class="competindo competindo-nulo">?'
         + '<span class="sr-apenas"> ainda não verificado; use conferir</span></span>';
  }
  if (it[SS] === iRegistrado || it[SS] === iLivre) {
    return '<span class="competindo competindo-nulo">&ndash;</span>';
  }
  const n = it[C];
  // O numero e de uma leitura, nao de agora (19/09/2026: cagada.com.br dizia
  // "1 candidato" tres dias depois de o pedido virar registro). A idade vai
  // colada na contagem, visivel, e no texto para leitor de tela.
  const lido = idadeDaContagem(it);
  const ao = lido ? `, lido ${lido}` : '';
  const idade = lido ? `<span class="idade-contagem" aria-hidden="true">${esc(lido)}</span>` : '';
  // leilao so abre com dois tickets; se a contagem guardada e menor, a
  // situacao veio da lista oficial e o numero exato ainda nao foi lido
  if (it[SS] === iLeilao && n < 2) {
    return '<span class="competindo competindo-pouco">≥2'
         + `<span class="sr-apenas"> candidatos, pelo menos dois${esc(ao)}</span></span>${idade}`;
  }
  if (n === 0) {
    return '<span class="competindo competindo-zero">0'
         + `<span class="sr-apenas"> candidatos visíveis, pode ser zero ou um${esc(ao)}</span>`
         + `</span>${idade}`;
  }
  const classe = n <= 2 ? 'competindo-pouco' : 'competindo-muito';
  const aviso = n <= 2 ? 'poucos candidatos' : 'muitos candidatos';
  const quantos = n === 1 ? '1 candidato' : `${n} candidatos`;
  const chegada = chegadaTexto(it);
  // a propria contagem abre quem disputa (web/disputa.js): consulta feita no
  // navegador do visitante, sob demanda
  if (window.Disputa) {
    return window.Disputa.contagem(it[D], n, classe,
      `${quantos}${ao}, ${aviso}` + (chegada ? `; ${chegada}` : ''), chegada, lido) + idade;
  }
  const title = chegada ? ` title="${esc(chegada)}"` : '';
  return `<span class="competindo ${classe}"${title}>${n}`
       + `<span class="sr-apenas"> ${esc(quantos + ao)}, ${aviso}`
       + (chegada ? `; ${esc(chegada)}` : '') + `</span></span>${idade}`;
}

/** A idade da leitura que deu a contagem: "agora" se conferida nesta aba. */
function idadeDaContagem(it) {
  const f = frescorDe(it);
  if (!f) return '';
  return f.aoVivo ? 'agora' : idadeTexto(f.idade);
}

/**
 * Quando os concorrentes chegaram, pelo numero do ticket (sequencial). E
 * estimativa por cima: o ticket pode ter sido emitido antes de a varredura
 * ve-lo. So aparece quando o instantaneo trouxe o dado.
 */
function chegadaTexto(it) {
  const primeiro = it[CH1], ultimo = it[CH2];
  if (!primeiro) return '';
  const fmt = (s) => new Date(s * 1000).toLocaleString('pt-BR', {
    day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit', timeZone: FUSO });
  // Ticket anterior ao primeiro ponto da curva so tem um limite: "ate" o
  // instante daquele ponto. Sem isto, dezenas de nomes apareceriam
  // "chegando" no mesmo minuto.
  const inicio = (estado.dados.ritmo || {}).desde;
  const quando = (s) => (inicio && s <= inicio ? `até ${fmt(s)}` : `por volta de ${fmt(s)}`);
  if (!ultimo || ultimo === primeiro || (it[C] || 0) < 2) {
    return `primeiro concorrente ${quando(primeiro)}`;
  }
  return `primeiro concorrente ${quando(primeiro)}; último visível ${quando(ultimo)}`;
}

function carimboDaLinha(it) {
  const f = frescorDe(it);
  if (!f) return '';
  if (f.aoVivo) {
    return '<span class="idade ao-vivo">conferido agora, no seu navegador</span>';
  }
  const texto = idadeTexto(f.idade)
    + (f.navegador ? ' · no seu navegador' : '')
    + (f.vencido ? ' · a confirmar' : '');
  const classe = f.vencido ? ' vencida' : (f.navegador ? ' navegador' : '');
  return `<span class="idade${classe}">${esc(texto)}</span>`;
}

/** O marcador de quem mudou ao ser conferido nesta lista (ver anotarMudanca). */
function marcadorDaMudanca(it) {
  const m = estado.retidos.get(it[D]);
  return m ? `<span class="mudou">${esc(m.texto)}</span>` : '';
}

function botaoConferir(it) {
  const nome = esc(it[D]);
  const ocupado = estado.conferindo === it[D];
  // depois de um 429, window.Disputa bloqueia consultas novas por 5 min
  // (compartilhado com "quem disputa" e a ficha); o botao some disabled
  // em vez de deixar tentar de novo na hora
  const bloqueado = !ocupado && window.Disputa && window.Disputa.bloqueado && window.Disputa.bloqueado();
  if (bloqueado) agendarReativacaoConferir();
  const verbo = ocupado ? 'conferindo' : 'conferir';
  const titulo = bloqueado ? ` title="${esc(window.Disputa.mensagemBloqueio())}"` : '';
  return `<button type="button" class="conferir" data-conferir="${nome}"`
       + ` aria-label="${verbo} ${nome} agora no Registro.br"${titulo}`
       + `${ocupado || bloqueado ? ' disabled' : ''}>${ocupado ? 'conferindo…' : 'conferir'}`
       + '</button>';
}

function botaoAcompanhar(it) {
  const nome = esc(it[D]);
  const sim = estado.acompanhados.has(it[D]);
  return `<button type="button" class="estrela" data-acompanhar="${nome}"`
       + ` aria-pressed="${sim}" aria-label="acompanhar ${nome}"`
       + ` title="${sim ? 'Acompanhando: toque para parar' : 'Acompanhar: avisa se mudar'}">`
       + `<span aria-hidden="true">${sim ? '★' : '☆'}</span></button>`;
}

/*
 * Lembrete do fim do leilao, direto no calendario de quem usa.
 *
 * A dor que isto resolve esta na regra: o Registro.br NAO avisa quando
 * alguem cobre o seu lance, e recomenda acompanhar os 10 minutos finais.
 *
 * O dialogo e as tres opcoes (Google, Outlook, Calendario da Apple) moram em
 * agenda.js desde 14/09/2026, quando a ficha "quando esse dominio volta?" e
 * a proxima rodada passaram a usar o mesmo lembrete. Aqui fica so o evento.
 *
 * O QUE O EVENTO MARCA E UM PISO, NAO UMA PREVISAO. A regra garante
 * "pelo menos 24 h" de ofertas depois que os tickets fecham; nao existe
 * fonte publica da hora em que um leilao fecha (o `date=` do RDAP e o
 * `ends-at` do avail sao o fim da RODADA, conferidos em 17/09/2026).
 * Medido no mesmo dia: vacina.com.br foi ate 16h com piso as 15h, e
 * groupon.com.br seguia em leilao com o piso vencido havia horas. Entao o
 * evento diz "nao termina antes de", e passado o piso o botao some, porque
 * nao ha data honesta para oferecer.
 */
const MINUTOS_ANTES = 30;
const PAINEL_LEILAO = 'https://registro.br/painel/dominios/processo-competitivo/';

function horaDeBrasilia(d) {
  return d.toLocaleString('pt-BR', {
    weekday: 'long', day: '2-digit', month: '2-digit',
    hour: '2-digit', minute: '2-digit', timeZone: 'America/Sao_Paulo',
  });
}

function abrirLembrete(dominio) {
  const fim = fimDoLeilao();
  if (!fim || !window.Agenda) return;
  window.Agenda.abrir({
    cabecalho: `Lembrar do fim do leilão de ${dominio}`,
    texto: `Não termina antes de ${horaDeBrasilia(fim)}, horário de Brasília. `
         + 'O evento ocupa a última meia hora antes disso.',
    nota: 'O Registro.br não avisa quando cobrem o seu lance, e não publica '
        + 'a hora do fim. Lance nos 10 minutos finais prorroga o prazo em mais 10.',
    titulo: `Leilão de ${dominio}: pode fechar a partir daqui`,
    detalhes: `Não termina antes de ${horaDeBrasilia(fim)} (horário de Brasília); `
            + 'pode ir muito além, e o Registro.br não publica a hora do fim. '
            + 'Lance nos 10 minutos finais prorroga por mais 10. '
            + 'O Registro.br não avisa quando cobrem o seu lance. '
            + 'Oferta é vinculante: pagar em até 15 dias.',
    inicio: new Date(fim.getTime() - MINUTOS_ANTES * 60 * 1000),
    fim,
    url: PAINEL_LEILAO,
    uid: `leilao-${dominio}`,
    // o .ics servido so existe para quem o exportador viu em leilao
    servido: estado.lembretesServidos.has(dominio)
      ? `lembretes/${encodeURIComponent(dominio)}.ics` : null,
    arquivo: `leilao-${dominio}.ics`,
  });
}

/** O piso: a primeira hora em que o leilao PODE fechar. Nunca o fim. */
function fimDoLeilao() {
  const fim = estado.dados.rodada && estado.dados.rodada.fim;
  if (!fim) return null;
  const quando = new Date(new Date(fim).getTime() + 24 * 3600 * 1000);
  return isNaN(quando) || quando < agoraDaPagina() ? null : quando;
}

function botaoLembrar(it) {
  const nome = esc(it[D]);
  if (FILTROS.aguardando(it) && proximaAberturaDoCalendario()) {
    return `<button type="button" class="conferir" data-lembrar-rodada="${nome}"`
         + ` aria-label="lembrar da próxima rodada para ${nome}">lembrar da próxima</button>`;
  }
  if (it[SS] !== iLeilao || !fimDoLeilao()) return '';
  return `<button type="button" class="conferir" data-lembrar="${nome}"`
       + ` aria-label="lembrar do fim do leilão de ${nome}">lembrar do fim</button>`;
}

/**
 * Nome que travou (15/09/2026): ninguem consegue desistir, entao a pergunta
 * de quem olha passa a ser quando ele volta e se volta em leilao. A ficha
 * responde e poe o dia da lista na agenda.
 */
function linkQuandoVolta(it) {
  // elegivel com dois candidatos vai a leilao agora, nao volta
  const travou = (it[SS] === iDisputado && it[C] >= 2 && it[E] !== 1) || it[SS] === iAguardando;
  if (!travou) return '';
  const nome = esc(it[D]);
  // nofollow como no servidor: a ficha tem canonical para /quando-volta/ e
  // ?d=<nome> nunca e indexada (20/09/2026)
  return `<a class="conferir" rel="nofollow" href="/quando-volta/?d=${encodeURIComponent(it[D])}"`
       + ` aria-label="quando ${nome} volta">quando volta</a>`;
}

/**
 * A etiqueta "elegivel" ao lado do nome, e o que ela diz em cada fase.
 *
 * Aberta, e so fora do leilao: leilao so abre para elegivel, entao ao lado
 * de "leilao aberto" a etiqueta nao diz nada. Num "sem competicao" ela diz
 * o que nada mais na linha diz: o nome ja travou antes, ja provou demanda.
 *
 * Fechada (25/09/2026): "elegivel" num nome ja "registrado" era lido como
 * "ainda em leilao, da para entrar" por quem abria o site pela primeira vez
 * (a lista "Foram a leilao" e a que mais recebe visita nova). Fechada a
 * rodada, a etiqueta conta o desfecho, no passado e sem a cor de convite:
 * "leilao encerrado" no registrado, e nada nos outros -- o selo de situacao
 * ("volta na proxima rodada", "fechou sem candidato") ja diz o que houve.
 */
function etiquetaElegivel(it) {
  if (!it[E] || it[SS] === iLeilao) return '';
  if (rodadaFechada()) {
    if (it[SS] !== iRegistrado) return '';
    return '<span class="pilula-elegivel encerrado">leilão encerrado'
         + '<span class="sr-apenas">: foi a leilão nesta rodada e já tem dono</span></span>';
  }
  return '<span class="pilula-elegivel">elegível<span class="sr-apenas"> ao processo competitivo</span></span>';
}

/**
 * O motivo "elegivel ao leilao" vem da nota (garimpo/dominio/relevancia.py)
 * e vale para a rodada inteira; num nome ja registrado com a rodada
 * fechada, o presente confundia tanto quanto a etiqueta. So o texto muda.
 */
function motivoDaLinha(it, motivo) {
  if (motivo === 'elegível ao leilão' && rodadaFechada() && it[SS] === iRegistrado) {
    return 'foi a leilão';
  }
  return motivo;
}

function linha(it) {
  const dominio = esc(it[D]);
  const motivos = esc(it[M].map((i) => motivoDaLinha(it, estado.dados.motivos[i])).join('; '));
  const elegivel = etiquetaElegivel(it);
  const risco = it[MK] === 2
    ? '<span class="aviso-marca">possível marca de terceiro</span>' : '';
  const url = `https://registro.br/busca-dominio?fqdn=${encodeURIComponent(it[D])}`;
  // o .com do mesmo nome, conferido no navegador so quando tocado (web/pontocom.js)
  const com = window.PontoCom ? window.PontoCom.botao(it[D]) : '';

  return `<tr role="row">
    <td class="col-marca" role="cell">${botaoAcompanhar(it)}</td>
    <td class="dominio" role="cell">
      <a href="${url}" target="_blank" rel="noopener noreferrer">${dominio}</a>${elegivel} ${com}
      ${risco}
    </td>
    <td class="col-situacao" role="cell"><div class="situacao-linha">${selo(it)}${carimboDaLinha(it)}${marcadorDaMudanca(it)}${botaoConferir(it)}${botaoLembrar(it)}${linkQuandoVolta(it)}</div></td>
    <td class="num col-competindo" role="cell">${competindo(it)}</td>
    <td class="num col-nota" role="cell">${esc(it[N])}</td>
    <td class="porque col-porque" role="cell">${motivos}</td>
  </tr>`;
}

// Enquanto a pessoa digita, a tabela sai em duas vezes (19/09/2026): as
// primeiras linhas no quadro seguinte, o resto no outro. Com a CPU 4x mais
// lenta, pintar 100 linhas de uma vez custava ~100 ms por tecla.
const PRIMEIRAS_LINHAS = 25;
let restoDaTabela = 0;

function pintarTabela({ aosPoucos = false } = {}) {
  const itens = estado.atual;
  const inicio = estado.pagina * estado.porPagina;
  const pagina = itens.slice(inicio, inicio + estado.porPagina);

  cancelAnimationFrame(restoDaTabela);
  const corpo = $('#corpo-tabela');
  if (aosPoucos && pagina.length > PRIMEIRAS_LINHAS) {
    corpo.innerHTML = pagina.slice(0, PRIMEIRAS_LINHAS).map(linha).join('');
    restoDaTabela = requestAnimationFrame(() => {
      restoDaTabela = requestAnimationFrame(() => {
        corpo.insertAdjacentHTML('beforeend', pagina.slice(PRIMEIRAS_LINHAS).map(linha).join(''));
      });
    });
  } else {
    corpo.innerHTML = pagina.map(linha).join('');
  }
  $('#tabela').classList.toggle('escondido', pagina.length === 0);

  const vazio = $('#vazio');
  vazio.classList.toggle('escondido', pagina.length !== 0);
  if (pagina.length === 0) pintarVazio();

  const paginas = Math.max(1, Math.ceil(itens.length / estado.porPagina));
  // quem mudou e ja nao pertence a lista continua na tela, mas nao na conta
  const fora = itens.filter((it) => (estado.retidos.get(it[D]) || {}).fora).length;
  // Com mais de uma pagina, o titulo diz que a lista continua. So o
  // "pagina 1 de 2" embaixo da tabela fazia os 160 em leilao parecerem 100.
  const faixa = paginas > 1
    ? ` · mostrando ${num(inicio + 1)} a ${num(inicio + pagina.length)}` : '';
  const efetivo = filtroEfetivo();
  $('#titulo-lista').textContent =
    `${efetivo !== estado.filtro ? 'Busca na rodada inteira' : (NOMES_FILTRO[efetivo] || efetivo)}: ${num(itens.length - fora)}`
    + faixa
    + (fora ? ` · ${fora} ${fora === 1 ? 'saiu' : 'saíram'} ao conferir` : '');
  const cartao = document.querySelector(`.cartao[data-filtro="${efetivo}"] .ajuda`);
  $('#explica-filtro').textContent = cartao ? cartao.textContent : (EXPLICA_FILTRO[efetivo] || '');
  pintarBotoesDaLista();

  $('#paginacao').classList.toggle('escondido', paginas === 1);
  $('#info-pagina').textContent = `página ${estado.pagina + 1} de ${num(paginas)}`;
  $('#btn-anterior').disabled = estado.pagina === 0;
  $('#btn-proxima').disabled = estado.pagina + 1 >= paginas;

  document.querySelectorAll('.cartao').forEach((c) => {
    c.setAttribute('aria-pressed', String(c.dataset.filtro === efetivo));
  });
}

/**
 * Lista vazia e convite, nao beco: diz por que esta vazia e oferece o
 * proximo passo num botao.
 */
function pintarVazio() {
  const filtrando = estado.busca.trim() || estado.extensao
    || estado.categoria !== '' || estado.marca !== '' || estado.situacao;
  let texto = 'Nenhum nome nesta lista agora.';
  let acao = ['Ver toda a rodada', () => escolherFiltro('rodada')];
  const busca = estado.busca.trim();
  const naRodada = buscaNaRodada();
  const cb = estado.contagemBusca;
  if (naRodada && cb && cb.total > 0) {
    // 19/09/2026: o termo existe, quem esconde e o filtro; nunca "nenhum
    // nome com vacina" quando a marca ou a extensao tiram os 9
    const onde = estado.rodada ? 'da rodada' : (cb.total === 1 ? 'já consultado' : 'já consultados');
    texto = cb.total === 1
      ? `O único nome ${onde} com “${busca}” não passa pelos filtros atuais.`
      : `Nenhum dos ${num(cb.total)} nomes ${onde} com “${busca}” passa pelos filtros atuais.`;
    acao = ['Limpar filtros', () => {
      // o botao some com a lista refeita: o foco vai ao resumo
      limparSoFiltros();
      const resumo = $('#resumo-busca');
      resumo.tabIndex = -1;
      resumo.focus({ preventScroll: true });
    }];
  } else if (naRodada) {
    // o resumo em cima da lista ja oferece a ficha e os nomes parecidos
    texto = estado.rodada ? `Nenhum nome da rodada com “${busca}”.`
      : `Nenhum nome com “${busca}” entre os já consultados.`;
    acao = estado.rodada ? null
      : [`Buscar nos ${num(estado.dados.total_rodada || 0)} nomes da rodada`, buscarNaRodadaInteira];
  } else if (busca && !['rodada', 'acompanhados', 'lista'].includes(estado.filtro)) {
    // quem busca um nome quer saber se ele esta na rodada, nao so neste
    // cartao: a busca que nao acha oferece a lista inteira
    texto = `Nenhum nome com “${busca}” em ${NOMES_FILTRO[estado.filtro] || 'esta lista'}.`;
    acao = [`Buscar nos ${num(estado.dados.total_rodada || 0)} nomes da rodada`,
            () => escolherFiltro('rodada')];
  } else if (filtrando) {
    texto = 'Nada com essa busca e esses filtros.';
    acao = ['Limpar busca e filtros', limparFiltros];
  } else if (estado.filtro === 'joias') {
    texto = `Nenhuma joia agora: os ${num(estado.dados.total_elegiveis || 0)} `
          + 'elegíveis ao leilão já têm candidato ou já estão em leilão. É o '
          + 'normal passado o primeiro dia da rodada.';
    // "Ver os sem competicao" so quando ha algum: relida a lista, eles viram
    // livre, registrado ou aguardando, e o botao levava a uma lista vazia
    const rotulos = {
      sem_competicao: 'Ver os sem competição',
      livres: 'Ver o que está livre agora',
      rodada: 'Ver toda a rodada',
    };
    const vis = visiveis();
    const destino = ['sem_competicao', 'livres'].find((f) => vis.some(FILTROS[f])) || 'rodada';
    acao = [rotulos[destino], () => escolherFiltro(destino)];
  } else if (estado.filtro === 'acompanhados') {
    texto = 'Você ainda não acompanha nenhum nome. Toque na estrela ao lado '
          + 'de um domínio e esta página avisa quando ele mudar.';
    acao = null;
  }
  const p = document.createElement('p');
  p.textContent = texto;
  const partes = [p];
  if (acao) {
    const b = document.createElement('button');
    b.type = 'button';
    b.textContent = acao[0];
    b.addEventListener('click', acao[1]);
    partes.push(b);
  }
  // Quem busca um nome que nao esta na lista quer saber dele mesmo assim: a
  // ficha diz se esta livre, com dono, e quando volta (14/09/2026)
  const nome = naRodada ? null : fichaDaBusca(modoDaBusca(busca).bruto);
  if (nome) {
    const a = document.createElement('a');
    a.className = 'ficha-da-busca';
    a.rel = 'nofollow';
    a.href = `/quando-volta/?d=${encodeURIComponent(nome)}`;
    a.textContent = `Ver se ${nome} está livre ou quando volta`;
    partes.push(a);
  }
  $('#vazio').replaceChildren(...partes);
}

/** O nome que a busca parece pedir, para a ficha; null se nao parece nome. */
function fichaDaBusca(busca) {
  const t = String(busca || '').trim().toLowerCase().replace(/^www\./, '');
  if (!/^[a-z0-9][a-z0-9-]{1,62}(\.[a-z0-9-]+)*$/.test(t)) return null;
  if (t.includes('.') && !t.endsWith('.br')) return null;
  return t.includes('.') ? t : `${t}.com.br`;
}

/**
 * Os filtros que estreitam o resumo (marca, extensao, ramo) estao ligados?
 * A situacao fica de fora: o resumo ja a detalha nos chips, e o "Todos"
 * a zera.
 */
function filtrosLigados() {
  return Boolean(estado.marca || estado.extensao || estado.categoria !== '');
}

/**
 * Os nomes dos filtros ligados, como o seletor mostra ("Só possível marca",
 * ".com.br"), para o resumo dizer qual deles esconde: no celular os
 * seletores ficam duas telas abaixo da busca.
 */
function rotulosDosFiltros() {
  return ['#marca', '#extensao', '#categoria'].map((id) => {
    const o = $(id)?.selectedOptions?.[0];
    return o && o.value ? (o.dataset.rotulo || o.textContent).trim() : '';
  }).filter(Boolean);
}

/** Zera marca, extensao, ramo e situacao; a busca fica (19/09/2026). */
function limparSoFiltros() {
  estado.extensao = '';
  estado.categoria = '';
  estado.marca = '';
  estado.situacao = '';
  $('#extensao').value = '';
  $('#categoria').value = '';
  $('#marca').value = '';
  $('#situacao').value = '';
  sincronizarBuscaveis();
  estado.pagina = 0;
  pintarContagens();   // os numeros dos cartoes dependem da marca
  aplicar();
}

function limparFiltros() {
  estado.busca = '';
  $('#busca').value = '';
  limparSoFiltros();
}

/**
 * A busca volta a olhar a rodada inteira (o "todos" do resumo e o botao da
 * lista vazia): sem cartao escolhido e sem situacao.
 */
async function buscarNaRodadaInteira() {
  estado.cartaoEscolhido = false;
  estado.filtro = estado.filtroInicial || estado.filtro;
  estado.situacao = '';
  $('#situacao').value = '';
  estado.pagina = 0;
  estado.retidos.clear();
  aplicar();
  if (!estado.rodada) {
    await carregarRodada({ aviso: false });
    aplicar();
  }
}

/** "09/09", no fuso do Registro.br. */
function diaMes(quando) {
  const d = new Date(quando);
  return isNaN(d) ? '' : d.toLocaleDateString('pt-BR', { timeZone: FUSO, day: '2-digit', month: '2-digit' });
}

/*
 * As situacoes do resumo da busca, na ordem do que da para fazer agora. Cada
 * uma e um cartao que ja existe: o toque leva ao cartao, com a busca, e o
 * numero do resumo e o que o cartao mostra (mesmo filtro, mesma marca).
 */
function situacoesDoResumo() {
  const proxima = proximaAberturaDoCalendario();
  const quando = proxima ? `em ${diaMes(proxima)}` : 'na próxima rodada';
  const volta = (n) => (n === 1 ? `travou e volta ${quando}` : `travaram e voltam ${quando}`);
  const livres = (n) => (n === 1 ? 'livre agora' : 'livres agora');
  const leilao = () => 'em leilão';
  if (rodadaFechada()) {
    return [['livres', livres], ['aguardando', volta],
      ['sem_competicao', (n) => (n === 1 ? 'fechou sem candidato visível' : 'fecharam sem candidato visível')],
      ['leilao', leilao]];
  }
  return [['livres', livres], ['sem_competicao', () => 'sem candidato visível'],
    ['disputados', (n) => (n === 1 ? 'já tem candidato' : 'já têm candidato')],
    ['leilao', leilao], ['aguardando', volta]];
}

function botaoDoResumo(texto, pressionado, dados) {
  const b = document.createElement('button');
  b.type = 'button';
  b.textContent = texto;
  b.setAttribute('aria-pressed', String(pressionado));
  Object.assign(b.dataset, dados);
  return b;
}

/**
 * Quantos nomes tem o termo e quantos deles passam pelos filtros. O total
 * ignora marca, extensao e ramo (e a situacao, que os chips detalham): e a resposta a "quantos nomes da
 * rodada tem vacina" (19/09/2026: com a marca em "so possivel marca", o
 * resumo dizia "0 nomes dos 125.453 da rodada" e eram 9).
 */
function contarBusca(linhas, q, passaFiltros) {
  let total = 0;
  let comFiltros = 0;
  for (const it of linhas) {
    if (!casaBusca(it, q)) continue;
    total++;
    if (passaFiltros(it)) comFiltros++;
  }
  return { total, comFiltros };
}

/** A contagem do resumo, na rodada inteira (ou nos consultados, sem ela); null sem termo. */
function contagemDaBusca(q) {
  if (q.termo.length < MINIMO_BUSCA_RODADA) return null;
  const cat = estado.categoria === '' ? -1 : Number(estado.categoria);
  const passa = (it) => passaMarca(it)
    && (!estado.extensao || extensaoDe(it[D]) === estado.extensao)
    && (cat < 0 || Boolean((it[CT] || 0) & (1 << cat)));
  return contarBusca(estado.rodada || estado.dados.itens, q, passa);
}

/**
 * O resumo da busca (19/09/2026): com 3 letras ou mais, quantos nomes da
 * rodada tem o termo e em que situacao estao, um toque por situacao. Nome
 * exato que nao esta na rodada ganha a ficha e ate 5 nomes da rodada com o
 * termo e sem concorrente a vista. Tudo por textContent (SEC-01).
 */
function pintarResumoDaBusca(q, casados = null) {
  const el = $('#resumo-busca');
  if (!el) return;
  const ativo = q.termo.length >= MINIMO_BUSCA_RODADA
    && !['acompanhados', 'lista'].includes(estado.filtro);
  el.classList.toggle('escondido', !ativo);
  // so a frase vai ao leitor de tela, e so quando muda
  const falar = (texto) => {
    const st = $('#resumo-busca-status');
    if (st && st.textContent !== texto) st.textContent = texto;
  };
  if (!ativo) {
    el.replaceChildren();
    falar('');
    return;
  }
  const cat = estado.categoria === '' ? -1 : Number(estado.categoria);
  const passa = (it) => casaBusca(it, q) && passaMarca(it)
    && (!estado.extensao || extensaoDe(it[D]) === estado.extensao)
    && (cat < 0 || Boolean((it[CT] || 0) & (1 << cat)));
  const naRodada = buscaNaRodada();
  const total = estado.dados.total_rodada || 0;
  const r = estado.dados.rodada || {};
  const periodo = r.inicio && r.fim ? ` da rodada de ${diaMes(r.inicio)} a ${diaMes(r.fim)}` : ' da rodada';
  // entre aspas o termo ja vem com as dele
  const termo = /^["“”].*["“”]$/.test(estado.busca.trim()) ? estado.busca.trim() : `“${estado.busca.trim()}”`;
  const partes = [];
  const contagem = estado.contagemBusca || contagemDaBusca(q);
  // o filtro esconde parte dos achados: a segunda linha diz quantos sobram
  const escondendo = filtrosLigados() && contagem.comFiltros < contagem.total;

  const cabeca = document.createElement('p');
  cabeca.className = 'resumo-cabeca';
  let achados = null;
  if (estado.rodada) {
    // os achados com os filtros: e o que os chips e a lista mostram
    achados = casados || estado.rodada.filter(passa);
    cabeca.textContent = `${termo}: ${num(contagem.total)} `
      + `${contagem.total === 1 ? 'nome' : 'nomes'} dos ${num(total)}${periodo}.`;
  } else if (estado.promessaRodada) {
    cabeca.textContent = `Buscando ${termo} nos ${num(total)} nomes${periodo}…`;
  } else {
    cabeca.textContent = `${termo} nos nomes já consultados. `;
    cabeca.append(botaoDoResumo(`Buscar nos ${num(total)} nomes da rodada`, false, { buscaRodada: '' }));
  }
  partes.push(cabeca);
  // a linha da fase se recolhe no modo busca: a data que importa vem para ca
  const fase = ($('#fase-inicio') || {}).textContent || '';
  if (estado.modoBusca && fase.trim()) {
    const p = document.createElement('p');
    p.className = 'resumo-fase';
    p.textContent = fase.replace(/\s+/g, ' ').trim();
    partes.push(p);
  }
  let frase = cabeca.firstChild ? cabeca.firstChild.textContent : '';
  if (escondendo) {
    const p = document.createElement('p');
    p.className = 'resumo-filtros';
    const quais = rotulosDosFiltros();
    const linha = `Com os filtros atuais${quais.length ? ` (${quais.join(', ')})` : ''}: `
      + `${num(contagem.comFiltros)}.`;
    const b = document.createElement('button');
    b.type = 'button';
    b.dataset.limparFiltros = '';
    b.textContent = 'Limpar filtros';
    p.append(`${linha} `, b);
    partes.push(p);
    frase = `${frase.trim()} ${linha}`;
  }
  // uma vez, ao entrar: o leitor de tela sabe que a pagina mudou e como
  // voltar. Depois, a mesma frase sem o aviso nao e fala nova (a conferencia
  // ao vivo repinta o resumo segundos depois de abrir)
  const aviso = ' Mostrando só a busca; o botão Limpar busca volta ao início.';
  if (estado.modoBusca && !estado.modoBuscaAnunciado) {
    frase = frase.trim() + aviso;
    estado.modoBuscaAnunciado = true;
  }
  const dito = ($('#resumo-busca-status') || {}).textContent || '';
  if (dito !== frase.trim() + aviso) falar(frase);

  const chips = document.createElement('div');
  chips.className = 'resumo-situacoes';
  chips.setAttribute('role', 'group');
  chips.setAttribute('aria-label', 'Ver a busca por situação');
  if (achados && achados.length) {
    chips.append(botaoDoResumo(escondendo ? `Os ${num(achados.length)} filtrados` : `Todos os ${num(achados.length)}`, naRodada && !estado.situacao,
                               { buscaRodada: '', rolar: '' }));
  }
  // so nome consultado tem situacao, e toda linha consultada da rodada esta
  // nos achados: conta em cima deles (centenas), nao do instantaneo inteiro
  const consultados = (achados || estado.dados.itens.filter(passa)).filter((it) => it[SS] !== NAO_VERIFICADO);
  for (const [chave, rotulo] of situacoesDoResumo()) {
    let n = 0;
    for (const it of consultados) if (FILTROS[chave](it)) n++;
    if (!n) continue;
    chips.append(botaoDoResumo(`${num(n)} ${rotulo(n)}`, !naRodada && estado.filtro === chave,
                               { cartao: chave, rolar: '' }));
  }
  if (chips.childElementCount) partes.push(chips);

  // nome exato fora da rodada: a ficha diz se esta livre ou quando volta
  const nome = fichaDaBusca(q.bruto);
  const linha = nome && estado.porDominio.get(nome);
  const naLista = Boolean(linha) && !provisorios.has(linha);
  if (nome && achados && !naLista
      && (q.modo === 'exato' || q.dominio || contagem.total === 0)) {
    const p = document.createElement('p');
    p.className = 'resumo-ficha';
    const a = document.createElement('a');
    a.rel = 'nofollow';
    a.href = `/quando-volta/?d=${encodeURIComponent(nome)}`;
    a.textContent = 'veja se está livre ou quando volta';
    p.append(`${nome} não está nesta rodada: `, a);
    partes.push(p);
    const parecido = { termo: normalizarTermo(nome.split('.')[0]), modo: 'contem', dominio: false };
    const sugestoes = (estado.rodada || [])
      .filter((it) => it[D] !== nome && casaBusca(it, parecido) && passaMarca(it)
        && (FILTROS.livres(it) || FILTROS.sem_competicao(it)))
      .sort((x, y) => y[N] - x[N] || x[D].length - y[D].length)
      .slice(0, 5);
    if (sugestoes.length) {
      const s = document.createElement('p');
      s.className = 'resumo-sugestoes';
      s.append('Na rodada, com o termo e sem concorrente à vista: ');
      sugestoes.forEach((it, i) => {
        const link = document.createElement('a');
        link.rel = 'nofollow';
        link.href = `/quando-volta/?d=${encodeURIComponent(it[D])}`;
        link.textContent = it[D];
        s.append(...(i ? [', ', link] : [link]));
      });
      partes.push(s);
    }
  }

  const dica = document.createElement('p');
  dica.className = 'resumo-dica';
  dica.textContent = 'pet* começa com · *pet termina com · "pet" só o nome exato';
  partes.push(dica);
  el.replaceChildren(...partes);
}

async function escolherFiltro(filtro) {
  estado.filtro = filtro;
  estado.cartaoEscolhido = true;   // a busca passa a olhar so este cartao
  estado.pagina = 0;
  estado.retidos.clear();       // quem mudou so fica ate a troca de lista
  if (filtro === 'rodada') await carregarRodada();
  aplicar();
}

function filtroInicial() {
  const vis = visiveis();
  // lista nova ainda sem leitura: a rodada inteira, pela nota
  if (aConferir()) return 'rodada';
  const ordem = rodadaFechada() ? PREFERENCIA_FECHADA : PREFERENCIA;
  return ordem.find((f) => vis.some(FILTROS[f])) || 'rodada';
}

/** A rodada do instantaneo ja fechou (assentando ou entre rodadas)? */
function rodadaFechada() {
  const fim = estado.dados && estado.dados.rodada && estado.dados.rodada.fim;
  const quando = fim ? new Date(fim) : null;
  return Boolean(quando && !isNaN(quando) && quando <= agoraDaPagina());
}

/** A lista da rodada ja saiu e as candidaturas ainda nao abriram? */
function antesDaAbertura() {
  const inicio = estado.dados && estado.dados.rodada && estado.dados.rodada.inicio;
  const quando = inicio ? new Date(inicio) : null;
  return Boolean(quando && !isNaN(quando) && agoraDaPagina() < quando);
}

/*
 * Nada conferido ainda na rodada desta lista: na virada o varrer.py esquece
 * as leituras da rodada anterior e, antes da abertura, nao consulta (o
 * Registro.br so diz algo util depois dela). Ate a primeira leitura chegar,
 * as contagens que dependem dela seriam "0" como se fosse fato.
 */
function aConferir() {
  if (!estado.dados || rodadaFechada()) return false;
  return antesDaAbertura() || !estado.dados.itens.length;
}

/**
 * Em que ponto do ciclo mensal estamos.
 *
 * O mesmo numero significa coisas diferentes conforme a fase: "0 competindo"
 * com a rodada aberta e uma oportunidade; com a rodada fechada e historia.
 *
 * Devolve a fracao decorrida da janela (para a regua), um texto completo
 * (para leitor de tela) e, so quando a informacao vira noticia, um texto
 * curto para aparecer na tela. Fora dessas horas a regua fala sozinha.
 */
const HORAS_DE_AVISO = 48;      // a partir daqui o prazo vira noticia
const DIA = 24;

function faseDaRodada(inicio, fim, agora = agoraDaPagina()) {
  if (!fim) return null;
  const abertura = inicio ? new Date(inicio) : null;
  const fechamento = new Date(fim);
  if (isNaN(fechamento)) return null;

  const horas = (fechamento - agora) / 3600000;
  const janela = abertura && !isNaN(abertura)
    ? (fechamento - abertura) / 3600000 : 7 * DIA;
  const decorrido = Math.min(1, Math.max(0, 1 - horas / janela));

  // sempre em horario de Brasilia: e o do Registro.br e o do resto da pagina
  const diaDe = (d) => d.toLocaleDateString('pt-BR',
    { day: '2-digit', month: '2-digit', timeZone: FUSO });
  const dia = diaDe(fechamento);
  const hora = fechamento.toLocaleTimeString('pt-BR',
    { hour: '2-digit', minute: '2-digit', timeZone: FUSO });

  // quanto falta, por extenso: "3 dias", "5 h", "menos de uma hora"
  const falta = horas > HORAS_DE_AVISO ? `${Math.round(horas / DIA)} dias`
    : horas < 1 ? 'menos de uma hora' : `${Math.round(horas)} h`;
  const quanto = { dia, hora, falta };

  // A lista nova saiu (dois dias antes) e a rodada ainda nao abriu: as datas
  // ja sao as dela, mas ninguem consegue se candidatar (18/09/2026)
  if (abertura && !isNaN(abertura) && agora < abertura) {
    const mes = MESES_EXTENSO[Number(abertura.toLocaleDateString('en-CA',
      { timeZone: FUSO }).slice(5, 7)) - 1];
    const abre = diaDe(abertura);
    return {
      ...quanto, fase: 'lista', decorrido: 0, mes,
      abre, horaAbre: horaCurta(abertura),
      curto: `abre em ${abre}`,
      completo: `A lista da rodada de ${mes} saiu: as candidaturas abrem em ${abre}, `
              + `às ${horaCurta(abertura)}, e vão até ${dia}, às ${horaCurta(fechamento)} `
              + '(horário de Brasília).',
    };
  }
  if (horas > HORAS_DE_AVISO) {
    return {
      ...quanto, fase: 'aberta', decorrido,
      completo: `Rodada aberta, fecha em ${falta}, `
              + `dia ${dia} às ${hora} (horário de Brasília). Candidaturas ainda valem.`,
    };
  }
  if (horas > 0) {
    return {
      ...quanto, fase: 'fim', decorrido,
      curto: `fecha em ${falta}`,
      completo: `Rodada aberta, mas fecha em ${falta}, dia ${dia} às ${hora} (horário de Brasília).`,
    };
  }
  // a atribuicao nao e instantanea: leva algumas horas para assentar
  if (horas > -HORAS_DE_AVISO) {
    return {
      ...quanto, fase: 'assentando', decorrido: 1,
      curto: 'rodada encerrada',
      completo: 'Rodada encerrada. Os resultados levam algumas horas para '
              + 'assentar; quem ficou sem concorrente cai no pool livre.',
    };
  }
  return {
    ...quanto, fase: 'entre', decorrido: 1,
    curto: 'entre rodadas',
    completo: 'Entre rodadas. Nao da para se candidatar agora, mas o que caiu '
            + 'no pool livre continua registravel e os leiloes seguem.',
  };
}

function pintarFase(rodada) {
  const regua = document.querySelector('#regua');
  const prazo = document.querySelector('#prazo');
  const info = faseDaRodada(rodada && rodada.inicio, rodada && rodada.fim);

  if (!info) {
    if (regua) regua.classList.add('escondido');
    return;
  }
  if (regua) {
    regua.style.setProperty('--decorrido', (info.decorrido * 100).toFixed(1) + '%');
    regua.dataset.fase = info.fase;
    regua.setAttribute('aria-label', info.completo);
  }
  if (prazo) {
    prazo.textContent = info.curto || '';
    prazo.classList.toggle('escondido', !info.curto);
    prazo.dataset.fase = info.fase;
  }
  pintarFaseInicio(info);
}

/**
 * A linha da apresentacao que diz se da para se candidatar agora. O build
 * grava as datas (e a proxima rodada, pela regra); aqui ela vira frase de
 * quem vai agir, e muda com o relogio de quem olha.
 */
let proximaRodada = null;   // lida do HTML uma vez: a frase apaga o span

function pintarFaseInicio(info) {
  const el = document.querySelector('#fase-inicio');
  if (!el) return;
  if (proximaRodada === null) {
    proximaRodada = (document.querySelector('#p-proxima-rodada') || {}).textContent || '';
  }
  const proxima = proximaRodada;
  const { falta, dia, hora } = info;
  // Entre rodadas a frase conta os dias ate a lista sair (2 dias antes da
  // abertura), que e quando da para escolher o nome de novo (14/09/2026)
  const abre = proximaAberturaDoCalendario();
  const lista = abre ? listaDaRodada(abre) : null;
  const curta = (d) => d.toLocaleDateString('pt-BR', { timeZone: 'America/Sao_Paulo', day: '2-digit', month: '2-digit' });
  // Quantos leiloes da rodada ainda estao abertos, pela lista oficial. Nao
  // da para calcular pelo relogio: leilao nao acaba junto com a rodada (L5).
  const aindaEmLeilao = estado.dados.itens
    .filter((it) => it[SS] === iLeilao).length;
  // 16/09/2026: a contagem regressiva (#relogio) diz quanto falta; a frase
  // fica com o que aconteceu e as datas
  const frases = {
    lista: info.completo,
    aberta: `Rodada aberta: candidaturas até ${dia} às ${hora}, horário de Brasília (faltam ${falta}).`,
    fim: `Últimas horas: a rodada fecha em ${falta}, dia ${dia} às ${hora} (horário de Brasília).`,
    assentando: aindaEmLeilao
      ? `A rodada fechou em ${dia}. Os livres e os que travaram já aparecem abaixo, e ${aindaEmLeilao === 1 ? 'um leilão continua aberto' : `${num(aindaEmLeilao)} leilões continuam abertos`}.`
      : `A rodada fechou em ${dia}. Os livres e os que travaram já aparecem abaixo.`,
    entre: abre && lista > agoraMs()
      ? `Entre rodadas: a lista da próxima sai em ${curta(lista)} e a rodada abre em ${curta(abre)}, às 15h.`
      : abre
        ? `A lista da próxima rodada já deve ter saído: a rodada abre em ${curta(abre)}, às 15h.`
        : /\d/.test(proxima)
          ? `Entre rodadas: a próxima começa em ${proxima.trim()}, pela regra da segunda quarta-feira.`
          : 'Entre rodadas: a próxima começa na segunda quarta-feira do mês.',
  };
  el.textContent = frases[info.fase] || el.textContent;
  el.dataset.fase = info.fase;
  pintarBotaoDaRodada(info, abre);
  // a frase de apresentacao fala da rodada aberta; fechada, fala do que sobrou
  // (a mesma frase sai do build em paginas.subtitulo_da_pagina: mude as duas)
  const subtitulo = document.querySelector('.apresentacao .subtitulo');
  if (subtitulo && (info.fase === 'assentando' || info.fase === 'entre')) {
    const total = document.createElement('strong');
    total.textContent = num(estado.dados.total_rodada || 0);
    subtitulo.replaceChildren('Todo mês o Registro.br devolve ao mercado os domínios que não foram '
      + 'renovados. Na última rodada foram ', total, '; agora você vê os que ficaram livres para '
      + 'registrar na hora e os que travaram e voltam na próxima.');
  }
}

/*
 * O calendario que o build grava na pagina (p-calendario, de
 * garimpo/dominio/calendario.py). A regra das datas mora la; aqui so se
 * escolhe a proxima abertura.
 */
let calendario = null;
function lerCalendario() {
  if (calendario === null) {
    try {
      calendario = JSON.parse((document.querySelector('#p-calendario') || {}).textContent || '{}');
    } catch (e) {
      calendario = {};
    }
  }
  return calendario;
}

function proximaAberturaDoCalendario() {
  const cal = lerCalendario();
  const hora = String(cal.hora_abertura || 15).padStart(2, '0');
  for (const iso of cal.aberturas || []) {
    const abre = new Date(`${iso}T${hora}:00:00-03:00`);
    if (abre > agoraDaPagina()) return abre;
  }
  return null;
}

function listaDaRodada(abre) {
  return new Date(abre.getTime() - (lerCalendario().dias_lista_antes || 2) * 86400000);
}

const MESES_EXTENSO = ['janeiro', 'fevereiro', 'março', 'abril', 'maio', 'junho', 'julho',
  'agosto', 'setembro', 'outubro', 'novembro', 'dezembro'];

/** O evento da proxima rodada: o dia em que a lista sai, as 9h. */
function eventoDaRodada(abre, dominio) {
  const lista = listaDaRodada(abre);
  const iso = abre.toLocaleDateString('en-CA', { timeZone: 'America/Sao_Paulo' });
  const diaLista = lista.toLocaleDateString('en-CA', { timeZone: 'America/Sao_Paulo' });
  const inicio = new Date(`${diaLista}T09:00:00-03:00`);
  const mes = MESES_EXTENSO[Number(iso.slice(5, 7)) - 1];
  const quando = (d) => d.toLocaleDateString('pt-BR', { timeZone: 'America/Sao_Paulo', day: '2-digit', month: '2-digit' });
  return {
    cabecalho: dominio ? `Lembrar da próxima rodada para ${dominio}` : 'Lembrar da próxima rodada',
    texto: `A lista da rodada de ${mes} sai em ${quando(lista)} e a rodada abre em ${quando(abre)}, `
         + 'às 15h. O lembrete fica no dia da lista, às 9h.',
    nota: 'Datas pela regra da segunda quarta-feira; o Registro.br pode mudar por feriado.'
        + (dominio ? ' No iPhone, o arquivo traz a rodada; o nome vai no Google e no Outlook.' : ''),
    titulo: dominio ? `Nova chance de pedir ${dominio}` : `Sai a lista da rodada de liberação de ${mes}`,
    detalhes: (dominio ? `${dominio} travou e volta na rodada de ${mes}. ` : '')
            + `A lista sai hoje; a rodada abre em ${quando(abre)} às 15h e candidatar-se é de graça.`,
    inicio,
    fim: new Date(inicio.getTime() + 30 * 60000),
    url: `${location.origin}/`,
    uid: `rodada-${iso}${dominio ? '-' + dominio : ''}`,
    servido: `/lembretes/rodadas/${iso}.ics`,
    arquivo: `rodada-${iso}.ics`,
  };
}

/**
 * A abertura da rodada da lista que ja saiu. A data vem do instantaneo (o
 * cabecalho da lista oficial), nao da regra: feriado muda a regra.
 */
function eventoDaAbertura(abre) {
  const iso = abre.toLocaleDateString('en-CA', { timeZone: FUSO });
  const mes = MESES_EXTENSO[Number(iso.slice(5, 7)) - 1];
  const hora = horaCurta(abre);
  return {
    cabecalho: 'Lembrar da abertura da rodada',
    texto: `A rodada de ${mes} abre em ${horaDeBrasilia(abre)}, horário de Brasília. `
         + 'O evento ocupa a primeira meia hora.',
    nota: 'Candidatura não tem botão de cancelar: escolha antes.',
    titulo: `Rodada de liberação de ${mes} abre hoje às ${hora}`,
    detalhes: `A rodada de ${mes} abre hoje às ${hora} (horário de Brasília) e fica aberta por `
            + 'uma semana. Candidatar-se é de graça; se só você pedir um nome, ele é seu pela anuidade.',
    inicio: abre,
    fim: new Date(abre.getTime() + 30 * 60000),
    url: `${location.origin}/`,
    uid: `abertura-rodada-${iso}`,
    arquivo: 'abertura-da-rodada.ics',
  };
}

function pintarBotaoDaRodada(info, abre) {
  const botao = document.querySelector('#lembrar-rodada');
  if (!botao) return;
  const aberta = info.fase === 'aberta' || info.fase === 'fim';
  const rodada = estado.dados.rodada || {};
  const fim = new Date(rodada.fim);
  // lista saiu, rodada ainda fechada: o lembrete e o da abertura dela
  if (info.fase === 'lista') {
    const inicio = new Date(rodada.inicio);
    botao.classList.toggle('escondido', !window.Agenda || !(inicio > agoraDaPagina()));
    botao.textContent = 'Lembrar da abertura da rodada';
    botao.onclick = () => { if (window.Agenda) window.Agenda.abrir(eventoDaAbertura(inicio)); };
    return;
  }
  botao.classList.toggle('escondido', !window.Agenda || (aberta ? !(fim > agoraDaPagina()) : !abre));
  botao.textContent = aberta ? 'Lembrar do fim da rodada' : 'Me avise da próxima rodada';
  botao.onclick = () => {
    if (!window.Agenda) return;
    if (!aberta) {
      window.Agenda.abrir(eventoDaRodada(abre));
      return;
    }
    window.Agenda.abrir({
      cabecalho: 'Lembrar do fim da rodada',
      texto: `A rodada fecha em ${horaDeBrasilia(fim)}, horário de Brasília. `
           + 'O evento ocupa a última meia hora.',
      nota: 'Candidatura não tem botão de cancelar: escolha antes.',
      titulo: 'Rodada de liberação fecha hoje às 15h',
      detalhes: 'Último dia para se candidatar aos domínios .br da rodada. '
              + 'Se só você pedir um nome, ele é seu pela anuidade.',
      inicio: new Date(fim.getTime() - 30 * 60000),
      fim,
      url: `${location.origin}/`,
      uid: `fim-rodada-${fim.toISOString().slice(0, 10)}`,
      arquivo: 'fim-da-rodada.ics',
    });
  };
}

// ------------------------------------------------------------------ relogio

/*
 * A contagem regressiva do inicio (16/09/2026). O build grava a caixa com as
 * tres datas da rodada que vem (garimpo/web/paginas.relogio_da_pagina); aqui
 * o relogio anda uma vez por segundo, so com a aba visivel, e a pessoa troca
 * o alvo tocando numa data. Os digitos ficam fora do leitor de tela (um
 * anuncio por segundo); ele le o rotulo e a data por extenso.
 */
const relogio = { alvo: null, timer: null };

function marcosDoRelogio() {
  return [...document.querySelectorAll('#relogio .relogio-marco')];
}

function escolherMarco(botao) {
  const caixa = document.querySelector('#relogio');
  for (const b of marcosDoRelogio()) b.setAttribute('aria-pressed', String(b === botao));
  relogio.alvo = botao;
  $('#relogio-rotulo').textContent = botao.dataset.rotulo;
  const quando = $('#relogio-quando');
  quando.textContent = botao.dataset.texto;
  quando.setAttribute('datetime', botao.dataset.alvo);
  // a barra vai do fim da rodada anterior ate a abertura; para o fechamento,
  // da abertura ate ele
  const abre = marcosDoRelogio().find((b) => b.dataset.marco === 'abre');
  caixa.dataset.desdeAlvo = botao.dataset.marco === 'fecha' && abre
    ? abre.dataset.alvo : caixa.dataset.desde;
  caixa.dataset.marco = botao.dataset.marco;
  tiqueDoRelogio();
}

/** O primeiro que ainda nao passou, preferindo a abertura (o que a pessoa quer saber). */
function marcoPadrao() {
  const agora = agoraMs();
  const futuros = marcosDoRelogio().filter((b) => new Date(b.dataset.alvo) > agora);
  return futuros.find((b) => b.dataset.marco !== 'lista') || futuros[0] || null;
}

function tiqueDoRelogio() {
  const caixa = document.querySelector('#relogio');
  if (!caixa || !relogio.alvo) return;
  const agora = agoraMs();
  for (const b of marcosDoRelogio()) {
    const passou = new Date(b.dataset.alvo) <= agora;
    b.classList.toggle('passou', passou);
    b.disabled = passou;
  }
  const alvo = new Date(relogio.alvo.dataset.alvo).getTime();
  let resta = Math.floor((alvo - agora) / 1000);
  if (resta < 0) {
    // chegou a hora: o alvo pula para a data seguinte, e a fase da pagina muda
    const seguinte = marcoPadrao();
    if (estado.dados) pintarFase(estado.dados.rodada);
    if (seguinte && seguinte !== relogio.alvo) {
      escolherMarco(seguinte);
    } else {
      // a pagina e de antes da rodada virar: o proximo build traz as datas
      // novas. Sem alvo, andarRelogio nao reagenda o tique (18/09/2026: a
      // caixa sumia e o relogio seguia repintando a fase a cada segundo)
      caixa.classList.add('escondido');
      relogio.alvo = null;
      pararRelogio();
    }
    return;
  }
  const partes = { d: Math.floor(resta / 86400) };
  resta %= 86400;
  partes.h = Math.floor(resta / 3600);
  partes.m = Math.floor((resta % 3600) / 60);
  partes.s = resta % 60;
  for (const [u, n] of Object.entries(partes)) {
    const el = document.getElementById(`relogio-${u}`);
    const texto = u === 'd' ? String(n) : String(n).padStart(2, '0');
    if (el && el.textContent !== texto) el.textContent = texto;
  }
  caixa.classList.toggle('reta-final', alvo - agora < 24 * 3600000);
  const desde = new Date(caixa.dataset.desdeAlvo || caixa.dataset.desde).getTime();
  const barra = $('#relogio-barra');
  if (barra && alvo > desde) {
    const feito = Math.min(1, Math.max(0, (agora - desde) / (alvo - desde)));
    barra.style.setProperty('--feito', (feito * 100).toFixed(2) + '%');
  }
}

function pararRelogio() {
  clearTimeout(relogio.timer);
  relogio.timer = null;
}

function andarRelogio() {
  pararRelogio();
  // no modo busca o relogio esta recolhido (display: none): nao repinta
  if (document.hidden || document.body.classList.contains('modo-busca') || !relogio.alvo) return;
  tiqueDoRelogio();
  if (!relogio.alvo) return;       // o ultimo marco passou: o relogio para aqui
  // alinhado a virada do segundo, para os digitos nao pularem
  relogio.timer = setTimeout(andarRelogio, 1000 - (Date.now() % 1000) + 5);
}

function iniciarRelogio() {
  if (!document.querySelector('#relogio')) return;
  const inicial = marcoPadrao();
  if (!inicial) {
    document.querySelector('#relogio').classList.add('escondido');
    return;
  }
  for (const b of marcosDoRelogio()) {
    b.addEventListener('click', () => {
      escolherMarco(b);
      andarRelogio();
    });
  }
  escolherMarco(inicial);
  andarRelogio();
  document.addEventListener('visibilitychange', andarRelogio);
}

// ------------------------------------------------------------------- painel

/**
 * O seletor de marca. Antes era uma caixa "esconder risco", ligada por
 * padrao; agora e um filtro como os outros, e o padrao mostra tudo: a
 * etiqueta "possivel marca de terceiro" continua na linha, e marca famosa
 * a pessoa reconhece. "So marca" usa o mesmo criterio da etiqueta (RISCO);
 * ATENCAO nao tem etiqueta e por isso nao entra.
 */
function passaMarca(it) {
  if (estado.marca === 'sem') return it[MK] !== 2;
  if (estado.marca === 'so') return it[MK] === 2;
  return true;
}

function visiveis() {
  return estado.dados.itens.filter(passaMarca);
}

/** Os numeros dos cartoes. A parte, porque a conferencia ao vivo os muda. */
function pintarContagens() {
  const vis = visiveis();
  const contagem = {};
  for (const [chave, teste] of Object.entries(FILTROS)) {
    contagem[chave] = vis.filter(teste).length;
  }
  // a rodada inteira nao esta carregada ainda: o total vem do instantaneo
  contagem.rodada = estado.dados.total_rodada || 0;
  // acompanhado pode estar fora do instantaneo: conta a lista, nao o filtro
  contagem.acompanhados = estado.acompanhados.size;
  for (const [chave, n] of Object.entries(contagem)) {
    const el = document.getElementById('n-' + chave);
    if (el) el.textContent = num(n);
    const cartao = document.querySelector(`.cartao[data-filtro="${chave}"]`);
    if (cartao) cartao.classList.toggle('zerado', n === 0);
  }
  // "Elegiveis ao leilao" muda de papel quando a rodada fecha.
  //
  // Aberta: so diz algo enquanto ha elegivel FORA do leilao, nas primeiras
  // ~30 h (joias e disputados). Depois e a mesma lista de "Em leilao", nome
  // por nome, e dois cartoes iguais confundem.
  //
  // Fechada: vira a historia da rodada ("Foram a leilao"). E a unica lista
  // que nao encolhe quando a varredura reclassifica os nomes, porque o
  // elegivel vem de lista-processo-competitivo.txt e fica; ja "Em leilao"
  // esvazia sozinho conforme cada nome vira REGISTRADO ou AGUARDANDO.
  const fechada = rodadaFechada();
  const foraDoLeilao = vis.filter((it) => it[E] === 1 && it[SS] !== iLeilao).length;
  const cardEleg = document.querySelector('[data-filtro="elegiveis"]');
  if (cardEleg) {
    // A regra de esconder e a mesma nas duas fases, e e sobre duplicacao:
    // enquanto TODO elegivel ainda esta em leilao, este cartao seria copia
    // de "Em leilao", nome por nome. Ele reaparece, ja como historia, assim
    // que a varredura tira o primeiro nome do leilao.
    cardEleg.classList.toggle('escondido', foraDoLeilao === 0);
    if (fechada) {
      cardEleg.querySelector('.titulo').textContent = 'Foram a leilão';
      cardEleg.querySelector('.ajuda').textContent = 'Os nomes mais disputados desta '
        + 'rodada: leva quem deu o maior lance. O valor de cada leilão não é publicado';
      NOMES_FILTRO.elegiveis = 'Foram a leilão';
    }
  }
  if (!fechada && foraDoLeilao === 0 && contagem.leilao
      && estado.filtro === 'elegiveis') estado.filtro = 'leilao';
  if (contagem.joias === 0 && estado.filtro === 'joias') {
    estado.filtro = contagem.sem_competicao ? 'sem_competicao' : filtroInicial();
  }
  const ajudaLeilao = document.querySelector('[data-filtro="leilao"] .ajuda');
  if (ajudaLeilao) {
    // a frase simples fica; o detalhe dos elegiveis so enquanto diz algo
    ajudaLeilao.textContent = fechada
      ? 'Ainda abertos: o leilão de um nome não acaba junto com a rodada'
      : foraDoLeilao > 0 && contagem.elegiveis
        ? `Leva quem der o maior lance: ${num(contagem.leilao)} dos ${num(contagem.elegiveis)} elegíveis já abriram`
        : 'Nomes muito disputados: leva quem der o maior lance';
  }

  // Joias nasce escondido: "0 Joias" como primeira coisa da pagina parecia
  // site quebrado. Aparece so quando ha o que mostrar, como Livre agora.
  const cardJoias = document.querySelector('[data-filtro="joias"]');
  if (cardJoias) cardJoias.classList.toggle('escondido', contagem.joias === 0);

  const cardAcomp = document.querySelector('[data-filtro="acompanhados"]');
  if (cardAcomp) cardAcomp.classList.toggle('escondido', contagem.acompanhados === 0);

  // o card de livres so aparece quando ha o que mostrar: durante a rodada
  // ninguem cai no pool livre, e um zero permanente e so ruido
  const livres = vis.filter(FILTROS.livres).length;
  const cardLivres = document.querySelector('[data-filtro="livres"]');
  if (cardLivres) cardLivres.classList.toggle('escondido', livres === 0);

  // Rodada fechada ("fechada" ja veio de cima): "Disputados" vira "Voltam na
  // proxima rodada" (os mesmos nomes, menos os elegiveis), e "Sem
  // competicao" vira historia.
  const cardAguard = document.querySelector('[data-filtro="aguardando"]');
  if (cardAguard) cardAguard.classList.toggle('escondido', contagem.aguardando === 0);
  const cardDisp = document.querySelector('[data-filtro="disputados"]');
  if (cardDisp) cardDisp.classList.toggle('escondido', fechada);
  if (fechada && estado.filtro === 'disputados') estado.filtro = 'aguardando';
  const semComp = document.querySelector('[data-filtro="sem_competicao"]');
  if (semComp && fechada) {
    semComp.querySelector('.titulo').textContent = 'Fecharam sem candidato';
    semComp.querySelector('.ajuda').textContent = 'Ninguém aparecia na consulta no fim da '
      + 'rodada: se era zero mesmo, o nome ficou livre para registro. Confira na hora';
    NOMES_FILTRO.sem_competicao = 'Fecharam sem candidato visível';
  }
  // Zerado entre rodadas, some (19/09/2026). Relida a lista inteira, nenhum
  // nome continua "fechou sem candidato": cada um virou livre, registrado ou
  // aguardando. Ficava semanas no alto da pagina, com 0 e um paragrafo de
  // explicacao, sendo a primeira coisa que alguem de fora lia. Durante a
  // rodada aberta ele nao some: ali o zero e momentaneo (todo nome lido tem
  // candidato) e um cartao que pisca parece defeito; so encurta a frase.
  if (semComp && contagem.sem_competicao === 0) {
    semComp.classList.toggle('escondido', fechada);
    if (!fechada) semComp.querySelector('.ajuda').textContent = 'Nenhum agora';
  } else if (semComp) {
    semComp.classList.remove('escondido');
  }
  if (fechada && contagem.sem_competicao === 0 && estado.filtro === 'sem_competicao') {
    estado.filtro = filtroInicial();
  }
  // o que da para fazer agora vem primeiro: livres, depois os que voltam
  const painelCartoes = document.querySelector('.cartoes');
  if (fechada && painelCartoes && cardLivres && cardAguard
      && painelCartoes.firstElementChild !== cardLivres) {
    painelCartoes.prepend(cardLivres, cardAguard);
  }
  // "Em leilao" e so o que a lista oficial (lista-competicao.txt) ainda
  // mostra, e so ela responde: LEILAO NAO ACABA JUNTO COM A RODADA. Medido
  // em 17/09/2026, uma hora depois do fim da rodada de setembro: a lista
  // ainda trazia um leilao aberto na rodada de julho, 25 da de agosto e 2
  // da de setembro (L5 em docs/limitacoes-registrobr.md). A conta antiga
  // daqui era "todo leilao acaba 24 h depois do fechamento", e anunciava
  // "os leiloes desta rodada terminaram em <data>" com leilao rodando.
  // Por isso nao ha relogio nenhum neste cartao: ele some quando zera.
  const cardLeilao = document.querySelector('[data-filtro="leilao"]');
  if (cardLeilao) cardLeilao.classList.toggle('escondido', contagem.leilao === 0);
  if (contagem.leilao === 0 && estado.filtro === 'leilao') estado.filtro = filtroInicial();
  const proxima = proximaAberturaDoCalendario();
  const ajudaAguard = cardAguard && cardAguard.querySelector('.ajuda');
  if (ajudaAguard && proxima) {
    ajudaAguard.textContent = 'Dois ou mais pediram e ninguém levou: voltam na rodada que '
      + `abre em ${proxima.toLocaleDateString('pt-BR', { timeZone: 'America/Sao_Paulo', day: '2-digit', month: '2-digit' })}`;
  }
  // Lista nova ainda sem leitura (18/09/2026): os cartoes que dependem da
  // consulta ao Registro.br somem em vez de dizer "0" como se fosse fato;
  // fica "Toda a rodada", pela nota, e o rodape diz quando a conferencia comeca
  if (aConferir()) {
    for (const f of ['joias', 'sem_competicao', 'disputados', 'elegiveis', 'livres',
      'aguardando', 'todos']) {
      const cartao = document.querySelector(`.cartao[data-filtro="${f}"]`);
      if (cartao) cartao.classList.add('escondido');
    }
  }
}

/** "a conferencia dos nomes comeca com a rodada, em 14/10, as 15h" */
function textoDaConferencia() {
  const inicio = new Date((estado.dados.rodada || {}).inicio);
  if (isNaN(inicio)) return 'A conferência dos nomes começa com a rodada.';
  const quando = `em ${inicio.toLocaleDateString('pt-BR',
    { timeZone: FUSO, day: '2-digit', month: '2-digit' })}, às ${horaCurta(inicio)}`;
  return inicio > agoraDaPagina()
    ? `A conferência dos nomes começa com a rodada, ${quando} (horário de Brasília).`
    : `A conferência dos nomes começou com a rodada, ${quando} (horário de Brasília); `
      + 'a primeira leitura chega nas próximas horas.';
}

function pintarPainel() {
  const d = estado.dados;
  pintarContagens();

  pintarCarimbo();
  pintarFase(d.rodada);

  // O denominador nao e a rodada inteira: 125 mil nomes vao para um filtro
  // de qualidade e so os selecionados sao consultados. Dizer so "X de 125
  // mil" dava a entender que o resto seria coberto um dia, e nao sera.
  // 13/09/2026: em frase de quem procura dominio. A conta do pool (quantos
  // passam no filtro, quantos na fila) mora na aba Dados e em Como
  // selecionamos, onde quem quer o numero vai procurar.
  let texto = aConferir()
    ? `A lista traz ${num(d.total_rodada || 0)} nomes, aqui pela nota. ${textoDaConferencia()}`
    : `Dos ${num(d.total_rodada)} nomes da rodada, consultamos no `
      + `Registro.br os que têm melhor nota: ${num(d.itens.length)} até agora.`;
  if (d.em_leilao_em) {
    texto += ` Leilões conferidos na lista oficial de ${formatarDataCurta(d.em_leilao_em)}.`;
  }
  // no celular o title da estrela nao aparece: sem esta frase, ninguem sabe
  // para que ela serve ate tocar
  if (!estado.acompanhados.size) {
    texto += ' Toque na estrela de um nome para acompanhá-lo e ver o que mudou quando voltar.';
  }
  $('#rodape-painel').textContent = texto;

  // Os numeros das paginas de texto sao gravados no HTML pelo build
  // (garimpo/web/paginas.py); aqui so o rodape desta pagina.
  const rodape = document.querySelector('#rodape-gerado');
  if (rodape) rodape.textContent = formatarData(d.gerado_em);
}

/**
 * A idade do instantaneo, no cabecalho. Relativa ("atualizado ha 2 h")
 * porque e isso que decide se vale conferir; a data completa fica no title
 * e no rodape. Repintada a cada minuto: a pagina costuma ficar aberta.
 */
function pintarCarimbo() {
  const d = estado.dados;
  const quando = new Date(d.gerado_em);
  const el = $('#carimbo');
  if (!el || isNaN(quando)) return;
  el.textContent = `atualizado ${idadeTexto(Math.max(0, (agoraMs() - quando) / 1000))}`;
  el.title = `Instantâneo de ${formatarData(d.gerado_em)}, `
           + `${num(d.itens.length)} domínios verificados`;
}

/**
 * Cria as opcoes do seletor de extensoes, sem duplicar (quando morava em
 * pintarPainel(), cada clique em "esconder risco de marca" duplicava a lista
 * inteira). Os numeros de cada opcao sao reescritos a cada aplicar(), em
 * pintarContagensDosFiltros.
 */
function preencherExtensoes(daRodada) {
  // chamada de novo com as extensoes da rodada inteira: so acrescenta as
  // que faltam, sem duplicar as que ja estao no seletor
  const sel = $('#extensao');
  if (daRodada) {
    const ja = new Set([...sel.options].map((o) => o.value));
    for (const ext of daRodada) {
      if (ja.has(ext)) continue;
      const o = document.createElement('option');
      o.value = ext;
      o.textContent = `.${ext}`;
      o.dataset.rotulo = `.${ext}`;
      sel.appendChild(o);
    }
    return;
  }
  const d = estado.dados;
  const contagem = new Map();
  for (const it of d.itens) {
    const e = extensaoDe(it[D]);
    contagem.set(e, (contagem.get(e) || 0) + 1);
  }
  [...contagem.entries()]
    .sort((a, b) => b[1] - a[1])
    .forEach(([ext, n]) => {
      const o = document.createElement('option');
      o.value = ext;
      o.textContent = `.${ext} (${num(n)})`;
      o.dataset.rotulo = `.${ext}`;
      sel.appendChild(o);
    });
}

// ---------------------------------------------------------- por pagina

function lerPorPagina() {
  try {
    const n = Number(localStorage.getItem(CHAVE_POR_PAGINA));
    if (TAMANHOS_PAGINA.includes(n)) estado.porPagina = n;
  } catch (e) { /* navegacao anonima ou storage bloqueado */ }
  $('#por-pagina').value = String(estado.porPagina);
}

/** Troca o tamanho sem perder de vista o primeiro nome que estava na tela. */
function trocarPorPagina(valor) {
  const n = Number(valor);
  if (!TAMANHOS_PAGINA.includes(n)) return;
  const primeiro = estado.pagina * estado.porPagina;
  estado.porPagina = n;
  estado.pagina = Math.floor(primeiro / n);
  try {
    localStorage.setItem(CHAVE_POR_PAGINA, String(n));
  } catch (e) { /* vale so para esta aba */ }
  pintarTabela();
}

// --------------------------------------------------------------------- csv

function baixarCsv() {
  const linhas = ['dominio,situacao,candidatos,relevancia,elegivel_leilao,verificado_em'];
  for (const it of estado.atual) {
    const quando = it[VF] ? new Date(it[VF] * 1000).toISOString() : '';
    const situacao = it[SS] === NAO_VERIFICADO ? 'NAO_VERIFICADO' : estado.dados.status[it[SS]];
    linhas.push([it[D], situacao, it[C] ?? '', it[N],
                 it[E] ? 'sim' : 'nao', quando].join(','));
  }
  const blob = new Blob([linhas.join('\n')], { type: 'text/csv;charset=utf-8' });
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob);
  a.download = `liberado-${estado.filtro}.csv`;
  a.click();
  URL.revokeObjectURL(a.href);
}

// ------------------------------------------------------------- conferencia

/*
 * Conferencia ao vivo, do navegador de quem visita, direto no RDAP do
 * Registro.br. O RDAP responde com CORS aberto (`*`); o endpoint de
 * disponibilidade que a varredura usa so aceita a origem do proprio
 * Registro.br, entao nao serve daqui.
 *
 * Tres escolhas de proposito:
 *
 * - Cada visitante confere para si. Nada volta para o servidor nem passa a
 *   valer para os outros: resultado vindo de navegador alheio poderia ser
 *   forjado, e o site mostraria a mentira para todo mundo.
 * - Os links `?ticket=` da resposta NUNCA sao seguidos. Cada um devolve nome
 *   e CPF parcial de quem se candidatou. A contagem sai de `publicIds`.
 * - Uma consulta por vez, com pausa, e a fila para no primeiro erro. O
 *   limite do Registro.br e por IP e nao tem numero oficial; o que circula
 *   em fonte de terceiros e ~30 consultas a cada 5 minutos.
 *
 * O cabecalho `Nicbr-Resource` (exposto pelo CORS) separa liberacao,
 * leilao e nome travado. Mapeamento conferido em 10/09/2026 contra o endpoint de
 * disponibilidade, nome a nome.
 *
 * A consulta em si e window.Disputa.consultar (disputa.js, carregado antes
 * deste arquivo): um 429 ali bloqueia consultas novas por 5 min, cota
 * compartilhada com "quem disputa" e a ficha (18/09/2026). Sem isto, o
 * botao "conferir" deixava tentar de novo na hora, e cada toque so
 * empurrava o bloqueio do Registro.br para mais tarde.
 */
const PAUSA_RDAP = 2500;          // ms entre consultas
// Teto da conferencia que roda sozinha ao abrir, SOMANDO acompanhados e
// joias: o limite do Registro.br e por IP, e vale para o total.
const AUTOMATICAS = 20;

const fila = { itens: [], rodando: false, parada: false };

function esperar(ms) {
  return new Promise((pronto) => setTimeout(pronto, ms));
}

let reativarConferirAgendado = false;
/**
 * Sem isto, o botao "conferir" ficava desabilitado para sempre depois do
 * bloqueio de 5 min: nada mais repinta a tabela enquanto a pessoa nao troca
 * de filtro ou de pagina. Chamado do proprio render do botao (botaoConferir),
 * deduplicado por `reativarConferirAgendado` para nao empilhar um setTimeout
 * por linha da tabela.
 */
function agendarReativacaoConferir() {
  if (reativarConferirAgendado || !window.Disputa || !window.Disputa.bloqueado || !window.Disputa.bloqueado()) return;
  reativarConferirAgendado = true;
  setTimeout(() => {
    reativarConferirAgendado = false;
    pintarTabela();
  }, window.Disputa.restanteBloqueio() + 200);
}

async function consultarRdap(dominio) {
  const r = await window.Disputa.consultar('domain/' + encodeURIComponent(dominio));
  // 404 no RDAP e resposta, nao erro: o nome nao existe no cadastro
  if (r.status === 404) return { situacao: 'LIVRE', candidatos: 0 };

  const recurso = r.recurso;
  const corpo = r.json;
  const tickets = (corpo.publicIds || [])
    .filter((p) => p && p.type === 'ticket').length;

  // Leilao aberto (`-running`) ou com a rodada ja fechada e ofertas ate o dia
  // seguinte (`-closed;date=<fim da rodada>`, visto em 16/09/2026).
  if (recurso.startsWith('competitive-release-process-')) {
    return { situacao: 'COMPETITIVO', candidatos: tickets };
  }
  // Nome que travou: status 5 do ISAVAIL. O RDAP responde 200 com um objeto
  // `domain` vazio (sem status, eventos nem tickets), que sem este teste caia
  // em REGISTRADO (16/09/2026, limitacao S12).
  if (recurso.startsWith('release-process-waiting')) {
    return { situacao: 'AGUARDANDO_LIBERACAO', candidatos: 0 };
  }
  if (recurso.startsWith('release-process-running')) {
    return {
      situacao: tickets ? 'LIBERACAO_DISPUTADA' : 'LIBERACAO_LIVRE',
      candidatos: tickets,
    };
  }
  if (corpo.objectClassName === 'domain') {
    return { situacao: 'REGISTRADO', candidatos: 0 };
  }
  throw new Error('resposta em formato inesperado');
}

function aplicarAoVivo(it, resposta) {
  const indice = estado.dados.status.indexOf(resposta.situacao);
  if (indice >= 0) it[SS] = indice;
  it[C] = resposta.candidatos;
  it[VF] = agoraSeg();
  estado.aoVivo.add(it[D]);
  estado.doNavegador.delete(it[D]);
  estado.conferidos.set(it[D], { s: resposta.situacao, c: resposta.candidatos, t: it[VF] });
  gravarConferidos();
}

/**
 * O que a conferencia mudou, dito em texto.
 *
 * Antes a linha simplesmente sumia: a conferencia dizia "leilao", o filtro
 * "sem competicao" a tirava da tela no mesmo instante, e quem clicou ficava
 * procurando o nome na pagina. Agora a linha fica onde estava, com um
 * marcador, ate a pessoa trocar de lista; a linha de status conta a
 * mudanca; e o titulo separa quem ja nao pertence a lista.
 *
 * `antes` e a fotografia tirada antes da consulta (aplicarAoVivo muda a
 * linha no lugar). Devolve o texto para a linha de status, ou null.
 */
function anotarMudanca(it, antes, naLista) {
  const depois = fotografia(it);
  const texto = antes.s ? textoDaMudanca(it[D], antes, depois) : null;
  if (!naLista) return texto;
  const teste = FILTROS[estado.filtro] || FILTROS.todos;
  const fora = !teste(it);
  if (!texto && !fora) return null;
  let marcador;
  if (antes.s && antes.s !== depois.s) marcador = `mudou: era ${rotuloSituacao(antes.s)}`;
  else if (texto) marcador = `mudou: candidatos de ${antes.c} para ${depois.c}`;
  else marcador = 'mudou';
  if (fora) marcador += ' · já não pertence a esta lista';
  estado.retidos.set(it[D], { texto: marcador, fora });
  return texto;
}

function avisar(texto) {
  const el = $('#ao-vivo');
  if (el) el.textContent = texto;
}

/** `frente`: pedido de quem clicou passa na frente da conferencia automatica. */
function enfileirar(itens, frente = false) {
  const novos = itens.filter((it) => !estado.aoVivo.has(it[D]) &&
                                     !fila.itens.includes(it));
  if (frente) fila.itens.unshift(...novos);
  else fila.itens.push(...novos);
  processarFila();
}

async function processarFila() {
  if (fila.rodando) return;
  fila.rodando = true;
  let feitos = 0;
  let comparados = 0;        // ja tinham situacao antes: da para dizer se mudou
  const mudados = [];

  while (fila.itens.length && !fila.parada) {
    const it = fila.itens.shift();
    estado.conferindo = it[D];
    pintarTabela();
    const faltam = fila.itens.length ? `, faltam ${fila.itens.length}` : '';
    avisar(`Conferindo ${it[D]} direto no Registro.br${faltam}…`);

    try {
      const antes = fotografia(it);
      const naLista = estado.atual.includes(it);
      aplicarAoVivo(it, await consultarRdap(it[D]));
      feitos++;
      if (antes.s) comparados++;
      const texto = anotarMudanca(it, antes, naLista);
      if (texto) mudados.push(texto);
      if (estado.acompanhados.has(it[D])) {
        const mudou = registrarMudanca(it);
        // com a pagina na frente, o quadro de mudancas ja basta
        if (mudou && document.visibilityState === 'hidden') notificar(it[D], mudou);
      }
    } catch (e) {
      fila.parada = true;
      fila.itens = [];
      // depois de um 429, e.message ja e a mensagem padrao do bloqueio
      // ("tente de novo em N min."); o prefixo generico so duplicaria
      avisar(window.Disputa && window.Disputa.bloqueado && window.Disputa.bloqueado()
        ? `${e.message} O resto da tabela continua com a idade que cada linha mostra.`
        : `A conferência parou: ${e.message}. O resto da tabela continua `
          + 'com a idade que cada linha mostra.');
    }
    estado.conferindo = null;
    pintarContagens();
    aplicar({ manterOrdem: true });

    if (fila.itens.length && !fila.parada) await esperar(PAUSA_RDAP);
  }

  if (!fila.parada && feitos) {
    const quantos = feitos === 1 ? '1 nome conferido' : `${feitos} nomes conferidos`;
    let msg = `${quantos} agora, direto no Registro.br, do seu navegador.`;
    if (mudados.length) {
      const mais = mudados.length > 3 ? `; e mais ${mudados.length - 3}` : '';
      msg += ` Mudou: ${mudados.slice(0, 3).join('; ')}${mais}. Quem saiu da lista `
           + 'fica marcado nela até você trocar de filtro.';
    } else if (comparados === feitos) {
      msg += ' Nada mudou.';
    }
    avisar(msg);
  }
  fila.rodando = false;
}

/**
 * Foi conferido ha menos de REVER_MINUTOS (na propria aba ou salvo no
 * aparelho, tanto faz: os dois atualizam it[VF]). Usado para nao reconferir
 * de novo ao abrir a pagina.
 */
function recenteConferido(it) {
  return Boolean(it[VF]) && agoraSeg() - it[VF] < REVER_MINUTOS * 60;
}

/**
 * Conferido sozinho ao abrir: primeiro os acompanhados (o mais velho antes),
 * depois as joias, que sao o destaque e ja apareceram erradas. O teto e da
 * soma, e protege o limite por IP de quem visita.
 *
 * Quem ja foi conferido ha menos de REVER_MINUTOS fica fora: sem isto, ir e
 * voltar da inicial (Dominios -> Perguntas -> Dominios) reconferia os mesmos
 * nomes a cada volta, porque estado.aoVivo (em memoria) zera a cada
 * carregamento da pagina e nao enxerga o que o localStorage 'conferidos' ja
 * sabe. A lista compartilhada fica fora do filtro: quem abriu um link quer
 * o numero fresco, mesmo que outra aba tenha conferido ha pouco.
 */
function conferirAoAbrir() {
  const acomp = [...estado.acompanhados.entries()]
    .sort((a, b) => (a[1].t || 0) - (b[1].t || 0))
    .map(([dominio]) => garantirLinha(dominio))
    .filter((it) => !recenteConferido(it));
  const joias = visiveis().filter(FILTROS.joias).filter((it) => !recenteConferido(it)).sort((a, b) => b[N] - a[N]);
  // quem abriu uma lista compartilhada quer os numeros dela, frescos
  const compartilhada = estado.filtro === 'lista' ? [...estado.lista].map(garantirLinha) : [];
  const lista = [...new Set([...compartilhada, ...acomp, ...joias])].slice(0, AUTOMATICAS);
  if (lista.length) enfileirar(lista);
}

// ----------------------------------------------------- conferido guardado

/*
 * O que voce conferiu fica no aparelho (localStorage), como a estrela.
 *
 * Sem isto, recarregar a pagina desfazia a conferencia: o nome que voce
 * acabou de ver em leilao voltava como "sem competicao, ha 21 h", e a lista
 * parecia nao ter ouvido nada. Agora a leitura do navegador vale enquanto
 * for mais nova que a do servidor (comparada nome a nome, pelo carimbo de
 * cada linha, nunca pelo gerado_em) e por no maximo 7 dias, uma rodada.
 * Continua valendo so para quem conferiu: nada volta ao servidor.
 */
const CHAVE_CONFERIDOS = 'conferidos';
const VALIDADE_CONFERIDO = 7 * 24 * 3600;

function lerConferidos() {
  const agora = agoraSeg();
  const status = estado.dados.status;
  try {
    const bruto = JSON.parse(localStorage.getItem(CHAVE_CONFERIDOS) || '{}');
    return new Map(Object.entries(bruto).filter(([d, v]) =>
      /^[a-z0-9.-]+$/.test(d) && v && typeof v === 'object'
      && status.includes(v.s)
      && Number.isInteger(v.t) && v.t > agora - VALIDADE_CONFERIDO && v.t <= agora + 300
      && Number.isInteger(v.c) && v.c >= 0));
  } catch (e) {
    return new Map();      // navegacao anonima ou storage bloqueado
  }
}

function gravarConferidos() {
  try {
    localStorage.setItem(CHAVE_CONFERIDOS,
                         JSON.stringify(Object.fromEntries(estado.conferidos)));
  } catch (e) { /* vale so para esta aba */ }
}

/** Aplica a leitura guardada a uma linha, se for mais nova que a do servidor. */
function restaurarConferido(it) {
  const v = estado.conferidos.get(it[D]);
  if (!v) return;
  // O servidor ja passou na frente, ou a lista oficial de leiloes (baixada a
  // cada execucao, sem mexer no carimbo da linha) diz leilao e a leitura
  // guardada e de antes de o nome entrar nele. A lista oficial manda.
  const superada = v.t <= (it[VF] || 0)
    || (it[EL] === 1 && v.s !== 'COMPETITIVO');
  if (superada) {
    estado.conferidos.delete(it[D]);
    return;
  }
  it[SS] = estado.dados.status.indexOf(v.s);
  it[C] = v.c;
  it[VF] = v.t;
  estado.doNavegador.add(it[D]);
}

// ------------------------------------------------------------ acompanhados

/*
 * "Me avisa se isto mudar", sem servidor.
 *
 * A estrela guarda o nome e a ultima situacao vista NESTE aparelho
 * (localStorage). Na volta, a pagina compara com o instantaneo novo e
 * confere ao vivo no RDAP; o que mudou vira um quadro no topo. Com a pagina
 * aberta, a lista e reconferida a cada 20 minutos e, se a pessoa deixou,
 * sai um aviso do sistema.
 *
 * Aviso com a pagina FECHADA exigiria servidor guardando a inscricao de
 * cada aparelho (Web Push) ou um bot com a lista de quem segue o que. As
 * duas opcoes, com custo, estao em docs/opcoes-atualizacao.md. Nada disto
 * volta ao servidor: a mesma regra da conferencia ao vivo.
 */
const CHAVE_ACOMPANHADOS = 'acompanhados';
const REVER_MINUTOS = 20;
const provisorios = new WeakSet();   // linhas criadas so para um acompanhado

function lerAcompanhados() {
  try {
    const bruto = JSON.parse(localStorage.getItem(CHAVE_ACOMPANHADOS) || '{}');
    return new Map(Object.entries(bruto).filter(([d]) => /^[a-z0-9.-]+$/.test(d)));
  } catch (e) {
    return new Map();      // navegacao anonima ou storage bloqueado
  }
}

function gravarAcompanhados() {
  try {
    localStorage.setItem(CHAVE_ACOMPANHADOS,
                         JSON.stringify(Object.fromEntries(estado.acompanhados)));
  } catch (e) { /* vale so para esta aba */ }
}

/** Linha de um nome que nao esta no instantaneo: so o nome, a conferir. */
function garantirLinha(dominio) {
  let it = estado.porDominio.get(dominio);
  if (!it) {
    it = [dominio, NAO_VERIFICADO, null, 0, 0, [], 0, 0, 0, -1, 0];
    provisorios.add(it);
    estado.porDominio.set(dominio, it);
    restaurarConferido(it);
  }
  return it;
}

/** O que se guarda de cada acompanhado. Leilao mostra "2 ou mais". */
function fotografia(it) {
  if (it[SS] === NAO_VERIFICADO) return { s: null, c: null, t: 0 };
  const s = estado.dados.status[it[SS]];
  const c = it[SS] === iLeilao ? Math.max(it[C] || 0, 2) : (it[C] ?? null);
  return { s, c, t: it[VF] || 0 };
}

function rotuloSituacao(nome) {
  return (SELOS[nome] || [null, 'não verificado'])[1];
}

function textoDaMudanca(dominio, de, para) {
  if (de.s !== para.s) {
    let texto = `${dominio} passou de ${rotuloSituacao(de.s)} para ${rotuloSituacao(para.s)}`;
    if (para.c && para.s !== 'REGISTRADO' && para.s !== 'LIVRE') {
      texto += ` (${para.c} candidatos)`;
    }
    return texto;
  }
  if (de.c != null && para.c != null && de.c !== para.c) {
    return `${dominio}: candidatos visíveis foram de ${de.c} para ${para.c}`;
  }
  return null;
}

/**
 * Compara com o guardado, guarda o novo e devolve o texto se ESTA leitura
 * mudou algo. O quadro fica com uma linha por nome, do primeiro valor
 * visto na visita ao ultimo: o instantaneo diz 7 e a conferencia ao vivo
 * diz 9 vira "de 2 para 9", nao duas linhas.
 */
function registrarMudanca(it) {
  const antes = estado.acompanhados.get(it[D]);
  const agora = fotografia(it);
  if (!antes || !agora.s) return null;
  estado.acompanhados.set(it[D], agora);
  gravarAcompanhados();
  if (!antes.s) return null;          // primeira leitura nao e mudanca

  const de = (estado.mudancas.get(it[D]) || { de: antes }).de;
  const texto = textoDaMudanca(it[D], de, agora);
  if (texto) estado.mudancas.set(it[D], { de, texto });
  else estado.mudancas.delete(it[D]);   // mudou e voltou: nada a contar
  pintarMudancas();
  return textoDaMudanca(it[D], antes, agora) ? texto : null;
}

/** Na abertura: o instantaneo novo ja pode contar o que mudou, sem rede. */
function mudancasDesdeAUltimaVisita() {
  for (const [dominio, antes] of estado.acompanhados) {
    const it = estado.porDominio.get(dominio);
    if (it && it[SS] !== NAO_VERIFICADO && (it[VF] || 0) > (antes.t || 0)) {
      registrarMudanca(it);
    }
  }
}

function pintarMudancas() {
  const caixa = $('#mudancas');
  if (!caixa) return;
  if (!estado.mudancas.size) {
    caixa.classList.add('escondido');
    caixa.replaceChildren();
    return;
  }
  const titulo = document.createElement('p');
  titulo.className = 'mudancas-titulo';
  titulo.textContent = estado.mudancas.size === 1
    ? 'Um nome que você acompanha mudou'
    : `${estado.mudancas.size} nomes que você acompanha mudaram`;
  const lista = document.createElement('ul');
  for (const { texto } of estado.mudancas.values()) {
    const li = document.createElement('li');
    li.textContent = texto;
    lista.append(li);
  }
  const ver = document.createElement('button');
  ver.type = 'button';
  ver.textContent = 'Ver acompanhados';
  ver.addEventListener('click', () => escolherFiltro('acompanhados'));
  const ok = document.createElement('button');
  ok.type = 'button';
  ok.className = 'discreto';
  ok.textContent = 'Dispensar';
  ok.addEventListener('click', () => { estado.mudancas.clear(); pintarMudancas(); });
  const acoes = document.createElement('div');
  acoes.className = 'acoes';
  acoes.append(ver, ok);
  caixa.replaceChildren(titulo, lista, acoes);
  caixa.classList.remove('escondido');
}

function podeNotificar() {
  return 'Notification' in window && Notification.permission === 'granted';
}

/**
 * O Chrome do Android recusa `new Notification()`: la o aviso so sai pelo
 * service worker. Onde nao ha nenhum dos dois (Safari fora da tela de
 * inicio), fica o quadro de mudancas.
 */
async function notificar(dominio, texto) {
  if (!podeNotificar()) return;
  const opcoes = { body: texto, tag: `liberado-${dominio}`, lang: 'pt-BR' };
  try {
    const reg = navigator.serviceWorker && await navigator.serviceWorker.getRegistration();
    if (reg) {
      await reg.showNotification('Um nome que você acompanha mudou', opcoes);
      return;
    }
    new Notification('Um nome que você acompanha mudou', opcoes);
  } catch (e) { /* sem aviso do sistema; o quadro de mudancas continua */ }
}

function registrarServico() {
  if (!('serviceWorker' in navigator)) return;
  navigator.serviceWorker.register('sw.js').catch(() => {});
}

/** So pede permissao depois de a pessoa tocar numa estrela, nunca ao abrir. */
async function pedirPermissao() {
  if (!('Notification' in window) || Notification.permission !== 'default') return;
  registrarServico();
  try { await Notification.requestPermission(); } catch (e) { /* recusou */ }
}

let revisao = null;

function iniciarRevisao() {
  if (revisao || !estado.acompanhados.size) return;
  revisao = setInterval(() => {
    if (!estado.acompanhados.size) return;
    const itens = [...estado.acompanhados.keys()].slice(0, AUTOMATICAS).map(garantirLinha);
    for (const it of itens) estado.aoVivo.delete(it[D]);   // confere de novo
    fila.parada = false;
    enfileirar(itens);
  }, REVER_MINUTOS * 60 * 1000);
}

function alternarAcompanhar(dominio) {
  const it = garantirLinha(dominio);
  if (estado.acompanhados.has(dominio)) {
    estado.acompanhados.delete(dominio);
    avisar(`Você deixou de acompanhar ${dominio}.`);
  } else {
    estado.acompanhados.set(dominio, fotografia(it));
    avisar(`Acompanhando ${dominio}, neste aparelho. Quando você voltar, a página `
         + 'confere e mostra o que mudou; com ela aberta, confere a cada '
         + `${REVER_MINUTOS} minutos.`);
    pedirPermissao();
    iniciarRevisao();
  }
  gravarAcompanhados();
  pintarContagens();
  aplicar();
}

/**
 * O seletor de ramo de negocio. As categorias vem do JSON, na ordem dos
 * bits de dominio/categorias.py: a regra mora num lugar so.
 */
function preencherCategorias() {
  const sel = $('#categoria');
  const lista = estado.dados.categorias || [];
  if (!sel) return;
  if (!lista.length) {
    sel.classList.add('escondido');     // instantaneo antigo, sem categoria
    return;
  }
  lista.forEach((c, i) => {
    const o = document.createElement('option');
    o.value = String(i);
    o.textContent = c.rotulo;
    o.dataset.rotulo = c.rotulo;
    sel.appendChild(o);
  });
}

/**
 * Link direto para um recorte (14/09/2026): as paginas por ramo levam a
 * /?ramo=pet, e um link compartilhado pode trazer ?busca= ou ?filtro=.
 */
function lerParametros() {
  const q = new URLSearchParams(location.search);
  const ramo = q.get('ramo');
  const i = (estado.dados.categorias || []).findIndex((c) => c.nome === ramo);
  if (i >= 0) {
    estado.categoria = String(i);
    $('#categoria').value = String(i);
  }
  const busca = (q.get('busca') || '').trim();
  if (busca) {
    estado.busca = busca;
    $('#busca').value = busca;
  }
  const filtro = q.get('filtro');
  if (filtro && FILTROS[filtro] && filtro !== 'lista') estado.filtroPedido = filtro;
  const opcao = (sel, v) => [...$(sel).options].some((o) => o.value === v);
  const ordem = q.get('ordem');
  if (ordem && opcao('#ordem', ordem)) {
    estado.ordem = ordem;
    $('#ordem').value = ordem;
  }
  const marca = q.get('marca');
  if (marca && opcao('#marca', marca)) {
    estado.marca = marca;
    $('#marca').value = marca;
  }
  const situacao = q.get('situacao');
  if (situacao && opcao('#situacao', situacao)) {
    estado.situacao = situacao;
    $('#situacao').value = situacao;
  }
  // extensao que so existe na rodada inteira ainda nao tem opcao: cria
  const ext = (q.get('ext') || '').toLowerCase();
  if (/^([a-z0-9-]+\.)+br$/.test(ext)) {
    if (!opcao('#extensao', ext)) {
      const o = document.createElement('option');
      o.value = ext;
      o.textContent = `.${ext}`;
      o.dataset.rotulo = `.${ext}`;
      $('#extensao').appendChild(o);
    }
    estado.extensao = ext;
    $('#extensao').value = ext;
  }
  const lista = lerListaDoLink(q.get('lista'));
  if (lista.size) {
    estado.lista = lista;
    estado.filtroPedido = 'lista';
  }
}

// --------------------------------------------------- contagem dos filtros

/**
 * Escreve em cada opcao quantos nomes ela daria agora. A opcao nao some nem
 * muda de lugar (o valor escolhido e o link ?ramo= continuam valendo); no
 * painel de extensao e ramo, a de zero fica escondida, salvo a escolhida.
 */
function pintarContagensDosFiltros(porExt, porCat, porSit) {
  const escrever = (sel, contar) => {
    if (!sel) return;
    for (const o of sel.options) {
      if (!o.value) continue;
      o.dataset.rotulo = o.dataset.rotulo || o.textContent.replace(/ \([\d.]+\)$/, '');
      const n = contar(o.value);
      o.dataset.n = String(n);
      o.textContent = `${o.dataset.rotulo} (${num(n)})`;
    }
  };
  escrever($('#extensao'), (v) => porExt.get(v) || 0);
  escrever($('#categoria'), (v) => porCat[Number(v)] || 0);
  escrever($('#situacao'), (v) => porSit.get(v) || 0);
  for (const o of $('#situacao').options) o.hidden = Boolean(o.value) && o.dataset.n === '0' && !o.selected;
  sincronizarBuscaveis();
}

// ------------------------------------------------------ lista compartilhada

/*
 * "Manda a minha lista para um amigo" (15/09/2026). Sem servidor, o link
 * carrega os proprios nomes: /?lista=one,peca,grita.ia.br (.com.br sai
 * abreviado). Quem abre ve a lista com a situacao do instantaneo, a pagina
 * confere as primeiras ao vivo, e nada entra nos favoritos dele sem o botao
 * "Acompanhar todos".
 */
const MAXIMO_LISTA = 200;

function lerListaDoLink(bruto) {
  const nomes = new Set();
  for (const pedaco of String(bruto || '').toLowerCase().split(',')) {
    let d = pedaco.trim().replace(/^www\./, '');
    if (!d) continue;
    if (!d.includes('.')) d += '.com.br';
    if (!/^[a-z0-9][a-z0-9-]{0,62}(\.[a-z0-9-]{1,63})*\.br$/.test(d)) continue;
    nomes.add(d);
    if (nomes.size >= MAXIMO_LISTA) break;
  }
  return nomes;
}

function linkDaLista(nomes) {
  const curtos = [...nomes].slice(0, MAXIMO_LISTA)
    .map((d) => (d.endsWith('.com.br') && d.split('.').length === 3 ? d.slice(0, -7) : d));
  return `${location.origin}/?lista=${curtos.join(',')}`;
}

function avisarLista(texto) {
  const el = $('#lista-aviso');
  el.textContent = texto;
  clearTimeout(el.timer);
  el.timer = setTimeout(() => { el.textContent = ''; }, 3000);
}

// ------------------------------------------------- endereco = o que esta na tela

/*
 * O endereco da pagina carrega o cartao e os filtros (15/09/2026), como em
 * loja online e na busca do GitHub: /?filtro=leilao&ext=com.br&ramo=pet.
 * Quem recebe o link abre a mesma lista, conferida no navegador dele. So vai
 * no endereco o que difere do padrao. "Acompanhando" vira ?filtro=acompanhados
 * na barra (recarregar mostra os seus); ao compartilhar vira ?lista= com os
 * nomes, porque o amigo nao tem as suas estrelas.
 */
function parametrosDaTela(paraCompartilhar = false) {
  const q = new URLSearchParams();
  const f = estado.filtro;
  let lista = null;
  if (f === 'lista') lista = estado.lista;
  else if (f === 'acompanhados' && paraCompartilhar) lista = estado.acompanhados.keys();
  // ao compartilhar o cartao vai sempre: o cartao inicial de quem abre pode ser outro
  // a busca na rodada inteira nao leva cartao: quem abre o link cai nela
  // tambem; cartao escolhido com busca vai sempre, senao o link voltaria a
  // rodada inteira
  else if (f && !buscaNaRodada()
           && (paraCompartilhar || f !== estado.filtroInicial || estado.cartaoEscolhido)) {
    q.set('filtro', f);
  }
  const busca = estado.busca.trim();
  if (busca) q.set('busca', busca);
  if (estado.ordem !== 'nota') q.set('ordem', estado.ordem);
  if (estado.extensao) q.set('ext', estado.extensao);
  const cat = (estado.dados.categorias || [])[Number(estado.categoria)];
  if (estado.categoria !== '' && cat) q.set('ramo', cat.nome);
  if (estado.marca) q.set('marca', estado.marca);
  if (estado.situacao) q.set('situacao', estado.situacao);
  // a lista vai por ultimo e com virgula legivel (so [a-z0-9.-], sem escape)
  let texto = q.toString();
  if (lista) {
    const nomes = linkDaLista(lista).split('?lista=')[1];
    texto = `lista=${nomes}${texto ? `&${texto}` : ''}`;
  }
  return texto;
}

function atualizarEndereco() {
  if (!estado.dados) return;
  const busca = parametrosDaTela();
  const novo = location.pathname + (busca ? `?${busca}` : '') + location.hash;
  if (novo !== location.pathname + location.search + location.hash) {
    history.replaceState(null, '', novo);
  }
}

async function compartilharTela() {
  const busca = parametrosDaTela(true);
  const url = `${location.origin}/${busca ? `?${busca}` : ''}`;
  const n = estado.atual.length;
  const partes = [buscaNaRodada() ? 'Toda a rodada' : (NOMES_FILTRO[estado.filtro] || 'Domínios')];
  if (estado.extensao) partes.push(`.${estado.extensao}`);
  const cat = (estado.dados.categorias || [])[Number(estado.categoria)];
  if (estado.categoria !== '' && cat) partes.push(cat.rotulo);
  const termo = estado.busca.trim();
  if (termo) partes.push(/^["“”].*["“”]$/.test(termo) ? termo : `“${termo}”`);
  const texto = `${partes.join(' · ')}: ${num(n)} ${n === 1 ? 'domínio' : 'domínios'} no Liberados`;
  try {
    if (window.matchMedia('(pointer: coarse)').matches && navigator.share) {
      await navigator.share({ title: 'Liberados', text: texto, url });
      return;
    }
    await navigator.clipboard.writeText(url);
    const cortada = estado.filtro === 'acompanhados' && estado.acompanhados.size > MAXIMO_LISTA;
    avisarLista(cortada ? `Link copiado com os primeiros ${MAXIMO_LISTA} nomes` : 'Link copiado');
  } catch (e) {
    // fechar a folha de compartilhar cai aqui; sem area de transferencia,
    // mostra o link para copiar a mao
    if (e && e.name !== 'AbortError') window.prompt('Copie o link:', url);
  }
}

function acompanharLista() {
  let novos = 0;
  for (const d of estado.lista) {
    if (estado.acompanhados.has(d)) continue;
    estado.acompanhados.set(d, fotografia(garantirLinha(d)));
    novos++;
  }
  gravarAcompanhados();
  if (novos) iniciarRevisao();
  pintarContagens();
  aplicar();
  avisarLista(novos ? `${novos} ${novos === 1 ? 'nome adicionado' : 'nomes adicionados'} aos seus acompanhados`
                    : 'Você já acompanha todos');
}

const ICONE_COMPARTILHAR = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 3v12M7.5 7.5 12 3l4.5 4.5"/><path d="M5 12v7a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2v-7"/></svg>';

function pintarBotoesDaLista() {
  $('#btn-lista-acompanhar').classList.toggle('escondido',
    !(estado.filtro === 'lista' && estado.lista.size));
}

// ----------------------------------------------------------- rodada inteira

/**
 * Carrega todos.json e junta ao instantaneo.
 *
 * Nome que ja foi consultado aparece com a linha do instantaneo, que tem
 * situacao e idade. O resto vira linha NAO_VERIFICADO: nota, motivos e
 * risco de marca, sem situacao. "conferir" funciona igual nas duas.
 */
function carregarRodada({ aviso = true } = {}) {
  if (estado.rodada) return Promise.resolve();
  // quem chega com a carga em andamento espera a mesma (o foco na busca
  // comeca a baixar; o cartao ou o resumo tocados logo depois esperam ela)
  if (!estado.promessaRodada) {
    estado.promessaRodada = baixarRodada(aviso).finally(() => { estado.promessaRodada = null; });
  }
  return estado.promessaRodada;
}

async function baixarRodada(aviso) {
  estado.carregandoRodada = true;
  // a busca avisa no proprio resumo ("buscando nos N nomes"); o #ao-vivo e
  // da conferencia ao vivo
  if (aviso) avisar('Carregando a lista completa da rodada (cerca de 0,8 MB)…');
  try {
    const r = await fetch('todos.json');
    if (!r.ok) throw new Error(`http ${r.status}`);
    const t = await r.json();
    const d = estado.dados;
    // os motivos do todos.json entram no fim do vocabulario do instantaneo
    const deslocamento = d.motivos.length;
    d.motivos.push(...t.motivos);
    const riscos = (t.marcas || []).map((m) => d.marcas.indexOf(m));
    const juntos = [];
    const vistos = new Set();
    for (const [rotulo, ext, nota, tipos, risco, cats] of t.itens) {
      const dominio = `${rotulo}.${t.extensoes[ext]}`;
      const conhecido = estado.porDominio.get(dominio);
      if (conhecido && provisorios.has(conhecido)) {
        // acompanhado de fora do instantaneo: ganha nota, motivos e ramo
        conhecido[N] = nota;
        conhecido[M] = tipos.map((i) => i + deslocamento);
        conhecido[MK] = Math.max(0, riscos[risco] ?? 0);
        conhecido[CT] = cats || 0;
        conhecido[RN] = normalizarTermo(rotulo);
        provisorios.delete(conhecido);
        juntos.push(conhecido);
      } else if (conhecido) {
        conhecido[RN] = normalizarTermo(rotulo);
        juntos.push(conhecido);
      } else {
        // o rotulo normalizado uma vez, na carga: cada tecla so compara
        const linha = [dominio, NAO_VERIFICADO, null, nota, 0,
                       tipos.map((i) => i + deslocamento),
                       Math.max(0, riscos[risco] ?? 0), 0, 0, -1, cats || 0,
                       0, 0, normalizarTermo(rotulo)];
        estado.porDominio.set(dominio, linha);
        restaurarConferido(linha);
        juntos.push(linha);
      }
      vistos.add(dominio);
    }
    // o instantaneo pode ter nome que ja saiu da lista (historico): fica
    for (const it of d.itens) if (!vistos.has(it[D])) juntos.push(it);
    estado.rodada = juntos;
    preencherExtensoes(t.extensoes);
    if (aviso) avisar('');
  } catch (e) {
    avisar(`Não consegui carregar a lista completa (${e.message}).`);
  } finally {
    estado.carregandoRodada = false;
  }
}

// --------------------------------------------------------- filtro com busca

/**
 * Extensao (116 opcoes na rodada inteira) e ramo (19): um botao com cara de
 * seletor abre um painel com busca e a lista (14/09/2026).
 *
 * A primeira versao (mesmo dia) era um campo de texto no lugar do seletor.
 * No celular, tocar nele abria o teclado e selecionava o texto antes de a
 * pessoa ver a lista (relato do dono, com captura). O desenho de agora e o
 * de bibliotecas como shadcn/ui (painel inferior no celular, painel ancorado
 * no computador) e o que a Baymard recomenda para lista longa no celular:
 *
 * - o gatilho e um <button>: tocar nao abre teclado;
 * - o painel e um <dialog> modal (prende o foco, Esc fecha, o resto da
 *   pagina fica inerte para leitor de tela);
 * - no celular o foco vai para a opcao escolhida e a busca so abre o teclado
 *   se for tocada; no computador vai direto para a busca;
 * - cada opcao e um <button> com aria-pressed: nativo, sem
 *   aria-activedescendant.
 *
 * O <select> continua no DOM, escondido, como fonte da verdade: quem le ou
 * escreve .value e ouve 'change' nao muda. Quem escreve .value por codigo
 * chama sincronizarBuscaveis() depois. Ordem e marca ficam nativos (5 e 3
 * opcoes).
 */
const buscaveis = [];
const celular = () => window.matchMedia('(max-width: 40rem)').matches;

function semAcento(texto) {
  return String(texto).normalize('NFD').replace(/[̀-ͯ]/g, '').toLowerCase();
}

function tornarBuscavel(sel) {
  if (!sel) return;
  const rotulo = document.querySelector(`label[for="${sel.id}"]`);
  const nomeCurto = sel.id === 'extensao' ? 'extensão' : 'ramo';

  const botao = document.createElement('button');
  botao.type = 'button';
  botao.id = `${sel.id}-botao`;
  botao.className = 'combo-botao';
  botao.setAttribute('aria-haspopup', 'dialog');
  botao.setAttribute('aria-expanded', 'false');
  const valor = document.createElement('span');
  valor.id = `${sel.id}-valor`;
  valor.className = 'combo-valor';
  botao.appendChild(valor);
  if (rotulo) {
    rotulo.id = rotulo.id || `${sel.id}-rotulo`;
    rotulo.htmlFor = botao.id;
    // "Filtrar por extensao, .com.br (14.658)": o rotulo sozinho apagaria o valor
    botao.setAttribute('aria-labelledby', `${rotulo.id} ${valor.id}`);
  }

  const painel = document.createElement('dialog');
  painel.className = 'combo-painel';
  painel.setAttribute('aria-labelledby', `${sel.id}-titulo`);
  painel.innerHTML = `
    <div class="combo-topo">
      <h2 class="combo-titulo" id="${sel.id}-titulo">${esc(rotulo ? rotulo.textContent : nomeCurto)}</h2>
      <button type="button" class="combo-fechar" aria-label="Fechar">&times;</button>
    </div>
    <label class="sr-apenas" for="${sel.id}-filtro">Buscar ${nomeCurto}</label>
    <input type="search" class="combo-busca" id="${sel.id}-filtro"
           placeholder="Buscar ${nomeCurto}" autocomplete="off" spellcheck="false"
           enterkeyhint="done">
    <p class="sr-apenas" aria-live="polite" id="${sel.id}-contagem"></p>
    <div class="combo-opcoes" role="group" aria-labelledby="${sel.id}-titulo"></div>`;

  const caixa = document.createElement('div');
  caixa.className = 'combo';
  sel.parentNode.insertBefore(caixa, sel);
  caixa.append(botao, sel);
  document.body.appendChild(painel);
  // hidden, nao a classe escondido: preencherCategorias() usa a classe para
  // dizer "instantaneo sem ramo", e sincronizarBuscaveis() a le
  sel.hidden = true;
  sel.tabIndex = -1;

  const busca = painel.querySelector('.combo-busca');
  const lista = painel.querySelector('.combo-opcoes');
  const contagem = painel.querySelector(`#${sel.id}-contagem`);
  const b = { sel, caixa, botao, valor, painel };
  buscaveis.push(b);

  function pintar() {
    const q = semAcento(busca.value).trim().replace(/^\./, '');
    let vis = [...sel.options].map((o, i) => ({ o, i, t: semAcento(o.textContent).replace(/^\./, '') }));
    // opcao que daria lista vazia agora fica fora do painel, salvo a escolhida
    vis = vis.filter((x) => !x.o.value || x.o.selected || x.o.dataset.n !== '0');
    if (q) {
      vis = vis.filter((x) => x.o.value && x.t.includes(q));
      // quem digita "rio" quer .rio.br antes de .floripa.br
      vis.sort((a, c) => (a.t.startsWith(q) ? 0 : 1) - (c.t.startsWith(q) ? 0 : 1) || a.i - c.i);
    }
    lista.replaceChildren(...vis.map((x) => {
      const op = document.createElement('button');
      op.type = 'button';
      op.className = 'combo-opcao';
      op.dataset.i = String(x.i);
      op.setAttribute('aria-pressed', String(x.o.selected));
      op.textContent = x.o.textContent;
      return op;
    }));
    if (!vis.length) {
      const p = document.createElement('p');
      p.className = 'combo-vazio';
      p.textContent = `Nenhuma ${nomeCurto} com esse nome.`;
      lista.appendChild(p);
    }
    contagem.textContent = q ? `${vis.length} ${vis.length === 1 ? 'opção' : 'opções'}` : '';
  }

  function posicionar() {
    if (celular()) {
      painel.style.removeProperty('--combo-topo');
      painel.style.removeProperty('--combo-esquerda');
      return;
    }
    const r = botao.getBoundingClientRect();
    const largura = Math.max(r.width, 280);
    const esquerda = Math.min(r.left, window.innerWidth - largura - 16);
    painel.style.setProperty('--combo-topo', `${Math.round(r.bottom + 4)}px`);
    painel.style.setProperty('--combo-esquerda', `${Math.round(Math.max(16, esquerda))}px`);
    painel.style.setProperty('--combo-largura', `${Math.round(largura)}px`);
  }

  // teclado virtual: o painel inferior encolhe para a busca e a lista
  // ficarem acima dele (no Android o layout nao encolhe sozinho)
  function acompanharTeclado() {
    const vv = window.visualViewport;
    if (!vv || !celular()) return;
    painel.style.setProperty('--combo-visivel', `${Math.round(vv.height + vv.offsetTop)}px`);
  }

  function abrir() {
    busca.value = '';
    pintar();
    posicionar();
    acompanharTeclado();
    painel.showModal();
    botao.setAttribute('aria-expanded', 'true');
    const escolhida = lista.querySelector('[aria-pressed="true"]');
    if (celular()) {
      // sem teclado: a pessoa ve a lista; a busca abre o teclado se tocada
      (escolhida || lista.querySelector('.combo-opcao'))?.focus({ preventScroll: true });
      escolhida?.scrollIntoView({ block: 'center' });
    } else {
      busca.focus();
      escolhida?.scrollIntoView({ block: 'nearest' });
    }
  }

  function fechar() {
    if (painel.open) painel.close();
  }

  function escolher(i) {
    const o = sel.options[i];
    if (o && sel.value !== o.value) {
      sel.value = o.value;
      sel.dispatchEvent(new Event('change', { bubbles: true }));
    }
    fechar();
  }

  botao.addEventListener('click', abrir);
  painel.addEventListener('close', () => {
    botao.setAttribute('aria-expanded', 'false');
    sincronizarBuscaveis();
    botao.focus({ preventScroll: true });
  });
  painel.querySelector('.combo-fechar').addEventListener('click', fechar);
  // clique fora do quadro (no fundo do modal) fecha
  painel.addEventListener('click', (e) => {
    if (e.target === painel) fechar();
    const op = e.target.closest('.combo-opcao');
    if (op) escolher(Number(op.dataset.i));
  });
  busca.addEventListener('input', pintar);
  busca.addEventListener('keydown', (e) => {
    if (e.key === 'ArrowDown') {
      e.preventDefault();
      lista.querySelector('.combo-opcao')?.focus();
    } else if (e.key === 'Enter') {
      // uma busca, um Enter: fica com a primeira da lista filtrada
      e.preventDefault();
      const primeira = lista.querySelector('.combo-opcao');
      if (busca.value.trim() && primeira) escolher(Number(primeira.dataset.i));
      else busca.blur();
    }
  });
  lista.addEventListener('keydown', (e) => {
    const ops = [...lista.querySelectorAll('.combo-opcao')];
    const n = ops.indexOf(document.activeElement);
    if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
      e.preventDefault();
      if (e.key === 'ArrowUp' && n <= 0) { busca.focus(); return; }
      ops[Math.min(ops.length - 1, n + (e.key === 'ArrowDown' ? 1 : -1))]?.focus();
    } else if (e.key === 'Home' || e.key === 'End') {
      e.preventDefault();
      (e.key === 'Home' ? ops[0] : ops[ops.length - 1])?.focus();
    } else if (e.key.length === 1 && !e.ctrlKey && !e.metaKey && !e.altKey && e.key !== ' ') {
      // digitar com a lista em foco vai para a busca, como num seletor nativo
      busca.focus();
    }
  });
  window.visualViewport?.addEventListener('resize', () => { if (painel.open) acompanharTeclado(); });
  window.addEventListener('resize', () => { if (painel.open) posicionar(); });
  // no computador o painel e ancorado ao botao: rolar a pagina o soltaria
  window.addEventListener('scroll', () => { if (painel.open && !celular()) fechar(); }, { passive: true });
}

/** Mostra no botao o que o <select> tem agora (depois de .value por codigo). */
function sincronizarBuscaveis() {
  for (const b of buscaveis) {
    b.caixa.classList.toggle('escondido', b.sel.classList.contains('escondido'));
    b.valor.textContent = (b.sel.selectedOptions[0] || b.sel.options[0] || {}).textContent || '';
  }
}

// ------------------------------------------------------------------ eventos

function ligarEventos() {
  // um ouvinte so, na tabela: as linhas sao refeitas a cada pagina
  $('#corpo-tabela').addEventListener('click', (e) => {
    const lembrar = e.target.closest('[data-lembrar]');
    if (lembrar) {
      abrirLembrete(lembrar.dataset.lembrar);
      return;
    }
    const rodada = e.target.closest('[data-lembrar-rodada]');
    if (rodada) {
      const abre = proximaAberturaDoCalendario();
      if (abre && window.Agenda) window.Agenda.abrir(eventoDaRodada(abre, rodada.dataset.lembrarRodada));
      return;
    }
    const estrela = e.target.closest('[data-acompanhar]');
    if (estrela) {
      alternarAcompanhar(estrela.dataset.acompanhar);
      return;
    }
    const botao = e.target.closest('[data-conferir]');
    if (!botao) return;
    const it = estado.porDominio.get(botao.dataset.conferir);
    if (!it) return;
    if (window.Disputa && window.Disputa.bloqueado && window.Disputa.bloqueado()) {
      avisar(window.Disputa.mensagemBloqueio());
      pintarTabela();               // desenha o botao ja desabilitado
      return;
    }
    estado.aoVivo.delete(it[D]);   // pedido explicito: confere de novo
    fila.parada = false;           // e retoma, se um erro tinha parado a fila
    enfileirar([it], true);
  });

  document.querySelectorAll('.cartao').forEach((c) => {
    c.addEventListener('click', () => escolherFiltro(c.dataset.filtro));
  });

  let timer;
  const buscar = () => {
    clearTimeout(timer);
    estado.busca = $('#busca').value;
    estado.pagina = 0;
    aplicar({ aosPoucos: true });
  };
  $('#busca').addEventListener('input', () => {
    clearTimeout(timer);
    timer = setTimeout(buscar, 100);
  });
  // A rodada inteira (todos.json) comeca a baixar no primeiro foco, nao na
  // abertura: quem nao busca nao paga por ela (19/09/2026)
  $('#busca').addEventListener('focus', () => {
    carregarRodada({ aviso: false }).then(() => {
      if (estado.rodada && modoDaBusca(estado.busca).termo.length >= MINIMO_BUSCA_RODADA) aplicar();
    });
    // o resumo passa a dizer "buscando nos N nomes" enquanto baixa
    if (!estado.rodada && modoDaBusca(estado.busca).termo.length >= MINIMO_BUSCA_RODADA) aplicar();
  }, { once: true });
  // Enter leva a lista. No modo busca ela ja esta logo abaixo da caixa: no
  // celular o teclado fecha e a caixa vai ao topo, e o resumo e as primeiras
  // linhas cabem na tela; no computador o foco fica na caixa
  $('#busca').addEventListener('keydown', (e) => {
    if (e.key !== 'Enter') return;
    buscar();
    if (!estado.modoBusca) {
      $('#controles').scrollIntoView({ block: 'start' });
      return;
    }
    if (window.matchMedia && matchMedia('(pointer: coarse)').matches) $('#busca').blur();
    $('.busca-topo').scrollIntoView({ block: 'start' });
  });
  $('#limpar-busca').addEventListener('click', limparBusca);
  $('#resumo-busca').addEventListener('click', (e) => {
    const b = e.target.closest('button');
    if (!b) return;
    if ('limparFiltros' in b.dataset) {
      // o botao some com o resumo refeito: o foco fica no resumo, nao no vazio
      limparSoFiltros();
      const resumo = $('#resumo-busca');
      resumo.tabIndex = -1;
      resumo.focus({ preventScroll: true });
      return;
    }
    if (b.dataset.cartao && b.getAttribute('aria-pressed') !== 'true') {
      escolherFiltro(b.dataset.cartao);
    } else {
      buscarNaRodadaInteira();
    }
    if ('rolar' in b.dataset) $('#controles').scrollIntoView({ block: 'start' });
  });

  $('#ordem').addEventListener('change', (e) => {
    estado.ordem = e.target.value;
    estado.pagina = 0;
    aplicar();
  });

  $('#extensao').addEventListener('change', (e) => {
    estado.extensao = e.target.value;
    estado.pagina = 0;
    aplicar();
  });

  $('#categoria').addEventListener('change', (e) => {
    estado.categoria = e.target.value;
    estado.pagina = 0;
    aplicar();
  });

  $('#marca').addEventListener('change', (e) => {
    estado.marca = e.target.value;
    estado.pagina = 0;
    pintarContagens();
    aplicar();
  });

  $('#situacao').addEventListener('change', (e) => {
    estado.situacao = e.target.value;
    estado.pagina = 0;
    aplicar();
  });

  $('#btn-compartilhar').addEventListener('click', compartilharTela);
  $('#btn-lista-acompanhar').addEventListener('click', acompanharLista);

  $('#por-pagina').addEventListener('change', (e) => trocarPorPagina(e.target.value));

  $('#btn-anterior').addEventListener('click', () => {
    if (estado.pagina > 0) { estado.pagina--; pintarTabela(); window.scrollTo(0, 0); }
  });
  $('#btn-proxima').addEventListener('click', () => {
    estado.pagina++; pintarTabela(); window.scrollTo(0, 0);
  });

  $('#btn-csv').addEventListener('click', baixarCsv);
}

// -------------------------------------------------------------------- inicio

async function iniciar() {
  const r = await fetch('dados.json');
  estado.dados = await r.json();

  const s = estado.dados.status;
  iSemComp = s.indexOf('LIBERACAO_LIVRE');
  iDisputado = s.indexOf('LIBERACAO_DISPUTADA');
  iLeilao = s.indexOf('COMPETITIVO');
  iLivre = s.indexOf('LIVRE');
  iRegistrado = s.indexOf('REGISTRADO');
  iAguardando = s.indexOf('AGUARDANDO_LIBERACAO');

  // Defesa em profundidade: o exportador ja aplica a lista oficial de
  // leiloes, mas um instantaneo antigo nao aplicava. Nome na lista nunca e
  // "sem competicao", seja la o que diga a ultima consulta.
  for (const it of estado.dados.itens) {
    if (it[EL] === 1 && (it[SS] === iSemComp || it[SS] === iDisputado)) {
      it[SS] = iLeilao;
    }
  }

  estado.porDominio = new Map(estado.dados.itens.map((it) => [it[D], it]));

  // os .ics que o exportador gerou: leilao segundo o instantaneo, antes de
  // qualquer conferencia ao vivo mexer na situacao
  estado.lembretesServidos = new Set(
    estado.dados.itens.filter((it) => it[SS] === iLeilao).map((it) => it[D]));
  // Depois da defesa acima e dos lembretes: a leitura guardada e mais nova
  // que o instantaneo e manda sobre ele, mas o .ics so existe para quem o
  // exportador viu em leilao.
  estado.conferidos = lerConferidos();
  for (const it of estado.dados.itens) restaurarConferido(it);
  gravarConferidos();          // sem o que venceu ou o servidor ja cobriu

  estado.acompanhados = lerAcompanhados();
  for (const dominio of estado.acompanhados.keys()) garantirLinha(dominio);

  $('#btn-compartilhar').innerHTML = ICONE_COMPARTILHAR;
  ligarEventos();
  pintarPainel();
  preencherExtensoes();
  preencherCategorias();
  tornarBuscavel($('#extensao'));
  tornarBuscavel($('#categoria'));
  lerParametros();
  lerPorPagina();
  sincronizarBuscaveis();
  mudancasDesdeAUltimaVisita();

  // Rodada nova: quando a lista muda, o instantaneo recomeca do zero e todo
  // cartao mostra 0 ate as consultas acumularem. filtroInicial() cai entao
  // na lista completa, a unica com o que mostrar.
  estado.filtroInicial = filtroInicial();
  estado.filtro = estado.filtroPedido || estado.filtroInicial;
  // ?filtro= no link e cartao escolhido: a busca fica nele
  estado.cartaoEscolhido = Boolean(estado.filtroPedido);
  // link com ?busca= de 3 letras ou mais reabre a busca na rodada inteira
  if (estado.filtro === 'rodada' || buscaNaRodada()) await carregarRodada();
  aplicar();
  conferirAoAbrir();

  if (estado.acompanhados.size) {
    if (podeNotificar()) registrarServico();
    iniciarRevisao();
  }
  setInterval(pintarCarimbo, 60 * 1000);
}

// Link com ?busca= de 3 letras ou mais: o modo busca entra antes de o JSON
// chegar, para o relogio e os cartoes nao aparecerem e sumirem (sem script
// inline por causa da CSP, este e o primeiro ponto possivel)
try {
  const q = new URLSearchParams(location.search);
  if (!q.has('lista') && buscaPedeModo(q.get('busca') || '', q.get('filtro'))) {
    // sem teclado aberto a caixa pode subir: no celular o subtitulo sai
    document.body.classList.add('modo-busca', 'modo-busca-link');
  }
} catch (e) { /* sem o modo, a pagina abre como sempre */ }
iniciarRelogio();
iniciar().catch((e) => {
  console.error('falha ao iniciar', e);
  const vazio = document.querySelector('#vazio');
  if (vazio) {
    vazio.classList.remove('escondido');
    vazio.textContent = 'Não consegui carregar os dados desta página.';
  }
});
