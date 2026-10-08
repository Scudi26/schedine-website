/* Scudi as an installed app: network first for everything of this site (a new upload or a new price pull always shows),
   the last copy only when there is no connection. Other sites (ESPN, crests, fonts) are never touched.
   Decision 95: the notifications sent by the private store's scudi-notify function arrive here, even with Scudi closed;
   tapping one opens Scudi on the screen it names (Live for the slips, Matches for the line-ups). */
const CACHE = 'scudi-v3';
self.addEventListener('install', (e) => {
  self.skipWaiting();
  e.waitUntil(caches.open(CACHE).then((c) => c.addAll(['./', 'index.html', 'manifest.webmanifest', 'icons/icon-192.png'])).catch(() => {}));
});
self.addEventListener('activate', (e) => {
  e.waitUntil(caches.keys().then((ks) => Promise.all(ks.filter((k) => k !== CACHE).map((k) => caches.delete(k)))).then(() => self.clients.claim()));
});
self.addEventListener('fetch', (e) => {
  const r = e.request;
  if (r.method !== 'GET' || new URL(r.url).origin !== self.location.origin) return;
  e.respondWith(fetch(r).then((res) => {
    if (res.ok) { const copy = res.clone(); caches.open(CACHE).then((c) => c.put(r, copy)); }
    return res;
  }).catch(() => caches.match(r, { ignoreSearch: true }).then((m) => m || caches.match('index.html'))));
});
/* every message is shown (iPhone stops the deliveries of an app that receives one without showing it) */
self.addEventListener('push', (e) => {
  let d = {};
  try { d = e.data ? e.data.json() : {}; } catch (_) { d = { body: e.data ? e.data.text() : '' }; }
  const scope = self.registration.scope;
  let url = scope;
  try { const u = new URL(d.url || scope, scope); if (u.origin === self.location.origin) url = u.href; } catch (_) { /* only this site's own pages */ }
  e.waitUntil(self.registration.showNotification(String(d.title || 'Scudi').slice(0, 120), {
    body: String(d.body || '').slice(0, 600), tag: d.tag ? String(d.tag).slice(0, 64) : undefined, data: { url },
    icon: new URL('icons/icon-192.png', scope).href, badge: new URL('icons/icon-192.png', scope).href,
  }));
});
self.addEventListener('notificationclick', (e) => {
  e.notification.close();
  const url = (e.notification.data && e.notification.data.url) || self.registration.scope;
  e.waitUntil(self.clients.matchAll({ type: 'window', includeUncontrolled: true }).then((list) => {
    for (const c of list) {
      if (c.url.startsWith(self.registration.scope) && 'focus' in c) {
        return c.focus().then((w) => (w && 'navigate' in w ? w.navigate(url) : w)).catch(() => c);
      }
    }
    return self.clients.openWindow ? self.clients.openWindow(url) : null;
  }));
});
