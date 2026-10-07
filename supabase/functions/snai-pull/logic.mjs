/* Scudi · automatic SNAI prices (decision 92): the pure part of the snai-pull function, shared by the Edge Function
   (Deno) and the tests (node). Nothing here talks to the network or the database.

   What it decides:
   - when to spend one of odss-api.com's requests (500 a month on the free plan): never at night, more often in the three
     hours before a kick-off of one of Scudi's matches, spread so that the month's quota lasts until it reopens;
   - which of SNAI's events are Scudi's matches (same kick-off, names or competition alike), so that the frequent pulls
     ask only for those, by event id (one request for all of them);
   - how odss-api's records become SNAI's own codes, exactly as the extension reads them off snai.it:
     [market, line, outcome, price] with 3 = 1X2, 28319 = double chance, 7989 = under/over (line × 100), 18 = goal/no goal,
     and a suspended price as null (SNAI's padlock). */

export const ODSS = 'https://odss-api.com/api/v1';
export const DEFAULTS = {
  enabled: true,
  books: ['snai'],          // the book whose prices Scudi uses; others can be added later at no extra request
  monthly: 500,             // the free plan's quota, used until the first answer tells the real one
  reserve: 25,              // kept for "Update now" from the site
  floor: 3,                 // below this nothing is spent, not even by hand
  nightFrom: 0.5,           // Rome hours with no pulls: from 00:30 …
  nightTo: 8,               // … to 08:00
  preMatchH: 3,             // the hours before a kick-off that count more
  preMatchW: 4,             // how much more (an hour before a match is worth four ordinary hours)
  typicalW: 1.8,            // the weight of an ordinary day's hour beyond the matches already known
  discoverEveryH: 12,       // SNAI's whole football list (1X2 only) is read again after this long
  nearH: 48,                // full markets for the matches kicking off within this many hours, every pull
  farEveryH: 12,            // matches further away: full markets again after this long
  maxIds: 150,              // event ids in one request
  maxPages: 3,              // pages of one request (5,000 records each)
  kickTolMin: 10,           // SNAI's kick-off and Scudi's may differ by this much
  manualGapMin: 3,          // "Update now" at most this often
  windowDays: 8,            // how far ahead the list is read
  slotMin: 10,              // the planner's time step (the cron runs every 10 minutes)
};
export function config(over) { return Object.assign({}, DEFAULTS, over || {}); }

