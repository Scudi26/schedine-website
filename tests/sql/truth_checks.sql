-- Checks for the results, the closing truth and SNAI against the close (decision 98), run on a local Postgres after
-- supabase_stub.sql, every migration and feed_checks.sql (which makes the owner 1111… and a second account 2222…).
-- Every check raises an exception when it fails; the last line prints "truth sql checks passed". Reference numbers come
-- from the feed's own maths (snai-pull/logic.mjs: powerDevig, summaryOf) and a Python mirror of its 0..9 matrix.
\set ON_ERROR_STOP on
create or replace function pg_temp.ok(cond boolean, msg text) returns void language plpgsql as $$
begin if not coalesce(cond, false) then raise exception 'FAIL: %', msg; end if; end $$;
create or replace function pg_temp.near(a double precision, b double precision, msg text) returns void language plpgsql as $$
begin if a is null or abs(a - b) > 1e-9 then raise exception 'FAIL: % (got %, want %)', msg, a, b; end if; end $$;
-- the fit's expected goals are stored as real (about 7 digits): its chances agree to 1e-7
create or replace function pg_temp.near7(a double precision, b double precision, msg text) returns void language plpgsql as $$
begin if a is null or abs(a - b) > 1e-7 then raise exception 'FAIL: % (got %, want %)', msg, a, b; end if; end $$;

-- ---------- the maths ----------
select pg_temp.near((public.devig_power(array[2.05, 3.50, 3.95]))[1], 0.478910669284, 'power de-vig as the feed''s: home');
select pg_temp.near((public.devig_power(array[2.05, 3.50, 3.95]))[3], 0.244404664071, 'power de-vig as the feed''s: away');
select pg_temp.near((public.devig_power(array[1.9, 3.5, 4.2]))[2], 0.268480001209, 'power de-vig on another market');
select pg_temp.near((public.devig_power(array[2.1, 2.1]))[1], 0.5, 'prices adding up to under 100% are only normalised');
select pg_temp.ok(public.devig_power(array[1.0, 3.0]) is null and public.devig_power(array[2.0]) is null and public.devig_power(array[2.0, null]) is null,
                  'no fair chances from a price of 1, a single price or a missing one');
create temp table dc as select * from public.dc_chances(1.6, 1.0, -0.05);
select pg_temp.near((select p from dc where code = 100001), 0.507492171272, 'the matrix: home win as the site''s summaryOf');
select pg_temp.near((select p from dc where code = 100002), 0.261884385118, 'the matrix: draw');
select pg_temp.near((select p from dc where code = 302502), 0.481566663496, 'the matrix: over 2.5');
select pg_temp.near((select p from dc where code = 301502), 0.738555108238, 'the matrix: over 1.5');
select pg_temp.near((select p from dc where code = 303501), 0.736006983171, 'the matrix: under 3.5');
select pg_temp.near((select p from dc where code = 400001), 0.525438604165, 'both to score with decision 60''s +1.5 points');
select pg_temp.near((select p from dc where code = 200003), 0.261884385118 + 0.23062344361, 'X2 = draw + away');
select pg_temp.ok((select count(*) = 14 from dc) and (select abs(sum(p) - 1) < 1e-12 from dc where code / 100000 = 1), 'fourteen selections, the result adding up to one');
select pg_temp.near((select p from public.dc_chances(3, 3, 0.2) where code = 302502), 0.937894329543, 'an out-of-range correction is clipped like the site''s');
select pg_temp.ok(not exists (select 1 from public.dc_chances(0, 1, 0)) and not exists (select 1 from public.dc_chances(null, 1, 0)), 'no matrix without expected goals');
select pg_temp.ok(public.settles(100001, 2, 1) and not public.settles(100002, 2, 1) and public.settles(200001, 1, 1) and public.settles(200002, 0, 2)
                  and not public.settles(200003, 2, 1) and public.settles(302502, 2, 1) and public.settles(301501, 1, 0) and not public.settles(303501, 3, 1)
                  and public.settles(400001, 1, 1) and public.settles(400002, 0, 3) and public.settles(100001, null, 1) is null, 'every selection settles on the 90-minute score');

