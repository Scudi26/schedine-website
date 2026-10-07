-- Scudi · Scudi's own chances from the sharp books, for every league (decision 94)
-- The snai-pull function now also brings the sharp books' prices (Pinnacle, the exchanges) in the same odss-api requests
-- and fits Scudi's score matrix to them: book_events.fit = { lh, la, rho, err, p: [1, X, 2, over 2.5], goals, books, at }.
-- Private like the rest of the store (odss-api's terms: internal use only); the owner's site turns the fixtures the weekly
-- job has not priced yet into matches with it.

alter table public.book_events add column if not exists fit jsonb;

create or replace function public.feed_save(p jsonb) returns void
language plpgsql security definer set search_path = '' as $$
begin
  insert into public.book_events as b (book, event_id, home, away, league, commence_time, m, odds_at, pulled_at, full_at, match_id, fit)
  select coalesce(x.book, 'snai'), x.event_id, coalesce(x.home, ''), coalesce(x.away, ''), coalesce(x.league, ''), x.commence_time,
         coalesce(x.m, '[]'::jsonb), x.odds_at, coalesce(x.pulled_at, now()), x.full_at, x.match_id, x.fit
    from jsonb_to_recordset(coalesce(p -> 'events', '[]'::jsonb))
      as x(book text, event_id text, home text, away text, league text, commence_time timestamptz, m jsonb,
           odds_at timestamptz, pulled_at timestamptz, full_at timestamptz, match_id text, fit jsonb)
   where x.event_id is not null
  on conflict (book, event_id) do update set
    home = excluded.home, away = excluded.away, league = excluded.league, commence_time = excluded.commence_time,
    m = excluded.m, odds_at = excluded.odds_at, pulled_at = excluded.pulled_at, full_at = excluded.full_at, match_id = excluded.match_id,
    fit = coalesce(excluded.fit, b.fit);

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

revoke all on function public.feed_save(jsonb) from public, anon, authenticated;
grant execute on function public.feed_save(jsonb) to service_role;