/* ---------- names ---------- */
const CLUB = /\b(fc|ac|afc|ssc|us|as|ss|cf|sc|calcio|club|de|cd|ud|rcd|fk|sk|bk|if|kv|krc|rsc|vfl|vfb|tsg|sv|1|04|05|1899|1909|1910|1913)\b/g;
export function fold(s) {
  return String(s || '').normalize('NFD').replace(/[̀-ͯ]/g, '').toLowerCase().replace(CLUB, ' ').replace(/[^a-z]/g, '');
}
function lev(a, b) {
  const m = a.length, n = b.length; let prev = []; for (let j = 0; j <= n; j++) prev[j] = j;
  for (let i = 1; i <= m; i++) { const cur = [i]; for (let j = 1; j <= n; j++) cur[j] = Math.min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (a[i - 1] === b[j - 1] ? 0 : 1)); prev = cur; }
  return prev[n];
}
/* 1 identical; 0.9 one inside the other; 0.8 the same first five letters (Bayern Munich / Bayern Monaco); else edit distance */
export function nameSim(a, b) {
  a = fold(a); b = fold(b); if (!a || !b) return 0; if (a === b) return 1;
  const sh = Math.min(a.length, b.length), lo = Math.max(a.length, b.length);
  if (sh >= 5 && sh / lo >= 0.5 && (a.includes(b) || b.includes(a))) return 0.9;
  const lv = 1 - lev(a, b) / lo;
  return sh >= 5 && a.slice(0, 5) === b.slice(0, 5) ? Math.max(0.8, lv) : lv;
}
/* the national teams Scudi has, in Italian (SNAI's names) — only those whose names differ a lot */
const NAT_IT = {
  england: 'inghilterra', wales: 'galles', scotland: 'scozia', northernireland: 'irlandadelnord', ireland: 'irlanda', republicofireland: 'irlanda',
  netherlands: 'olanda', germany: 'germania', spain: 'spagna', france: 'francia', switzerland: 'svizzera', hungary: 'ungheria', greece: 'grecia',
  sweden: 'svezia', norway: 'norvegia', denmark: 'danimarca', finland: 'finlandia', iceland: 'islanda', poland: 'polonia', czechia: 'repceca',
  czechrepublic: 'repceca', slovakia: 'slovacchia', slovenia: 'slovenia', croatia: 'croazia', serbia: 'serbia', montenegro: 'montenegro',
  northmacedonia: 'macedoniadelnord', albania: 'albania', kosovo: 'kosovo', bosniaandherzegovina: 'bosniaerzegovina', romania: 'romania',
  bulgaria: 'bulgaria', turkey: 'turchia', turkiye: 'turchia', cyprus: 'cipro', israel: 'israele', georgia: 'georgia', armenia: 'armenia',
  azerbaijan: 'azerbaigian', kazakhstan: 'kazakistan', belarus: 'bielorussia', ukraine: 'ucraina', moldova: 'moldavia', lithuania: 'lituania',
  latvia: 'lettonia', estonia: 'estonia', faroeislands: 'isolefaroe', luxembourg: 'lussemburgo', liechtenstein: 'liechtenstein', andorra: 'andorra',
  sanmarino: 'sanmarino', gibraltar: 'gibilterra', malta: 'malta', belgium: 'belgio', austria: 'austria', portugal: 'portogallo', italy: 'italia',
};
export function teamSim(scudiName, snaiName) {
  const k = fold(scudiName), it = NAT_IT[k];
  return Math.max(nameSim(scudiName, snaiName), it ? nameSim(it, snaiName) : 0);
}
/* youth, women's, five-a-side, beach and e-sports football share the clubs' names: never Scudi's matches */
export const NOT_SENIOR = /\b(u ?1[5-9]|u ?2[0-3]|primavera|under ?2[0-3]|under ?1[5-9]|femminile|women|womens|donne|femm?|futsal|calcio a 5|beach|youth|giovanili|riserve|reserves?|b team|ii|e-?sports?|cyber|virtual)\b|2x[45] ?min/i;
/* words of each of Scudi's competitions as books spell them (folded): a hint, never enough on its own without the kick-off */
const COMP_WORDS = {
  'Serie A': ['seriea'], 'Premier League': ['premierleague', 'inghilterra', 'england'], 'La Liga': ['laliga', 'primeradivision', 'spagna', 'spain'],
  'Bundesliga': ['bundesliga', 'germania', 'germany'], 'Ligue 1': ['ligue', 'francia', 'france'], 'Champions League': ['champions'],
  'Nations League': ['nations', 'nazioni'], 'Europa League': ['europaleague', 'uefaeuropa'], 'Conference League': ['conference'],
  'Serie B': ['serieb'], 'Championship': ['championship'], 'League One': ['leagueone'], 'La Liga 2': ['laliga', 'segunda', 'liga'],
  '2. Bundesliga': ['bundesliga'], 'Ligue 2': ['ligue'], 'Eredivisie': ['eredivisie', 'olanda', 'netherlands'],
  'Primeira Liga': ['primeira', 'portugal', 'portogallo'], 'Belgian Pro League': ['proleague', 'belgi', 'jupiler', 'firstdivisiona'],
  'Süper Lig': ['superlig', 'turchia', 'turkey'], 'Scottish Premiership': ['premiership', 'scozia', 'scotland'],
  'Austrian Bundesliga': ['bundesliga', 'austria'], 'Swiss Super League': ['superleague', 'svizzera', 'switzerland'],
  'Danish Superliga': ['superliga', 'danimarca', 'denmark'], 'Allsvenskan': ['allsvenskan', 'svezia', 'sweden'],
  'Eliteserien': ['eliteserien', 'norvegia', 'norway'], 'Greek Super League': ['superleague', 'grecia', 'greece'],
};
export function compHint(competition, league) {
  const w = COMP_WORDS[competition], l = String(league || '').normalize('NFD').replace(/[̀-ͯ]/g, '').toLowerCase().replace(/[^a-z0-9]/g, '');
  return !!(w && l && w.some(x => l.includes(x)));
}