-- ---------- a match through the memory: SNAI, Pinnacle, the Betfair exchange, Scudi's fit, the result ----------
delete from public.memory_events;   -- the earlier check files' events (their readings go with them): this match starts a clean memory
select now() - interval '2 hours' as k1, now() - interval '3 hours' as k2, now() + interval '1 day' as k3, now() - interval '4 hours' as k4, now() - interval '5 hours' as k5 \gset
set role service_role;
-- the first reading, 30 hours before T1's kick-off
select public.feed_save(jsonb_build_object(
  'events', jsonb_build_array(
     jsonb_build_object('event_id', 'T1', 'home', 'Napoli', 'away', 'Roma', 'league', 'Serie A', 'commence_time', :'k1', 'match_id', 'mt1',
                        'near_at', (:'k1'::timestamptz - interval '30 hours')::text, 'near_books', '["snai","pinnacle"]'::jsonb),
     jsonb_build_object('event_id', 'T2', 'home', 'Lecce', 'away', 'Como', 'league', 'Serie A', 'commence_time', :'k2', 'match_id', 'mt2'),
     jsonb_build_object('event_id', 'T3', 'home', 'Inter', 'away', 'Milan', 'league', 'Serie A', 'commence_time', :'k3', 'match_id', 'mt3'),
     -- T4: Pinnacle priced it once, but was gone at the last full reading; T5: only a fit made without a goals line
     jsonb_build_object('event_id', 'T4', 'home', 'Bari', 'away', 'Pisa', 'league', 'Serie B', 'commence_time', :'k4', 'match_id', 'mt4',
                        'near_at', (:'k4'::timestamptz - interval '10 minutes')::text, 'near_books', '["snai","betfair_ex_eu"]'::jsonb),
     jsonb_build_object('event_id', 'T5', 'home', 'Leeds', 'away', 'Hull', 'league', 'Championship', 'commence_time', :'k5', 'match_id', 'mt5')),
  'ticks', jsonb_build_array(
     jsonb_build_object('event_id', 'T1', 'book', 'snai', 'at', (:'k1'::timestamptz - interval '30 hours')::text,
                        'c', '[100001,100002,100003,302501,302502,400001,400002]'::jsonb, 'p', '[2.10,3.30,3.60,1.95,1.85,1.80,1.95]'::jsonb),
     jsonb_build_object('event_id', 'T1', 'book', 'pinnacle', 'at', (:'k1'::timestamptz - interval '30 hours')::text,
                        'c', '[100001,100002,100003,302501,302502,303501,303502]'::jsonb, 'p', '[2.20,3.40,3.70,2.05,1.85,null,2.40]'::jsonb),
     jsonb_build_object('event_id', 'T1', 'book', 'betfair_ex_eu', 'at', (:'k1'::timestamptz - interval '30 hours')::text,
                        'c', '[100001,100002,100003,400001,400002]'::jsonb, 'p', '[2.30,3.30,3.50,1.75,2.25]'::jsonb),
     jsonb_build_object('event_id', 'T1', 'book', 'bet365', 'at', (:'k1'::timestamptz - interval '30 hours')::text,
                        'c', '[100001,100002,100003]'::jsonb, 'p', '[1.50,4.00,6.00]'::jsonb),
     jsonb_build_object('event_id', 'T2', 'book', 'snai', 'at', (:'k2'::timestamptz - interval '5 hours')::text,
                        'c', '[100001,100002,100003]'::jsonb, 'p', '[2.50,3.10,2.90]'::jsonb),
     jsonb_build_object('event_id', 'T4', 'book', 'snai', 'at', (:'k4'::timestamptz - interval '30 hours')::text, 'c', '[100001,100002,100003,302501,302502]'::jsonb, 'p', '[2.00,3.20,3.80,1.80,1.95]'::jsonb),
     jsonb_build_object('event_id', 'T4', 'book', 'pinnacle', 'at', (:'k4'::timestamptz - interval '30 hours')::text, 'c', '[100001,100002,100003]'::jsonb, 'p', '[1.60,4.20,6.00]'::jsonb),
     jsonb_build_object('event_id', 'T4', 'book', 'betfair_ex_eu', 'at', (:'k4'::timestamptz - interval '30 hours')::text, 'c', '[100001,100002,100003]'::jsonb, 'p', '[2.10,3.40,4.00]'::jsonb),
     jsonb_build_object('event_id', 'T5', 'book', 'snai', 'at', (:'k5'::timestamptz - interval '3 hours')::text, 'c', '[100001,100002,100003,302502]'::jsonb, 'p', '[2.20,3.20,3.30,1.90]'::jsonb)),
  'fits', jsonb_build_array(jsonb_build_object('event_id', 'T1', 'at', (:'k1'::timestamptz - interval '1 hour')::text, 'p', '[0.40,0.30,0.30,0.43]'::jsonb,
                        'lh', 1.3, 'la', 1.1, 'rho', -0.08, 'err', 0, 'sharp', 1, 'nb', 3, 'tier', 'ref'),
     jsonb_build_object('event_id', 'T4', 'at', (:'k4'::timestamptz - interval '60 hours')::text, 'p', '[0.40,0.30,0.30,0.43]'::jsonb,
                        'lh', 1.3, 'la', 1.1, 'rho', -0.08, 'err', 0, 'sharp', 1, 'nb', 3, 'tier', 'ref'),
     jsonb_build_object('event_id', 'T5', 'at', (:'k5'::timestamptz - interval '1 hour')::text, 'p', '[0.40,0.30,0.30,null]'::jsonb,
                        'lh', 1.3, 'la', 1.1, 'rho', -0.08, 'err', 0, 'sharp', 0, 'nb', 3, 'tier', 'it')),
  'state', jsonb_build_object('why', 'due')));
