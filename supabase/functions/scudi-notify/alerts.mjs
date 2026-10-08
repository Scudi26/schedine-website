// Scudi · what to tell the phone about the placed slips (decision 95). Pure functions: the Edge Function reads the
// owner's placed slips (synced from the site), ESPN's public scoreboards and SNAI's prices from the private store, and
// these decide what is worth a notification. Every alert has a ref that names the thing it reports (a score, a final
// whistle, a slip); the function sends a ref once only (public.notify_claim), so running every minute is harmless.
// The live maths is the page's own: site.mjs is extracted from index.html (tools/pack_function.py).
import { Scudi, tkey, ALIASES, REG } from './site.mjs';

export const SLUG = {}; REG.forEach((r) => { if (r[2]) SLUG[r[0]] = r[2]; });
const ROME_ISO = new Intl.DateTimeFormat('en-CA', { timeZone: 'Europe/Rome', year: 'numeric', month: '2-digit', day: '2-digit' });
const ROME_HM = new Intl.DateTimeFormat('en-GB', { timeZone: 'Europe/Rome', hour: '2-digit', minute: '2-digit', hour12: false });
const ROME_DAY = { en: new Intl.DateTimeFormat('en-GB', { timeZone: 'Europe/Rome', weekday: 'short' }), it: new Intl.DateTimeFormat('it-IT', { timeZone: 'Europe/Rome', weekday: 'short' }) };
export const AHEAD = 75 * 6e4;          /* a match is followed from 75 minutes before its kick-off (the line-ups) */
export const AFTER = 12 * 36e5;         /* … and a slip until 12 hours after its last kick-off */
export const DEFAULTS = { on: true, lineups: true, goals: true, cards: true, results: true, hedge: true };

export function espnDate(t) { return ROME_ISO.format(new Date(t)).replace(/-/g, ''); }
const kickOf = (l) => new Date(l.kick).getTime();
/* the slips worth a look now: not settled (or settled in the last 6 hours on a device), with a leg starting within 75
   minutes or already started, and the last kick-off less than 12 hours ago */
export function watched(placed, now) {
  return (Array.isArray(placed) ? placed : []).filter((p) => p && Array.isArray(p.legs) && p.legs.length && p.id != null &&
    (!p.settled || now - Date.parse(p.settledAt || 0) < 6 * 36e5) &&
    p.legs.some((l) => kickOf(l) - now < AHEAD) && now - Math.max(...p.legs.map(kickOf)) < AFTER);
}
/* the ESPN scoreboards to read: [slug, YYYYMMDD] for every leg already started or about to, not known finished (memo) */
export function boards(slips, now, memo) {
  const out = {};
  for (const p of slips) p.legs.forEach((l, i) => {
    const s = SLUG[l.lg], k = kickOf(l);
    if (!s || k - now >= AHEAD || (memo && memo[legKey(p, i)])) return;
    out[s + '|' + espnDate(k)] = [s, espnDate(k)];
  });
  return Object.values(out);
}
export const legKey = (p, i) => p.id + ':' + i;

/* the page's own matching of a leg to an ESPN event: team ids when the leg has them, else names (with the aliases), and a
   kick-off within six hours */
export function eventFor(leg, events) {
  const ak = (x) => { const t = tkey(x); return ALIASES[t] || t; };
  const kick = kickOf(leg), hk = ak(leg.home), awk = ak(leg.away);
  return (events || []).find((ev) => {
    const c = ((ev.competitions || [])[0] || {}).competitors || [], ids = c.map((x) => String((x.team || {}).id)), nm = c.map((x) => ak((x.team || {}).displayName || ''));
    const byId = leg.th != null && leg.ta != null && ids.includes(String(leg.th)) && ids.includes(String(leg.ta));
    const byName = nm.some((n) => n && (n.includes(hk) || hk.includes(n))) && nm.some((n) => n && (n.includes(awk) || awk.includes(n)));
    return (byId || byName) && Math.abs(new Date(ev.date).getTime() - kick) < 36e5 * 6;
  });
}
const evId = (ev) => String(ev.id || (ev.date + ' ' + (ev.name || ''))).replace(/[^0-9A-Za-z:._-]/g, '').slice(0, 60);