/* ---------- SNAI's list → Scudi's matches ---------- */
/* records (any markets) → one event per event_id */
export function eventsOf(records) {
  const by = new Map();
  for (const r of records || []) {
    if (!r || !r.event_id) continue;
    let e = by.get(r.event_id);
    if (!e) {
      let home = r.home_team, away = r.away_team;
      if ((!home || !away) && r.event) { const p = String(r.event).split(/\s+[-–]\s+|\s+v\s+|\s+vs\.?\s+/i); if (p.length === 2) { home = home || p[0]; away = away || p[1]; } }
      e = { id: String(r.event_id), home: home || '', away: away || '', league: r.league || '', commence: r.commence_time || null };
      by.set(r.event_id, e);
    }
  }
  return [...by.values()];
}
/* Scudi's matches (week.json) ↔ SNAI's events: the same kick-off (± kickTolMin) and at least one name alike (the
   competition's words in the league only add to the score: on its own the league paired lower divisions playing at the
   same time, seen on the first real pull); the best two events per match at most, each event for one match only. The
   site pairs them for good with its own matching (names, kick-off and prices), as it does with the extension's rows. */
export function selectEvents(events, matches, now, cfg) {
  cfg = config(cfg);
  const tol = cfg.kickTolMin * 60e3, out = [], pairs = [], diag = [];
  const future = (matches || []).filter(m => m && m.kickoff && Date.parse(m.kickoff) > now - 2 * 3600e3);
  const evs = (events || []).filter(e => e.commence && !NOT_SENIOR.test(`${e.home} ${e.away} ${e.league}`));
  for (const m of future) {
    const k = Date.parse(m.kickoff); let near = null;
    for (const e of evs) {
      const dt = Math.abs(Date.parse(e.commence) - k);
      const hs = teamSim(m.home, e.home), as = teamSim(m.away, e.away), hint = compHint(m.competition, e.league);
      const sc = Math.max(hs, as) + (hs >= 0.55 && as >= 0.55 ? 0.5 : 0) + (hint ? 0.3 : 0);
      if (dt <= tol) { if (Math.max(hs, as) >= 0.55) pairs.push({ m: m.id, e: e.id, sc }); }
      else if (dt <= 3 * 3600e3 && Math.max(hs, as) >= 0.9 && Math.min(hs, as) >= 0.5 && (!near || sc > near.sc)) near = { sc, dt: Math.round((Date.parse(e.commence) - k) / 60e3) };
    }
    if (near && !pairs.some(p => p.m === m.id)) diag.push({ match: `${m.home} - ${m.away}`, offMin: near.dt });   /* names agree, kick-off does not: a time-zone slip? */
  }
  pairs.sort((a, b) => b.sc - a.sc);
  const perMatch = {}, usedE = {};
  for (const p of pairs) {
    if (usedE[p.e] || (perMatch[p.m] || 0) >= 2) continue;
    usedE[p.e] = p.m; perMatch[p.m] = (perMatch[p.m] || 0) + 1;
  }
  for (const e of evs) if (usedE[e.id]) out.push(Object.assign({}, e, { match: usedE[e.id] }));
  return { events: out, matched: Object.keys(perMatch).length, of: future.length, diag: diag.slice(0, 12) };
}