-- two hours before: SNAI's home price moves
select public.feed_save(jsonb_build_object(
  'events', jsonb_build_array(jsonb_build_object('event_id', 'T1', 'home', 'Napoli', 'away', 'Roma', 'league', 'Serie A', 'commence_time', :'k1',
                              'near_at', (:'k1'::timestamptz - interval '2 hours')::text, 'near_books', '["snai","pinnacle"]'::jsonb)),
  'ticks', jsonb_build_array(jsonb_build_object('event_id', 'T1', 'book', 'snai', 'at', (:'k1'::timestamptz - interval '2 hours')::text, 'c', '[100001]'::jsonb, 'p', '[2.00]'::jsonb)),
  'state', jsonb_build_object('why', 'due')));
-- the closing pull, eight minutes before: SNAI's home price again, Pinnacle's whole result market
select public.feed_save(jsonb_build_object(
  'events', jsonb_build_array(jsonb_build_object('event_id', 'T1', 'home', 'Napoli', 'away', 'Roma', 'league', 'Serie A', 'commence_time', :'k1',
                              'near_at', (:'k1'::timestamptz - interval '8 minutes')::text, 'near_books', '["snai","pinnacle","betfair_ex_eu"]'::jsonb)),
  'ticks', jsonb_build_array(
     jsonb_build_object('event_id', 'T1', 'book', 'snai', 'at', (:'k1'::timestamptz - interval '8 minutes')::text, 'c', '[100001]'::jsonb, 'p', '[1.95]'::jsonb),
     jsonb_build_object('event_id', 'T1', 'book', 'pinnacle', 'at', (:'k1'::timestamptz - interval '8 minutes')::text, 'c', '[100001,100002,100003]'::jsonb, 'p', '[2.05,3.50,3.95]'::jsonb)),
  'state', jsonb_build_object('why', 'closing')));
