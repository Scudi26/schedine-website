// Scudi · notifications on the phone (decision 95) — the scudi-notify Edge Function.
// Woken every minute by pg_cron (header x-cron-token, the same random value the price feed uses, living only in the
// database). It reads the owner's placed slips (synced from the site into public.user_state), ESPN's public scoreboards
// for the matches on them, and sends what is new (a goal, a red card, a final whistle, a slip landed, one leg left with
// the hedge, the line-ups) to the owner's devices with Web Push. Most wakes spend nothing: no slip on, no reading.
// Called by the site (the owner's sign-in): { action: 'key' } gives the public key a device subscribes with (the pair is
// made on the first call and stays in the database), { action: 'test' } sends a test to every device.
// Deploy with verify_jwt = false: the function checks its callers itself.
import { request, outcome, newKeys } from './push.mjs';
import { watched, boards, legStates, memoOf, lineupsWanted, alerts, words, DEFAULTS } from './alerts.mjs';

const SUPA = Deno.env.get('SUPABASE_URL') ?? '';
const KEY = (() => {
  try { const k = JSON.parse(Deno.env.get('SUPABASE_SECRET_KEYS') ?? '{}'); if (k && k.default) return String(k.default); } catch (_) { /* legacy project */ }
  return Deno.env.get('SUPABASE_SERVICE_ROLE_KEY') ?? '';
})();
const SITE = Deno.env.get('SCUDI_SITE_URL') || 'https://scudi26.github.io/schedine-website/';   // overridden only by the local tests
const ESPN = Deno.env.get('ESPN_BASE_URL') || 'https://site.web.api.espn.com/apis/site/v2/sports/soccer';   // idem
const CORS = {
  'Access-Control-Allow-Origin': Deno.env.get('SCUDI_ORIGIN') || 'https://scudi26.github.io',
  'Access-Control-Allow-Headers': 'authorization, apikey, content-type, x-client-info',
  'Access-Control-Allow-Methods': 'POST, OPTIONS',
  'Vary': 'Origin',
};

function json(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status, headers: { ...CORS, 'Content-Type': 'application/json' } });
}
function dbHeaders() {
  const h: Record<string, string> = { apikey: KEY, 'Content-Type': 'application/json' };
  if (!KEY.startsWith('sb_')) h.Authorization = `Bearer ${KEY}`;   // a legacy service_role key is a JWT
  return h;
}
async function rpc(name: string, args: Record<string, unknown>) {
  const r = await fetch(`${SUPA}/rest/v1/rpc/${name}`, { method: 'POST', headers: dbHeaders(), body: JSON.stringify(args) });
  if (!r.ok) throw new Error(`db ${name}: ${r.status} ${(await r.text()).slice(0, 200)}`);
  const t = await r.text();
  return t ? JSON.parse(t) : null;
}
async function select(path: string) {
  const r = await fetch(`${SUPA}/rest/v1/${path}`, { headers: dbHeaders() });
  if (!r.ok) throw new Error(`db select: ${r.status} ${(await r.text()).slice(0, 200)}`);
  return await r.json();
}
/* the site's calls: the caller must be signed in as the project's owner */
async function ownerOf(auth: string | null) {
  if (!auth || !/^Bearer\s+\S+/.test(auth)) return null;
  const r = await fetch(`${SUPA}/auth/v1/user`, { headers: { apikey: KEY, Authorization: auth } });
  if (!r.ok) return null;
  const u = await r.json();
  if (!u || !u.id) return null;
  const rows = await select(`owners?select=user_id&user_id=eq.${encodeURIComponent(u.id)}`);
  return rows.length ? u.id : null;
}
async function getJson(url: string, ms = 12000) {
  try {
    const r = await fetch(url, { headers: { Accept: 'application/json' }, signal: AbortSignal.timeout(ms) });
    return r.ok ? await r.json() : null;
  } catch (_) { return null; }
}
/* the VAPID pair: made and stored on the first use (a pair stored meanwhile by another wake wins), the same ever after */
async function keysOf(load: any) {
  if (load.keys && load.keys.public_key) return load.keys;
  const k = await newKeys();
  load.keys = await rpc('notify_keys_init', { pub: k.public_key, priv: k.private_jwk });
  return load.keys;
}
/* every device, one message each; the outcome goes back to the database (a device gone is removed) */
async function deliver(load: any, keys: any, msgs: any[]) {
  let ok = 0, failed = 0;
  for (const s of load.subs || []) for (const m of msgs) {
    let status = 0;
    try {
      const req = await request(s, { title: m.title, body: m.body, url: m.url, tag: m.ref }, keys, { ttl: m.ttl, urgency: m.urgency, topic: m.topic });
      const r = await fetch(req.url, { ...req.init, signal: AbortSignal.timeout(10000) });
      status = r.status; await r.body?.cancel();
    } catch (_) { status = 0; }
    const o = outcome(status);
    if (o === 'ok') ok++; else failed++;
    await rpc('notify_result', { sub_id: s.id, ok: o === 'ok', gone: o === 'gone' }).catch(() => {});
    if (o === 'gone') break;
  }
  return { ok, failed };
}