/* ---------- odss-api records → SNAI's codes ---------- */
const OUT_1X2 = { HOME: 1, '1': 1, DRAW: 2, X: 2, AWAY: 3, '2': 3 };
const OUT_DC = { '1X': 1, X1: 1, HOME_DRAW: 1, HOMEDRAW: 1, '1_X': 1, '12': 2, '21': 2, HOME_AWAY: 2, HOMEAWAY: 2, '1_2': 2, X2: 3, '2X': 3, DRAW_AWAY: 3, DRAWAWAY: 3, X_2: 3 };
const OUT_OU = { UNDER: 1, U: 1, OVER: 2, O: 2 };
const OUT_BTTS = { YES: 1, GG: 1, Y: 1, NO: 2, NG: 2, N: 2 };
export const MARKET_CODE = { '1x2': 3, dc: 28319, ou: 7989, btts: 18 };
/* the whole match only: no half, team, corner, card or player records */
export function fullTime(r) {
  if (r.player != null) return false;
  const p = String(r.period == null ? '' : r.period).toLowerCase(), s = String(r.scope == null ? '' : r.scope).toLowerCase();
  if (p && !/^(ft|full|fulltime|full_time|match|regular|reg|90|ordinario|finale)$/.test(p)) return false;
  if (s && !/^(match|full|fulltime|full_time|ft|game|total|event)$/.test(s)) return false;
  return true;
}
/* one record → [[market, line, outcome, price|null], …]; unknown outcome labels are reported, never guessed */
export function codesOf(r, book, unknown) {
  const mk = MARKET_CODE[r.market]; if (!mk || !fullTime(r)) return [];
  const b = (r.bookmakers || []).find(x => x && x.key === book); if (!b) return [];
  let line = 0;
  if (mk === 7989) { const l = Number(r.line); if (!isFinite(l) || l <= 0 || Math.round(l * 100) % 50 !== 0 || Math.round(l * 100) % 100 === 0) return []; line = Math.round(l * 100); }
  const map = mk === 3 ? OUT_1X2 : mk === 28319 ? OUT_DC : mk === 7989 ? OUT_OU : OUT_BTTS, out = [], sus = new Set((b.suspended || []).map(String));
  const keys = new Set(Object.keys(b.outcomes || {}).concat([...sus]));
  for (const k of keys) {
    const oc = map[String(k).toUpperCase().replace(/[\s/]/g, '')] || map[String(k).toUpperCase()];
    if (!oc) { if (unknown) unknown[`${r.market}:${k}`] = (unknown[`${r.market}:${k}`] || 0) + 1; continue; }
    const pr = b.outcomes ? Number(b.outcomes[k]) : NaN;
    out.push([mk, line, oc, sus.has(String(k)) || !(pr > 1 && pr < 1000) ? null : Math.round(pr * 100) / 100]);
  }
  return out;
}
/* records → per event: SNAI's codes, the newest price time, and which markets the records covered */
export function snaiOf(records, book, unknown) {
  const by = new Map();
  for (const r of records || []) {
    if (!r || !r.event_id) continue;
    const c = codesOf(r, book, unknown);
    if (!c.length) continue;
    let e = by.get(r.event_id); if (!e) by.set(r.event_id, (e = { m: [], at: null }));
    const seen = new Set(e.m.map(x => x.slice(0, 3).join('_')));
    for (const x of c) { const k = x.slice(0, 3).join('_'); if (!seen.has(k)) { e.m.push(x); seen.add(k); } }
    const b = (r.bookmakers || []).find(x => x && x.key === book), t = b && b.last_update ? Date.parse(b.last_update) : NaN;
    if (isFinite(t) && (!e.at || t > e.at)) e.at = t;
  }
  return by;
}
/* a stored event's codes with the markets just pulled replaced (a market the pull no longer has goes away) */
export function mergeCodes(old, fresh, markets) {
  const codes = new Set(markets.map(m => MARKET_CODE[m]));
  return (old || []).filter(x => !codes.has(x[0])).concat(fresh || []).sort((a, b) => a[0] - b[0] || a[1] - b[1] || a[2] - b[2]);
}

