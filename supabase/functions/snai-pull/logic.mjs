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
  maxChunks: 2,             // requests of up to maxIds events in one pull (all the leagues on a busy weekend)
  sharp: null,              // the reference books priced alongside SNAI (null: learnt from odss-api's list of books)
  booksEveryH: 168,         // odss-api's list of books is read again after this long (one request)
  maxAgeH: 48,              // a sharp book's price older than this is not used
  maxFitError: 0.01,        // the fitted score matrix may miss the market's chances by this much at most
  refBooks: 24,             // reference books asked for beside SNAI (sharp books first; payload only, no extra request)
  minBooks: 2,              // books a fit needs when Pinnacle has no price (the weekly job asks for two)
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
/* clubs SNAI names in Italian or shortens (the feed's names on the left, folded) — only where the names differ a lot */
const CLUB_IT = {
  parissaintgermain: 'psg', marseille: 'marsiglia', olympiquemarseille: 'marsiglia', lyon: 'lione', olympiquelyonnais: 'lione', nice: 'nizza',
  toulouse: 'tolosa', lille: 'lilla', strasbourg: 'strasburgo', rbleipzig: 'lipsia', leipzig: 'lipsia', freiburg: 'friburgo', koln: 'colonia',
  cologne: 'colonia', stuttgart: 'stoccarda', werderbremen: 'werderbrema', hamburger: 'amburgo', hamburg: 'amburgo', mainz: 'magonza',
  fsvmainz: 'magonza', eintrachtfrankfurt: 'eintrachtfrancoforte', unionberlin: 'unionberlino', herthaberlin: 'herthaberlino',
  bayernmunich: 'bayernmonaco', sevilla: 'siviglia', barcelona: 'barcellona', mallorca: 'maiorca', realzaragoza: 'saragozza',
  athleticbilbao: 'atleticobilbao', athleticclub: 'atleticobilbao', sportinglisbon: 'sportinglisbona', sportingcp: 'sportinglisbona',
  redstarbelgrade: 'stellarossa', crvenazvezda: 'stellarossa', dinamozagreb: 'dinamozagabria', copenhagen: 'copenaghen', clubbrugge: 'bruges',
  standardliege: 'standardliegi', olympiacos: 'olympiakos', manchesterunited: 'manchesterutd', borussiamonchengladbach: 'borussiamgladbach',
};
export function teamSim(scudiName, snaiName) {
  const k = fold(scudiName), it = NAT_IT[k] || CLUB_IT[k];
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
/* Scudi's matches and fixtures (week.json: the priced matches, then the fixtures not priced yet) ↔ SNAI's events: the
   same kick-off (± kickTolMin) and names alike — both at least 0.55, or one at least 0.8, or one at least 0.55 in a league
   with the competition's words (one name loosely alike, in any league, paired Foggia - Potenza of Serie C with Lazio -
   Monza at the same hour: "Monza" and "Potenza" are 0.57 apart). The league alone never pairs. The best two events per match at most, each event for one match only. The site
   pairs them for good with its own matching (names, kick-off and prices), as it does with the extension's rows.
   What was not paired is reported (diag.unpaired: SNAI's nearest namesake, if any), with the pairing per competition. */
export function namesAlike(hs, as, hint) { return (hs >= 0.55 && as >= 0.55) || Math.max(hs, as) >= 0.8 || (!!hint && Math.max(hs, as) >= 0.55); }
export function scudiItems(week, now, cfg) {
  cfg = config(cfg);
  const end = now + cfg.windowDays * 864e5, seen = new Set(), out = [];
  for (const [list, priced] of [[week && week.matches, true], [week && week.fixtures, false]]) {
    for (const m of Array.isArray(list) ? list : []) {
      if (!m || !m.id || !m.kickoff || seen.has(m.id)) continue;
      const k = Date.parse(m.kickoff); if (!(k > now - 2 * 3600e3 && k <= end)) continue;
      seen.add(m.id); out.push({ id: m.id, competition: m.competition, kickoff: m.kickoff, home: m.home, away: m.away, priced });
    }
  }
  return out;
}
/* the matches and fixtures in the list's window, as short keys: SNAI's list is read again when one appears that was not
   there at the last reading (a match that kicks off and leaves the window does not count) */
export function itemKeys(week, now, cfg) { return scudiItems(week, now, cfg).map(m => String(m.id).slice(0, 10)); }
export function freshCount(week, now, cfg, known) {
  if (!week) return 0;
  const k = new Set(Array.isArray(known) ? known : []);
  return itemKeys(week, now, cfg).filter(x => !k.has(x)).length;
}
/* SNAI's list by league, the biggest first: what SNAI quotes this week (diag.leagues) */
export function leagueCounts(events, top) {
  const c = {};
  for (const e of events || []) { if (NOT_SENIOR.test(`${e.home} ${e.away} ${e.league}`)) continue; const l = e.league || '?'; c[l] = (c[l] || 0) + 1; }
  return Object.entries(c).sort((a, b) => b[1] - a[1]).slice(0, top || 60).reduce((o, [k, v]) => (o[k] = v, o), {});
}
export function selectEvents(events, matches, now, cfg) {
  cfg = config(cfg);
  const tol = cfg.kickTolMin * 60e3, out = [], pairs = [], diag = [];
  const future = (matches || []).filter(m => m && m.kickoff && Date.parse(m.kickoff) > now - 2 * 3600e3);
  /* SNAI's events by kick-off, so each match is compared only with the events within three hours of it */
  const evs = (events || []).filter(e => e.commence && isFinite(Date.parse(e.commence)) && !NOT_SENIOR.test(`${e.home} ${e.away} ${e.league}`))
    .map(e => Object.assign({}, e, { t: Date.parse(e.commence) })).sort((a, b) => a.t - b.t);
  const firstAt = t => { let lo = 0, hi = evs.length; while (lo < hi) { const mid = (lo + hi) >> 1; if (evs[mid].t < t) lo = mid + 1; else hi = mid; } return lo; };
  for (const m of future) {
    const k = Date.parse(m.kickoff); let near = null;
    for (let i = firstAt(k - 3 * 3600e3); i < evs.length && evs[i].t <= k + 3 * 3600e3; i++) {
      const e = evs[i], dt = Math.abs(e.t - k);
      const hs = teamSim(m.home, e.home), as = teamSim(m.away, e.away), hint = compHint(m.competition, e.league);
      const sc = Math.max(hs, as) + (hs >= 0.55 && as >= 0.55 ? 0.5 : 0) + (hint ? 0.3 : 0);
      if (dt <= tol) { if (namesAlike(hs, as, hint)) pairs.push({ m: m.id, e: e.id, sc }); }
      else if (Math.max(hs, as) >= 0.9 && Math.min(hs, as) >= 0.5 && (!near || sc > near.sc)) near = { sc, dt: Math.round((e.t - k) / 60e3) };
    }
    if (near && !pairs.some(p => p.m === m.id)) diag.push({ match: `${m.home} - ${m.away}`, offMin: near.dt });   /* names agree, kick-off does not: a time-zone slip? */
  }
  pairs.sort((a, b) => b.sc - a.sc);
  const perMatch = {}, usedE = {};
  for (const p of pairs) {
    if (usedE[p.e] || (perMatch[p.m] || 0) >= 2) continue;
    usedE[p.e] = p.m; perMatch[p.m] = (perMatch[p.m] || 0) + 1;
  }
  for (const e of evs) if (usedE[e.id]) { const o = Object.assign({}, e, { match: usedE[e.id] }); delete o.t; out.push(o); }
  /* what was not paired, with SNAI's nearest namesake within two days (none: SNAI does not list it, or names it otherwise) */
  const unpaired = [], byComp = {};
  for (const m of future) {
    const c = m.competition || '?', got = !!perMatch[m.id];
    const b = byComp[c] || (byComp[c] = [0, 0]); b[1]++; if (got) b[0]++;
    if (got || unpaired.length >= 40) continue;
    const k = Date.parse(m.kickoff); let best = null;
    for (let i = firstAt(k - 2 * 864e5); i < evs.length && evs[i].t <= k + 2 * 864e5; i++) {
      const e = evs[i], hs = teamSim(m.home, e.home), as = teamSim(m.away, e.away), s = hs + as;
      if (Math.max(hs, as) >= 0.5 && (!best || s > best.s)) best = { s, e, hs, as };
    }
    unpaired.push({ match: `${m.home} - ${m.away}`, comp: c, kick: m.kickoff, priced: m.priced !== false,
      snai: best ? { name: `${best.e.home} - ${best.e.away}`, league: best.e.league, offMin: Math.round((best.e.t - k) / 60e3), sim: [Math.round(best.hs * 100) / 100, Math.round(best.as * 100) / 100] } : null });
  }
  return { events: out, matched: Object.keys(perMatch).length, of: future.length, diag: diag.slice(0, 12), unpaired, byComp,
    pricedMatched: future.filter(m => m.priced !== false && perMatch[m.id]).length, pricedOf: future.filter(m => m.priced !== false).length };
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

/* ---------- the sharp books' prices → Scudi's own chances (decision 94) ----------
   odss-api carries the sharp books (Pinnacle, the exchanges) next to SNAI, in the same records, so the requests that
   bring SNAI's prices bring theirs too. From them Scudi works out its chances for the matches its weekly job has not
   priced (the smaller leagues before Friday, any league any day), with the weekly job's own method: each book de-vigged
   on its own (power method), averaged with the sharp weights, and a Dixon–Coles score matrix fitted to the result and
   over/under 2.5 chances (mirrors scudi_slips/devig.py, consensus.py and matrix.py; the tests compare the two).
   odss-api's terms allow internal use only: the fit is stored in the private store and read by the owner alone. */
export const SHARP_W = [[/^pinnacle/i, 3], [/^betfair/i, 2], [/^matchbook/i, 1.5]];
export function sharpWeight(key) { for (const [re, w] of SHARP_W) if (re.test(String(key || ''))) return w; return 0; }
/* the books asked for beside SNAI, in this order: the sharp ones (weights above), the other exchanges and SBOBET, then
   big international books (weight 1, as in the weekly job's consensus of ~12 books); SNAI and the other Italian books
   are never part of the consensus (Scudi bets against SNAI; Italy's books often share one list). Seen on the first real
   pulls (7 Oct): odss-api carries Pinnacle for some events only (none for Arsenal - Leeds), and with five books 33 of 79
   events had no result price from any of them → a wide list. */
export const REF_ORDER = [/^pinnacle$/i, /^betfair/i, /^matchbook$/i, /^smarkets$/i, /^betdaq$/i, /^sbobet$/i, /^onexbet$/i, /^marathonbet$/i,
  /^williamhill$/i, /^bet365$/i, /^unibet_uk$/i, /^unibet_de$/i, /^ladbrokes$/i, /^coral$/i, /^paf_com$/i, /^888sport$/i, /^bwin_com$/i,
  /^betway$/i, /^pokerstars$/i, /^stake$/i, /^leovegas_com$/i, /^sportingbet_com$/i, /^betano_de$/i, /^superbet_ro$/i, /^winamax_fr$/i,
  /^pmu_fr$/i, /^tippmixpro$/i, /^svenska_spel_sport$/i, /^toto_nl$/i, /^draftkings$/i, /^fanduel$/i, /^bovada$/i];
/* last resort, for events no international book prices on odss-api (28 of 51 on 7 Oct): the big Italian books other than
   SNAI, at least three of them (soft books that often share lists: a fit from them is marked tier 'it') */
export const REF_IT = [/^sisal$/i, /^eurobet$/i, /^goldbet$/i, /^lottomatica$/i, /^betflag$/i, /^planetwin365$/i, /^bet365$/i, /^williamhill$/i,
  /^betsson$/i, /^netbet$/i, /^leovegas$/i, /^888sport_it$/i];
const EXCHANGE = /^(betfair|matchbook|smarkets|betdaq)/i;
/* odss-api's list of books (GET /bookmakers, any of the shapes it may take) → { keys: the reference books found, in
   REF_ORDER, at most `max`; it: the Italian ones of REF_IT (the last resort); all: every key } */
export function refBooks(body, max) {
  const list = Array.isArray(body) ? body : body && (body.bookmakers || body.data || body.books) || [];
  const all = [], info = {};
  for (const b of Array.isArray(list) ? list : []) {
    const key = typeof b === 'string' ? b : b && (b.key || b.id || b.name);
    if (!key || info[key]) continue;
    all.push(String(key)); info[key] = b && typeof b === 'object' ? b : {};
  }
  const keys = [], it = [], italian = k => info[k].playable_it === true || String(info[k].country || '').toUpperCase() === 'IT';
  for (const re of REF_ORDER) for (const k of all) {
    if (keys.length >= (max || 10) || keys.includes(k) || !re.test(k)) continue;
    if (/^betfair/i.test(k) && info[k].is_exchange === false) continue;   /* Betfair's sportsbook is an ordinary book */
    if (italian(k)) continue;   /* never an Italian book */
    keys.push(k);
  }
  for (const re of REF_IT) for (const k of all) if (re.test(k) && !keys.includes(k) && !it.includes(k) && !/^snai/i.test(k)) it.push(k);
  return { keys, all, it };
}
export function sharpBooks(body) { return refBooks(body, 3).keys.filter(k => sharpWeight(k) > 0); }
export function powerDevig(prices) {
  if (prices.length < 2 || prices.some(p => !(p > 1) || !isFinite(p))) throw new Error('bad prices');
  const raw = prices.map(p => 1 / p), total = raw.reduce((a, b) => a + b, 0);
  if (total <= 1) return raw.map(r => r / total);
  let lo = 1, hi = 50;
  for (let i = 0; i < 80; i++) { const mid = (lo + hi) / 2; if (raw.reduce((a, r) => a + r ** mid, 0) > 1) lo = mid; else hi = mid; }
  const k = (lo + hi) / 2, pr = raw.map(r => r ** k), s = pr.reduce((a, b) => a + b, 0);
  return pr.map(p => p / s);
}
const MAX_MARGIN = 0.15;
/* a book's market is usable when it is fresh and adds up: margin 0–15% (an exchange's best prices may add up to a little
   under 100%: down to −3% for them) */
export function usablePrices(prices, at, now, maxAgeH, book) {
  if (prices.some(p => !(p > 1))) return false;
  const margin = prices.reduce((a, p) => a + 1 / p, 0) - 1, lo = EXCHANGE.test(String(book || '')) ? -0.03 : 0;
  if (!(margin >= lo && margin <= MAX_MARGIN)) return false;
  return !(at && now && now - at > maxAgeH * 3600e3);
}
/* [{ book, prices, at }] → the weighted average of each usable book's fair chances, or null */
export function consensusOf(list, now, maxAgeH) {
  const good = list.filter(x => usablePrices(x.prices, x.at, now, maxAgeH == null ? 48 : maxAgeH, x.book));
  if (!good.length) return null;
  const n = good[0].prices.length, acc = new Array(n).fill(0); let tw = 0, sw = 0;
  for (const x of good) { const w = sharpWeight(x.book) || 1, f = powerDevig(x.prices); tw += w; if (sharpWeight(x.book)) sw += w; for (let i = 0; i < n; i++) acc[i] += w * f[i]; }
  return { probs: acc.map(a => a / tw), books: good.map(x => x.book), sharp: sw / tw };
}
/* the Dixon–Coles matrix (scorelines 0..9 each side) summed into home, draw, away and over 2.5 */
const NG = 10, FACT = [1]; for (let i = 1; i < NG; i++) FACT[i] = FACT[i - 1] * i;
export function safeRho(lh, la, rho) { const hi = Math.min(1 / (lh * la), 1) * 0.999, lo = -Math.min(1 / lh, 1 / la) * 0.999; return Math.max(lo, Math.min(hi, rho)); }
export function summaryOf(lh, la, rho) {
  rho = safeRho(lh, la, rho);
  const ph = [], pa = []; for (let i = 0; i < NG; i++) { ph[i] = Math.exp(-lh) * lh ** i / FACT[i]; pa[i] = Math.exp(-la) * la ** i / FACT[i]; }
  let H = 0, D = 0, A = 0, O = 0, T = 0;
  for (let h = 0; h < NG; h++) for (let a = 0; a < NG; a++) {
    let v = ph[h] * pa[a];
    if (h === 0 && a === 0) v *= 1 - lh * la * rho; else if (h === 0 && a === 1) v *= 1 + lh * rho; else if (h === 1 && a === 0) v *= 1 + la * rho; else if (h === 1 && a === 1) v *= 1 - rho;
    T += v; if (h > a) H += v; else if (h === a) D += v; else A += v; if (h + a >= 3) O += v;
  }
  return [H / T, D / T, A / T, O / T];
}
/* the matrix that reproduces the market's result and over 2.5 chances: least squares on (lh, la, rho) within the same
   bounds and from the same start as scudi_slips/matrix.fit_market (Levenberg–Marquardt, numerical derivatives) */
const LO = [0.05, 0.05, -0.30], HI = [6.0, 6.0, 0.20];
export function fitMarket(pH, pD, pA, pO) {
  const target = [pH, pD, pA, pO];
  if (target.some(p => !(p > 0 && p < 1)) || Math.abs(pH + pD + pA - 1) > 1e-6) throw new Error('not a valid set of fair chances');
  const clip = x => x.map((v, i) => Math.max(LO[i], Math.min(HI[i], v)));
  const res = x => { const s = summaryOf(x[0], x[1], x[2]); return s.map((v, i) => v - target[i]); };
  const cost = r => r.reduce((a, v) => a + v * v, 0);
  const total = pO <= 0 ? 2.7 : Math.max(1.2, Math.min(4.5, 1.6 + 2.2 * pO)), tilt = 0.5 + 0.9 * (pH - pA);
  let x = [Math.max(0.2, total * Math.min(0.9, Math.max(0.1, tilt))), 0, -0.05]; x[1] = Math.max(0.2, total - x[0]); x = clip(x);
  let r = res(x), c = cost(r), lam = 1e-3;
  for (let it = 0; it < 200 && c > 1e-26; it++) {
    const J = [0, 1, 2].map(j => { const hstep = 1e-6 * Math.max(1, Math.abs(x[j])), xp = x.slice(), xm = x.slice(); xp[j] += hstep; xm[j] -= hstep; const rp = res(xp), rm = res(xm); return rp.map((v, i) => (v - rm[i]) / (2 * hstep)); });
    const A = [0, 1, 2].map(a => [0, 1, 2].map(b => J[a].reduce((s, v, i) => s + v * J[b][i], 0)));
    const g = [0, 1, 2].map(a => J[a].reduce((s, v, i) => s + v * r[i], 0));
    let improved = false;
    for (let k = 0; k < 12 && !improved; k++) {
      const M = A.map((row, i) => row.map((v, j) => v + (i === j ? lam * Math.max(A[i][i], 1e-12) : 0)));
      const d = solve3(M, g.map(v => -v)); if (!d) { lam *= 10; continue; }
      const xn = clip(x.map((v, i) => v + d[i])), rn = res(xn), cn = cost(rn);
      if (cn < c) { const small = Math.max(...xn.map((v, i) => Math.abs(v - x[i]))) < 1e-12; x = xn; r = rn; c = cn; lam = Math.max(lam / 10, 1e-12); improved = true; if (small) it = 1e9; }
      else lam *= 10;
    }
    if (!improved) break;
  }
  const s = summaryOf(x[0], x[1], x[2]);
  return { lh: x[0], la: x[1], rho: safeRho(x[0], x[1], x[2]), err: Math.max(...s.map((v, i) => Math.abs(v - target[i]))) };
}
function solve3(M, b) {   /* Gaussian elimination with partial pivoting */
  const a = M.map((row, i) => row.concat([b[i]]));
  for (let c = 0; c < 3; c++) {
    let p = c; for (let i = c + 1; i < 3; i++) if (Math.abs(a[i][c]) > Math.abs(a[p][c])) p = i;
    if (Math.abs(a[p][c]) < 1e-300) return null;
    [a[c], a[p]] = [a[p], a[c]];
    for (let i = c + 1; i < 3; i++) { const f = a[i][c] / a[c][c]; for (let j = c; j < 4; j++) a[i][j] -= f * a[c][j]; }
  }
  const x = [0, 0, 0];
  for (let i = 2; i >= 0; i--) { let s = a[i][3]; for (let j = i + 1; j < 3; j++) s -= a[i][j] * x[j]; x[i] = s / a[i][i]; }
  return x.every(isFinite) ? x : null;
}
/* records → per event: the reference books' fit. { lh, la, rho, err, p: [1, X, 2, over 2.5], goals: over/under 2.5 known,
   books, sharp: share of the weight from the sharp books, at: the newest price time }. A fit needs Pinnacle's result
   price or at least minBooks usable books (the weekly job asks for two), and must reproduce the market within maxFitError;
   failing that, three or more Italian books other than SNAI (tier 'it' instead of 'ref').
   Without an over/under 2.5 the over chance is a bland 0.5 (as the weekly job does) and goals = false: the site then
   offers the result picks only. `why`, when given, counts the reasons for no fit and keeps a few examples. */
export function sharpFits(records, keys, now, cfg, why, itKeys) {
  cfg = config(cfg);
  keys = (keys || []).filter(k => !cfg.books.includes(k));
  const itk = (itKeys || []).filter(k => !cfg.books.includes(k) && !keys.includes(k));
  const by = new Map();
  for (const r of records || []) {
    if (!r || !r.event_id || !fullTime(r)) continue;
    const isX = r.market === '1x2', isO = r.market === 'ou' && Math.round(Number(r.line) * 100) === 250;
    if (!isX && !isO) continue;
    let e = by.get(r.event_id); if (!e) by.set(r.event_id, (e = { x: [], o: [], ix: [], io: [], at: 0, iat: 0, seen: {}, name: `${r.home_team || ''} - ${r.away_team || ''}` }));
    if (isX) for (const b of r.bookmakers || []) if (b && b.key) e.seen[b.key] = b.outcomes ? Object.keys(b.outcomes).length + (b.suspended || []).length : 0;
    for (const [list, X, O, T] of [[keys, 'x', 'o', 'at'], [itk, 'ix', 'io', 'iat']]) for (const k of list) {
      const b = (r.bookmakers || []).find(z => z && z.key === k); if (!b || !b.outcomes) continue;
      const c = codesOf(r, k, null), at = b.last_update ? Date.parse(b.last_update) : NaN, byOc = {};
      for (const z of c) if (z[3] != null) byOc[z[2]] = z[3];
      if (isX && byOc[1] && byOc[2] && byOc[3]) e[X].push({ book: k, prices: [byOc[1], byOc[2], byOc[3]], at: isFinite(at) ? at : null });
      if (isO && byOc[1] && byOc[2]) e[O].push({ book: k, prices: [byOc[2], byOc[1]], at: isFinite(at) ? at : null });   /* over, under */
      if (isFinite(at) && at > e[T]) e[T] = at;
    }
  }
  const out = new Map(), no = (id, e, reason, extra) => {
    if (!why) return;
    why.counts = why.counts || {}; why.counts[reason] = (why.counts[reason] || 0) + 1;
    why.sample = why.sample || [];
    if (why.sample.length < 8) why.sample.push(Object.assign({ ev: id, match: e.name, reason, books: Object.keys(e.seen).filter(k => keys.includes(k) || /^pinn/i.test(k)).slice(0, 8),
      x: e.x.map(z => [z.book, ...z.prices, z.at ? Math.round((now - z.at) / 3600e3) : null]) }, extra || {}));
  };
  const r4 = v => Math.round(v * 1e4) / 1e4;
  const tryFit = (X, O, minBooks) => {
    if (!X.length) return 'no-result-price';
    const c1 = consensusOf(X, now, cfg.maxAgeH); if (!c1) return 'not-usable';
    if (c1.books.length < minBooks && !c1.books.some(k => /^pinnacle/i.test(k))) return 'few-books';
    const c2 = O.length ? consensusOf(O, now, cfg.maxAgeH) : null;
    let f; try { f = fitMarket(c1.probs[0], c1.probs[1], c1.probs[2], c2 ? c2.probs[0] : 0.5); } catch (_) { return 'bad-chances'; }
    if (!(f.err <= cfg.maxFitError)) return 'fit-error';
    return { lh: r4(f.lh), la: r4(f.la), rho: r4(f.rho), err: r4(f.err), p: [...c1.probs, c2 ? c2.probs[0] : null].map(v => v == null ? null : r4(v)),
      goals: !!c2, books: c1.books, sharp: r4(c1.sharp) };
  };
  for (const [id, e] of by) {
    let f = tryFit(e.x, e.o, cfg.minBooks), tier = 'ref', at = e.at;
    if (typeof f === 'string' && itk.length) {   /* the last resort: three or more of the big Italian books other than SNAI */
      const g = tryFit(e.ix, e.io, Math.max(3, cfg.minBooks));
      if (typeof g !== 'string') { f = g; tier = 'it'; at = e.iat; } else if (f === 'no-result-price') f = 'no-result-price' + (e.ix.length ? '/it-' + g : '');
    }
    if (typeof f === 'string') { no(id, e, f); continue; }
    out.set(id, Object.assign(f, { tier, at: at ? new Date(at).toISOString() : null }));
  }
  return out;
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
/* pull now or not. st: the stored state; kicks: Scudi's kick-offs ahead (ms, sorted); manual: "Update now" from the site;
   fresh: Scudi's list has matches or fixtures SNAI's list was not read for yet.
   The month's requests left (less the reserve) are spread over the weighted time left until the quota reopens: a pull is
   due once the weighted time since the last one reaches that share, times what a pull usually costs. */
export function plan({ now, st, cfg, kicks, manual, fresh }) {
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
  /* new matches or fixtures in Scudi's list (the Friday pull, a new day in the window): SNAI's list is read now */
  if (fresh) return Object.assign(base, { discover: true, pull: true, why: 'new-matches' });
  const cost = st.avg_cost > 0 ? +st.avg_cost : 1.3;
  const ahead = weightBetween(now, reset, kicks, cfg);
  const share = ahead * cost / spend;   /* weighted hours per pull */
  const since = last ? weightBetween(Math.max(last, now - 7 * 864e5), now, kicks, cfg) : Infinity;
  const nextIn = since >= share ? 0 : (share - since) / Math.max(weight(now, kicks, cfg), 1) * 3600e3;
  return Object.assign(base, { pull: since >= share, why: since >= share ? 'due' : 'waiting', share, since, ahead, next: now + nextIn });
}
/* the events a pull asks for, soonest first: all within nearH, the further ones only when their markets are old
   (or all of them on "Update now"); at most maxChunks requests of maxIds */
export function pickIds(rows, now, cfg, all) {
  cfg = config(cfg);
  return (rows || []).filter(r => {
    const k = Date.parse(r.commence_time); if (!(k > now + 2 * 60e3)) return false;
    if (all || k - now <= cfg.nearH * 3600e3) return true;
    return !r.full_at || now - Date.parse(r.full_at) >= cfg.farEveryH * 3600e3;
  }).sort((a, b) => Date.parse(a.commence_time) - Date.parse(b.commence_time)).slice(0, cfg.maxIds * cfg.maxChunks).map(r => r.event_id);
}
/* the ids in requests of up to maxIds each */
export function chunks(ids, size) { const out = []; for (let i = 0; i < ids.length; i += size) out.push(ids.slice(i, i + size)); return out; }

/* ---------- requests ---------- */
export function oddsUrl(params, base) {
  const q = Object.entries(params).filter(([, v]) => v != null).map(([k, v]) => `${k}=${Array.isArray(v) ? v.map(encodeURIComponent).join(',') : encodeURIComponent(v)}`).join('&');
  return `${base || ODSS}/odds?${q}`;
}
export function discoverParams(now, cfg) {
  cfg = config(cfg);
  return { sport: 'calcio', market: '1x2', bookmakers: cfg.books, commence_from: new Date(now).toISOString(), commence_to: new Date(now + cfg.windowDays * 864e5).toISOString(), limit: 5000, after: '' };
}
export function nearParams(ids, cfg, sharp) {
  cfg = config(cfg);
  const books = cfg.books.concat((sharp || []).filter(k => !cfg.books.includes(k)));
  return { event_id: ids, market: ['1x2', 'dc', 'ou', 'btts'], bookmakers: books, limit: 5000, after: '' };
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
