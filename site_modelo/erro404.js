'use strict';

// O campo desta pagina manda para a ficha de /quando-volta/ (18/09/2026).
//
// A CSP do site tem form-action 'none' (site_modelo/_headers): um <form>
// nunca submete de verdade, ou o navegador bloqueia em silencio (testado
// com a mesma CSP, o clique nao navega e so aparece um erro no console).
// Por isso o form aqui nao tem method/action, igual ao ficha-form de
// /quando-volta/ (ficha.js): o clique sempre vira navegacao por script.
const forma = document.getElementById('ficha-404-form');
const campo = document.getElementById('ficha-404-nome');

if (forma && campo) {
  forma.addEventListener('submit', (e) => {
    e.preventDefault();
    const nome = campo.value.trim();
    if (nome) location.href = '/quando-volta/?d=' + encodeURIComponent(nome);
  });
}