/* ---------- the planner ---------- */
const ROME = new Intl.DateTimeFormat('en-GB', { timeZone: 'Europe/Rome', hour: '2-digit', minute: '2-digit', hourCycle: 'h23' });
const OFFSET = new Map();   /* Rome's offset from UTC, worked out once per hour (summer time changes on the hour) */
export function romeHour(t) {
  const hr = Math.floor(t / 3600e3);
  let off = OFFSET.get(hr);
  if (off === undefined) {
    const p = ROME.formatToParts(new Date(hr * 3600e3)), h = +p.find(x => x.type === 'hour').value;
    off = ((h - (hr % 24)) % 24 + 24) % 24;
    if (OFFSET.size > 20000) OFFSET.clear();
    OFFSET.set(hr, off);
  }
  return ((t / 3600e3 + off) % 24 + 24) % 24;
}
export function night(t, cfg) { const h = romeHour(t); return cfg.nightFrom < cfg.nightTo ? h >= cfg.nightFrom && h < cfg.nightTo : h >= cfg.nightFrom || h < cfg.nightTo; }
/* how much an instant is worth: 0 at night, 1 by day, preMatchW in the hours before one of Scudi's kick-offs */
export function weight(t, kicks, cfg) {
  if (night(t, cfg)) return 0;
  const w = cfg.preMatchH * 3600e3;
  for (const k of kicks) { if (k > t && k - t <= w) return cfg.preMatchW; if (k > t + w) break; }
  return 1;
}
/* the weight between two instants, slot by slot; past the last known kick-off an ordinary day's weight (typicalW) */
export function weightBetween(a, b, kicks, cfg) {
  const step = cfg.slotMin * 60e3, last = kicks.length ? kicks[kicks.length - 1] : a;
  let w = 0;
  for (let t = a; t < b; t += step) {
    const dt = Math.min(step, b - t) / step;
    if (t > last) w += (night(t, cfg) ? 0 : cfg.typicalW) * dt;
    else w += weight(t, kicks, cfg) * dt;
  }
  return w * cfg.slotMin / 60;   /* in weighted hours */
}
/* pull now or not. st: the stored state; kicks: Scudi's kick-offs ahead (ms, sorted); manual: "Update now" from the site.
   The month's requests left (less the reserve) are spread over the weighted time left until the quota reopens: a pull is
   due once the weighted time since the last one reaches that share, times what a pull usually costs. */
export function plan({ now, st, cfg, kicks, manual }) {
  cfg = config(cfg); st = st || {};
  kicks = (kicks || []).filter(k => k > now - 3600e3).sort((a, b) => a - b);
  let left = st.quota_remaining == null ? cfg.monthly : +st.quota_remaining;
  let reset = st.quota_reset_at ? Date.parse(st.quota_reset_at) : now + 30 * 864e5;
  if (reset <= now) { left = st.quota_limit == null ? cfg.monthly : +st.quota_limit; reset = now + 30 * 864e5; }   /* the window reopened */
  const last = st.last_pull_at ? Date.parse(st.last_pull_at) : 0;
  const disc = !st.discovered_at || now - Date.parse(st.discovered_at) >= cfg.discoverEveryH * 3600e3;
  const base = { left, reset, discover: disc, next: null, share: null, since: null, ahead: null };
  if (!cfg.enabled) return Object.assign(base, { pull: false, why: 'off' });
  if (st.backoff_until && Date.parse(st.backoff_until) > now) return Object.assign(base, { pull: false, why: 'backoff' });
  if (manual) {
    if (left <= cfg.floor) return Object.assign(base, { pull: false, why: 'quota' });
    if (now - last < cfg.manualGapMin * 60e3) return Object.assign(base, { pull: false, why: 'just-pulled' });
    return Object.assign(base, { pull: true, why: 'manual' });
  }
  const spend = left - cfg.reserve;
  if (spend <= 0) return Object.assign(base, { pull: false, why: 'reserve' });
  if (night(now, cfg)) return Object.assign(base, { pull: false, why: 'night' });
  const cost = st.avg_cost > 0 ? +st.avg_cost : 1.3;
  const ahead = weightBetween(now, reset, kicks, cfg);
  const share = ahead * cost / spend;   /* weighted hours per pull */
  const since = last ? weightBetween(Math.max(last, now - 7 * 864e5), now, kicks, cfg) : Infinity;
  const nextIn = since >= share ? 0 : (share - since) / Math.max(weight(now, kicks, cfg), 1) * 3600e3;
  return Object.assign(base, { pull: since >= share, why: since >= share ? 'due' : 'waiting', share, since, ahead, next: now + nextIn });
}
/* the events a pull asks for, soonest first: all within nearH, the further ones only when their markets are old
   (or all of them when Gianluca presses Update now) */
