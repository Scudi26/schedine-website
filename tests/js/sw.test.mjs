/* The service worker's notifications (decision 95), run with `node tests/js/sw.test.mjs`: sw.js loaded in a stand-in
   for the browser's worker, a push shown as a notification (never a page outside the site), a tap opening Scudi. */
import fs from 'fs';
import vm from 'vm';
import path from 'path';
import { fileURLToPath } from 'url';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..', '..');
let failures = 0, checks = 0;
function ok(cond, msg) { checks++; if (!cond) { failures++; console.error('FAIL: ' + msg); } }

function worker(windows) {
  const on = {}, shown = [], opened = [], nav = [];
  const scope = 'https://scudi26.github.io/schedine-website/';
  const self = {
    location: new URL(scope + 'sw.js'), addEventListener: (t, f) => { on[t] = f; }, skipWaiting() {},
    registration: { scope, showNotification: (title, o) => { shown.push({ title, ...o }); return Promise.resolve(); } },
    clients: {
      claim: () => Promise.resolve(),
      matchAll: () => Promise.resolve(windows || []),
      openWindow: (u) => { opened.push(u); return Promise.resolve({}); },
    },
  };
  windows && windows.forEach((w) => { w.focus = () => Promise.resolve(w); w.navigate = (u) => { nav.push(u); return Promise.resolve(w); }; });
  vm.runInNewContext(fs.readFileSync(path.join(root, 'sw.js'), 'utf8'), { self, caches: {}, fetch: () => Promise.reject(new Error('offline')), URL, console });
  const fire = async (t, ev) => { let p = null; ev.waitUntil = (x) => { p = x; }; on[t](ev); await p; };
  return { on, shown, opened, nav, fire, scope };
}
const data = (obj) => ({ json: () => (typeof obj === 'string' ? JSON.parse(obj) : obj), text: () => (typeof obj === 'string' ? obj : JSON.stringify(obj)) });

let w = worker();
ok(typeof w.on.push === 'function' && typeof w.on.notificationclick === 'function', 'push and notificationclick handled');
await w.fire('push', { data: data({ title: "Goal 67' · Inter 1–0 Juventus", body: '1X winning', url: w.scope + '#live', tag: 'goal:401:1-0' }) });
ok(w.shown.length === 1 && w.shown[0].title === "Goal 67' · Inter 1–0 Juventus" && w.shown[0].body === '1X winning' && w.shown[0].tag === 'goal:401:1-0', 'a push shown as it came');
ok(w.shown[0].data.url === w.scope + '#live' && /icons\/icon-192\.png$/.test(w.shown[0].icon), 'with the site\'s link and icon');
await w.fire('push', { data: data({ title: 'x', url: 'https://evil.example/phish' }) });
ok(w.shown[1].data.url === w.scope, 'a link outside the site is never opened: Scudi instead');
await w.fire('push', { data: { json: () => { throw new Error('not json'); }, text: () => 'plain words' } });
ok(w.shown[2].title === 'Scudi' && w.shown[2].body === 'plain words', 'a plain-text push still shows');
await w.fire('push', { data: null });
ok(w.shown[3].title === 'Scudi', 'an empty push shows Scudi (iPhone wants every push shown)');

/* a tap: an open Scudi is focused and moved to the screen; otherwise Scudi opens */
let closed = 0;
w = worker([{ url: 'https://scudi26.github.io/schedine-website/#slips' }]);
await w.fire('notificationclick', { notification: { data: { url: w.scope + '#live' }, close: () => { closed++; } } });
ok(closed === 1 && w.nav[0] === w.scope + '#live' && !w.opened.length, 'an open Scudi is brought forward on the Live screen');
w = worker([{ url: 'https://other.example/' }]);
await w.fire('notificationclick', { notification: { data: { url: w.scope + '#matches' }, close() {} } });
ok(w.opened[0] === w.scope + '#matches', 'otherwise Scudi opens there');

console.log(`${checks - failures}/${checks} service worker checks passed`);
if (failures) process.exit(1);
