-- Checks for the feed's migration (decision 92), run on a local Postgres after supabase_stub.sql and the migration.
-- Every check raises an exception when it fails; the last line prints "feed sql checks passed".
\set ON_ERROR_STOP on
create or replace function pg_temp.ok(cond boolean, msg text) returns void language plpgsql as $$
begin if not coalesce(cond, false) then raise exception 'FAIL: %', msg; end if; end $$;

-- the first account becomes the owner, the second does not
insert into auth.users (id, email) values ('11111111-1111-1111-1111-111111111111', 'gianluca@example.com');
insert into auth.users (id, email) values ('22222222-2222-2222-2222-222222222222', 'someone@example.com');
select pg_temp.ok((select count(*) = 1 from public.owners where user_id = '11111111-1111-1111-1111-111111111111'), 'the first account is the owner');
select pg_temp.ok((select count(*) = 1 from public.owners), 'a second account is not an owner');

-- the function's writes (secret key = service_role)
set role service_role;
select pg_temp.ok((public.feed_load(null) ->> 'cron_ok')::boolean = false, 'no token, no cron');
select pg_temp.ok((public.feed_load('wrong-token-wrong-token-wrong-token-xx') ->> 'cron_ok')::boolean = false, 'a wrong token is refused');
reset role;
select pg_temp.ok((public.feed_load((select cron_token from private.feed_config)) ->> 'cron_ok')::boolean, 'the stored token is accepted');
select pg_temp.ok(length((select cron_token from private.feed_config)) = 64, 'the token is 64 random hex characters');
set role service_role;
select pg_temp.ok(public.feed_claim(), 'the first claim gets the lease');
select pg_temp.ok(not public.feed_claim(), 'a second pull at the same time does not');
select public.feed_save(jsonb_build_object(
  'events', jsonb_build_array(
    jsonb_build_object('event_id', 'ev1', 'home', 'Juventus', 'away', 'Inter', 'league', 'Serie A', 'commence_time', (now() + interval '1 day')::text,
                       'm', '[[3,0,1,2.1],[3,0,2,3.3],[3,0,3,null]]'::jsonb, 'odds_at', now()::text, 'match_id', 'm1'),
    jsonb_build_object('event_id', 'ev2', 'home', 'Old', 'away', 'Match', 'commence_time', (now() - interval '2 days')::text, 'm', '[]'::jsonb),
    jsonb_build_object('event_id', 'ev3', 'home', 'Dropped', 'away', 'Later', 'commence_time', (now() + interval '2 days')::text, 'm', '[]'::jsonb)),
  'state', jsonb_build_object('last_status', 'ok', 'quota_remaining', 431, 'last_pull_at', now()::text),
  'log', jsonb_build_object('kind', 'prices', 'requests', 1, 'records', 40, 'events', 3, 'status', 'ok', 'quota_remaining', 431, 'ms', 900)));
select pg_temp.ok((select count(*) = 2 from public.book_events), 'events stored, a match two days old cleared');
select pg_temp.ok((select (m -> 2 -> 3) = 'null'::jsonb from public.book_events where event_id = 'ev1'), 'a padlock stays null');
select pg_temp.ok((select quota_remaining = 431 and last_status = 'ok' and busy_until is null and events = 2 from public.feed_state), 'the state is saved and the lease freed');
select pg_temp.ok(public.feed_claim(), 'after a save the next pull can claim');
select public.feed_save(jsonb_build_object('events', jsonb_build_array(
    jsonb_build_object('event_id', 'ev1', 'home', 'Juventus', 'away', 'Inter', 'league', 'Serie A', 'commence_time', (now() + interval '1 day')::text,
                       'm', '[[3,0,1,2.2]]'::jsonb, 'match_id', 'm1')),
  'drop', jsonb_build_array('ev3'), 'state', jsonb_build_object('why', 'due')));
select pg_temp.ok((select m = '[[3,0,1,2.2]]'::jsonb from public.book_events where event_id = 'ev1'), 'a second save replaces the prices');
select pg_temp.ok((select count(*) = 0 from public.book_events where event_id = 'ev3'), 'an event no longer paired is dropped');
select pg_temp.ok((select quota_remaining = 431 and why = 'due' from public.feed_state), 'fields not sent keep their value');
select public.feed_tick('{"checked_at": "2026-10-06T10:00:00Z", "why": "night"}'::jsonb);
select pg_temp.ok((select why = 'night' and quota_remaining = 431 from public.feed_state), 'a wake with nothing to do only notes the time');
reset role;

-- the owner reads; another account and the anonymous key read nothing and write nothing
set role authenticated;
set request.jwt.claim.sub = '11111111-1111-1111-1111-111111111111';
select pg_temp.ok(public.is_owner(), 'the owner is recognised');
select pg_temp.ok((select count(*) = 1 from public.book_events), 'the owner reads the prices');
select pg_temp.ok((select count(*) = 1 from public.feed_state), 'the owner reads the feed state');
select pg_temp.ok((select count(*) >= 1 from public.feed_log), 'the owner reads the log');
do $$ begin
  begin update public.book_events set m = '[]'; raise exception 'FAIL: the owner could write'; exception when insufficient_privilege then null; end;
  begin perform public.feed_save('{}'::jsonb); raise exception 'FAIL: the site could call feed_save'; exception when insufficient_privilege then null; end;
  begin perform public.feed_load(null); raise exception 'FAIL: the site could read the cron token check'; exception when insufficient_privilege then null; end;
  begin perform 1 from private.feed_config; raise exception 'FAIL: the site could read the config'; exception when insufficient_privilege then null; end;
end $$;
set request.jwt.claim.sub = '22222222-2222-2222-2222-222222222222';
select pg_temp.ok(not public.is_owner(), 'another account is not the owner');
select pg_temp.ok((select count(*) = 0 from public.book_events), 'another account reads no prices');
select pg_temp.ok((select count(*) = 0 from public.feed_state), 'another account reads no state');
reset request.jwt.claim.sub;
reset role;
set role anon;
do $$ begin
  begin perform 1 from public.book_events; raise exception 'FAIL: anon could read'; exception when insufficient_privilege then null; end;
  begin perform public.feed_claim(); raise exception 'FAIL: anon could claim'; exception when insufficient_privilege then null; end;
  begin perform public.is_owner(); raise exception 'FAIL: anon could call is_owner'; exception when insufficient_privilege then null; end;
end $$;
reset role;
select 'feed sql checks passed';