export function pickIds(rows, now, cfg, all) {
  cfg = config(cfg);
  return (rows || []).filter(r => {
    const k = Date.parse(r.commence_time); if (!(k > now + 2 * 60e3)) return false;
    if (all || k - now <= cfg.nearH * 3600e3) return true;
    return !r.full_at || now - Date.parse(r.full_at) >= cfg.farEveryH * 3600e3;
  }).sort((a, b) => Date.parse(a.commence_time) - Date.parse(b.commence_time)).slice(0, cfg.maxIds).map(r => r.event_id);
}

/* ---------- requests ---------- */
export function oddsUrl(params, base) {
  const q = Object.entries(params).filter(([, v]) => v != null).map(([k, v]) => `${k}=${Array.isArray(v) ? v.map(encodeURIComponent).join(',') : encodeURIComponent(v)}`).join('&');
  return `${base || ODSS}/odds?${q}`;
}
export function discoverParams(now, cfg) {
  cfg = config(cfg);
  return { sport: 'calcio', market: '1x2', bookmakers: cfg.books, commence_from: new Date(now).toISOString(), commence_to: new Date(now + cfg.windowDays * 864e5).toISOString(), limit: 5000, after: '' };
}
export function nearParams(ids, cfg) {
  cfg = config(cfg);
  return { event_id: ids, market: ['1x2', 'dc', 'ou', 'btts'], bookmakers: cfg.books, limit: 5000, after: '' };
}
/* the quota headers (any spelling odss-api uses) */
export function quotaOf(headers, now) {
  const g = n => { const v = headers.get ? headers.get(n) : headers[n.toLowerCase()]; return v == null || v === '' ? null : +v; };
  const lim = g('X-Quota-Limit') ?? g('X-RateLimit-Limit'), rem = g('X-Quota-Remaining') ?? g('X-RateLimit-Remaining'), rs = g('X-Quota-Reset') ?? g('X-RateLimit-Reset');
  const out = {};
  if (lim != null && isFinite(lim)) out.quota_limit = lim;
  if (rem != null && isFinite(rem)) out.quota_remaining = rem;
  if (rs != null && isFinite(rs)) out.quota_reset_at = new Date(now + rs * 1000).toISOString();
  return out;
}
/* an error answer → what to store and how long to wait */
export function failure(status, body) {
  const code = body && body.code ? String(body.code) : '';
  if (status === 401) return { status: 'bad-key', wait: 6 * 3600e3, code };
  if (status === 403) return { status: 'forbidden', wait: 6 * 3600e3, code };
  if (status === 429) return { status: code.includes('quota') || code.includes('month') ? 'quota' : 'rate', wait: code.includes('quota') || code.includes('month') ? 24 * 3600e3 : 5 * 60e3, code };
  if (status === 400) return { status: 'bad-request', wait: 3600e3, code };
  return { status: 'odss-down', wait: 20 * 60e3, code };
}
