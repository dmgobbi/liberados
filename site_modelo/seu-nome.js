/*
 * "Seu nome .com.br está livre?" (/seu-nome/), 19/09/2026.
 *
 * A pessoa digita nome e sobrenome; daqui saem no maximo tres .com.br
 * (nomesobrenome, sobrenome e nome, sem acento nem espaco) e cada um e
 * conferido pela MESMA funcao da ficha de /quando-volta/ (Ficha.conferir, em
 * ficha.js): RDAP do Registro.br consultado do navegador de quem olha, o
 * indice das listas guardadas e o do Internet Archive. Um cartao por nome.
 *
 * Ritmo: uma consulta por vez, PAUSA entre elas (a mesma da ficha, 2,5 s),
 * e para tudo se o Registro.br pedir para esperar (Disputa.bloqueado).
 *
 * Nada e guardado: nem localStorage, nem servidor. O nome digitado fica so
 * no endereco (?n=), para a pessoa refazer a consulta ou guardar o link.
 * Compartilhar manda a situacao do dominio e o link de /seu-nome/, para o
 * amigo testar o dele; nunca o nome do titular.
 */
(function () {
  'use strict';

  const MAXIMO = 3;
  const PAUSA = 2500;
  // "Maria da Silva": o sobrenome e o ultimo nome que nao e particula
  const PARTICULAS = new Set(['da', 'das', 'de', 'di', 'do', 'dos', 'du', 'e', 'y']);
  // "Joao Silva Filho": o sufixo no fim nao e o sobrenome; com dois nomes so
  // ("Carlos Neto") ele continua valendo como sobrenome
  const SUFIXOS = new Set(['filho', 'filha', 'junior', 'jr', 'neto', 'neta', 'sobrinho', 'sobrinha', 'segundo']);

  const esperar = (ms) => new Promise((r) => setTimeout(r, ms));
  const esc = (v) => String(v ?? '').replace(/[&<>"']/g, (c) => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));

  /**
   * Os .com.br a conferir, do mais pessoal ao mais disputado. Pura, sem DOM:
   * o teste roda no node. Rotulo de 2 a 26 caracteres, nao so numeros
   * (a regra do .br, a mesma de foraDaRegra em ficha.js).
   */
  function candidatos(texto) {
    const limpo = String(texto || '').normalize('NFD').replace(/[\u0300-\u036f]/g, '')
      .toLowerCase().trim().replace(/^[a-z]+:\/\//, '').replace(/^www\./, '')
      .replace(/\.(com\.)?br\b.*$/, '');
    let partes = limpo.split(/[^a-z0-9]+/).filter(Boolean);
    if (partes.length > 1) partes = partes.filter((p, i) => i === 0 || !PARTICULAS.has(p));
    if (partes.length >= 3 && SUFIXOS.has(partes[partes.length - 1])) partes = partes.slice(0, -1);
    if (!partes.length) return [];
    const nome = partes[0];
    const sobrenome = partes[partes.length - 1];
    const rotulos = partes.length > 1 ? [nome + sobrenome, sobrenome, nome] : [nome];
    const valido = (r) => r.length >= 2 && r.length <= 26 && !/^[0-9]+$/.test(r);
    return [...new Set(rotulos)].filter(valido).slice(0, MAXIMO).map((r) => `${r}.com.br`);
  }

  /**
   * Confere os nomes um por vez, com PAUSA entre um e outro. `conferir`
   * recebe (nome, indice); `vigente` diz se a pessoa nao pediu outra busca no
   * meio; `aoErro` devolve false para parar (bloqueio do Registro.br).
   */
  async function conferirTodos(nomes, { conferir, vigente = () => true, aoErro = () => true }) {
    for (let i = 0; i < nomes.length; i += 1) {
      if (i > 0) await esperar(PAUSA);
      if (!vigente()) return;
      try {
        await conferir(nomes[i], i);
      } catch (e) {
        if (aoErro(e, i) === false) return;
      }
    }
  }

  window.SeuNome = { candidatos, conferirTodos, MAXIMO, PAUSA };

  // ------------------------------------------------------------ pagina

  const $ = (s) => document.querySelector(s);
  const form = $('#seu-nome-form');
  if (!form) return;
  const campo = $('#seu-nome-campo');
  const saida = $('#seu-nome-resultados');
  const aviso = $('#seu-nome-aviso');
  const deToque = window.matchMedia && window.matchMedia('(pointer: coarse)').matches;
  let rodada = 0;                      // cada busca nova invalida a anterior
  let emCurso = Promise.resolve();     // e so comeca depois que a consulta no ar volta

  function avisar(botao, texto) {
    let nota = botao.nextElementSibling;
    if (!nota || !nota.classList.contains('link-copiado')) {
      nota = document.createElement('span');
      nota.className = 'link-copiado';
      nota.setAttribute('role', 'status');
      botao.after(nota);
    }
    nota.textContent = texto;
    clearTimeout(nota.timer);
    nota.timer = setTimeout(() => { nota.textContent = ''; }, 2500);
  }

  async function compartilhar(botao, texto) {
    const url = `${location.origin}/seu-nome/`;
    try {
      if (deToque && navigator.share) {
        await navigator.share({ title: 'Seu nome .com.br está livre?', text: texto, url });
        return;
      }
      await navigator.clipboard.writeText(`${texto} ${url}`);
      avisar(botao, 'Texto e link copiados');
    } catch (e) {
      // fechar a folha de compartilhar cai aqui: nao e erro
    }
  }

  /*
   * O botao de cada cartao. Se a ficha ja trouxer o dela
   * ([data-compartilhar], r3-ficha-compartilhar), este nao entra. O texto e
   * o titulo do cartao, que nunca leva o titular, e a pergunta para o amigo.
   */
  function botaoDoCartao(alvo) {
    const cartao = alvo.querySelector('.ficha-cartao');
    const titulo = alvo.querySelector('.ficha-titulo');
    if (!cartao || !titulo || cartao.querySelector('[data-compartilhar]')) return;
    let acoes = cartao.querySelector('.ficha-acoes');
    if (!acoes) {
      acoes = document.createElement('div');
      acoes.className = 'ficha-acoes';
      titulo.parentNode.insertBefore(acoes, cartao.querySelector('.ficha-passagens'));
    }
    const botao = document.createElement('button');
    botao.type = 'button';
    botao.textContent = 'Compartilhar';
    const situacao = titulo.textContent.replace(/\s+/g, ' ').trim();
    botao.addEventListener('click', () => compartilhar(botao,
      `${situacao}. E o seu nome .com.br, está livre?`));
    acoes.append(botao);
  }

  async function buscar(texto) {
    const nomes = candidatos(texto);
    const minha = ++rodada;
    saida.innerHTML = '';
    if (!nomes.length) {
      aviso.textContent = texto.trim() ? 'Digite um nome com pelo menos duas letras.' : '';
      return;
    }
    history.replaceState(null, '', `?${new URLSearchParams({ n: texto.trim() })}`);
    if (!window.Ficha || !window.Ficha.conferir) {
      aviso.textContent = 'A página não carregou inteira; recarregue.';
      return;
    }
    aviso.textContent = nomes.length > 1
      ? `Conferindo ${nomes.length} nomes, um por vez, direto no Registro.br.`
      : 'Conferindo direto no Registro.br.';
    const alvos = nomes.map((nome) => {
      const alvo = document.createElement('div');
      alvo.className = 'ficha-resultado';
      alvo.setAttribute('aria-live', 'polite');
      alvo.innerHTML = `<p class="ficha-carregando">Na fila: <code>${esc(nome)}</code></p>`;
      saida.append(alvo);
      return alvo;
    });
    const anterior = emCurso;
    emCurso = anterior.then(() => conferirTodos(nomes, {
      conferir: async (nome, i) => {
        await window.Ficha.conferir(nome, nome, alvos[i]);
        if (minha === rodada) botaoDoCartao(alvos[i]);
      },
      vigente: () => minha === rodada,
      aoErro: (e, i) => {
        const bloqueado = Boolean(window.Disputa && window.Disputa.bloqueado && window.Disputa.bloqueado());
        alvos[i].innerHTML = `<p class="ficha-erro">${bloqueado ? esc(e.message)
          : `Não deu para consultar <code>${esc(nomes[i])}</code> agora: ${esc(e.message)}.`}</p>`;
        if (bloqueado) {
          for (const resto of alvos.slice(i + 1)) resto.remove();
          return false;
        }
        return true;
      },
    }));
    await emCurso;
    if (minha === rodada) aviso.textContent = '';
  }

  // form-action 'none' na CSP: o envio e sempre por aqui, nunca navegacao
  form.addEventListener('submit', (e) => {
    e.preventDefault();
    buscar(campo.value);
  });
  const pedido = new URLSearchParams(location.search).get('n');
  if (pedido) {
    campo.value = pedido;
    buscar(pedido);
  }
})();
