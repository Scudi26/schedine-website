/* Scudi · SNAI — the extension's centre (decision 91). Every snai.it tab sends its reading here; the readings of all tabs
   still alive are merged (one row per SNAI event, the one with most prices) and passed to every open Scudi tab through
   its bridge. Scudi answers how many rows it matched; the SNAI tabs show it on their card. The extension's own icon
   opens Scudi, or brings its tab to the front. Nothing here touches SNAI: it only moves what the tabs read.
   The service worker can be put to sleep at any time, so the state lives in chrome.storage.session. */
'use strict';
var SCUDI = 'https://scudi26.github.io/schedine-website/';
var FRESH = 75000;   /* a tab silent for longer than this no longer counts (its last "still here" was 30 s ago at most) */

var chain = Promise.resolve();
function serial(fn) { var p = chain.then(fn, fn); chain = p.catch(function () {}); return p; }
function load() { return chrome.storage.session.get(['tabs', 'ack']).then(function (s) { return { tabs: s.tabs || {}, ack: s.ack || null }; }); }
function merged(tabs) {
  var now = Date.now(), byId = {}, out = [];
  Object.keys(tabs).forEach(function (k) {
    var t = tabs[k]; if (!t || now - t.at > FRESH) return;
    (t.rows || []).forEach(function (r) { var o = byId[r.id]; if (!o || r.m.length > o.m.length) byId[r.id] = r; });
  });
  Object.keys(byId).forEach(function (k) { out.push(byId[k]); });
  return out;
}
function scudiTabs() { return chrome.tabs.query({ url: SCUDI + '*' }).catch(function () { return []; }); }
function push(msg) {
  return scudiTabs().then(function (tabs) {
    tabs.forEach(function (t) { chrome.tabs.sendMessage(t.id, { kind: 'push', msg: msg }).catch(function () {}); });
    return tabs.length;
  });
}
function liveCount(tabs) { var now = Date.now(); return Object.keys(tabs).filter(function (k) { return tabs[k] && now - tabs[k].at <= FRESH && (tabs[k].rows || []).length; }).length; }
function reading(st, page) {
  return { type: 'scudi-snai', v: 1, via: 'scudi-ext', at: Date.now(), page: page || '', tabs: liveCount(st.tabs), rows: merged(st.tabs) };
}
function openScudi() {
  return scudiTabs().then(function (tabs) {
    if (tabs.length) return chrome.tabs.update(tabs[0].id, { active: true }).then(function () { return chrome.windows.update(tabs[0].windowId, { focused: true }); });
    return chrome.tabs.create({ url: SCUDI + '#today' });
  }).catch(function () {});
}

function handle(m, sender) {
  return load().then(function (st) {
    var tab = sender && sender.tab ? String(sender.tab.id) : null;
    if (m.kind === 'reading' && tab && Array.isArray(m.rows)) {
      st.tabs[tab] = { rows: m.rows.slice(0, 800), at: Date.now(), page: String(m.page || '').slice(0, 200) };
      return chrome.storage.session.set({ tabs: st.tabs }).then(function () { return push(reading(st, m.page)); })
        .then(function (n) { return { scudi: n, ack: st.ack }; });
    }
    if (m.kind === 'ping' && tab) {
      if (st.tabs[tab]) st.tabs[tab].at = Date.now();
      return chrome.storage.session.set({ tabs: st.tabs }).then(function () { return push({ type: 'scudi-snai-ping', v: 1, via: 'scudi-ext', at: Date.now(), tabs: liveCount(st.tabs) }); })
        .then(function (n) { return { scudi: n, ack: st.ack }; });
    }
    if (m.kind === 'stopped' && tab) { delete st.tabs[tab]; return chrome.storage.session.set({ tabs: st.tabs }).then(function () { return {}; }); }
    if (m.kind === 'hello') {   /* a Scudi tab is ready: what the SNAI tabs read recently, at once */
      var r = reading(st, '');
      return r.rows.length ? { msg: r } : {};
    }
    if (m.kind === 'ack') {   /* Scudi's answer: kept for the next reading's reply, and shown on every SNAI card at once */
      var ack = { hit: +m.hit || 0, rows: +m.rows || 0, at: Date.now() };
      return chrome.storage.session.set({ ack: ack }).then(function () {
        Object.keys(st.tabs).forEach(function (k) { chrome.tabs.sendMessage(+k, { kind: 'ack', ack: ack }).catch(function () {}); });
        return {};
      });
    }
    if (m.kind === 'open') return openScudi().then(function () { return {}; });
    return {};
  });
}
chrome.runtime.onMessage.addListener(function (m, sender, reply) {
  if (!m || typeof m !== 'object') return false;
  serial(function () { return handle(m, sender); }).then(reply, function () { reply({}); });
  return true;   /* the reply comes asynchronously */
});
chrome.tabs.onRemoved.addListener(function (id) {
  serial(function () { return load().then(function (st) { if (st.tabs[String(id)]) { delete st.tabs[String(id)]; return chrome.storage.session.set({ tabs: st.tabs }); } }); });
});
chrome.action.onClicked.addListener(function () { openScudi(); });