/* every leg of the watched slips, now: its ESPN event and state (or the memo's final score), its live chance */
export function legStates(slips, events, now, memo) {
  const out = [];
  for (const p of slips) p.legs.forEach((l, i) => {
    const m = memo && memo[legKey(p, i)];
    let ev = null, st;
    if (m) st = { state: 'post', h: m.h, a: m.a, hh: m.hh, ha: m.ha, minute: 90 };
    else { ev = eventFor(l, events) || null; st = Scudi.espnState(l, ev, now); }
    out.push({ slip: p, i, leg: l, ev, eid: ev ? evId(ev) : m ? m.eid : null, st, live: Scudi.legLive(l, st) });
  });
  return out;
}
/* final scores to remember (a leg decided needs no more reading): { slipId:i → { eid, h, a, hh, ha, at } } */
export function memoOf(states, memo, now) {
  const out = {};
  for (const [k, v] of Object.entries(memo || {})) if (now - (v.at || 0) < 10 * 864e5) out[k] = v;
  for (const s of states) if (s.st.state === 'post' && s.live.done && !out[legKey(s.slip, s.i)])
    out[legKey(s.slip, s.i)] = { eid: s.eid, h: s.st.h, a: s.st.a, hh: s.st.hh, ha: s.st.ha, at: now };
  return out;
}
/* the matches whose line-ups to look for: kick-off within 70 minutes, not started, not reported yet */
export function lineupsWanted(states, now, sent, prefs) {
  if (!prefs.lineups) return [];
  const out = {};
  for (const s of states) {
    const k = kickOf(s.leg);
    if (!s.ev || s.st.state !== 'pre' || k - now > 70 * 6e4 || k < now - 5 * 6e4 || sent.has('lu:' + s.eid)) continue;
    out[s.eid] = { eid: s.eid, id: String(s.ev.id || ''), slug: SLUG[s.leg.lg] };
  }
  return Object.values(out).filter((x) => x.id && x.slug);
}