-- a reading after the kick-off (live prices): never part of the close, and it does not move near_at
select public.feed_save(jsonb_build_object(
  'events', jsonb_build_array(jsonb_build_object('event_id', 'T1', 'home', 'Napoli', 'away', 'Roma', 'league', 'Serie A', 'commence_time', :'k1')),
  'ticks', jsonb_build_array(jsonb_build_object('event_id', 'T1', 'book', 'snai', 'at', (:'k1'::timestamptz + interval '10 minutes')::text, 'c', '[100001]'::jsonb, 'p', '[1.50]'::jsonb)),
  'state', jsonb_build_object('why', 'due')));
-- the results, as the daily job writes them (with junk the function must leave out)
select pg_temp.ok(public.results_save(jsonb_build_object('done', jsonb_build_object(
  'mt1', jsonb_build_array(2, 1, 1, 0, to_char(:'k1'::timestamptz at time zone 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS') || '+00:00'),
  'bad1', 'x', 'bad2', jsonb_build_array('a', 1, null, null, null), 'bad3', jsonb_build_array(1, 1, 2, 0, null),
  'mt9', jsonb_build_array(0, 0, null, null, null)))) = 3, 'three results saved (bad3 without its impossible half time), the malformed ones left out');
reset role;

select pg_temp.ok((select near_at = :'k1'::timestamptz - interval '8 minutes' and near_books = '{snai,pinnacle,betfair_ex_eu}' from public.memory_events where event_id = 'T1'),
                  'the last full reading before the kick-off is kept, with its books; a later reading without one does not move it');
select pg_temp.ok((select ft_h = 2 and ft_a = 1 and ht_h = 1 and ht_a = 0 and kickoff = date_trunc('second', :'k1'::timestamptz) from public.match_results where match_id = 'mt1'),
                  'the result is stored with its half time and kick-off');
select pg_temp.ok((select ht_h is null and kickoff is null from public.match_results where match_id = 'mt9'), 'a result without half time or kick-off is kept as it is');
select pg_temp.ok((select ft_h = 1 and ft_a = 1 and ht_h is null from public.match_results where match_id = 'bad3'), 'a half time above the final score is left out, the score kept');
select saved_at as s1 from public.match_results where match_id = 'mt1' \gset
set role service_role;
select pg_temp.ok(public.results_save(jsonb_build_object('done', jsonb_build_object('mt1', jsonb_build_array(2, 1, 1, 0, null), 'mt9', jsonb_build_array(0, 0, null, null, null)))) = 0
                  and public.results_save(jsonb_build_object('done', jsonb_build_object('mt1', jsonb_build_array(2, 1, null, null, null)))) = 0,
                  'the same results again (or one without its half time) change nothing');
select pg_temp.ok(public.results_save(jsonb_build_object('done', jsonb_build_object('mt9', jsonb_build_array(1, 0, null, null, null)))) = 1, 'a corrected score is saved');
reset role;
select pg_temp.ok((select saved_at = :'s1'::timestamptz and kickoff is not null and ht_h = 1 from public.match_results where match_id = 'mt1'), '… and the stored row keeps its time, kick-off and half time');

-- the truth at T1's kick-off
create temp table tr as select * from public.truth_of('T1');
select pg_temp.ok((select count(*) = 14 from tr), 'fourteen selections have a fair chance');
select pg_temp.near((select p from tr where code = 100001), 0.478910669284, 'the result from Pinnacle''s closing prices');
select pg_temp.ok((select source = 'pinnacle' and src_at = :'k1'::timestamptz - interval '8 minutes' from tr where code = 100001),
                  '… named, with the time of the closing pull (Pinnacle first, though the exchange priced the result too)');
select pg_temp.near((select p from tr where code = 200001), 0.478910669284 + 0.276684666645, 'the double chance from the result''s fair chances');
select pg_temp.near((select p from tr where code = 302501), 0.473281344635, 'under 2.5 from Pinnacle''s price that never moved');
select pg_temp.ok((select source = 'pinnacle' and src_at = :'k1'::timestamptz - interval '30 hours' from tr where code = 302502), '… still the close (only changes are stored)');
select pg_temp.near((select p from tr where code = 400001), 0.563954510357, 'both to score from the exchange: Pinnacle had no price');
select pg_temp.ok((select source = 'betfair_ex_eu' from tr where code = 400002), '… named');
select pg_temp.near7((select p from tr where code = 303501), 0.778724029693, 'under 3.5 from the fit: Pinnacle''s under was padlocked');
select pg_temp.near7((select p from tr where code = 301502), 0.701936664497, 'over 1.5 from the fit: no book priced it');
select pg_temp.ok((select bool_and(source = 'fit') from tr where code in (301501, 301502, 303501, 303502)), '… named as the fit');
select pg_temp.ok(not exists (select 1 from tr where source = 'bet365' or source = 'snai'), 'bet365 and SNAI never make the truth');
select pg_temp.ok(not exists (select 1 from public.truth_of('T2')), 'no sharp book and no fit: no truth');
create temp table tr4 as select * from public.truth_of('T4');
select pg_temp.ok((select bool_and(source = 'betfair_ex_eu') and count(*) = 6 from tr4),
                  'Pinnacle had gone at the last full reading: its old price is not the close; the exchange is, and a fit from 60 hours before says nothing');
select pg_temp.near((select p from tr4 where code = 100001), (public.devig_power(array[2.10, 3.40, 4.00]))[1], '… the exchange''s home win');
create temp table tr5 as select * from public.truth_of('T5');
select pg_temp.ok((select count(*) = 6 and bool_and(source = 'fit:it') and bool_and(code / 100000 <= 2) from tr5),
                  'a fit made without a goals line gives the result and double chances only, named as the Italian books'' fit');

-- SNAI against the close
create temp table sv as select * from public.snai_vs_close();
select pg_temp.ok((select count(*) = 42 from sv where event_id = 'T1') and not exists (select 1 from sv where event_id in ('T2', 'T3')),
                  'T1: seven SNAI selections at six checkpoints (none 48 hours before the first reading); T2 has no truth, T3 has not started');
select pg_temp.ok((select count(*) = 3 * 6 from sv where event_id = 'T4') and (select count(*) = 3 * 3 from sv where event_id = 'T5'),
                  'T4 and T5: only the selections with a truth (the result), at every checkpoint after the first reading');
select pg_temp.ok((select price = 1.95::real and read_at = :'k1'::timestamptz - interval '8 minutes' and won and confirmed from sv where event_id = 'T1' and code = 100001 and hours_before = 0),
                  'at the kick-off: SNAI''s last price before it, won, the close confirmed by the closing pull');
select pg_temp.near((select clv from sv where event_id = 'T1' and code = 100001 and hours_before = 0), 1.95 * 0.478910669284 - 1, 'CLV = SNAI''s price × the fair chance − 1');
select pg_temp.ok((select price = 2.00::real from sv where event_id = 'T1' and code = 100001 and hours_before = 1) and (select price = 2.10::real from sv where event_id = 'T1' and code = 100001 and hours_before = 3)
                  and (select price = 2.10::real from sv where event_id = 'T1' and code = 100001 and hours_before = 24), 'each checkpoint takes the price as it stood then');
select pg_temp.ok(not exists (select 1 from sv where price = 1.50::real), 'a price read after the kick-off is never used');
select pg_temp.near((select clv from sv where event_id = 'T1' and code = 400001 and hours_before = 0), 1.80 * 0.563954510357 - 1, 'GG at SNAI against the exchange''s close');
select pg_temp.ok((select won from sv where event_id = 'T1' and code = 302502 and hours_before = 0) and not (select won from sv where event_id = 'T1' and code = 100002 and hours_before = 0)
                  and not (select won from sv where event_id = 'T1' and code = 400002 and hours_before = 0), 'over 2.5 and GG won on 2-1, the draw and NG lost');

-- the map and the health check
create temp table mp as select * from public.snai_map(hours => 0);
select pg_temp.ok((select count(*) = 4 from mp where league = 'Serie A'), 'four Serie A cells: two result price bands, under/over 2.5, goal/no goal');
select pg_temp.ok((select n = 2 and settled = 2 and won = 0 from mp where league = 'Serie A' and market = '1X2' and band = '3.00-4.99'), 'draw and away at 3.30 and 3.60, both lost');
select pg_temp.near((select expected from mp where league = 'Serie A' and market = '1X2' and band = '3.00-4.99'), 0.276684666645 + 0.244404664071, 'what the close expected them to win');
select pg_temp.ok((select n = 2 and won = 1 from mp where league = 'Serie A' and market = 'Under/over 2.5'), 'the under/over 2.5 cell is labelled with its line');
create temp table hl as select public.radar_health(7) as j;
select pg_temp.ok((select (j ->> 'matches')::int = 4 and (j ->> 'closing_read')::int = 2 and (j ->> 'snai_priced')::int = 4 and (j ->> 'pinnacle_at_close')::int = 1
                   and (j ->> 'sharp_at_close')::int = 2 and (j ->> 'fit_only')::int = 1 and (j ->> 'no_truth')::int = 1 and (j ->> 'with_result')::int = 1
                   and (j -> 'by_league' -> 'Serie A' ->> 'matches')::int = 2 and (j ->> 'database_mb')::numeric > 0 from hl),
                  'the health check: four finished matches, two closed, Pinnacle at the close only where it was still there, one with no truth');

-- who can see and do what
set role anon;
do $$ begin perform public.radar_health(7); raise exception 'FAIL: the anonymous key ran the health check'; exception when insufficient_privilege then null; end $$;
do $$ begin perform * from public.snai_vs_close(); raise exception 'FAIL: the anonymous key read SNAI against the close'; exception when insufficient_privilege then null; end $$;
do $$ begin perform 1 from public.match_results; raise exception 'FAIL: the anonymous key read the results'; exception when insufficient_privilege then null; end $$;
do $$ begin perform public.results_save('{}'::jsonb); raise exception 'FAIL: the anonymous key saved results'; exception when insufficient_privilege then null; end $$;
reset role;
set role authenticated;
set request.jwt.claim.sub = '22222222-2222-2222-2222-222222222222';
select pg_temp.ok((select count(*) = 0 from public.snai_vs_close()) and (select count(*) = 0 from public.match_results)
                  and (public.radar_health(7) ->> 'matches')::int = 0 and not exists (select 1 from public.truth_of('T1')), 'another account sees nothing');
set request.jwt.claim.sub = '11111111-1111-1111-1111-111111111111';
select pg_temp.ok((select count(*) = 42 + 18 + 9 from public.snai_vs_close()) and (public.radar_health(7) ->> 'with_result')::int = 1, 'the owner sees it all');
do $$ begin perform public.results_save('{}'::jsonb); raise exception 'FAIL: the site saved results'; exception when insufficient_privilege then null; end $$;
do $$ begin insert into public.match_results (match_id, ft_h, ft_a) values ('x', 1, 0); raise exception 'FAIL: the owner wrote a result'; exception when insufficient_privilege then null; end $$;
reset request.jwt.claim.sub;
reset role;
do $$ begin insert into public.match_results (match_id, ft_h, ft_a, ht_h, ht_a) values ('y', 1, 0, 2, 0); raise exception 'FAIL: a half time above the final score was stored'; exception when check_violation then null; end $$;

select 'truth sql checks passed';
