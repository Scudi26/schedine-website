/* Scudi · SNAI — runs by itself on every snai.it page (decision 91). It reads the SNAI list on screen with the same reading
   as the bookmark (reader.js), again every 5 seconds and whenever the page changes, and hands it to the extension, which
   passes it to every Scudi tab that is open. Only what changed is sent, plus a short "still here" every 30 seconds.
   It never clicks, types, fetches or reloads anything on SNAI. A small card at the bottom left says what it is doing,
   only on pages that show prices; its × stops it on this tab until the page is loaded again. */
/* global scudiReadSnai */
(function () {
  'use strict';
  if (window.__scudiExtSnai) return;
  window.__scudiExtSnai = true;
  var D = document, IT = /^it\b/i.test(navigator.language || '');
  var L = IT
    ? { read: 'partite lette', hit: 'abbinate da Scudi', wait: 'in attesa di Scudi…', closed: 'Scudi non è aperto', open: 'Apri Scudi', live: 'collegato', ago: 'inviate', now: 'ora', s: 's fa', stop: 'Ferma su questa scheda', gone: 'estensione aggiornata: ricarica la pagina' }
    : { read: 'matches read', hit: 'matched by Scudi', wait: 'waiting for Scudi…', closed: 'Scudi is not open', open: 'Open Scudi', live: 'connected', ago: 'sent', now: 'now', s: 's ago', stop: 'Stop on this tab', gone: 'extension updated: reload the page' };
  var R = { alive: true, last: '', n: 0, sentAt: 0, scudi: null, ack: null, t: 0, deb: 0, mo: null, gone: false };

  function ask(msg, then) {
    try {
      chrome.runtime.sendMessage(msg, function (res) {
        if (chrome.runtime.lastError) { if (/context invalidated/i.test(chrome.runtime.lastError.message || '')) dead(); return; }
        if (then) then(res || {});
      });
    } catch (e) { dead(); }   /* the extension was updated or removed: this copy can no longer talk to it */
  }
  function dead() { R.gone = true; stop(true); }
  function send(force) {
    if (!R.alive) return;
    var rows = scudiReadSnai(D), key = JSON.stringify(rows), now = Date.now();
    R.n = rows.length;
    var got = function (res) { R.sentAt = Date.now(); R.scudi = res.scudi == null ? null : +res.scudi; R.ack = res.ack || null; draw(); };
    if (!force && key === R.last) {
      if (rows.length && now - R.sentAt > 30000) ask({ kind: 'ping' }, got);
    } else {
      R.last = key;
      ask({ kind: 'reading', rows: rows, page: location.pathname }, got);
    }
    draw();
  }

  /* the card */
  var host = D.createElement('div');
  host.style.cssText = 'all:initial;position:fixed;left:16px;bottom:16px;z-index:2147483647;display:none';
  var root = host.attachShadow ? host.attachShadow({ mode: 'open' }) : host;
  root.innerHTML = '<style>.b{box-sizing:border-box;max-width:min(460px,calc(100vw - 32px));font:600 13px/1.35 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif;color:#F4F1E8;background:linear-gradient(180deg,#191F42,#10152E);border:1px solid rgba(150,160,230,.26);border-radius:18px;padding:10px 10px 10px 12px;display:flex;align-items:center;gap:10px;box-shadow:0 18px 40px -16px rgba(0,0,0,.8);transition:border-color .4s}' +
    '.b.fl{border-color:#E9B949}.d{width:9px;height:9px;border-radius:50%;background:#E9B949;flex:none}.d.on{background:#3DDC97;animation:p 1.8s infinite}.d.off{background:#6F75A1}' +
    '@keyframes p{0%{box-shadow:0 0 0 0 rgba(61,220,151,.6)}70%{box-shadow:0 0 0 8px rgba(61,220,151,0)}100%{box-shadow:0 0 0 0 rgba(61,220,151,0)}}' +
    '.m{width:22px;height:22px;flex:none}.t{display:flex;flex-direction:column;min-width:0;flex:1}.t small{font-weight:500;color:#A6ACCE;font-size:12px}.k{background:linear-gradient(135deg,#FBE7A6,#E9B949 45%,#C9952B);-webkit-background-clip:text;background-clip:text;color:transparent}' +
    'button{font:inherit;cursor:pointer;border-radius:11px;border:1px solid rgba(150,160,230,.26);background:#191F42;color:#F4F1E8;padding:6px 10px;flex:none}button:hover{border-color:#E9B949}.x{padding:6px 9px}' +
    '@media (prefers-reduced-motion:reduce){.d.on{animation:none}}</style>' +
    '<div class="b"><svg class="m" viewBox="0 0 48 48" aria-hidden="true"><defs><linearGradient id="g" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#FBE7A6"/><stop offset=".45" stop-color="#E9B949"/><stop offset="1" stop-color="#B8861F"/></linearGradient></defs><path d="M24 4 41 9.5V22c0 11.5-7.4 19.6-17 22.5C14.4 41.6 7 33.5 7 22V9.5Z" fill="url(#g)"/><path d="M24 8.2 37.4 12.6V22c0 9.6-5.8 16.2-13.4 18.8C16.4 38.2 10.6 31.6 10.6 22v-9.4Z" fill="#10152E"/><circle cx="24" cy="23.6" r="7.4" fill="url(#g)"/><circle cx="24" cy="23.6" r="4.7" fill="none" stroke="#141A38" stroke-width="1.7"/></svg>' +
    '<i class="d"></i><span class="t"><span><span class="k">Scudi</span> · <span class="s"></span></span><small class="n"></small></span><button class="o"></button><button class="x">×</button></div>';
  var box = root.querySelector('.b'), dot = root.querySelector('.d'), st = root.querySelector('.s'), nn = root.querySelector('.n'), ob = root.querySelector('.o'), xb = root.querySelector('.x');
  ob.textContent = L.open; xb.title = L.stop; xb.setAttribute('aria-label', L.stop);
  function draw() {
    if (!R.alive && !R.gone) return;
    host.style.display = R.n || R.gone ? '' : 'none';
    var open = R.scudi > 0, fresh = open && R.ack && Date.now() - R.ack.at < 70000, ago = R.sentAt ? Math.round((Date.now() - R.sentAt) / 1000) : null;
    dot.className = 'd' + (fresh ? ' on' : open ? '' : ' off');
    st.textContent = R.gone ? L.gone : fresh ? L.live : open ? L.wait : L.closed;
    nn.textContent = R.gone ? '' : R.n + ' ' + L.read + (fresh && R.ack.hit != null ? ' · ' + R.ack.hit + ' ' + L.hit : '') + (ago != null ? ' · ' + L.ago + ' ' + (ago < 3 ? L.now : ago + L.s) : '');
    ob.style.display = R.gone || fresh ? 'none' : '';
  }
  function flash() { box.classList.add('fl'); setTimeout(function () { box.classList.remove('fl'); }, 600); }
  function stop(keepCard) {
    R.alive = false; clearInterval(R.t); clearTimeout(R.deb);
    if (R.mo) R.mo.disconnect();
    if (keepCard) { draw(); return; }
    if (host.parentNode) host.parentNode.removeChild(host);
  }
  ob.onclick = function () { ask({ kind: 'open' }); flash(); setTimeout(function () { R.last = ''; send(true); }, 1500); };
  xb.onclick = function () { if (R.gone) { if (host.parentNode) host.parentNode.removeChild(host); return; } ask({ kind: 'stopped' }); stop(false); };

  try { chrome.runtime.onMessage.addListener(function (m) { if (R.alive && m && m.kind === 'ack' && m.ack) { R.ack = m.ack; R.scudi = Math.max(R.scudi || 0, 1); draw(); } }); } catch (e) {}
  (D.body || D.documentElement).appendChild(host);
  R.t = setInterval(function () { send(false); }, 5000);
  if (window.MutationObserver) {
    R.mo = new MutationObserver(function (list) {
      for (var i = 0; i < list.length; i++) if (list[i].target !== host) { clearTimeout(R.deb); R.deb = setTimeout(function () { send(false); }, 700); return; }
    });
    R.mo.observe(D.body || D.documentElement, { subtree: true, childList: true, characterData: true, attributes: true, attributeFilter: ['disabled', 'data-qa'] });
  }
  send(true);
})();