/* ---------- words ---------- */
const W = {
  en: {
    goal: 'Goal', red: 'Red card', ht: 'Half time', ft: 'Full time', lu: 'Line-ups', left: 'One leg left', landed: 'It landed!',
    winning: 'winning', losing: 'losing', won: 'won', lost: 'lost', slipNow: (n, p) => `${n}: now ${p}`, out: (n) => `${n} is out.`,
    tally: (n, w, t) => `${n}: ${w} of ${t} won`, toPlay: (k) => `${k} to play`, more: (k) => `and ${k} more`,
    pays: (n, e) => `${n} pays ${e}.`, kick: (t) => `kick-off ${t}`, ifLands: (e) => `It pays ${e} if it lands.`,
    cover: (h, c, q, e, pr) => `Cover it: ${h} on ${c} at SNAI's ${q} → ${e} whatever happens (${pr}).`,
    coverLive: 'Open Scudi and type SNAI\'s live price to work out the hedge.', notStarting: (x) => `Not starting from the last XI: ${x}.`,
    redFor: (t) => `${t} down to ten`, profit: (v, e) => v >= 0 ? `${e} profit locked` : `${e} lost whatever happens`, test: 'Scudi notifications work on this device.', testT: 'Scudi',
  },
  it: {
    goal: 'Gol', red: 'Espulsione', ht: 'Fine primo tempo', ft: 'Finale', lu: 'Formazioni', left: 'Manca un evento', landed: 'È entrata!',
    winning: 'in vantaggio', losing: 'in svantaggio', won: 'vinto', lost: 'perso', slipNow: (n, p) => `${n}: ora ${p}`, out: (n) => `${n} è persa.`,
    tally: (n, w, t) => `${n}: ${w} su ${t} vinti`, toPlay: (k) => `${k} da giocare`, more: (k) => `e altre ${k}`,
    pays: (n, e) => `${n} paga ${e}.`, kick: (t) => `inizio ${t}`, ifLands: (e) => `Se entra paga ${e}.`,
    cover: (h, c, q, e, pr) => `Copertura: ${h} su ${c} a ${q} su SNAI → ${e} comunque vada (${pr}).`,
    coverLive: 'Apri Scudi e scrivi la quota live di SNAI per calcolare la copertura.', notStarting: (x) => `Fuori dall'ultimo undici: ${x}.`,
    redFor: (t) => `${t} in dieci`, profit: (v, e) => v >= 0 ? `guadagno sicuro ${e}` : `${e} persi comunque vada`, test: 'Le notifiche di Scudi funzionano su questo dispositivo.', testT: 'Scudi',
  },
};
export function words(lang) { return W[lang === 'it' ? 'it' : 'en']; }
export function euro(v, lang) { const s = (Math.round(v * 100) / 100).toFixed(2); return lang === 'it' ? s.replace('.', ',') + ' €' : '€' + s; }
export function pct(p) { return p >= 0.9995 ? '100%' : p <= 0 ? '0%' : p >= 0.1 ? Math.round(p * 100) + '%' : p >= 0.01 ? (p * 100).toFixed(1) + '%' : '1 in ' + Math.round(1 / p).toLocaleString('en-GB'); }
const LINE = (c) => c.replace(/^(\d)(\d)$/, '$1.$2');
/* a pick's short name, as SNAI's coupon shows it */
export function pickName(code, lang) {
  const it = lang === 'it', c = String(code || '');
  let m;
  if (/^(1|X|2|1X|X2|12)$/.test(c)) return c;
  if ((m = /^([OU])(\d\d)$/.exec(c))) return (m[1] === 'O' ? 'Over ' : 'Under ') + LINE(m[2]);
  if (c === 'GG') return it ? 'Goal' : 'Both score';
  if (c === 'NG') return it ? 'No goal' : 'Not both score';
  if ((m = /^MG(\d-\d)$/.exec(c))) return 'Multigol ' + m[1];
  if ((m = /^([HA])([OU])(\d\d)$/.exec(c))) return (m[1] === 'H' ? (it ? 'Casa ' : 'Home ') : (it ? 'Ospite ' : 'Away ')) + (m[2] === 'O' ? 'over ' : 'under ') + LINE(m[3]);
  if ((m = /^1T(.+)$/.exec(c))) return pickName(m[1], lang) + (it ? ' 1° tempo' : ' 1st half');
  return c;
}
/* the single SNAI market that wins exactly when the pick loses (the hedge), or null */
const COMP = { '1': 'X2', 'X': '12', '2': '1X', '1X': '2', 'X2': '1', '12': 'X', GG: 'NG', NG: 'GG' };
export function complement(code) {
  const c = String(code || ''); let m;
  if (COMP[c]) return COMP[c];
  if ((m = /^([HA]?)([OU])(\d5)$/.exec(c))) return m[1] + (m[2] === 'O' ? 'U' : 'O') + m[3];
  if ((m = /^1T(.+)$/.exec(c)) && complement(m[1])) return '1T' + complement(m[1]);
  return null;
}
/* SNAI's price for a pick from the private store's codes (book_events.m), or null */
export function snaiPrice(code, m) {
  const c = String(code || ''), list = Array.isArray(m) ? m : [];
  const find = (mk, ln, oc) => { const x = list.find((y) => y[0] === mk && (ln == null || y[1] === ln) && y[2] === oc); return x && x[3] > 1 ? x[3] : null; };
  const one = { '1': 1, 'X': 2, '2': 3 }[c]; if (one) return find(3, null, one);
  const dc = { '1X': 1, '12': 2, 'X2': 3 }[c]; if (dc) return find(28319, null, dc);
  if (c === 'GG' || c === 'NG') return find(18, null, c === 'GG' ? 1 : 2);
  const ou = /^([OU])(\d)5$/.exec(c); if (ou) return find(7989, +ou[2] * 100 + 50, ou[1] === 'U' ? 1 : 2);
  return null;
}
/* the hedge for one leg left: payout P (stake × pays), stake S, the complement's price q → full cover H = P / q pays P
   either way; locked = P − S − H. Break-even cover B = S / (q − 1): back what was staked if the leg loses. */
export function hedge(P, S, q) {
  if (!(P > 0) || !(q > 1)) return null;
  const H = P / q, B = q > 1 ? S / (q - 1) : null;
  return { H, locked: P - S - H, B, ifWins: B != null ? P - S - B : null };
}

/* ---------- the alerts ---------- */
const nameOf = (p) => '“' + String(p.name || 'Slip').slice(0, 40) + '”';
function slipLine(p, all, w, lang) {
  const mine = all.filter((s) => s.slip === p), chance = mine.reduce((a, s) => a * s.live.p, 1);
  const done = mine.filter((s) => s.live.done), lost = done.some((s) => s.live.p === 0);
  if (lost) return w.out(nameOf(p));
  if (done.length === mine.length) return w.pays(nameOf(p), euro(p.stake * p.pays, lang));
  return w.slipNow(nameOf(p), pct(chance));
}
function scoreLine(ev, s) {
  const c = ((ev.competitions || [])[0] || {}).competitors || [], h = c.find((x) => x.homeAway === 'home') || {}, a = c.find((x) => x.homeAway === 'away') || {};
  return { text: `${(h.team || {}).displayName || s.leg.home} ${+h.score || 0}–${+a.score || 0} ${(a.team || {}).displayName || s.leg.away}`, H: +h.score || 0, A: +a.score || 0 };
}
function lastPlay(ev, pred) {
  const d = (((ev.competitions || [])[0] || {}).details || []).filter(pred);
  const x = d[d.length - 1]; if (!x) return null;
  const who = ((x.athletesInvolved || [])[0] || {});
  return { minute: (x.clock || {}).displayValue || '', who: who.shortName || who.displayName || '', team: String((x.team || {}).id || '') };
}
function lines(arr, w, max) { const k = arr.length - (max || 3); return (k > 0 ? arr.slice(0, max || 3).concat([w.more(k)]) : arr).join('\n'); }

