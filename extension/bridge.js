/* Scudi · SNAI — the bridge on the Scudi site (decision 91). It marks the page as having the extension, passes the
   readings the extension sends into the page (window.postMessage, to the page's own address only) and passes the
   page's answer (how many rows it matched) back. When the page says it is ready, it asks for what the SNAI tabs read
   recently, so a Scudi tab opened or reloaded later gets the prices at once. */
(function () {
  'use strict';
  var ORIGIN = location.origin;
  try { document.documentElement.setAttribute('data-scudi-ext', chrome.runtime.getManifest().version); } catch (e) { return; }
  function toPage(msg) { if (msg && typeof msg === 'object') window.postMessage(msg, ORIGIN); }
  chrome.runtime.onMessage.addListener(function (m) { if (m && m.kind === 'push') toPage(m.msg); });
  function hello() {
    try { chrome.runtime.sendMessage({ kind: 'hello' }, function (res) { if (chrome.runtime.lastError) return; if (res && res.msg) toPage(res.msg); }); } catch (e) {}
  }
  window.addEventListener('message', function (e) {
    if (e.source !== window || e.origin !== ORIGIN) return;
    var d = e.data; if (!d || typeof d !== 'object' || d.via !== 'scudi-page') return;
    if (d.type === 'scudi-ext-ready') hello();
    else if (d.type === 'scudi-ack') { try { chrome.runtime.sendMessage({ kind: 'ack', hit: +d.hit || 0, rows: +d.rows || 0 }, function () { void chrome.runtime.lastError; }); } catch (x) {} }
  });
})();
