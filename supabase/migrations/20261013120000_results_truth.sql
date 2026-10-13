-- Scudi · results, the closing truth and SNAI against the close (decision 98: phase 1 steps 1.3, 1.4 and 1.6 of the
-- value radar, claude/roadmap-radar.md)
--
-- 1.3 results   public.match_results: the 90-minute score (and half time) of every match Scudi lists, keyed by Scudi's
--               match id — the id public.memory_events keeps for every paired event. Settled from ESPN by the daily
--               GitHub job (tools/results.py, into data/week.json → "results") and saved here by the snai-pull function
--               through public.results_save, the only way in.
--               memory_events.near_at / near_books: the last time an event's four markets were read (a near pull, the
--               closing pull included) and which books had prices then — so a closing price can be told apart from a
--               price that simply stopped being read.
-- 1.4 truth     public.truth_of(event): the fair chance of each selection at kick-off, from the sharpest book that priced
--               the whole market at its last reading before the kick-off (Pinnacle, then the Betfair exchange, Matchbook,
--               Smarkets; margin removed with the power method, as everywhere in Scudi), else from Scudi's own fit to the
--               books (public.fit_ticks → public.dc_chances, the same Dixon–Coles matrix as the site; both teams to score
--               carries the +1.5 point correction of decision 60). The double chances come from the result's chances.
--               public.snai_vs_close(): every SNAI price as it stood at the kick-off and 1, 3, 6, 12, 24 and 48 hours
--               before, against that truth: CLV = SNAI price × fair chance − 1 (above zero = SNAI paid more than the
--               close says the bet was worth), and whether it won.
--               public.snai_map(): the same grouped by league, market and price band — what the private
--               "SNAI vs the close" page will draw (step 1.5).
-- 1.6 health    public.radar_health(days): matches, closing readings, sharp books at the close, results, storage.
--               Run in the SQL editor:  select public.radar_health(7);
--
-- Everything stays private (odss-api's licence: internal use only): the tables answer the owner alone, the functions run
-- with the caller's rights (row-level security applies), the anonymous key can call none of them.

alter table public.memory_events add column if not exists near_at timestamptz;
alter table public.memory_events add column if not exists near_books text[];

create table if not exists public.match_results (
  match_id text primary key,
  ft_h smallint not null check (ft_h >= 0),
  ft_a smallint not null check (ft_a >= 0),
  ht_h smallint check (ht_h >= 0),
  ht_a smallint check (ht_a >= 0),
  kickoff timestamptz,
  saved_at timestamptz not null default now(),
  check ((ht_h is null) = (ht_a is null) and (ht_h is null or (ht_h <= ft_h and ht_a <= ft_a)))
);
alter table public.match_results enable row level security;
drop policy if exists "the owner reads the results" on public.match_results;
create policy "the owner reads the results" on public.match_results for select to authenticated using ((select public.is_owner()));
revoke all on public.match_results from anon;
revoke insert, update, delete, truncate on public.match_results from authenticated;

-- the daily job's results, as they ride in data/week.json: {"done": {match id: [home, away, ht home, ht away, kick-off]}}
create or replace function public.results_save(p jsonb) returns integer
language plpgsql security definer set search_path = '' as $$
declare n integer;
begin
  with x as (
    select e.k, e.v, coalesce((e.v ->> 2) ~ '^\d{1,2}$' and (e.v ->> 3) ~ '^\d{1,2}$', false) as ht
      from jsonb_each(case when jsonb_typeof(p -> 'done') = 'object' then p -> 'done' else '{}'::jsonb end) as e(k, v)
     where jsonb_typeof(e.v) = 'array' and length(e.k) between 1 and 80
       and coalesce((e.v ->> 0) ~ '^\d{1,2}$' and (e.v ->> 1) ~ '^\d{1,2}$', false)
  )
  , y as (   -- a half time above the final score cannot be right: the score is kept, the half time left out
    select x.k, (x.v ->> 0)::smallint as fh, (x.v ->> 1)::smallint as fa,
           case when x.ht then case when (x.v ->> 2)::int <= (x.v ->> 0)::int and (x.v ->> 3)::int <= (x.v ->> 1)::int then (x.v ->> 2)::smallint end end as hh,
           case when x.ht then case when (x.v ->> 2)::int <= (x.v ->> 0)::int and (x.v ->> 3)::int <= (x.v ->> 1)::int then (x.v ->> 3)::smallint end end as ha,
           case when coalesce((x.v ->> 4) ~ '^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}', false) then (x.v ->> 4)::timestamptz end as ko
      from x
  )
  insert into public.match_results as r (match_id, ft_h, ft_a, ht_h, ht_a, kickoff)
  select y.k, y.fh, y.fa, case when y.ha is not null then y.hh end, case when y.hh is not null then y.ha end, y.ko from y
  on conflict (match_id) do update set
    -- a known half time is kept when a later copy has none (and it still fits the score); an unchanged row is left alone
    ft_h = excluded.ft_h, ft_a = excluded.ft_a,
    ht_h = case when excluded.ht_h is not null then excluded.ht_h when r.ht_h <= excluded.ft_h and r.ht_a <= excluded.ft_a then r.ht_h end,
    ht_a = case when excluded.ht_h is not null then excluded.ht_a when r.ht_h <= excluded.ft_h and r.ht_a <= excluded.ft_a then r.ht_a end,
    kickoff = coalesce(excluded.kickoff, r.kickoff), saved_at = now()
    where (r.ft_h, r.ft_a, r.ht_h, r.ht_a, r.kickoff) is distinct from
          (excluded.ft_h, excluded.ft_a,
           case when excluded.ht_h is not null then excluded.ht_h when r.ht_h <= excluded.ft_h and r.ht_a <= excluded.ft_a then r.ht_h end,
           case when excluded.ht_h is not null then excluded.ht_a when r.ht_h <= excluded.ft_h and r.ht_a <= excluded.ft_a then r.ht_a end,
           coalesce(excluded.kickoff, r.kickoff));
  get diagnostics n = row_count;
  return n;
end;
$$;
revoke all on function public.results_save(jsonb) from public, anon, authenticated;
grant execute on function public.results_save(jsonb) to service_role;

-- a pull's result in one go: as before (decisions 94 and 96), plus when each event's markets were last read and by whom
create or replace function public.feed_save(p jsonb) returns void
language plpgsql security definer set search_path = '' as $$
begin
  insert into public.book_events as b (book, event_id, home, away, league, commence_time, m, odds_at, pulled_at, full_at, match_id, fit, ref)
  select coalesce(x.book, 'snai'), x.event_id, coalesce(x.home, ''), coalesce(x.away, ''), coalesce(x.league, ''), x.commence_time,
         coalesce(x.m, '[]'::jsonb), x.odds_at, coalesce(x.pulled_at, now()), x.full_at, x.match_id, x.fit, x.ref
    from jsonb_to_recordset(coalesce(p -> 'events', '[]'::jsonb))
      as x(book text, event_id text, home text, away text, league text, commence_time timestamptz, m jsonb,
           odds_at timestamptz, pulled_at timestamptz, full_at timestamptz, match_id text, fit jsonb, ref jsonb)
   where x.event_id is not null
  on conflict (book, event_id) do update set
    home = excluded.home, away = excluded.away, league = excluded.league, commence_time = excluded.commence_time,
    m = excluded.m, odds_at = excluded.odds_at, pulled_at = excluded.pulled_at, full_at = excluded.full_at, match_id = excluded.match_id,
    fit = coalesce(excluded.fit, b.fit), ref = coalesce(excluded.ref, b.ref);

  -- the memory: every event read, when its four markets were last read and which books had prices then
  insert into public.memory_events as e (event_id, home, away, league, commence_time, match_id, near_at, near_books)
  select x.event_id, coalesce(x.home, ''), coalesce(x.away, ''), coalesce(x.league, ''), x.commence_time, x.match_id, x.near_at, x.near_books
    from jsonb_to_recordset(coalesce(p -> 'events', '[]'::jsonb))
      as x(event_id text, home text, away text, league text, commence_time timestamptz, match_id text, near_at timestamptz, near_books text[])
   where x.event_id is not null
  on conflict (event_id) do update set
    home = excluded.home, away = excluded.away, league = excluded.league, commence_time = excluded.commence_time,
    match_id = coalesce(excluded.match_id, e.match_id), last_at = now(),
    near_at = coalesce(excluded.near_at, e.near_at),
    near_books = case when excluded.near_at is not null then excluded.near_books else e.near_books end;

  insert into public.price_ticks (event_id, book, at, c, p)
  select x.event_id, x.book, x.at, x.c, x.p
    from jsonb_to_recordset(coalesce(p -> 'ticks', '[]'::jsonb)) as x(event_id text, book text, at timestamptz, c int[], p real[])
   where x.event_id is not null and x.book is not null and x.at is not null and cardinality(x.c) > 0
     and exists (select 1 from public.memory_events m where m.event_id = x.event_id)
  on conflict do nothing;

  insert into public.fit_ticks (event_id, at, p, lh, la, rho, err, sharp, nb, tier, src_at)
  select x.event_id, x.at, x.p, x.lh, x.la, x.rho, x.err, x.sharp, x.nb, x.tier, x.src_at
    from jsonb_to_recordset(coalesce(p -> 'fits', '[]'::jsonb))
      as x(event_id text, at timestamptz, p real[], lh real, la real, rho real, err real, sharp real, nb smallint, tier text, src_at timestamptz)
   where x.event_id is not null and x.at is not null and x.p is not null
     and exists (select 1 from public.memory_events m where m.event_id = x.event_id)
  on conflict do nothing;

  delete from public.book_events
   where event_id in (select jsonb_array_elements_text(coalesce(p -> 'drop', '[]'::jsonb)));
  delete from public.book_events where commence_time < now() - interval '1 day';
  delete from public.memory_events where commence_time < now() - interval '200 days';   -- their readings go with them

  if p ? 'log' then
    insert into public.feed_log (kind, requests, records, events, status, quota_remaining, ms, note)
    select x.kind, x.requests, x.records, x.events, x.status, x.quota_remaining, x.ms, x.note
      from jsonb_to_record(p -> 'log') as x(kind text, requests int, records int, events int, status text, quota_remaining int, ms int, note text);
    delete from public.feed_log where id < (select coalesce(max(id), 0) - 1000 from public.feed_log);
  end if;

  perform private.feed_patch(coalesce(p -> 'state', '{}'::jsonb) || jsonb_build_object(
    'events', (select count(*) from public.book_events where commence_time > now()),
    'busy_until', null));
end;
$$;
revoke all on function public.feed_save(jsonb) from public, anon, authenticated;
grant execute on function public.feed_save(jsonb) to service_role;

-- ---------- the maths, the same as the site's and the feed's ----------

-- a book's prices → its fair chances (power method; prices adding up to 100% or less are only normalised), or null
create or replace function public.devig_power(prices double precision[]) returns double precision[]
language plpgsql immutable set search_path = '' as $$
declare
  n int := coalesce(array_length(prices, 1), 0);
  raw double precision[]; tot double precision := 0; lo double precision := 1; hi double precision := 50; mid double precision; s double precision;
begin
  if n < 2 then return null; end if;
  for i in 1..n loop
    if prices[i] is null or not (prices[i] > 1) or prices[i] = 'Infinity'::double precision then return null; end if;
    raw[i] := 1 / prices[i]; tot := tot + raw[i];
  end loop;
  if tot <= 1 then
    for i in 1..n loop raw[i] := raw[i] / tot; end loop;
    return raw;
  end if;
  for it in 1..80 loop
    mid := (lo + hi) / 2; s := 0;
    for i in 1..n loop s := s + raw[i] ^ mid; end loop;
    if s > 1 then lo := mid; else hi := mid; end if;
  end loop;
  mid := (lo + hi) / 2; s := 0;
  for i in 1..n loop raw[i] := raw[i] ^ mid; s := s + raw[i]; end loop;
  for i in 1..n loop raw[i] := raw[i] / s; end loop;
  return raw;
end;
$$;

-- the Dixon–Coles matrix (scorelines 0..9 each side, the low-score correction clipped like the site's safeRho) → the fair
-- chance of each of the memory's selections, in its packed codes (market × 100000 + line × 10 + outcome)
create or replace function public.dc_chances(lh double precision, la double precision, rho double precision)
returns table(code int, p double precision)
language plpgsql immutable set search_path = '' as $$
declare
  ph double precision[]; pa double precision[]; fact double precision := 1; r double precision; rhi double precision; rlo double precision;
  v double precision; t double precision := 0; hw double precision := 0; dr double precision := 0; aw double precision := 0;
  o15 double precision := 0; o25 double precision := 0; o35 double precision := 0; bt double precision := 0;
begin
  if lh is null or la is null or not (lh > 0 and la > 0 and lh < 20 and la < 20) then return; end if;
  rhi := least(1 / (lh * la), 1) * 0.999; rlo := -least(1 / lh, 1 / la) * 0.999;
  r := greatest(rlo, least(rhi, coalesce(rho, 0)));
  for i in 0..9 loop
    ph[i + 1] := exp(-lh) * lh ^ i / fact; pa[i + 1] := exp(-la) * la ^ i / fact; fact := fact * (i + 1);
  end loop;
  for i in 0..9 loop
    for j in 0..9 loop
      v := ph[i + 1] * pa[j + 1];
      if i = 0 and j = 0 then v := v * (1 - lh * la * r);
      elsif i = 0 and j = 1 then v := v * (1 + lh * r);
      elsif i = 1 and j = 0 then v := v * (1 + la * r);
      elsif i = 1 and j = 1 then v := v * (1 - r);
      end if;
      t := t + v;
      if i > j then hw := hw + v; elsif i = j then dr := dr + v; else aw := aw + v; end if;
      if i + j >= 2 then o15 := o15 + v; end if;
      if i + j >= 3 then o25 := o25 + v; end if;
      if i + j >= 4 then o35 := o35 + v; end if;
      if i >= 1 and j >= 1 then bt := bt + v; end if;
    end loop;
  end loop;
  hw := hw / t; dr := dr / t; aw := aw / t; o15 := o15 / t; o25 := o25 / t; o35 := o35 / t; bt := bt / t;
  return query values (100001, hw), (100002, dr), (100003, aw), (200001, hw + dr), (200002, hw + aw), (200003, dr + aw),
    (301501, 1 - o15), (301502, o15), (302501, 1 - o25), (302502, o25), (303501, 1 - o35), (303502, o35),
    (400001, least(0.99, bt + 0.015)), (400002, greatest(0.01, 1 - bt - 0.015));   -- decision 60: +1.5 points on both to score
end;
$$;

-- did a selection win on this 90-minute score? (null when there is no score)
create or replace function public.settles(code int, h int, a int) returns boolean
language sql immutable strict set search_path = '' as $$
  select case code / 100000
    when 1 then case code % 10 when 1 then h > a when 2 then h = a when 3 then h < a end
    when 2 then case code % 10 when 1 then h >= a when 2 then h <> a when 3 then h <= a end
    when 3 then case code % 10 when 1 then (h + a) * 100 < (code % 100000) / 10 when 2 then (h + a) * 100 > (code % 100000) / 10 end
    when 4 then case code % 10 when 1 then h > 0 and a > 0 when 2 then not (h > 0 and a > 0) end
  end;
$$;

-- ---------- 1.4: the truth at kick-off ----------
-- one row per event and selection: its fair chance at the close and where it came from ('pinnacle', 'betfair_ex_eu', …
-- the book's key; 'fit' = Scudi's fit to the international books, 'fit:it' = to the Italian ones, the weakest), and the
-- time of the reading it rests on (a price is stored only when it changes: an old time is still the close when the book
-- was there at the last full reading, near_books). Set-based: every event of a window in one pass.
--   a book's market counts only if the book still had prices at the event's last full reading, every outcome is priced
--   and it adds up (margin 0–15%; an exchange may be down to −3%); Pinnacle first, then the Betfair exchange, Matchbook,
--   Smarkets; the double chances come from the result's fair chances
--   otherwise the last fit of the 48 hours before the kick-off — for goals only a fit that had a goals line
create or replace function public.truths(since timestamptz, till timestamptz, only_event text default null)
returns table(event_id text, code int, p double precision, source text, src_at timestamptz)
language plpgsql stable set search_path = '' as $$
#variable_conflict use_column
begin
  return query
  with ev as (
    select e.event_id, e.commence_time, e.near_books
      from public.memory_events e
     where e.commence_time >= since and e.commence_time < till and (only_event is null or e.event_id = only_event)
  ), cp as (   -- each sharp book's last price of each selection before the kick-off
    select distinct on (t.event_id, t.book, u.code) t.event_id, t.book, u.code, u.price, t.at
      from ev
      join public.price_ticks t on t.event_id = ev.event_id and t.at <= ev.commence_time
       and t.book ~* '^(pinnacle|betfair|matchbook|smarkets)' and t.book !~* 'sportsbook'
       and (ev.near_books is null or t.book = any(ev.near_books))
     cross join lateral unnest(t.c, t.p) as u(code, price)
     order by t.event_id, t.book, u.code, t.at desc
  ), gp as (   -- the selection's market: 1 = the result, 3150 / 3250 / 3350 = an under/over line, 4 = goal/no goal
    select cp.event_id, cp.book, cp.code, cp.price, cp.at,
           case cp.code / 100000 when 1 then 1 when 4 then 4 else 3000 + (cp.code % 100000) / 10 end as g
      from cp
     where (cp.code / 100000 in (1, 4) and cp.code % 100000 / 10 = 0) or (cp.code / 100000 = 3 and cp.code % 100000 / 10 in (150, 250, 350))
  ), whole as (
    select gp.event_id, gp.book, gp.g, array_agg(gp.code order by gp.code) as codes,
           array_agg(round(gp.price::numeric, 2)::double precision order by gp.code) as pr, max(gp.at) as at
      from gp
     group by gp.event_id, gp.book, gp.g
    having count(*) = case when gp.g = 1 then 3 else 2 end and count(*) filter (where gp.price > 1) = count(*)
       and sum(case when gp.price > 1 then 1.0 / gp.price end) - 1
           between case when gp.book ~* '^(betfair|matchbook|smarkets)' then -0.03 else 0 end and 0.15
  ), best as (
    select distinct on (w.event_id, w.g) w.event_id, w.book, w.g, w.codes, w.at, public.devig_power(w.pr) as fair
      from whole w
     order by w.event_id, w.g, case when w.book ~* '^pinnacle' then 1 when w.book ~* '^betfair' then 2 when w.book ~* '^matchbook' then 3 else 4 end, w.book
  ), fit as (
    select distinct on (t.event_id) t.event_id, t.at, t.lh, t.la, t.rho, t.tier, t.p[4] is not null as goals
      from ev join public.fit_ticks t on t.event_id = ev.event_id and t.at <= ev.commence_time and t.at > ev.commence_time - interval '48 hours'
     order by t.event_id, t.at desc
  )
  select b.event_id, b.codes[i], b.fair[i], b.book, b.at
    from best b cross join lateral generate_subscripts(b.codes, 1) as i
   where b.fair is not null
  union all
  select b.event_id, d.code, d.p, b.book, b.at
    from best b cross join lateral (values (200001, b.fair[1] + b.fair[2]), (200002, b.fair[1] + b.fair[3]), (200003, b.fair[2] + b.fair[3])) as d(code, p)
   where b.g = 1 and b.fair is not null
  union all
  select f.event_id, d.code, d.p, case when f.tier = 'it' then 'fit:it' else 'fit' end, f.at
    from fit f cross join lateral public.dc_chances(f.lh, f.la, f.rho) as d
   where (f.goals or d.code / 100000 <= 2)
     and not exists (select 1 from best b where b.event_id = f.event_id and b.fair is not null
                        and b.g = case d.code / 100000 when 1 then 1 when 2 then 1 when 4 then 4 else 3000 + (d.code % 100000) / 10 end);
end;
$$;

-- one event's truth (for a look in the SQL editor:  select * from public.truth_of('<event id>');)
create or replace function public.truth_of(eid text)
returns table(code int, p double precision, source text, src_at timestamptz)
language sql stable set search_path = '' as $$
  select t.code, t.p, t.source, t.src_at from public.truths('-infinity', 'infinity', eid) t order by t.code;
$$;

-- (plpgsql, not sql: the planner then sees the window's real dates; as a plain SQL function it planned blind and took
-- over a minute on two months of data, against ~3 seconds now)
-- every SNAI price as it stood at the kick-off (hours_before = 0) and 1, 3, 6, 12, 24, 48 hours before, against the truth
create or replace function public.snai_vs_close(since timestamptz default now() - interval '60 days', till timestamptz default now())
returns table(event_id text, league text, home text, away text, commence_time timestamptz, match_id text, code int, hours_before int,
              price real, read_at timestamptz, p_fair double precision, source text, clv double precision, won boolean, confirmed boolean)
language plpgsql stable set search_path = '' as $$
#variable_conflict use_column
begin
  return query
  with ev as (
    select e.event_id, e.league, e.home, e.away, e.commence_time, e.match_id, e.near_at
      from public.memory_events e
     where e.commence_time >= since and e.commence_time < least(till, now())
       and exists (select 1 from public.price_ticks t where t.event_id = e.event_id and t.book = 'snai' and t.at <= e.commence_time)
  ), tr as (
    select t.event_id, t.code, t.p, t.source from public.truths(since, least(till, now())) t
     where t.event_id in (select ev.event_id from ev)
  ), sn as (
    select v.event_id, v.code, v.at, v.price
      from ev join public.price_ticks_v v on v.event_id = ev.event_id and v.book = 'snai' and v.at <= ev.commence_time
  ), cp(h) as (values (0), (1), (3), (6), (12), (24), (48)
  ), asof as (
    select distinct on (sn.event_id, sn.code, cp.h) sn.event_id, sn.code, cp.h, sn.price, sn.at
      from sn join ev on ev.event_id = sn.event_id cross join cp
     where sn.at <= ev.commence_time - make_interval(hours => cp.h)
     order by sn.event_id, sn.code, cp.h, sn.at desc
  )
  select ev.event_id, ev.league, ev.home, ev.away, ev.commence_time, ev.match_id, a.code, a.h, a.price, a.at, tr.p, tr.source,
         round(a.price::numeric, 2)::double precision * tr.p - 1, public.settles(a.code, r.ft_h, r.ft_a),
         coalesce(ev.near_at between ev.commence_time - interval '30 minutes' and ev.commence_time, false)
    from asof a
    join ev on ev.event_id = a.event_id
    join tr on tr.event_id = a.event_id and tr.code = a.code
    left join public.match_results r on r.match_id = ev.match_id
   where a.price is not null
   order by ev.commence_time, ev.event_id, a.code, a.h;
end;
$$;

-- the same, grouped: league × market × SNAI's price band, at one checkpoint (0 = the close)
create or replace function public.snai_map(since timestamptz default now() - interval '60 days', till timestamptz default now(), hours int default 0)
returns table(league text, market text, band text, band_from real, n bigint, events bigint, avg_clv double precision, median_clv double precision,
              beat_close double precision, settled bigint, won bigint, expected double precision)
language plpgsql stable set search_path = '' as $$
#variable_conflict use_column
begin
  return query
  select x.league,
         case x.code / 100000 when 1 then '1X2' when 2 then 'Double chance' when 4 then 'Goal/no goal'
              else 'Under/over ' || to_char((x.code % 100000) / 1000.0, 'FM0.0') end,
         case when x.price < 1.5 then 'under 1.50' when x.price < 2 then '1.50-1.99' when x.price < 3 then '2.00-2.99'
              when x.price < 5 then '3.00-4.99' else '5.00 and up' end,
         case when x.price < 1.5 then 1 when x.price < 2 then 1.5 when x.price < 3 then 2 when x.price < 5 then 3 else 5 end::real,
         count(*), count(distinct x.event_id), avg(x.clv), percentile_cont(0.5) within group (order by x.clv),
         avg(case when x.clv > 0 then 1.0 else 0.0 end)::double precision, count(*) filter (where x.won is not null), count(*) filter (where x.won),
         sum(x.p_fair) filter (where x.won is not null)
    from public.snai_vs_close(since, till) x
   where x.hours_before = hours
   group by 1, 2, 3, 4
   order by 1, 2, 4;
end;
$$;

-- ---------- 1.6: is the memory healthy? ----------
create or replace function public.radar_health(days int default 7) returns jsonb
language sql stable set search_path = '' as $$
  with ev as (
    select e.event_id, e.league, e.commence_time, e.match_id, e.near_at, e.near_books
      from public.memory_events e
     where e.commence_time > now() - make_interval(days => days) and e.commence_time <= now()
  ), home as (   -- each book's last home-win price before the kick-off (books still there at the last full reading)
    select distinct on (t.event_id, t.book) t.event_id, t.book, u.price
      from ev join public.price_ticks t on t.event_id = ev.event_id and t.at <= ev.commence_time
       and (t.book = 'snai' or ev.near_books is null or t.book = any(ev.near_books))
     cross join lateral unnest(t.c, t.p) as u(code, price)
     where u.code = 100001
     order by t.event_id, t.book, t.at desc
  ), cl as (
    select ev.event_id, ev.league,
           coalesce(ev.near_at between ev.commence_time - interval '30 minutes' and ev.commence_time, false) as closed,   -- a shared closing pull: up to 24 min
           exists (select 1 from home h where h.event_id = ev.event_id and h.book = 'snai' and h.price is not null) as snai,
           exists (select 1 from home h where h.event_id = ev.event_id and h.book ~* '^pinnacle' and h.price is not null) as pin,
           exists (select 1 from home h where h.event_id = ev.event_id and h.price is not null
                      and h.book ~* '^(pinnacle|betfair|matchbook|smarkets)' and h.book !~* 'sportsbook') as sharp,
           exists (select 1 from public.fit_ticks f where f.event_id = ev.event_id and f.at <= ev.commence_time and f.at > ev.commence_time - interval '48 hours') as fit,
           exists (select 1 from public.match_results r where r.match_id = ev.match_id) as result
      from ev
  )
  select jsonb_build_object(
    'days', days,
    'matches', count(*),
    'closing_read', count(*) filter (where cl.closed),
    'snai_priced', count(*) filter (where cl.snai),
    'pinnacle_at_close', count(*) filter (where cl.pin),
    'sharp_at_close', count(*) filter (where cl.sharp),
    'fit_only', count(*) filter (where cl.fit and not cl.sharp),
    'no_truth', count(*) filter (where not cl.fit and not cl.sharp),
    'with_result', count(*) filter (where cl.result),
    'by_league', coalesce((select jsonb_object_agg(l.league, l.j) from (
        select c2.league, jsonb_build_object('matches', count(*), 'closing_read', count(*) filter (where c2.closed),
               'sharp_at_close', count(*) filter (where c2.sharp), 'with_result', count(*) filter (where c2.result)) as j
          from cl c2 group by c2.league) l), '{}'::jsonb),
    'closing_pulls', (select count(*) from public.feed_log g where g.kind = 'closing' and g.at > now() - make_interval(days => days)),
    'last_pull', (select max(g.at) from public.feed_log g),
    'readings_kept', (select count(*) from public.price_ticks),
    'results_saved', (select count(*) from public.match_results),
    'database_mb', round(pg_database_size(current_database()) / 1048576.0, 1)
  ) from cl;
$$;

revoke all on function public.devig_power(double precision[]), public.dc_chances(double precision, double precision, double precision),
  public.settles(int, int, int), public.truths(timestamptz, timestamptz, text), public.truth_of(text),
  public.snai_vs_close(timestamptz, timestamptz), public.snai_map(timestamptz, timestamptz, int), public.radar_health(int) from public, anon;
grant execute on function public.devig_power(double precision[]), public.dc_chances(double precision, double precision, double precision),
  public.settles(int, int, int), public.truths(timestamptz, timestamptz, text), public.truth_of(text),
  public.snai_vs_close(timestamptz, timestamptz), public.snai_map(timestamptz, timestamptz, int), public.radar_health(int) to authenticated;
