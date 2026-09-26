'use strict';

// Link de cada trecho, em toda pagina de texto (13/09/2026).
//
// O build ja da id a todo titulo e transforma o texto do titulo num link para
// ele mesmo (garimpo/web/paginas.py, ancorar), entao sem JS o endereco do
// trecho ja existe. Aqui entra so o icone discreto ao lado: no celular abre a
// folha de compartilhar do sistema; no computador copia o link e avisa.
//
// Os cartoes da pagina Dados usam o mesmo icone. Antes eram botoes grandes
// "Compartilhar" em cada cartao e grafico: chamavam mais atencao que o numero.

const ICONE_LINK = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M10 14a4.5 4.5 0 0 0 6.4 0l3.2-3.2a4.5 4.5 0 0 0-6.4-6.4L12 5.6"/><path d="M14 10a4.5 4.5 0 0 0-6.4 0l-3.2 3.2a4.5 4.5 0 0 0 6.4 6.4l1.2-1.2"/></svg>';
const ICONE_COMPARTILHAR = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 3v12M7.5 7.5 12 3l4.5 4.5"/><path d="M5 12v7a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2v-7"/></svg>';

// Folha do sistema so onde ela e o gesto natural (toque). No computador o
// navigator.share tambem existe em alguns navegadores, mas abre um dialogo
// pesado para quem so queria o link.
const deToque = window.matchMedia('(pointer: coarse)').matches;

function limpo(texto) {
  return (texto || '').replace(/\s+/g, ' ').trim();
}

function urlDe(ancora) {
  return location.origin + location.pathname + (ancora ? `#${ancora}` : '');
}

function avisar(botao, texto) {
  let aviso = botao.nextElementSibling;
  if (!aviso || !aviso.classList.contains('link-copiado')) {
    aviso = document.createElement('span');
    aviso.className = 'link-copiado';
    aviso.setAttribute('role', 'status');
    botao.after(aviso);
  }
  aviso.textContent = texto;
  clearTimeout(aviso.timer);
  aviso.timer = setTimeout(() => { aviso.textContent = ''; }, 2000);
}

async function compartilhar(botao, { titulo, texto, ancora, copiarTexto }) {
  const url = urlDe(ancora);
  try {
    if (deToque && navigator.share) {
      await navigator.share({ title: titulo, text: texto, url });
      return;
    }
    await navigator.clipboard.writeText(copiarTexto ? `${texto} ${url}` : url);
    avisar(botao, 'Link copiado');
    // o endereco na barra passa a ser o do trecho, como num clique no titulo
    if (ancora) history.replaceState(null, '', `#${ancora}`);
  } catch (e) {
    // fechar a folha de compartilhar cai aqui: nao e erro
  }
}

// Titulos: o icone vai dentro do h2/h3/dt, depois do link do texto.
document.querySelectorAll('.prosa a.ancora').forEach((link) => {
  const titulo = link.parentElement;
  const nome = limpo(link.textContent);
  const botao = document.createElement('button');
  botao.type = 'button';
  botao.className = 'copiar-link';
  botao.innerHTML = deToque ? ICONE_COMPARTILHAR : ICONE_LINK;
  botao.setAttribute('aria-label', `${deToque ? 'Compartilhar' : 'Copiar link de'}: ${nome}`);
  botao.title = deToque ? 'Compartilhar' : 'Copiar link';
  botao.addEventListener('click', () => compartilhar(botao, {
    titulo: `${nome} · ${document.title.split(' · ').pop()}`,
    texto: nome,
    ancora: titulo.id,
  }));
  link.after(botao);
});

// Cartoes da pagina Dados: o texto do numero vai junto do link.
document.querySelectorAll('.compartilhar').forEach((botao) => {
  botao.classList.remove('escondido');
  if (!botao.innerHTML.trim()) botao.innerHTML = ICONE_COMPARTILHAR;
  botao.title = botao.title || 'Compartilhar';
  botao.addEventListener('click', () => {
    const cartao = botao.closest('.cartao');
    const paragrafo = cartao && cartao.querySelector('p');
    compartilhar(botao, {
      titulo: document.title,
      texto: limpo(botao.dataset.texto || (paragrafo ? paragrafo.textContent : document.title)),
      ancora: botao.dataset.ancora || (cartao && cartao.id) || '',
      copiarTexto: true,
    });
  });
});