async function run(load: any, now: number) {
  const st = load.state || {}, prefs = Object.assign({}, DEFAULTS, st['scudi-notify'] || {});
  const lang = prefs.lang === 'it' || (!prefs.lang && st['scudi-lang'] === 'it') ? 'it' : 'en';
  if (!prefs.on) return { slips: 0, why: 'off' };
  if (!(load.subs || []).length) return { slips: 0, why: 'no-device' };
  const slips = watched(st['scudi-placed'], now);
  if (!slips.length) return { slips: 0, why: 'nothing-on' };
  const memo = (load.memo && typeof load.memo === 'object') ? load.memo : {};
  /* 1. ESPN's scoreboards for the legs started or about to start */
  const pairs = boards(slips, now, memo), events: any[] = [];
  const lists = await Promise.all(pairs.map(([s, d]) => getJson(`${ESPN}/${s}/scoreboard?dates=${d}`)));
  lists.forEach((j) => { if (j && Array.isArray(j.events)) events.push(...j.events); });
  const states = legStates(slips, events, now, memo);
  const sent = new Set<string>(load.sent || []);
  /* 2. the line-ups, for the matches starting within 70 minutes (ESPN's match page; the team data for "not starting") */
  const wantLu = lineupsWanted(states, now, sent, prefs), summaries: Record<string, any> = {};
  let teams: any = null;
  if (wantLu.length) {
    const sums = await Promise.all(wantLu.map((x) => getJson(`${ESPN}/${x.slug}/summary?event=${encodeURIComponent(x.id)}`)));
    wantLu.forEach((x, i) => { if (sums[i]) summaries[x.eid] = sums[i]; });
    if (Object.values(summaries).some((s: any) => (s.rosters || []).some((r: any) => (r.roster || []).some((p: any) => p.starter)))) {
      const t = await getJson(new URL('data/teams.json', SITE).href, 20000);
      teams = t && t.teams ? t.teams : null;
    }
  }
  /* 3. SNAI's prices for the one-leg-left hedge (the private store; the price before kick-off) */
  const prices: Record<string, any> = {};
  const mids = [...new Set(states.map((s) => s.leg.mid).filter(Boolean))].slice(0, 60);
  if (mids.length) {
    try {
      const rows = await select(`book_events?select=match_id,m&book=eq.snai&match_id=in.(${mids.map((m) => '"' + String(m).replace(/["\\,()]/g, '') + '"').join(',')})`);
      for (const r of rows || []) if (r.match_id && Array.isArray(r.m)) prices[r.match_id] = r.m;
    } catch (_) { /* no prices: the hedge alert asks for SNAI's live price instead */ }
  }
  const list = alerts({ now, lang, prefs, site: SITE, sent, states, summaries, teams, prices });
  /* 4. claim what is new (two wakes never send the same alert twice), send it, remember the final scores */
  let res = { ok: 0, failed: 0 }, claimed: string[] = [];
  if (list.length) {
    claimed = await rpc('notify_claim', { uid: load.owner, items: list.map((a) => ({ ref: a.ref, title: a.title, body: a.body })) }) || [];
    const fresh = list.filter((a) => claimed.includes(a.ref)).slice(0, 8);
    if (fresh.length) res = await deliver(load, await keysOf(load), fresh);
  }
  const memo2 = memoOf(states, memo, now);
  if (JSON.stringify(memo2) !== JSON.stringify(memo)) await rpc('notify_memo_save', { memo: memo2 }).catch(() => {});
  return { slips: slips.length, boards: pairs.length, events: events.length, alerts: list.length, sent: claimed.length, delivered: res.ok, failed: res.failed };
}

Deno.serve(async (req) => {
  if (req.method === 'OPTIONS') return new Response(null, { headers: CORS });
  if (req.method !== 'POST') return json({ error: 'POST only' }, 405);
  const now = Date.now();
  try {
    const cron = req.headers.get('x-cron-token');
    const load = await rpc('notify_load', { cron });
    if (cron) {
      if (!load || !load.cron_ok) return json({ error: 'bad token' }, 401);
      if (!load.owner) return json({ ok: true, why: 'no-owner' });
      return json({ ok: true, ...(await run(load, now)) });
    }
    const uid = await ownerOf(req.headers.get('authorization'));
    if (!uid || uid !== load.owner) return json({ error: 'owner only' }, 401);
    const body = await req.json().catch(() => ({}));
    if (body.action === 'key') {
      const k = await keysOf(load);
      return json({ ok: true, key: k.public_key, devices: (load.subs || []).length });
    }
    if (body.action === 'test') {
      if (!(load.subs || []).length) return json({ ok: false, why: 'no-device', devices: 0 });
      const st = load.state || {}, p = st['scudi-notify'] || {}, w = words(p.lang === 'it' || (!p.lang && st['scudi-lang'] === 'it') ? 'it' : 'en');
      const res = await deliver(load, await keysOf(load), [{ ref: 'test:' + now, title: w.testT, body: w.test, url: SITE + '#today', ttl: 600, urgency: 'high' }]);
      return json({ ok: res.ok > 0, devices: (load.subs || []).length, delivered: res.ok, failed: res.failed });
    }
    return json({ error: 'unknown action' }, 400);
  } catch (e) {
    return json({ error: String(e).slice(0, 300) }, 500);
  }
});
