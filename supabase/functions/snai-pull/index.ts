// Scudi · automatic SNAI prices (decision 92) — the snai-pull Edge Function.
// Woken every 10 minutes by pg_cron (header x-cron-token, a random value that lives only in the database), or by the
// site's "Update now" (the owner's sign-in). It decides with logic.mjs whether to spend odss-api requests now, pulls
// SNAI's prices for Scudi's matches, and stores them in SNAI's own codes in public.book_events, readable only by the
// owner. The odss-api key is read from the function's secrets (ODSS_API_KEY) and is never stored or returned.
// Deploy with verify_jwt = false: the function checks its callers itself (the new secret keys are not JWTs).
import {
  config, plan, pickIds, eventsOf, selectEvents, snaiOf, mergeCodes, oddsUrl, discoverParams, nearParams, quotaOf, failure,
} from './logic.mjs';

const SUPA = Deno.env.get('SUPABASE_URL') ?? '';
const KEY = (() => {
  try { const k = JSON.parse(Deno.env.get('SUPABASE_SECRET_KEYS') ?? '{}'); if (k && k.default) return String(k.default); } catch (_) { /* legacy project */ }
  return Deno.env.get('SUPABASE_SERVICE_ROLE_KEY') ?? '';
})();
const ODSS_KEY = Deno.env.get('ODSS_API_KEY') ?? '';
const SITE = Deno.env.get('SCUDI_SITE_URL') || 'https://scudi26.github.io/schedine-website/';   // overridden only by the local tests
const ODSS_BASE = Deno.env.get('ODSS_BASE_URL') || undefined;                                       // idem
const CORS = {
  'Access-Control-Allow-Origin': 'https://scudi26.github.io',
  'Access-Control-Allow-Headers': 'authorization, apikey, content-type, x-client-info',
  'Access-Control-Allow-Methods': 'POST, OPTIONS',
  'Vary': 'Origin',
};
const MARKETS = ['1x2', 'dc', 'ou', 'btts'];

