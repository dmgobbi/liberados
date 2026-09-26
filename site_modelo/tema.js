'use strict';

/*
 * O botao de tema, em toda pagina do site.
 *
 * Tres estados em ciclo: sistema -> claro -> escuro -> sistema. "sistema" e
 * a ausencia do atributo, entao a media query volta a mandar. Guardar so
 * "claro" ou "escuro" no storage significa que voltar para o sistema apaga
 * a escolha, que e exatamente o comportamento esperado.
 *
 * Mora num arquivo proprio porque as paginas de texto nao carregam o
 * app.js (ele busca dados.json e espera a tabela), e o inline do <head> so
 * aplica o tema guardado, nao troca.
 */
(function () {
  const CICLO = ['sistema', 'claro', 'escuro'];
  const ROTULOS = {
    sistema: ['seguindo o sistema', 'usar o tema claro'],
    claro: ['tema claro', 'usar o tema escuro'],
    escuro: ['tema escuro', 'seguir o sistema'],
  };

  function atual() {
    return document.documentElement.getAttribute('data-tema') || 'sistema';
  }

  function aplicar(tema) {
    const raiz = document.documentElement;
    if (tema === 'sistema') raiz.removeAttribute('data-tema');
    else raiz.setAttribute('data-tema', tema);
    try {
      if (tema === 'sistema') localStorage.removeItem('tema');
      else localStorage.setItem('tema', tema);
    } catch (e) { /* navegacao anonima: vale so para esta aba */ }

    const botao = document.querySelector('#btn-tema');
    if (botao) {
      const [estado, proximo] = ROTULOS[tema];
      botao.setAttribute('aria-label', `Tema: ${estado}. Clique para ${proximo}.`);
      botao.title = `Tema: ${estado}`;
    }
  }

  // Rola a aba ativa para dentro da vista: a faixa e mais larga que a
  // tela em 5 das 8 secoes, e como cada pagina ja carrega com uma aba
  // diferente marcada (as abas viraram links em 11/09/2026), sem isto a
  // aba aberta ficava escondida atras da borda direita cortada.
  const faixa = document.querySelector('.abas');
  const ativa = faixa && faixa.querySelector('[aria-current="page"]');
  if (ativa && faixa.scrollWidth > faixa.clientWidth) {
    const f = faixa.getBoundingClientRect();
    const a = ativa.getBoundingClientRect();
    faixa.scrollLeft += (a.left - f.left) - (f.width - a.width) / 2;
  }

  // A seta na borda direita da faixa, enquanto houver aba escondida. A
  // mascara que esfuma a borda estava no ar e as tres personas de
  // 19/09/2026 nao a notaram: ninguem descobriu que as abas continuavam
  // para o lado. A seta fica fora da faixa (irma dela no <header>, posta
  // por cima pelo extra.css) porque a mascara esfumaria tambem o que
  // estivesse dentro, e porque um filho a mais tiraria da ultima aba o
  // :last-child do scroll-snap. So aparece no celular (o CSS a esconde a
  // partir de 64rem). Fica fora da ordem do Tab: quem navega pelo teclado
  // ja rola a faixa ao focar cada aba.
  if (faixa) {
    const seta = document.createElement('button');
    seta.type = 'button';
    seta.className = 'abas-seta escondido';
    seta.tabIndex = -1;
    seta.setAttribute('aria-hidden', 'true');
    seta.textContent = '\u203A';
    faixa.insertAdjacentElement('afterend', seta);

    // - 1: scrollLeft pode ser fracionario e deixar a seta acesa no fim
    // da faixa por meio pixel.
    const conferirSeta = () => {
      const falta = faixa.scrollLeft + faixa.clientWidth < faixa.scrollWidth - 1;
      seta.classList.toggle('escondido', !falta);
    };
    seta.addEventListener('click', () => {
      const suave = !window.matchMedia('(prefers-reduced-motion: reduce)').matches;
      faixa.scrollBy({ left: faixa.clientWidth * 0.6, behavior: suave ? 'smooth' : 'auto' });
    });
    faixa.addEventListener('scroll', conferirSeta, { passive: true });
    window.addEventListener('resize', conferirSeta);
    // a largura das abas so e a final depois da fonte: sem isto a seta
    // podia ficar acesa (ou apagada) pela medida de antes da fonte
    window.addEventListener('load', conferirSeta);
    if (document.fonts && document.fonts.ready) document.fonts.ready.then(conferirSeta);
    conferirSeta();
  }

  // Publica a altura real do cabecalho fixo para o scroll-padding-top de
  // extra.css reservar o espaco certo: ela muda com a pagina e a largura
  // (65, 113 ou 149px), entao um valor fixo erraria em algum tamanho.
  const cabecalho = document.querySelector('header');
  if (cabecalho && 'ResizeObserver' in window) {
    new ResizeObserver(() => {
      document.documentElement.style.setProperty('--altura-cabecalho', cabecalho.offsetHeight + 'px');
    }).observe(cabecalho);
  }

  const botao = document.querySelector('#btn-tema');
  if (!botao) return;
  botao.addEventListener('click', () => {
    const i = CICLO.indexOf(atual());
    aplicar(CICLO[(i + 1) % CICLO.length]);
  });
  aplicar(atual());
})();
