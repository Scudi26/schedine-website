/* Checks for the automatic SNAI prices (decision 92): the pure part of the snai-pull Edge Function
   (supabase/functions/snai-pull/logic.mjs), run with `node tests/js/feed.test.mjs` (pytest runs it too). */
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import * as F from '../../supabase/functions/snai-pull/logic.mjs';

const here = path.dirname(fileURLToPath(import.meta.url));
let checks = 0, failures = 0;
function ok(cond, msg) { checks++; if (!cond) { failures++; console.error('FAIL: ' + msg); } }
const same = (a, b) => JSON.stringify(a) === JSON.stringify(b);
const rec = (o) => Object.assign({ event_id: 'e1', event: 'Juventus - Inter', league: 'Serie A', home_team: 'Juventus', away_team: 'Inter', commence_time: '2026-10-18T18:45:00.000Z', line: null, scope: null, period: null, state: 'prematch' }, o);
const bk = (outcomes, extra) => [Object.assign({ key: 'snai', outcomes, last_update: '2026-10-18T10:00:00.000Z' }, extra || {}), { key: 'pinnacle', outcomes: { HOME: 9, DRAW: 9, AWAY: 9, OVER: 9, UNDER: 9, YES: 9, NO: 9 } }];

/* ---------- odss-api → SNAI's codes ---------- */
{
  const u = {};
  ok(same(F.codesOf(rec({ market: '1x2', bookmakers: bk({ HOME: 2.1, DRAW: 3.3, AWAY: 3.6 }) }), 'snai', u), [[3, 0, 1, 2.1], [3, 0, 2, 3.3], [3, 0, 3, 3.6]]), '1X2: HOME/DRAW/AWAY → market 3, outcomes 1/2/3');
  ok(same(F.codesOf(rec({ market: 'dc', bookmakers: bk({ '1X': 1.3, '12': 1.33, X2: 1.7 }) }), 'snai', u).sort(), [[28319, 0, 1, 1.3], [28319, 0, 2, 1.33], [28319, 0, 3, 1.7]]), 'double chance: 1X → 1, 12 → 2, X2 → 3 (SNAI\'s order)');
  ok(same(F.codesOf(rec({ market: 'dc', bookmakers: bk({ HOME_DRAW: 1.3, HOME_AWAY: 1.33, DRAW_AWAY: 1.7 }) }), 'snai', u).map(x => x[2]).sort(), [1, 2, 3]), 'double chance spelled HOME_DRAW / HOME_AWAY / DRAW_AWAY is read too');
  ok(same(F.codesOf(rec({ market: 'ou', line: 2.5, bookmakers: bk({ UNDER: 1.8, OVER: 1.95 }) }), 'snai', u), [[7989, 250, 1, 1.8], [7989, 250, 2, 1.95]]), 'under/over 2.5 → market 7989, line 250, under 1, over 2');
  ok(same(F.codesOf(rec({ market: 'ou', line: 0.5, bookmakers: bk({ UNDER: 9, OVER: 1.05 }) }), 'snai', u).map(x => x[1]), [50, 50]), 'under/over 0.5 → line 50');
  ok(F.codesOf(rec({ market: 'ou', line: 2.25, bookmakers: bk({ UNDER: 1.8, OVER: 1.95 }) }), 'snai', u).length === 0, 'an Asian line (2.25) is not one of SNAI\'s lines: left out');
  ok(F.codesOf(rec({ market: 'ou', line: 3, bookmakers: bk({ UNDER: 1.8, OVER: 1.95 }) }), 'snai', u).length === 0, 'a whole line (3.0) is left out');
  ok(same(F.codesOf(rec({ market: 'btts', bookmakers: bk({ YES: 1.7, NO: 2.05 }) }), 'snai', u), [[18, 0, 1, 1.7], [18, 0, 2, 2.05]]), 'goal/no goal: YES → 1, NO → 2');
  ok(same(F.codesOf(rec({ market: '1x2', bookmakers: bk({ HOME: 2.1, DRAW: 3.3 }, { suspended: ['AWAY'] }) }), 'snai', u), [[3, 0, 1, 2.1], [3, 0, 2, 3.3], [3, 0, 3, null]]), 'a suspended outcome becomes SNAI\'s padlock (null)');
  ok(F.codesOf(rec({ market: '1x2', period: '1T', bookmakers: bk({ HOME: 2.9, DRAW: 2, AWAY: 4 }) }), 'snai', u).length === 0, 'first-half markets are left out');
  ok(F.codesOf(rec({ market: 'ou', line: 1.5, scope: 'home', bookmakers: bk({ UNDER: 1.4, OVER: 2.8 }) }), 'snai', u).length === 0, 'team totals are left out');
  ok(F.codesOf(rec({ market: 'btts', player: 'Lautaro', bookmakers: bk({ YES: 2 }) }), 'snai', u).length === 0, 'player rows are left out');
  ok(F.codesOf(rec({ market: 'ah', line: -0.5, bookmakers: bk({ HOME: 2 }) }), 'snai', u).length === 0, 'markets Scudi does not read (Asian handicap) are left out');
  ok(F.codesOf(rec({ market: '1x2', bookmakers: [{ key: 'pinnacle', outcomes: { HOME: 2 } }] }), 'snai', u).length === 0, 'another book\'s prices are never taken for SNAI\'s');
  ok(F.codesOf(rec({ market: '1x2', bookmakers: bk({ HOME: 0.5, DRAW: 3.3, AWAY: 1 }) }), 'snai', u).filter(x => x[3] === null).length === 2, 'a price that is not a price (≤ 1) counts as suspended');
  const u2 = {};
  F.codesOf(rec({ market: 'dc', bookmakers: bk({ WEIRD: 1.5, '1X': 1.2 }) }), 'snai', u2);
  ok(u2['dc:WEIRD'] === 1, 'an outcome label never seen is reported, not guessed');
  ok(F.fullTime({ period: 'FT', scope: null }) && F.fullTime({ period: null, scope: 'match' }) && !F.fullTime({ period: '2T' }) && !F.fullTime({ period: 'HT' }), 'full time: FT / match yes, halves no');
}
{
  const recs = [
    rec({ market: '1x2', bookmakers: bk({ HOME: 2.1, DRAW: 3.3, AWAY: 3.6 }, { last_update: '2026-10-18T10:00:00.000Z' }) }),
    rec({ market: 'ou', line: 2.5, bookmakers: bk({ UNDER: 1.8, OVER: 1.95 }, { last_update: '2026-10-18T10:05:00.000Z' }) }),
    rec({ market: 'ou', line: 2.5, bookmakers: bk({ UNDER: 1.7, OVER: 2.1 }) }),   /* a second record of the same line: the first stays */
    rec({ event_id: 'e2', market: 'btts', bookmakers: bk({ YES: 1.7, NO: 2.05 }) }),
  ];
  const by = F.snaiOf(recs, 'snai', {});
  ok(by.size === 2 && by.get('e1').m.length === 5, 'records grouped by event: 3 + 2 prices for e1, no duplicates');
  ok(by.get('e1').at === Date.parse('2026-10-18T10:05:00.000Z'), 'the event\'s price time is the newest of its records');
  ok(F.mergeCodes([[3, 0, 1, 2], [18, 0, 1, 1.5], [7989, 250, 1, 1.8]], [[3, 0, 1, 2.2]], ['1x2']).length === 3, 'a 1X2-only pull keeps the other markets');
  ok(same(F.mergeCodes([[3, 0, 1, 2], [18, 0, 1, 1.5], [7989, 250, 1, 1.8]], [[3, 0, 1, 2.2]], ['1x2', 'dc', 'ou', 'btts']), [[3, 0, 1, 2.2]]), 'a full pull replaces every market (one SNAI no longer offers goes away)');
}
/* odss-api's answer shape (tests/js/odss_mock_sample.json: its fields, our own invented events and prices) */
{
  const mock = JSON.parse(fs.readFileSync(path.join(here, 'odss_mock_sample.json'), 'utf8'));
  const by = F.snaiOf(mock.odds, 'book_a', {});
  const ev = F.eventsOf(mock.odds);
  ok(ev.length === 3 && ev.every(e => e.home && e.away && e.commence && e.league), 'the sandbox\'s events have names, league and kick-off');
  ok(by.size === 3 && [...by.values()].every(e => e.m.some(x => x[0] === 3) && e.m.some(x => x[0] === 7989 && x[1] === 250) && e.m.some(x => x[0] === 18)), 'the sandbox\'s 1X2, under/over 2.5 and goal/no goal all become SNAI codes');
  const sus = F.snaiOf(mock.odds, 'book_b', {});
  ok([...sus.values()].some(e => e.m.some(x => x[3] === null)), 'the sandbox\'s suspended outcomes become padlocks');
}
ok(same(F.eventsOf([{ event_id: 'x', event: 'Bologna - Torino', commence_time: '2026-10-18T13:00:00Z' }]).map(e => [e.home, e.away]), [['Bologna', 'Torino']]), 'names taken from "Home - Away" when the record has no team fields');

