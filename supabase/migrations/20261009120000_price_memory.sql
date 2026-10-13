-- Scudi · the price memory (decision 96, phase 1 of the value radar)
-- Until now every pull replaced the last one in book_events, and an event was cleared a day after kick-off: the history
-- of SNAI's prices against the sharp books', the raw material of the radar, was thrown away. From now on every reading
-- is kept, with its time, and only what changed:
--   memory_events  one row per event ever paired (names, league, kick-off, Scudi's match), kept 200 days
--   price_ticks    one row per event, book and reading: the selections whose price changed (c = packed codes, p = prices,
--                  null = padlocked or no longer offered); SNAI's prices and the sharp books' own (Pinnacle, exchanges)
--   fit_ticks      Scudi's chances fitted to the reference books, each time they moved
-- A code packs market (1 = 1X2, 2 = double chance, 3 = under/over, 4 = goal/no goal) × 100000 + line (hundredths) × 10 +
-- outcome: 100001 = home win, 100002 = draw, 200001 = 1X, 302502 = over 2.5, 400001 = goal. Private like the rest of the
-- store (odss-api's licence: internal use only): only the owner reads it.

alter table public.book_events add column if not exists ref jsonb;   -- the sharp books' latest prices, in SNAI's codes

create table if not exists public.memory_events (
  event_id text primary key,
  home text not null default '',
  away text not null default '',
  league text not null default '',
  commence_time timestamptz,
  match_id text,
  first_at timestamptz not null default now(),
  last_at timestamptz not null default now()
);
create index if not exists memory_events_commence on public.memory_events (commence_time);

create table if not exists public.price_ticks (
  event_id text not null references public.memory_events (event_id) on delete cascade,
  book text not null,
  at timestamptz not null,
  c int[] not null,
  p real[] not null,
  primary key (event_id, book, at),
  check (cardinality(c) > 0 and cardinality(c) = cardinality(p))
);

create table if not exists public.fit_ticks (
  event_id text not null references public.memory_events (event_id) on delete cascade,
  at timestamptz not null,
  p real[] not null,              -- [home, draw, away, over 2.5] (over null when no goals line was priced)
  lh real, la real, rho real, err real,
  sharp real,                     -- the share of the weight that came from the sharp books
  nb smallint,                    -- books in the consensus
  tier text,                      -- 'ref' (international books) or 'it' (the Italian last resort)
  src_at timestamptz,             -- the newest of those books' price times
  primary key (event_id, at)
);

alter table public.memory_events enable row level security;
alter table public.price_ticks enable row level security;
alter table public.fit_ticks enable row level security;
create policy "the owner reads the memory" on public.memory_events for select to authenticated using ((select public.is_owner()));
create policy "the owner reads the prices kept" on public.price_ticks for select to authenticated using ((select public.is_owner()));
create policy "the owner reads the fits kept" on public.fit_ticks for select to authenticated using ((select public.is_owner()));
revoke all on public.memory_events, public.price_ticks, public.fit_ticks from anon;
revoke insert, update, delete, truncate on public.memory_events, public.price_ticks, public.fit_ticks from authenticated;

-- one row per selection and reading, decoded (the owner's own rows, through row-level security)
create or replace view public.price_ticks_v with (security_invoker = true) as
select t.event_id, t.book, t.at, u.code,
       case u.code / 100000 when 1 then 3 when 2 then 28319 when 3 then 7989 when 4 then 18 end as market,
       (u.code % 100000) / 10 as line, u.code % 10 as outcome, u.price
  from public.price_ticks t
  cross join lateral unnest(t.c, t.p) as u(code, price);

-- each book's last price for each selection before the kick-off: the closing price
create or replace view public.closing_prices with (security_invoker = true) as
select distinct on (v.event_id, v.book, v.code)
       v.event_id, v.book, v.code, v.market, v.line, v.outcome, v.price, v.at, e.commence_time,
       extract(epoch from (e.commence_time - v.at)) / 60 as minutes_before
  from public.price_ticks_v v
  join public.memory_events e on e.event_id = v.event_id
 where v.at <= e.commence_time
 order by v.event_id, v.book, v.code, v.at desc;

revoke all on public.price_ticks_v, public.closing_prices from anon;
revoke insert, update, delete, truncate on public.price_ticks_v, public.closing_prices from authenticated;

-- how big the memory is (the owner only)
create or replace function public.memory_stats() returns jsonb
language sql stable security definer set search_path = '' as $$
  select case when (select public.is_owner()) then jsonb_build_object(
    'events', (select count(*) from public.memory_events),
    'readings', (select count(*) from public.price_ticks),
    'fits', (select count(*) from public.fit_ticks),
    'first', (select min(at) from public.price_ticks),
    'last', (select max(at) from public.price_ticks),
    'bytes', pg_total_relation_size('public.memory_events') + pg_total_relation_size('public.price_ticks') + pg_total_relation_size('public.fit_ticks'),
    'database_bytes', pg_database_size(current_database())) end;
$$;
revoke all on function public.memory_stats() from public, anon;
grant execute on function public.memory_stats() to authenticated;

-- a pull's result in one go: as before (decision 94), plus the memory
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

  -- the memory: every event read, then what changed in this reading
  insert into public.memory_events as e (event_id, home, away, league, commence_time, match_id)
  select x.event_id, coalesce(x.home, ''), coalesce(x.away, ''), coalesce(x.league, ''), x.commence_time, x.match_id
    from jsonb_to_recordset(coalesce(p -> 'events', '[]'::jsonb))
      as x(event_id text, home text, away text, league text, commence_time timestamptz, match_id text)
   where x.event_id is not null
  on conflict (event_id) do update set
    home = excluded.home, away = excluded.away, league = excluded.league, commence_time = excluded.commence_time,
    match_id = coalesce(excluded.match_id, e.match_id), last_at = now();

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
