-- Checks for the price memory (decision 96), run on a local Postgres after supabase_stub.sql, every migration and
-- feed_checks.sql (which makes the owner 1111… and a second account 2222…). Every check raises an exception when it
-- fails; the last line prints "memory sql checks passed".
\set ON_ERROR_STOP on
create or replace function pg_temp.ok(cond boolean, msg text) returns void language plpgsql as $$
begin if not coalesce(cond, false) then raise exception 'FAIL: %', msg; end if; end $$;

set role service_role;
-- a first reading: SNAI's prices, Pinnacle's, and the fit
select public.feed_save(jsonb_build_object(
  'events', jsonb_build_array(jsonb_build_object('event_id', 'mem1', 'home', 'Napoli', 'away', 'Roma', 'league', 'Serie A',
     'commence_time', (now() + interval '3 hours')::text, 'match_id', 'nap-rom', 'm', '[[3,0,1,1.9],[3,0,2,3.5],[3,0,3,4.2]]'::jsonb,
     'ref', '{"pinnacle": [[3,0,1,1.95],[3,0,2,3.7],[3,0,3,4.4]]}'::jsonb)),
  'ticks', jsonb_build_array(
     jsonb_build_object('event_id', 'mem1', 'book', 'snai', 'at', (now() - interval '2 hours')::text, 'c', '[100001,100002,100003]'::jsonb, 'p', '[1.9,3.5,4.2]'::jsonb),
     jsonb_build_object('event_id', 'mem1', 'book', 'pinnacle', 'at', (now() - interval '2 hours')::text, 'c', '[100001,100002,100003]'::jsonb, 'p', '[1.95,3.7,4.4]'::jsonb),
     jsonb_build_object('event_id', 'ghost', 'book', 'snai', 'at', now()::text, 'c', '[100001]'::jsonb, 'p', '[2]'::jsonb)),
  'fits', jsonb_build_array(jsonb_build_object('event_id', 'mem1', 'at', (now() - interval '2 hours')::text, 'p', '[0.5,0.26,0.24,0.55]'::jsonb,
     'lh', 1.6, 'la', 1.0, 'rho', -0.05, 'err', 0, 'sharp', 1, 'nb', 2, 'tier', 'ref', 'src_at', (now() - interval '2 hours')::text)),
  'state', jsonb_build_object('why', 'due')));
select pg_temp.ok((select count(*) = 1 from public.memory_events where event_id = 'mem1' and match_id = 'nap-rom' and league = 'Serie A'), 'the event is in the memory');
select pg_temp.ok((select count(*) = 2 from public.price_ticks where event_id = 'mem1'), 'one reading for SNAI and one for Pinnacle');
select pg_temp.ok((select c = '{100001,100002,100003}'::int[] and p[1] = 1.9::real from public.price_ticks where event_id = 'mem1' and book = 'snai'), 'JSON arrays become the packed codes and the prices');
select pg_temp.ok((select count(*) = 0 from public.price_ticks where event_id = 'ghost'), 'a reading of an event not in the memory is left out (no orphan)');
select pg_temp.ok((select count(*) = 1 from public.fit_ticks where event_id = 'mem1' and nb = 2 and tier = 'ref' and p[4] = 0.55::real), 'the fit is kept');
select pg_temp.ok((select ref -> 'pinnacle' -> 0 ->> 3 = '1.95' from public.book_events where event_id = 'mem1'), 'the sharp book''s latest prices sit beside SNAI''s');

-- a second reading: SNAI's home price moved, the away price padlocked; the same reading sent twice is stored once
select public.feed_save(jsonb_build_object(
  'events', jsonb_build_array(jsonb_build_object('event_id', 'mem1', 'home', 'Napoli', 'away', 'Roma', 'league', 'Serie A',
     'commence_time', (now() + interval '3 hours')::text, 'm', '[[3,0,1,1.85],[3,0,2,3.5],[3,0,3,null]]'::jsonb)),
  'ticks', jsonb_build_array(
     jsonb_build_object('event_id', 'mem1', 'book', 'snai', 'at', (now() - interval '1 hour')::text, 'c', '[100001,100003]'::jsonb, 'p', '[1.85,null]'::jsonb),
     jsonb_build_object('event_id', 'mem1', 'book', 'snai', 'at', (now() - interval '1 hour')::text, 'c', '[100001,100003]'::jsonb, 'p', '[1.85,null]'::jsonb),
     jsonb_build_object('event_id', 'mem1', 'book', 'snai', 'at', now()::text, 'c', '[]'::jsonb, 'p', '[]'::jsonb)),
  'state', jsonb_build_object('why', 'due')));