/* ---------- which of SNAI's events are Scudi's matches ---------- */
{
  const K = '2026-10-18T18:45:00Z', K2 = '2026-10-14T18:45:00Z';
  const matches = [
    { id: 'm1', competition: 'Serie A', kickoff: K, home: 'Juventus', away: 'Internazionale' },
    { id: 'm2', competition: 'Nations League', kickoff: K2, home: 'Germany', away: 'Netherlands' },
    { id: 'm3', competition: 'Bundesliga', kickoff: '2026-10-18T13:30:00Z', home: 'Bayern Munich', away: 'Borussia Dortmund' },
    { id: 'm4', competition: 'Premier League', kickoff: '2026-10-18T14:00:00Z', home: 'Arsenal', away: 'Chelsea' },
  ];
  const ev = [
    { id: 'a', home: 'Juventus', away: 'Inter', league: 'Serie A', commence: '2026-10-18T18:45:00.000Z' },
    { id: 'b', home: 'Juventus U19', away: 'Inter U19', league: 'Primavera 1', commence: '2026-10-18T18:45:00.000Z' },
    { id: 'c', home: 'Emelec', away: 'Barcelona SC', league: 'Serie A', commence: '2026-10-18T18:50:00.000Z' },
    { id: 'd', home: 'Germania', away: 'Olanda', league: 'UEFA Nations League', commence: '2026-10-14T18:45:00.000Z' },
    { id: 'e', home: 'Bayern Monaco', away: 'Borussia Dortmund', league: 'Bundesliga', commence: '2026-10-18T13:30:00.000Z' },
    { id: 'f', home: 'Arsenal', away: 'Chelsea', league: 'Premier League', commence: '2026-10-18T15:00:00.000Z' },
    { id: 'g', home: 'Sassuolo', away: 'Lecce', league: 'Serie A', commence: '2026-10-18T18:45:00.000Z' },
    { id: 'h', home: 'Cremonese', away: 'Pisa', league: 'Serie A', commence: '2026-10-18T18:45:00.000Z' },
    { id: 'i', home: 'Arsenal Women', away: 'Chelsea Women', league: 'WSL', commence: '2026-10-18T14:00:00.000Z' },
    { id: 'j', home: 'Forest Green', away: 'Hartlepool United FC', league: 'Inghilterra 5', commence: '2026-10-18T13:30:00.000Z' },   /* same time as m3, only the league's words in common with nothing */
    { id: 'k', home: 'AD Ceuta', away: 'CE Sabadell', league: 'LaLiga 2', commence: '2026-10-18T18:45:00.000Z' },                  /* La Liga's words, Juventus' kick-off */
  ];
  const s = F.selectEvents(ev, matches, Date.parse('2026-10-12T10:00:00Z'), {});
  const got = Object.fromEntries(s.events.map(e => [e.id, e.match]));
  ok(got.a === 'm1', 'Juventus - Inter on SNAI is Scudi\'s Juventus - Internazionale (same kick-off, one name alike)');
  ok(!got.b && !got.i, 'youth and women\'s matches are never picked');
  ok(!got.j && !got.k, 'another match at the same time whose league only shares words with the competition is not picked (first real pull)');
  ok(got.d === 'm2', 'Germania - Olanda (Italian names) is Germany - Netherlands: same kick-off, Italian names known');
  ok(got.e === 'm3', 'Bayern Monaco - Borussia Dortmund is Bayern Munich - Borussia Dortmund');
  ok(!got.f, 'the same names an hour later are not the same match …');
  ok(s.diag.some(d => /Arsenal/.test(d.match) && d.offMin === 60), '… but the hour\'s gap is reported (a time-zone slip would show here)');
  ok(s.events.filter(e => e.match === 'm1').length <= 2, 'at most two of SNAI\'s events per Scudi match');
  ok(!got.c || got.c === 'm1', 'Ecuador\'s Serie A five minutes later is at most a spare candidate, the site pairs for good');
  ok(s.matched === 3 && s.of === 4, 'three of four matches found: ' + s.matched + '/' + s.of);
  ok(F.compHint('La Liga', 'LaLiga') && F.compHint('Nations League', 'UEFA Nations League') && !F.compHint('Serie A', 'Premier League'), 'competition words');
  ok(F.teamSim('Faroe Islands', 'Isole Faroe') >= 0.8 && F.teamSim('England', 'Inghilterra') === 1, 'national teams in Italian');
  ok(F.nameSim('Hellas Verona', 'Verona') >= 0.9 && F.nameSim('AC Milan', 'Milan') === 1, 'club words and one name inside the other');
}