/* ctx: { now, lang, prefs, site, sent: Set, states (legStates), summaries: { eid: ESPN summary }, teams: { id: team } | null,
   prices: { matchId: m codes } } → [{ ref, title, body, url, ttl, urgency }] */
export function alerts(ctx) {
  const { now, states } = ctx, lang = ctx.lang === 'it' ? 'it' : 'en', w = words(lang), prefs = Object.assign({}, DEFAULTS, ctx.prefs || {});
  const sent = ctx.sent || new Set(), out = [], url = (ctx.site || './') + '#live';
  const add = (a) => { if (!sent.has(a.ref) && !out.some((x) => x.ref === a.ref)) out.push(Object.assign({ url, ttl: 1800, urgency: 'high' }, a)); };
  if (!prefs.on) return out;
  const byEv = {};
  for (const s of states) if (s.ev) (byEv[s.eid] = byEv[s.eid] || []).push(s);
  const slipsOf = (list) => [...new Set(list.map((s) => s.slip))];

  for (const [eid, list] of Object.entries(byEv)) {
    const s0 = list[0], ev = s0.ev, st = s0.st, sc = scoreLine(ev, s0);
    const recent = now - kickOf(s0.leg) < 4 * 36e5;
    /* a goal, while the match is on: one alert per score (a goal ruled out afterwards is not reported) */
    if (prefs.goals && st.state === 'in' && sc.H + sc.A > 0) {
      const g = lastPlay(ev, (d) => d.scoringPlay && !d.shootout);
      const legs = list.map((s) => `${pickName(s.leg.code, lang)} ${s.live.now === true ? w.winning : s.live.now === false ? w.losing : ''}`.trim());
      add({ ref: `goal:${eid}:${sc.H}-${sc.A}`, title: `${w.goal}${g && g.minute ? ' ' + g.minute : ''} · ${sc.text}`,
        body: (g && g.who ? g.who + '\n' : '') + lines([...new Set(legs)].concat(slipsOf(list).map((p) => slipLine(p, states, w, lang))), w, 4), topic: 'g' + eid });
    }
    /* a red card */
    const reds = (st.rh || 0) + (st.ra || 0);
    if (prefs.cards && st.state === 'in' && reds > 0) {
      const r = lastPlay(ev, (d) => d.redCard), c = ((ev.competitions || [])[0] || {}).competitors || [];
      const team = r && (c.find((x) => String((x.team || {}).id) === r.team) || {}).team;
      add({ ref: `red:${eid}:${reds}`, title: `${w.red}${r && r.minute ? ' ' + r.minute : ''} · ${sc.text}`,
        body: lines((team ? [w.redFor(team.displayName) + (r.who ? ` (${r.who})` : '')] : []).concat(slipsOf(list).map((p) => slipLine(p, states, w, lang))), w, 4) });
    }
    /* half time, for first-half picks */
    const halves = list.filter((s) => Scudi.BY_ID[s.leg.code] && Scudi.BY_ID[s.leg.code].half && s.live.done);
    if (prefs.results && halves.length && recent && st.hh != null) {
      add({ ref: `ht:${eid}`, title: `${w.ht} · ${s0.leg.home} ${st.hh}–${st.ha} ${s0.leg.away}`, ttl: 3 * 3600, urgency: 'normal',
        body: lines(halves.map((s) => `${pickName(s.leg.code, lang)} ${s.live.p === 1 ? '✓ ' + w.won : '✗ ' + w.lost}`).concat(slipsOf(halves).map((p) => slipLine(p, states, w, lang))), w, 4) });
    }
    /* full time */
    const full = list.filter((s) => !(Scudi.BY_ID[s.leg.code] && Scudi.BY_ID[s.leg.code].half));
    if (prefs.results && full.length && st.state === 'post' && recent) {
      add({ ref: `ft:${eid}`, title: `${w.ft} · ${sc.text}`, ttl: 6 * 3600, urgency: 'normal',
        body: lines([...new Set(full.map((s) => `${pickName(s.leg.code, lang)} ${s.live.p === 1 ? '✓ ' + w.won : '✗ ' + w.lost}`))].concat(slipsOf(full).map((p) => {
          const mine = states.filter((x) => x.slip === p), won = mine.filter((x) => x.live.done && x.live.p === 1).length, left = mine.filter((x) => !x.live.done).length;
          return mine.some((x) => x.live.done && x.live.p === 0) ? w.out(nameOf(p)) : left ? w.tally(nameOf(p), won, mine.length) + ', ' + w.toPlay(left) : w.pays(nameOf(p), euro(p.stake * p.pays, lang));
        })), w, 4) });
    }
  }

  /* per slip: landed; one leg left (the hedge) */
  for (const p of [...new Set(states.map((s) => s.slip))]) {
    const mine = states.filter((s) => s.slip === p), done = mine.filter((s) => s.live.done), lost = done.some((s) => s.live.p === 0);
    if (prefs.results && !lost && done.length === mine.length && now - Math.max(...p.legs.map(kickOf)) < 6 * 36e5)
      add({ ref: `land:${p.id}`, title: `${w.landed} ${nameOf(p)}`, body: w.pays(nameOf(p), euro(p.stake * p.pays, lang)), ttl: 86400, urgency: 'normal' });
    const left = mine.filter((s) => !s.live.done);
    if (prefs.hedge && !p.settled && !lost && mine.length > 1 && left.length === 1 && done.length === mine.length - 1 && left[0].st.state !== 'post') {
      const L = left[0], P = p.stake * p.pays, comp = complement(L.leg.code);
      const q = comp && L.st.state === 'pre' && ctx.prices ? snaiPrice(comp, ctx.prices[L.leg.mid]) : null, hg = q ? hedge(P, p.stake, q) : null;
      const k = kickOf(L.leg), when = L.st.state === 'pre' ? ' · ' + w.kick((now - k > -20 * 3600e3 ? '' : ROME_DAY[lang].format(new Date(k)) + ' ') + ROME_HM.format(new Date(k))) : '';
      const body = [`${L.leg.home} – ${L.leg.away}: ${pickName(L.leg.code, lang)}${when}`, w.ifLands(euro(P, lang))];
      if (hg) body.push(w.cover(euro(hg.H, lang), pickName(comp, lang), q.toFixed(2), euro(P, lang), w.profit(hg.locked, euro(Math.abs(hg.locked), lang))));
      else if (comp) body.push(w.coverLive);
      add({ ref: `hedge:${p.id}`, title: `${w.left} · ${nameOf(p)}`, body: body.join('\n'), ttl: 6 * 3600, urgency: 'normal' });
    }
  }

  /* line-ups (the caller read ESPN's summary for the matches lineupsWanted named) */
  for (const [eid, sum] of Object.entries(ctx.summaries || {})) {
    const list = byEv[eid]; if (!list || !sum) continue;
    const ros = (sum.rosters || []).filter((r) => (r.roster || []).filter((x) => x.starter).length >= 11);
    if (ros.length < 2) continue;
    const s0 = list[0], k = kickOf(s0.leg), body = [];
    const missing = [];
    for (const r of ros) {
      const t = ctx.teams && ctx.teams[String((r.team || {}).id)], xi = new Set((r.roster || []).filter((x) => x.starter).map((x) => String((x.athlete || {}).id)));
      if (t && t.last && Array.isArray(t.last.xi) && Array.isArray(t.players)) {
        const names = {}; t.players.forEach((pl) => { names[String(pl.id)] = pl.short || pl.name; });
        t.last.xi.forEach((e) => { if (!xi.has(String(e.id)) && names[String(e.id)]) missing.push(names[String(e.id)]); });
      }
    }
    if (missing.length) body.push(w.notStarting(missing.slice(0, 6).join(', ') + (missing.length > 6 ? '…' : '')));
    for (const r of ros) body.push(`${(r.team || {}).displayName || (r.homeAway === 'home' ? s0.leg.home : s0.leg.away)}: ` +
      (r.roster || []).filter((x) => x.starter).map((x) => { const a = x.athlete || {}; return a.lastName || String(a.shortName || a.displayName || '').replace(/^\S+\.\s*/, ''); }).join(', '));
    add({ ref: `lu:${eid}`, title: `${w.lu} · ${s0.leg.home} – ${s0.leg.away} (${ROME_HM.format(new Date(k))})`, body: body.join('\n'), ttl: 3600, urgency: 'normal',
      url: (ctx.site || './') + '#matches' });
  }
  return out;
}