select pg_temp.ok((select count(*) = 2 from public.price_ticks where event_id = 'mem1' and book = 'snai'), 'a second reading is added, a repeated one and an empty one are not');
select pg_temp.ok((select p[2] is null from public.price_ticks where event_id = 'mem1' and book = 'snai' and cardinality(c) = 2), 'a padlock is kept as null');
select pg_temp.ok((select match_id = 'nap-rom' from public.memory_events where event_id = 'mem1'), 'a later reading without the match keeps the pairing');
select pg_temp.ok((select ref is not null from public.book_events where event_id = 'mem1'), 'a pull without the sharp books keeps their last prices');
-- a reading after the kick-off does not count as the close
select public.feed_save(jsonb_build_object(
  'events', jsonb_build_array(jsonb_build_object('event_id', 'mem2', 'home', 'Lecce', 'away', 'Como', 'league', 'Serie A', 'commence_time', (now() - interval '30 minutes')::text)),
  'ticks', jsonb_build_array(
     jsonb_build_object('event_id', 'mem2', 'book', 'snai', 'at', (now() - interval '40 minutes')::text, 'c', '[100001]'::jsonb, 'p', '[2.5]'::jsonb),
     jsonb_build_object('event_id', 'mem2', 'book', 'snai', 'at', (now() - interval '10 minutes')::text, 'c', '[100001]'::jsonb, 'p', '[1.4]'::jsonb)),
  'state', jsonb_build_object('why', 'due')));
reset role;

-- the decoded rows and the closing prices
select pg_temp.ok((select count(*) = 4 from public.price_ticks_v where event_id = 'mem1' and book = 'snai' and market = 3 and line = 0 and outcome in (1, 3)), 'the view decodes market, line and outcome');
select pg_temp.ok((select price = 1.85::real from public.closing_prices where event_id = 'mem1' and book = 'snai' and outcome = 1 and market = 3), 'the close is the last price read before the kick-off');
select pg_temp.ok((select price = 3.5::real from public.closing_prices where event_id = 'mem1' and book = 'snai' and code = 100002), 'a price that never moved closes at its first reading');
select pg_temp.ok((select price is null from public.closing_prices where event_id = 'mem1' and book = 'snai' and code = 100003), 'a padlock at the close is a close with no price');
select pg_temp.ok((select price = 2.5::real and minutes_before between 9 and 11 from public.closing_prices where event_id = 'mem2' and book = 'snai'), 'a reading after the kick-off is not the close');

-- who reads it: the owner only; the anonymous key and another account nothing; nobody writes but the function
set role anon;
do $$ begin perform 1 from public.price_ticks; raise exception 'FAIL: the anonymous key read the memory'; exception when insufficient_privilege then null; end $$;
do $$ begin perform 1 from public.memory_events; raise exception 'FAIL: the anonymous key read the events'; exception when insufficient_privilege then null; end $$;
do $$ begin perform public.memory_stats(); raise exception 'FAIL: the anonymous key read the stats'; exception when insufficient_privilege then null; end $$;
reset role;
set role authenticated;
set request.jwt.claim.sub = '22222222-2222-2222-2222-222222222222';
select pg_temp.ok((select count(*) = 0 from public.price_ticks) and (select count(*) = 0 from public.fit_ticks) and (select count(*) = 0 from public.closing_prices) and (select count(*) = 0 from public.price_ticks_v) and (select count(*) = 0 from public.memory_events), 'another account reads nothing');
select pg_temp.ok(public.memory_stats() is null, 'another account gets no stats');
set request.jwt.claim.sub = '11111111-1111-1111-1111-111111111111';
select pg_temp.ok((select count(*) = 5 from public.price_ticks) and (select count(*) >= 1 from public.closing_prices), 'the owner reads the memory and the closes');
select pg_temp.ok((public.memory_stats() ->> 'readings')::int = 5 and (public.memory_stats() ->> 'bytes')::bigint > 0, 'the owner sees how big the memory is');
do $$ begin insert into public.price_ticks (event_id, book, at, c, p) values ('mem1', 'snai', now(), '{1}', '{2}'); raise exception 'FAIL: the owner wrote a reading'; exception when insufficient_privilege then null; end $$;
do $$ begin delete from public.memory_events; raise exception 'FAIL: the owner deleted the memory'; exception when insufficient_privilege then null; end $$;
do $$ begin perform public.feed_save('{}'::jsonb); raise exception 'FAIL: the site called feed_save'; exception when insufficient_privilege then null; end $$;
reset request.jwt.claim.sub;
reset role;

-- a reading must have as many prices as codes
do $$ begin insert into public.price_ticks (event_id, book, at, c, p) values ('mem1', 'x', now(), '{1,2}', '{2}'); raise exception 'FAIL: a reading with a price missing was stored'; exception when check_violation then null; end $$;
-- 200 days after the kick-off an event and its readings go
update public.memory_events set commence_time = now() - interval '201 days' where event_id = 'mem2';
set role service_role;
select public.feed_save(jsonb_build_object('state', jsonb_build_object('why', 'due')));
reset role;
select pg_temp.ok((select count(*) = 0 from public.memory_events where event_id = 'mem2') and (select count(*) = 0 from public.price_ticks where event_id = 'mem2'), 'an event 200 days old goes, with its readings');
select pg_temp.ok((select count(*) = 1 from public.memory_events where event_id = 'mem1'), 'a recent one stays');
-- book_events still clears a match a day after it started; the memory keeps it
update public.book_events set commence_time = now() - interval '2 days' where event_id = 'mem1';
update public.memory_events set commence_time = now() - interval '2 days' where event_id = 'mem1';
set role service_role;
select public.feed_save(jsonb_build_object('state', jsonb_build_object('why', 'due')));
reset role;
select pg_temp.ok((select count(*) = 0 from public.book_events where event_id = 'mem1') and (select count(*) = 3 from public.price_ticks where event_id = 'mem1'), 'the current prices clear after the match, the memory stays');

select 'memory sql checks passed';
