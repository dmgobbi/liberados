'use strict';

const $ = (s) => document.querySelector(s);
const POR_PAGINA = 100;

const estado = {
  filtro: 'joias',
  busca: '',
  ordem: 'nota',
  pagina: 0,
  esconderRisco: true,
  visiveis: [],
  rodando: false,
};

const NOMES_FILTRO = {
  joias: 'Joias: elegível ao leilão e sem candidato visível',
  sem_competicao: 'Sem competição',
  disputados: 'Disputados',
  leilao: 'Em leilão',
  marcados: 'Marcados',
  nao_verificados: 'Ainda não verificados',
  todos: 'Todos',
  elegiveis: 'Elegíveis ao leilão',
  livres: 'Livres para registro imediato',
  risco_marca: 'Risco de marca',
};

const SELOS = {
  LIBERACAO_LIVRE: ['sem_competicao', 'sem competição'],
  LIBERACAO_DISPUTADA: ['disputado', 'disputado'],
  COMPETITIVO: ['leilao', 'leilão aberto'],
  LIVRE: ['livre', 'livre agora'],
  REGISTRADO: ['registrado', 'registrado'],
  LIMITADO: ['erro', 'bloqueado'],
  ERRO: ['erro', 'erro'],
};

// --------------------------------------------------------------- utilidades

/** Nada vindo do servidor entra no DOM sem passar por aqui (SEC-01). */
function esc(valor) {
  return String(valor ?? '').replace(/[&<>"']/g, (c) => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
  }[c]));
}

async function api(rota, opcoes) {
  const r = await fetch(rota, opcoes);
  if (!r.ok && r.status >= 500) throw new Error(`servidor respondeu ${r.status}`);
  return r.json();
}

const postar = (rota, corpo) => api(rota, {
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify(corpo || {}),
});

function quando(iso) {
  if (!iso) return 'nunca';
  const min = Math.round((Date.now() - new Date(iso).getTime()) / 60000);
  if (min < 1) return 'agora';
  if (min < 60) return `há ${min} min`;
  const h = Math.round(min / 60);
  return h < 24 ? `há ${h} h` : new Date(iso).toLocaleDateString('pt-BR');
}

function duracao(seg) {
  if (seg == null) return '';
  if (seg < 60) return `${seg}s restantes`;
  const m = Math.round(seg / 60);
  return m < 60 ? `~${m} min restantes` : `~${Math.round(m / 60)} h restantes`;
}

const num = (n) => Number(n).toLocaleString('pt-BR');

const HORAS_DE_AVISO = 48;      // a partir daqui o prazo vira noticia
const DIA = 24;