function json(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status, headers: { ...CORS, 'Content-Type': 'application/json' } });
}
function dbHeaders(extra: Record<string, string> = {}) {
  const h: Record<string, string> = { apikey: KEY, 'Content-Type': 'application/json', ...extra };
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
/* "Update now": the caller must be signed in as the project's owner */
async function ownerOf(auth: string | null) {
  if (!auth || !/^Bearer\s+\S+/.test(auth)) return null;
  const r = await fetch(`${SUPA}/auth/v1/user`, { headers: { apikey: KEY, Authorization: auth } });
  if (!r.ok) return null;
  const u = await r.json();
  if (!u || !u.id) return null;
  const rows = await select(`owners?select=user_id&user_id=eq.${encodeURIComponent(u.id)}`);
  return rows.length ? u.id : null;
}

/* one odss-api request, page by page; the key goes in the header, never in the address */
async function pull(params: Record<string, unknown>, maxPages: number) {
  const out = { records: [] as any[], requests: 0, quota: {} as Record<string, unknown>, complete: false, error: null as null | ReturnType<typeof failure> & { msg?: string } };
  let after = '';
  for (let page = 0; page < maxPages; page++) {
    const url = oddsUrl({ ...params, after }, ODSS_BASE);
    let r: Response;
    try { r = await fetch(url, { headers: { 'x-api-key': ODSS_KEY, Accept: 'application/json' }, signal: AbortSignal.timeout(25000) }); }
    catch (e) { out.error = { ...failure(0, null), msg: String(e).slice(0, 200) }; break; }
    out.requests++;
    Object.assign(out.quota, quotaOf(r.headers, Date.now()));
    let body: any = null;
    try { body = await r.json(); } catch (_) { body = null; }
    if (!r.ok || !body) { out.error = { ...failure(r.status, body), msg: body && body.error ? String(body.error).slice(0, 200) : `HTTP ${r.status}` }; break; }
    out.records.push(...(body.odds || []));
    if (!body.next_after) { out.complete = true; break; }
    after = String(body.next_after);
  }
  return out;
}

Deno.serve(async (req) => {
  if (req.method === 'OPTIONS') return new Response(null, { headers: CORS });
  if (req.method !== 'POST') return json({ error: 'POST only' }, 405);
  if (!SUPA || !KEY) return json({ error: 'the function has no database key' }, 500);
  const t0 = Date.now(), now = t0, nowIso = new Date(now).toISOString();
  const cron = req.headers.get('x-cron-token');
  const loaded = await rpc('feed_load', { cron: cron || null });
  let manual = false;
  if (cron) { if (!loaded || !loaded.cron_ok) return json({ error: 'forbidden' }, 403); }
  else { if (!(await ownerOf(req.headers.get('authorization')))) return json({ error: 'sign in as the owner' }, 401); manual = true; }

  const cfg = config(loaded.settings), st = loaded.state || {}, book = cfg.books[0] || 'snai';
  const rows: any[] = await select(`book_events?select=event_id,home,away,league,commence_time,m,odds_at,full_at,match_id&book=eq.${encodeURIComponent(book)}&commence_time=gt.${encodeURIComponent(new Date(now - 3 * 3600e3).toISOString())}`);
  const kicks = rows.map(r => Date.parse(r.commence_time)).filter(Number.isFinite).sort((a, b) => a - b);
  const p = plan({ now, st, cfg, kicks, manual });
  if (!ODSS_KEY) {
    await rpc('feed_tick', { p: { checked_at: nowIso, last_status: 'no-key', why: 'no-key' } });
    return json({ pulled: false, why: 'no-key' });
  }
  if (!p.pull) {
    await rpc('feed_tick', { p: { checked_at: nowIso, why: p.why, next_at: p.next ? new Date(p.next).toISOString() : null } });
    return json({ pulled: false, why: p.why, left: p.left, next: p.next ? new Date(p.next).toISOString() : null });
  }
  if (!(await rpc('feed_claim', {}))) return json({ pulled: false, why: 'busy' });

  const unknown: Record<string, number> = {}, updates = new Map<string, any>(), drop: string[] = [];
  const byId = new Map(rows.map(r => [r.event_id, r]));
  let requests = 0, records = 0, err: any = null, note: string | null = null, quota: Record<string, unknown> = {}, discovered = false, sel: any = null;
  const discover = p.discover || !rows.length;
  try {
    /* 1. SNAI's whole football list for the days ahead, 1X2 only (one request): which of its events are Scudi's matches */
    if (discover) {
      const week = await fetch(`${SITE}data/week.json`, { cache: 'no-store', signal: AbortSignal.timeout(20000) }).then(r => r.ok ? r.json() : null).catch(() => null);
      const res = await pull(discoverParams(now, cfg), cfg.maxPages);
      requests += res.requests; records += res.records.length; Object.assign(quota, res.quota);
      if (res.error) err = res.error;
      else if (week && Array.isArray(week.matches)) {
        sel = selectEvents(eventsOf(res.records), week.matches, now, cfg);
        const codes = snaiOf(res.records, book, unknown), keep = new Set(sel.events.map((e: any) => e.id));
        for (const e of sel.events) {
          const old = byId.get(e.id), c = codes.get(e.id);
          updates.set(e.id, {
            book, event_id: e.id, home: e.home, away: e.away, league: e.league, commence_time: e.commence,
            m: mergeCodes(old ? old.m : [], c ? c.m : [], ['1x2']), odds_at: c && c.at ? new Date(c.at).toISOString() : (old ? old.odds_at : null),
            pulled_at: nowIso, full_at: old ? old.full_at : null, match_id: e.match,
          });
        }
        if (res.complete) for (const r of rows) if (!keep.has(r.event_id) && Date.parse(r.commence_time) > now) drop.push(r.event_id);
        discovered = res.complete;
      } else note = 'data/week.json could not be read: the list was not paired this time';
    }
    /* 2. all four markets of Scudi's matches, by event id (one request for up to 150 matches) */
    if (!err) {
      const pool = [...rows.filter(r => !drop.includes(r.event_id)).map(r => updates.get(r.event_id) || r), ...[...updates.values()].filter(u => !byId.has(u.event_id))];
      const ids = pickIds(pool, now, cfg, manual);
      if (ids.length) {
        const res = await pull(nearParams(ids, cfg), cfg.maxPages);
        requests += res.requests; records += res.records.length; Object.assign(quota, res.quota);
        if (res.error) err = res.error;
        const codes = snaiOf(res.records, book, unknown), evs = new Map(eventsOf(res.records).map(e => [e.id, e]));
        const base = new Map(pool.map(r => [r.event_id, r]));
        for (const id of ids) {
          const b = updates.get(id) || base.get(id), c = codes.get(id), e = evs.get(id);
          if (!b || (!c && !res.complete)) continue;   /* a page not read is not a market gone */
          updates.set(id, {
            ...b, book, home: e && e.home ? e.home : b.home, away: e && e.away ? e.away : b.away, league: e && e.league ? e.league : b.league,
            commence_time: e && e.commence ? e.commence : b.commence_time, m: mergeCodes(b.m, c ? c.m : [], MARKETS),
            odds_at: c && c.at ? new Date(c.at).toISOString() : b.odds_at, pulled_at: nowIso, full_at: nowIso,
          });
        }
      }
    }
  } catch (e) {
    err = { status: 'error', wait: 10 * 60e3, msg: String(e).slice(0, 200) };
  }

  const status = err ? err.status : 'ok';
  const state: Record<string, unknown> = {
    checked_at: nowIso, last_kind: manual ? 'manual' : discover ? 'list+prices' : 'prices', last_status: status,
    last_error: err ? (err.msg || err.code || err.status) : note, why: p.why, ...quota,
  };
  if (requests) {
    state.last_pull_at = nowIso; state.last_requests = requests;
    if (!manual) state.avg_cost = st.avg_cost > 0 ? Math.round((0.8 * st.avg_cost + 0.2 * requests) * 100) / 100 : requests;
  }
  if (err && err.wait) state.backoff_until = new Date(now + err.wait).toISOString();
  if (discovered) state.discovered_at = nowIso;
  const diag: Record<string, unknown> = Object.assign({}, st.diag || {});
  if (sel) { state.matched = sel.matched; state.of_matches = sel.of; diag.timezone = sel.diag; }
  if (Object.keys(unknown).length) diag.unknown = unknown;
  state.diag = diag;
  /* the next pull, as the planner sees it now */
  const after = plan({ now: now + 60e3, st: { ...st, ...state }, cfg, kicks, manual: false });
  state.next_at = after.next ? new Date(after.next).toISOString() : null;

  await rpc('feed_save', { p: {
    events: [...updates.values()], drop, state,
    log: { kind: state.last_kind, requests, records, events: updates.size, status, quota_remaining: (quota as any).quota_remaining ?? null, ms: Date.now() - t0, note: state.last_error ? String(state.last_error).slice(0, 200) : null },
  } });
  return json({ pulled: true, status, requests, events: updates.size, left: (quota as any).quota_remaining ?? null, next: state.next_at });
});
