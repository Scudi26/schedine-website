-- Scudi · automatic SNAI prices (decision 92)
-- A private store for SNAI's prices pulled from odss-api.com. Its licence allows internal use only (no display to
-- anyone else, no redistribution), so nothing here is public: only the owner's account reads it, after signing in on
-- the site. The odss-api key is not here either: it lives in the Edge Function's secrets (ODSS_API_KEY), typed there by
-- Gianluca in Supabase's dashboard. Writes come only from the snai-pull Edge Function, with the project's secret key.

create schema if not exists private;
revoke all on schema private from public;

-- ---------- who may read: the first account created in this project, and only that one ----------
create table public.owners (
  user_id uuid primary key references auth.users (id) on delete cascade,
  added_at timestamptz not null default now()
);
alter table public.owners enable row level security;
create policy "an owner sees their own row" on public.owners for select to authenticated using (user_id = (select auth.uid()));

create or replace function public.is_owner() returns boolean
language sql stable security definer set search_path = '' as $$
  select exists (select 1 from public.owners where user_id = (select auth.uid()));
$$;

create or replace function private.first_owner() returns trigger
language plpgsql security definer set search_path = '' as $$
begin
  perform pg_advisory_xact_lock(hashtext('scudi-first-owner'));
  if not exists (select 1 from public.owners) then
    insert into public.owners (user_id) values (new.id);
  end if;
  return new;
end;
$$;
create trigger scudi_first_owner after insert on auth.users for each row execute function private.first_owner();

-- ---------- SNAI's events that are Scudi's matches, with their prices in SNAI's own codes ----------
-- m: [[market, line, outcome, price | null], …] — 3 = 1X2 (1/2/3 = 1/X/2), 28319 = double chance (1 = 1X, 2 = 12,
-- 3 = X2), 7989 = under/over (line × 100; 1 = under, 2 = over), 18 = goal/no goal (1/2); null = suspended.
create table public.book_events (
  book text not null default 'snai',
  event_id text not null,
  home text not null default '',
  away text not null default '',
  league text not null default '',
  commence_time timestamptz,
  m jsonb not null default '[]'::jsonb,
  odds_at timestamptz,            -- the newest of the book's price times, as odss-api reports them
  pulled_at timestamptz not null default now(),
  full_at timestamptz,            -- when all four markets were last pulled (else 1X2 only, from the list)
  match_id text,                  -- the Scudi match the function paired it with (the site checks it again)
  primary key (book, event_id)
);
create index book_events_commence on public.book_events (commence_time);
alter table public.book_events enable row level security;
create policy "the owner reads the prices" on public.book_events for select to authenticated using ((select public.is_owner()));

-- ---------- the feed's own state: quota, last pull, what went wrong ----------
create table public.feed_state (
  id int primary key default 1 check (id = 1),
  checked_at timestamptz,         -- the last time the function woke up (every 10 minutes)
  last_pull_at timestamptz,       -- the last time it spent requests
  last_kind text,                 -- 'list+prices', 'prices', 'manual'
  last_status text,               -- 'ok', 'no-key', 'bad-key', 'quota', 'rate', 'odss-down', …
  last_error text,
  last_requests int,
  avg_cost real,                  -- requests per pull, on average
  quota_limit int,
  quota_remaining int,
  quota_reset_at timestamptz,
  backoff_until timestamptz,
  discovered_at timestamptz,      -- SNAI's football list last read
  matched int,                    -- Scudi's matches with a SNAI event at the last reading of the list
  of_matches int,
  events int,                     -- SNAI events stored
  next_at timestamptz,            -- the planner's guess of the next pull
  why text,                       -- the planner's last reason
  diag jsonb not null default '{}'::jsonb,
  busy_until timestamptz,
  updated_at timestamptz not null default now()
);
insert into public.feed_state (id) values (1);
alter table public.feed_state enable row level security;
create policy "the owner reads the feed's state" on public.feed_state for select to authenticated using ((select public.is_owner()));

create table public.feed_log (
  id bigint generated always as identity primary key,
  at timestamptz not null default now(),
  kind text,
  requests int,
  records int,
  events int,
  status text,
  quota_remaining int,
  ms int,
  note text
);
alter table public.feed_log enable row level security;
create policy "the owner reads the log" on public.feed_log for select to authenticated using ((select public.is_owner()));

