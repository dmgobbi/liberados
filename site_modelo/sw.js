'use strict';

/*
 * Service worker minimo, so para o aviso de "mudou" dos nomes acompanhados.
 *
 * O Chrome do Android nao aceita `new Notification()` na pagina: aviso so
 * sai por registration.showNotification(), que exige um service worker. Este
 * nao guarda nada em cache nem intercepta requisicao (sem ouvinte de fetch):
 * a pagina continua sempre vindo da rede, com o dados.json mais novo.
 */

self.addEventListener('install', () => self.skipWaiting());
self.addEventListener('activate', (e) => e.waitUntil(self.clients.claim()));

// tocar no aviso traz a aba de volta, ou abre uma se ela foi fechada
self.addEventListener('notificationclick', (e) => {
  e.notification.close();
  e.waitUntil((async () => {
    const abas = await self.clients.matchAll({ type: 'window', includeUncontrolled: true });
    for (const aba of abas) {
      if ('focus' in aba) return aba.focus();
    }
    return self.clients.openWindow('./');
  })());
});