/* ---------- the planner ---------- */
const H = 3600e3, D = 864e5;
const rome = (iso) => Date.parse(iso);   /* the ISO strings below carry their offset */
{
  const cfg = F.config();
  ok(F.night(rome('2026-10-17T03:00:00+02:00'), cfg) && !F.night(rome('2026-10-17T09:00:00+02:00'), cfg) && F.night(rome('2026-10-17T00:45:00+02:00'), cfg), 'night is 00:30-08:00 in Rome');
  ok(F.romeHour(rome('2026-12-17T21:30:00+01:00')) === 21.5, 'Rome time also in winter (CET)');
  const kick = rome('2026-10-17T20:45:00+02:00');
  ok(F.weight(kick - H, [kick], cfg) === 4 && F.weight(kick - 4 * H, [kick], cfg) === 1 && F.weight(kick + 10 * 60e3, [kick], cfg) === 1, 'the three hours before a kick-off weigh four times');
  const now = rome('2026-10-17T10:00:00+02:00');
  ok(F.plan({ now, st: {}, kicks: [kick] }).pull === true, 'the first wake by day pulls at once');
  ok(F.plan({ now: rome('2026-10-17T03:00:00+02:00'), st: {}, kicks: [kick] }).pull === false, 'never at night');
  const st = { last_pull_at: new Date(now - 10 * 60e3).toISOString(), quota_remaining: 400, quota_reset_at: new Date(now + 20 * D).toISOString(), discovered_at: new Date(now - H).toISOString() };
  ok(F.plan({ now, st, kicks: [kick] }).pull === false, 'not again ten minutes later in an ordinary hour');
  ok(F.plan({ now, st, kicks: [kick], manual: true }).pull === true, '"Update now" pulls whenever three minutes have passed');
  ok(F.plan({ now, st: Object.assign({}, st, { last_pull_at: new Date(now - 60e3).toISOString() }), kicks: [kick], manual: true }).why === 'just-pulled', '… and not twice in a minute');
  ok(F.plan({ now, st: Object.assign({}, st, { quota_remaining: 20 }), kicks: [kick] }).why === 'reserve', 'the last 25 requests are kept for "Update now"');
  ok(F.plan({ now, st: Object.assign({}, st, { quota_remaining: 2 }), kicks: [kick], manual: true }).why === 'quota', 'below 3 left nothing is spent, not even by hand');
  ok(F.plan({ now, st: Object.assign({}, st, { backoff_until: new Date(now + H).toISOString() }), kicks: [kick] }).why === 'backoff', 'after an error the feed waits');
  const reopened = F.plan({ now, st: Object.assign({}, st, { quota_remaining: 0, quota_limit: 500, quota_reset_at: new Date(now - H).toISOString(), last_pull_at: new Date(now - 12 * H).toISOString() }), kicks: [kick] });
  ok(reopened.left === 500 && reopened.pull, 'when the month\'s window has reopened the quota is full again');
  ok(F.plan({ now, st: Object.assign({}, st, { discovered_at: new Date(now - 13 * H).toISOString() }), kicks: [kick] }).discover === true, 'SNAI\'s list is read again after 12 hours');
}
/* a month of wake-ups every 10 minutes: Scudi's usual weeks (weekend afternoons and evenings, two midweek evenings) */
{
  const cfg = F.config(), start = rome('2026-11-02T00:05:00+01:00'), end = start + 30 * D;
  const kicksAll = [];
  for (let d = 0; d < 32; d++) {
    const day = new Date(start + d * D), dow = day.getUTCDay();   /* Rome is UTC+1 in November */
    const at = (h, m) => Date.UTC(day.getUTCFullYear(), day.getUTCMonth(), day.getUTCDate(), h - 1, m);
    if (dow === 6 || dow === 0) for (const [h, m] of [[12, 30], [15, 0], [15, 0], [18, 0], [20, 45]]) kicksAll.push(at(h, m));
    if (dow === 2 || dow === 3) for (const [h, m] of [[18, 45], [21, 0], [21, 0]]) kicksAll.push(at(h, m));
  }
  kicksAll.sort((a, b) => a - b);
  let st = {}, left = 500, used = 0, reset = null;
  const pulls = [];
  for (let t = start; t < end; t += 10 * 60e3) {
    const kicks = kicksAll.filter(k => k > t - H && k <= t + 8 * D);
    const p = F.plan({ now: t, st, cfg, kicks });
    if (!p.pull) continue;
    const cost = p.discover ? 2 : 1;
    if (reset === null) reset = t + 30 * D;
    left -= cost; used += cost;
    pulls.push({ t, kind: p.discover ? 'd' : 'n' });
    st = Object.assign({}, st, { last_pull_at: new Date(t).toISOString(), quota_remaining: left, quota_limit: 500, quota_reset_at: new Date(reset).toISOString(),
      avg_cost: st.avg_cost ? 0.8 * st.avg_cost + 0.2 * cost : cost, discovered_at: p.discover ? new Date(t).toISOString() : st.discovered_at });
  }
  const pre = pulls.filter(p => kicksAll.some(k => k > p.t && k - p.t <= 3 * H)).length;
  ok(Math.abs(F.romeHour(rome('2026-10-25T01:30:00+02:00')) - 1.5) < 1e-9 && Math.abs(F.romeHour(rome('2026-10-25T02:30:00+01:00')) - 2.5) < 1e-9, 'Rome time across the end of summer time');
  const atNight = pulls.filter(p => F.night(p.t, cfg)).length;
  let worst = 0;
  for (const k of kicksAll.filter(k => k > start + 3 * H && k < end)) {   /* the longest wait for fresh prices in the last 3 hours before a kick-off */
    const inWin = pulls.filter(p => p.t > k - 3 * H && p.t <= k).map(p => p.t);
    const marks = [k - 3 * H, ...inWin, k];
    for (let i = 1; i < marks.length; i++) worst = Math.max(worst, marks[i] - marks[i - 1]);
  }
  console.log(`  a simulated month: ${pulls.length} pulls, ${used} requests, ${pre} in the 3 h before a kick-off, longest pre-match gap ${Math.round(worst / 60e3)} min`);
  ok(used <= 500 - cfg.reserve + 2, `the month stays within the quota less the reserve (${used} used)`);
  ok(used >= 380, `most of the month's quota is used, not left idle (${used} used)`);
  ok(atNight === 0, 'no pull at night');
  ok(pre / pulls.length >= 0.45, `pulls gather before kick-offs (${pre} of ${pulls.length})`);
  ok(worst <= 75 * 60e3, `before every kick-off the prices are never older than about an hour (${Math.round(worst / 60e3)} min)`);
}

