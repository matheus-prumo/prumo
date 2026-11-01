// Prumo no celular: guarda o app para abrir sem internet (na academia, por exemplo).
// Só guarda os arquivos do próprio app; os dados ficam no celular e no OneDrive.
const CACHE = 'prumo-app-v1';
const ARQS = ['./', 'index.html', 'manifest.webmanifest', 'icon-192.png', 'icon-512.png', 'icon-maskable-512.png'];
self.addEventListener('install', (e) => { e.waitUntil(caches.open(CACHE).then((c) => c.addAll(ARQS)).then(() => self.skipWaiting())); });
self.addEventListener('activate', (e) => { e.waitUntil(caches.keys().then((ks) => Promise.all(ks.filter((k) => k !== CACHE).map((k) => caches.delete(k)))).then(() => self.clients.claim())); });
self.addEventListener('fetch', (e) => {
  const u = new URL(e.request.url);
  if (e.request.method !== 'GET' || u.origin !== location.origin) return; // Microsoft e OneDrive passam direto
  const pagina = e.request.mode === 'navigate';
  if (pagina) {
    // o app: tenta a versão nova (até 4 s); sem internet, abre a guardada
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
