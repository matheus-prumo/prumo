// Prumo no celular: guarda o app para abrir sem internet, recebe o que é compartilhado e avisa das contas.
// Só guarda os arquivos do próprio app; os dados ficam no celular e no OneDrive.
const CACHE = 'prumo-app-v2';
const ARQS = ['./', 'index.html', 'manifest.webmanifest', 'icon-192.png', 'icon-512.png', 'icon-maskable-512.png'];
self.addEventListener('install', (e) => { e.waitUntil(caches.open(CACHE).then((c) => c.addAll(ARQS)).then(() => self.skipWaiting())); });
self.addEventListener('activate', (e) => { e.waitUntil(caches.keys().then((ks) => Promise.all(ks.filter((k) => k.startsWith('prumo-app-') && k !== CACHE).map((k) => caches.delete(k)))).then(() => self.clients.claim())); });
self.addEventListener('fetch', (e) => {
  const u = new URL(e.request.url);
  // "Compartilhar com o Prumo": guarda o texto e a foto e abre o app
  if (e.request.method === 'POST' && u.origin === location.origin && u.searchParams.has('compartilhar')) {
    e.respondWith((async () => {
      try {
        const f = await e.request.formData(); const c = await caches.open('prumo-compartilhado');
        const txt = [f.get('title'), f.get('text'), f.get('url')].filter(Boolean).join('\n');
        await c.put('texto', new Response(txt));
        const foto = f.getAll('arquivos').find((x) => x && x.size);
        if (foto) await c.put('foto', new Response(foto, { headers: { 'Content-Type': foto.type || 'image/jpeg' } }));
      } catch (err) { /* abre o app mesmo assim */ }
      return Response.redirect('./?acao=compartilhado', 303);
    })());
    return;
  }
  if (e.request.method !== 'GET' || u.origin !== location.origin) return; // Microsoft e OneDrive passam direto
  if (e.request.mode === 'navigate') {
    e.respondWith((async () => {
      const c = await caches.open(CACHE);
      try {
        const r = await Promise.race([fetch(e.request, { cache: 'no-store' }), new Promise((_, rej) => setTimeout(() => rej(new Error('lento')), 4000))]);
        if (r.ok) c.put('index.html', r.clone());
        return r;
      } catch (err) { return (await c.match('index.html')) || (await c.match('./')) || Response.error(); }
    })());
    return;
  }
  e.respondWith(caches.match(e.request, { ignoreSearch: true }).then((r) => r || fetch(e.request)));
});
// lembretes de contas: o Android acorda o app de vez em quando
self.addEventListener('periodicsync', (e) => { if (e.tag === 'prumo-lembretes') e.waitUntil(avisarContas()); });
async function avisarContas() {
  const c = await caches.open('prumo-lembretes'); const r = await c.match('agenda'); if (!r) return;
  const { itens = [] } = await r.json(); const hoje = new Date(); const iso = (d) => new Date(d.getTime() - d.getTimezoneOffset() * 60000).toISOString().slice(0, 10);
  const H = iso(hoje); const A = iso(new Date(hoje.getTime() + 86400000));
  const vistos = await (await c.match('vistos'))?.json().catch(() => ({})) || {};
  for (const x of itens) {
    const quando = x.d < H ? 'está atrasada' : x.d === H ? 'vence hoje' : x.d === A ? 'vence amanhã' : ''; if (!quando) continue;
    const k = x.id + '|' + H; if (vistos[k]) continue; vistos[k] = 1;
    await self.registration.showNotification('Prumo · conta ' + quando, { body: x.t, tag: 'prumo-' + x.id, icon: 'icon-192.png', badge: 'icon-192.png', data: { url: './' } });
  }
  await c.put('vistos', new Response(JSON.stringify(vistos)));
}
self.addEventListener('notificationclick', (e) => {
  e.notification.close();
  e.waitUntil(self.clients.matchAll({ type: 'window' }).then((cs) => (cs[0] ? cs[0].focus() : self.clients.openWindow('./'))));
});