/* ---------- which events a pull asks for ---------- */
{
  const now = Date.parse('2026-10-17T08:00:00Z'), iso = (h) => new Date(now + h * H).toISOString();
  const rows = [
    { event_id: 'late', commence_time: iso(100), full_at: iso(-20) },
    { event_id: 'lateFresh', commence_time: iso(100), full_at: iso(-2) },
    { event_id: 'soon', commence_time: iso(3), full_at: iso(-0.5) },
    { event_id: 'started', commence_time: iso(-0.5) },
    { event_id: 'tomorrow', commence_time: iso(30), full_at: null },
  ];
  ok(same(F.pickIds(rows, now, {}), ['soon', 'tomorrow', 'late']), 'soonest first; far matches only when their prices are 12 hours old; never a match already started');
  ok(same(F.pickIds(rows, now, {}, true), ['soon', 'tomorrow', 'late', 'lateFresh']), 'Update now asks for every match ahead');
  const many = Array.from({ length: 400 }, (_, i) => ({ event_id: 'e' + i, commence_time: iso(1 + i / 100) }));
  ok(F.pickIds(many, now, {}).length === 150, 'at most 150 ids in one request');
}

/* ---------- requests and answers ---------- */
{
  const u = F.oddsUrl(F.nearParams(['a1', 'b2'], {}));
  ok(u.startsWith('https://odss-api.com/api/v1/odds?') && u.includes('event_id=a1,b2') && u.includes('market=1x2,dc,ou,btts') && u.includes('bookmakers=snai') && u.endsWith('after='), 'the prices request: event ids, four markets, SNAI, first page');
  ok(!/key/i.test(u), 'the key never goes in the address');
  const d = F.oddsUrl(F.discoverParams(Date.parse('2026-10-17T08:00:00Z'), {}));
  ok(d.includes('sport=calcio') && d.includes('market=1x2') && d.includes('commence_from=2026-10-17T08%3A00%3A00.000Z') && d.includes('commence_to=2026-10-25T08%3A00%3A00.000Z') && d.includes('limit=5000'), 'the list request: football, 1X2, the next eight days, 5,000 a page');
  const h = new Headers({ 'X-Quota-Limit': '500', 'X-Quota-Remaining': '431', 'X-Quota-Reset': '86400' });
  const q = F.quotaOf(h, Date.parse('2026-10-17T08:00:00Z'));
  ok(q.quota_limit === 500 && q.quota_remaining === 431 && q.quota_reset_at === '2026-10-18T08:00:00.000Z', 'the quota headers are read');
  ok(F.quotaOf(new Headers({ 'X-RateLimit-Remaining': '12' }), 0).quota_remaining === 12, 'the older header names too');
  ok(F.failure(401, { code: 'auth_invalid' }).status === 'bad-key' && F.failure(429, { code: 'quota_exceeded' }).status === 'quota' && F.failure(429, { code: 'rate_limited' }).wait === 5 * 60e3 && F.failure(502, null).status === 'odss-down', 'errors: bad key, month used up, too fast, odss-api down');
}

console.log(`${checks - failures}/${checks} feed checks passed`);
if (failures) process.exit(1);