function faseDaRodada(inicio, fim) {
  if (!fim) return null;
  const abertura = inicio ? new Date(inicio) : null;
  const fechamento = new Date(fim);
  if (isNaN(fechamento)) return null;

  const agora = new Date();
  const horas = (fechamento - agora) / 3600000;
  const janela = abertura && !isNaN(abertura)
    ? (fechamento - abertura) / 3600000 : 7 * DIA;
  const decorrido = Math.min(1, Math.max(0, 1 - horas / janela));

  const dia = fechamento.toLocaleDateString('pt-BR',
    { day: '2-digit', month: '2-digit' });
  const hora = fechamento.toLocaleTimeString('pt-BR',
    { hour: '2-digit', minute: '2-digit' });

  if (horas > HORAS_DE_AVISO) {
    return {
      fase: 'aberta', decorrido,
      completo: `Rodada aberta, fecha em ${Math.round(horas / DIA)} dias, `
              + `dia ${dia} as ${hora}. Candidaturas ainda valem.`,
    };
  }
  if (horas > 0) {
    const resta = horas < 1
      ? 'menos de uma hora'
      : `${Math.round(horas)} h`;
    return {
      fase: 'fim', decorrido,
      curto: `fecha em ${resta}`,
      completo: `Rodada aberta, mas fecha em ${resta}, dia ${dia} as ${hora}.`,
    };
  }
  // a atribuicao nao e instantanea: leva algumas horas para assentar
  if (horas > -HORAS_DE_AVISO) {
    return {
      fase: 'assentando', decorrido: 1,
      curto: 'rodada encerrada',
      completo: 'Rodada encerrada. Os resultados levam algumas horas para '
              + 'assentar; quem ficou sem concorrente cai no pool livre.',
    };
  }
  return {
    fase: 'entre', decorrido: 1,
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
}

// ------------------------------------------------------------------- painel

async function carregarResumo() {
  const r = await api('/api/resumo');
  for (const k of ['joias', 'sem_competicao', 'disputados', 'leilao',
                   'marcados', 'nao_verificados', 'livres']) {
    const el = document.getElementById('n-' + k);
    if (el) el.textContent = num(r[k] ?? 0);
  }

  // o card de livres so aparece depois que a rodada resolve
  const cardLivres = document.querySelector('[data-filtro="livres"]');
  if (cardLivres) cardLivres.classList.toggle('escondido', !r.livres);

  pintarFase({ inicio: r.rodada_inicio, fim: r.rodada_fim });

  $('#carimbo').textContent = r.total
    ? `${num(r.verificados)} de ${num(r.total)} verificados` : '';

  const partes = [];
  if (r.total_liberacao) {
    partes.push(`${num(r.total_liberacao)} nomes na rodada`);
    partes.push(`${num(r.total_elegiveis)} elegíveis ao leilão`);
  }
  if (r.importado_em) partes.push(`listas baixadas ${quando(r.importado_em)}`);
  if (r.verificado_em) partes.push(`última verificação ${quando(r.verificado_em)}`);
  if (!r.total) partes.push('Comece clicando em "Baixar listas oficiais".');
  $('#rodape-painel').textContent = partes.join(' · ');
}

// ------------------------------------------------------------------- tabela

function selo(item) {
  const [cls, rotulo] = SELOS[item.status] || ['desconhecido', 'não verificado'];
  return `<span class="selo ${cls}">${esc(rotulo)}</span>`;
}

/**
 * A cor nao pode ser o unico portador do significado (A11Y-04): cada nivel
 * tem forma propria no CSS e um texto so para leitor de tela.
 */
function competindo(item) {
  const n = item.candidatos;
  if (n == null) {
    return '<span class="competindo competindo-nulo">&ndash;'
         + '<span class="sr-apenas"> não verificado</span></span>';
  }
  if (n === 0) {
    return '<span class="competindo competindo-zero">0'
         + '<span class="sr-apenas"> candidatos visíveis, pode ser zero ou um</span>'
         + '</span>';
  }
  const classe = n <= 2 ? 'competindo-pouco' : 'competindo-muito';
  const aviso = n <= 2 ? 'poucos candidatos' : 'muitos candidatos';
  if (window.Disputa) {
    return window.Disputa.contagem(item.dominio, n, classe, `${n} candidatos, ${aviso}`);
  }
  return `<span class="competindo ${classe}">${n}`
       + `<span class="sr-apenas"> candidatos, ${aviso}</span></span>`;
}

function linha(item) {
  const dominio = esc(item.dominio);
  const marcado = item.marcado ? 'true' : 'false';
  const elegivel = item.elegivel
    ? '<span class="pilula-elegivel">LEILAO<span class="sr-apenas">, elegível ao processo competitivo</span></span>'
    : '';
  const risco = item.nivel_marca === 'RISCO'
    ? `<span class="aviso-marca">marca: ${esc(item.motivo_marca)}</span>` : '';
  const url = `https://registro.br/busca-dominio?fqdn=${encodeURIComponent(item.dominio)}`;
  // o .com do mesmo nome, conferido no navegador so quando tocado (pontocom.js)
  const com = window.PontoCom ? window.PontoCom.botao(item.dominio) : '';

  return `<tr role="row" data-dominio="${dominio}">
    <td class="col-marca" role="cell">
      <button class="marcador" type="button" data-acao="marcar"
              aria-pressed="${marcado}"
              aria-label="Acompanhar ${dominio}">&#9733;</button>
    </td>
    <td class="dominio" role="cell">
      <a href="${url}" target="_blank" rel="noopener noreferrer">${dominio}</a>${elegivel} ${com}
      ${risco}
    </td>
    <td class="col-situacao" role="cell">${selo(item)}</td>
    <td class="num col-competindo" role="cell">${competindo(item)}</td>
    <td class="num col-nota" role="cell">${esc(item.nota)}</td>
    <td class="porque col-porque" role="cell">${esc(item.motivos)}</td>
    <td class="num col-acao" role="cell">
      <button type="button" data-acao="verificar"
              aria-label="Atualizar ${dominio} consultando o Registro.br">Atualizar</button>
    </td>
  </tr>`;
}

async function carregarLista() {
  const p = new URLSearchParams({
    filtro: estado.filtro,
    busca: estado.busca,
    ordem: estado.ordem,
    limite: POR_PAGINA,
    deslocamento: estado.pagina * POR_PAGINA,
    risco: estado.esconderRisco ? 'esconder' : 'mostrar',
  });

  let r;
  try {
    r = await api('/api/dominios?' + p);
  } catch (e) {
    $('#vazio').classList.remove('escondido');
    $('#vazio').textContent = 'Não consegui falar com o servidor local. '
      + 'Ele ainda está rodando?';
    return;
  }

  estado.visiveis = r.itens.map((i) => i.dominio);
  $('#corpo-tabela').innerHTML = r.itens.map(linha).join('');
  $('#tabela').classList.toggle('escondido', r.itens.length === 0);

  const vazio = $('#vazio');
  vazio.classList.toggle('escondido', r.itens.length !== 0);
  if (!r.itens.length) {
    vazio.textContent = estado.filtro === 'nao_verificados'
      ? 'Tudo verificado neste pool.'
      : 'Nada aqui. Baixe as listas, verifique alguns domínios ou troque o filtro.';
  }

  $('#titulo-lista').textContent =
    `${NOMES_FILTRO[estado.filtro] || estado.filtro} · ${num(r.total)}`;

  const paginas = Math.max(1, Math.ceil(r.total / POR_PAGINA));
  $('#info-pagina').textContent = `página ${estado.pagina + 1} de ${paginas}`;
  $('#btn-anterior').disabled = estado.pagina === 0;
  $('#btn-proxima').disabled = estado.pagina + 1 >= paginas;

  $('#link-exportar').href = '/api/exportar?' + new URLSearchParams({
    filtro: estado.filtro,
    busca: estado.busca,
    ordem: estado.ordem,
    risco: estado.esconderRisco ? 'esconder' : 'mostrar',
  });

  document.querySelectorAll('.cartao').forEach((c) => {
    c.setAttribute('aria-pressed', String(c.dataset.filtro === estado.filtro));
  });
}

const recarregar = () => Promise.all([carregarResumo(), carregarLista()]);

// ---------------------------------------------------------------- progresso

function pintarProgresso(p) {
  $('#progresso').classList.toggle('escondido', !p.rodando);
  $('#btn-parar').classList.toggle('escondido', !p.rodando);
  for (const id of ['#btn-importar', '#btn-verificar-visiveis',
                    '#btn-verificar-filtro']) {
    const el = $(id);
    if (el) el.disabled = p.rodando;
  }

  if (p.rodando) {
    const indeterminado = !p.total;
    const pct = indeterminado ? 100 : (p.feitos / p.total) * 100;
    const barra = $('#barra-preenche');
    barra.style.width = pct + '%';
    barra.classList.toggle('indeterminado', indeterminado);
    barra.setAttribute('aria-valuenow', String(Math.round(indeterminado ? 0 : pct)));

    $('#progresso-msg').textContent = p.mensagem;
    const detalhes = [];
    if (p.total) detalhes.push(`${num(p.feitos)} de ${num(p.total)}`);
    if (p.atual) detalhes.push(p.atual);
    if (p.segundos_restantes != null) detalhes.push(duracao(p.segundos_restantes));
    if (p.erros) detalhes.push(`${p.erros} erros`);
    if (p.bloqueios) detalhes.push(`${p.bloqueios} bloqueios`);
    $('#progresso-detalhe').textContent = detalhes.join(' · ');
  }

  const nov = $('#novidades');
  if (p.novidades && p.novidades.length) {
    nov.classList.remove('escondido');
    $('#lista-novidades').innerHTML = p.novidades.map((n) =>
      `<li><strong>${esc(n.dominio)}</strong>: ${esc(n.de)} &rarr; ${esc(n.para)}`
      + (n.candidatos ? ` (${esc(n.candidatos)} competindo)` : '') + '</li>').join('');
  } else {
    nov.classList.add('escondido');
  }

  if (estado.rodando && !p.rodando) recarregar();
  estado.rodando = p.rodando;
}

async function acompanhar() {
  try {
    pintarProgresso(await api('/api/progresso'));
  } catch (e) { /* servidor fora do ar; tenta de novo no proximo tick */ }
}

// -------------------------------------------------------------------- acoes

async function verificar(dominios) {
  const r = await postar('/api/verificar', {
    dominios,
    delay: parseFloat($('#delay').value) || 2,
  });
  if (!r.ok) alert(r.mensagem);
  acompanhar();
}

function trocarFiltro(filtro) {
  estado.filtro = filtro;
  estado.pagina = 0;
  carregarLista();
}

function ligarEventos() {
  ligarTema();

  document.querySelectorAll('.cartao').forEach((c) => {
    c.addEventListener('click', () => trocarFiltro(c.dataset.filtro));
  });

  let timer;
  $('#busca').addEventListener('input', (e) => {
    clearTimeout(timer);
    timer = setTimeout(() => {
      estado.busca = e.target.value;
      estado.pagina = 0;
      carregarLista();
    }, 250);
  });

  $('#ordem').addEventListener('change', (e) => {
    estado.ordem = e.target.value;
    estado.pagina = 0;
    carregarLista();
  });

  $('#esconder-risco').addEventListener('change', (e) => {
    estado.esconderRisco = e.target.checked;
    estado.pagina = 0;
    carregarLista();
  });

  $('#btn-anterior').addEventListener('click', () => {
    if (estado.pagina > 0) { estado.pagina--; carregarLista(); window.scrollTo(0, 0); }
  });
  $('#btn-proxima').addEventListener('click', () => {
    estado.pagina++; carregarLista(); window.scrollTo(0, 0);
  });

  $('#corpo-tabela').addEventListener('click', async (e) => {
    const botao = e.target.closest('button');
    if (!botao) return;
    const dominio = botao.closest('tr').dataset.dominio;

    if (botao.dataset.acao === 'marcar') {
      const novo = botao.getAttribute('aria-pressed') !== 'true';
      botao.setAttribute('aria-pressed', String(novo));
      await postar('/api/marcar', { dominio, marcado: novo });
      carregarResumo();
    }

    if (botao.dataset.acao === 'verificar') {
      botao.disabled = true;
      botao.textContent = '...';
      await verificar([dominio]);
    }
  });

  $('#btn-verificar-visiveis').addEventListener('click', () => {
    if (!estado.visiveis.length) return alert('nada na tela para atualizar');
    verificar(estado.visiveis);
  });

  $('#btn-verificar-filtro').addEventListener('click', async () => {
    const r = await postar('/api/verificar', {
      filtro: estado.filtro,
      limite: parseInt($('#limite-verificar').value, 10) || 200,
      delay: parseFloat($('#delay').value) || 2,
    });
    if (!r.ok) alert(r.mensagem);
    acompanhar();
  });

  $('#btn-importar').addEventListener('click', async () => {
    const r = await postar('/api/importar', {});
    if (!r.ok) alert(r.mensagem);
    acompanhar();
  });

  $('#btn-parar').addEventListener('click', () => postar('/api/parar', {}));

  $('#btn-adicionar').addEventListener('click', async () => {
    const texto = $('#novos-dominios').value;
    if (!texto.trim()) return;
    const r = await postar('/api/adicionar', { texto });
    if (!r.ok) return alert(r.mensagem);
    $('#novos-dominios').value = '';
    await recarregar();
    if (confirm(`${r.adicionados} adicionados. Verificar agora?`)) {
      verificar(r.dominios);
    }
  });
}

ligarEventos();
recarregar();
acompanhar();
setInterval(acompanhar, 1000);