-- ---------- settings and the cron's token: never reachable from the API ----------
create table private.feed_config (
  id int primary key default 1 check (id = 1),
  cron_token text not null default replace(gen_random_uuid()::text || gen_random_uuid()::text, '-', ''),
  settings jsonb not null default '{}'::jsonb
);
insert into private.feed_config (id) values (1);

-- nobody but the function writes; the anonymous key reads nothing
revoke all on public.owners, public.book_events, public.feed_state, public.feed_log from anon;
revoke insert, update, delete, truncate on public.owners, public.book_events, public.feed_state, public.feed_log from authenticated;

-- ---------- what the snai-pull function calls (secret key only) ----------
create or replace function public.feed_load(cron text default null) returns jsonb
language sql stable security definer set search_path = '' as $$
  select jsonb_build_object(
    'state', (select to_jsonb(s) from public.feed_state s where s.id = 1),
    'settings', c.settings,
    'cron_ok', cron is not null and length(cron) >= 32 and cron = c.cron_token)
  from private.feed_config c where c.id = 1;
$$;

-- one pull at a time: a two-minute lease
create or replace function public.feed_claim() returns boolean
language plpgsql security definer set search_path = '' as $$
declare ok boolean;
begin
  update public.feed_state set busy_until = now() + interval '2 minutes'
   where id = 1 and (busy_until is null or busy_until < now())
  returning true into ok;
  return coalesce(ok, false);
end;
$$;

-- the state's fields present in p replace the stored ones; the others stay
create or replace function private.feed_patch(p jsonb) returns void
language plpgsql security definer set search_path = '' as $$
begin
  if p is null or p = '{}'::jsonb then return; end if;
  update public.feed_state t set
    checked_at = r.checked_at, last_pull_at = r.last_pull_at, last_kind = r.last_kind, last_status = r.last_status,
    last_error = r.last_error, last_requests = r.last_requests, avg_cost = r.avg_cost, quota_limit = r.quota_limit,
    quota_remaining = r.quota_remaining, quota_reset_at = r.quota_reset_at, backoff_until = r.backoff_until,
    discovered_at = r.discovered_at, matched = r.matched, of_matches = r.of_matches, events = r.events,
    next_at = r.next_at, why = r.why, diag = r.diag, busy_until = r.busy_until, updated_at = now()
  from (select (jsonb_populate_record(s, p)).* from public.feed_state s where s.id = 1) r
  where t.id = 1;
end;
$$;

create or replace function public.feed_tick(p jsonb) returns void
language sql security definer set search_path = '' as $$
  select private.feed_patch(p);
$$;

-- a pull's result in one go: events upserted or dropped, the state, a log line, old rows cleared
create or replace function public.feed_save(p jsonb) returns void
language plpgsql security definer set search_path = '' as $$
begin
  insert into public.book_events as b (book, event_id, home, away, league, commence_time, m, odds_at, pulled_at, full_at, match_id)
  select coalesce(x.book, 'snai'), x.event_id, coalesce(x.home, ''), coalesce(x.away, ''), coalesce(x.league, ''), x.commence_time,
         coalesce(x.m, '[]'::jsonb), x.odds_at, coalesce(x.pulled_at, now()), x.full_at, x.match_id
    from jsonb_to_recordset(coalesce(p -> 'events', '[]'::jsonb))
      as x(book text, event_id text, home text, away text, league text, commence_time timestamptz, m jsonb,
           odds_at timestamptz, pulled_at timestamptz, full_at timestamptz, match_id text)
   where x.event_id is not null
  on conflict (book, event_id) do update set
    home = excluded.home, away = excluded.away, league = excluded.league, commence_time = excluded.commence_time,
    m = excluded.m, odds_at = excluded.odds_at, pulled_at = excluded.pulled_at, full_at = excluded.full_at, match_id = excluded.match_id;

  delete from public.book_events
   where event_id in (select jsonb_array_elements_text(coalesce(p -> 'drop', '[]'::jsonb)));
  delete from public.book_events where commence_time < now() - interval '1 day';

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

revoke all on function public.feed_load(text), public.feed_claim(), public.feed_tick(jsonb), public.feed_save(jsonb) from public, anon, authenticated;
grant execute on function public.feed_load(text), public.feed_claim(), public.feed_tick(jsonb), public.feed_save(jsonb) to service_role;
revoke all on function private.feed_patch(jsonb), private.first_owner() from public, anon, authenticated;
revoke all on function public.is_owner() from public, anon;
grant execute on function public.is_owner() to authenticated;
