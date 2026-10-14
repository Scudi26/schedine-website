-- Checks for the "SNAI vs the close" page's one call (decision 99), run on a local Postgres after truth_checks.sql, on its
-- matches: T1 Napoli – Roma (closed by the closing pull, Pinnacle's close, won 2-1), T2 (no truth), T3 (not started),
-- T4 Bari – Pisa (closed, the exchange's close, no result yet), T5 Leeds – Hull (never closed: an unconfirmed close).
-- Every expected number is recomputed here straight from public.snai_vs_close(), another way. Last line: "page sql checks passed".
\set ON_ERROR_STOP on
create or replace function pg_temp.ok(cond boolean, msg text) returns void language plpgsql as $$
begin if not coalesce(cond, false) then raise exception 'FAIL: %', msg; end if; end $$;
create or replace function pg_temp.near(a double precision, b double precision, tol double precision, msg text) returns void language plpgsql as $$
begin if a is null or b is null or abs(a - b) > tol then raise exception 'FAIL: % (got %, want %)', msg, a, b; end if; end $$;
-- one group of the page: kind, hours, market, selection, league, band → its array
create or replace function pg_temp.grp(j jsonb, k text, h int, mk int, code int, lg text, band real) returns jsonb language sql as $$
  select g from jsonb_array_elements(j -> 'groups') g
   where g ->> 0 = k and (g ->> 1)::int = h and (g ->> 2)::int is not distinct from mk and (g ->> 3)::int is not distinct from code
     and g ->> 4 is not distinct from lg and (g ->> 5)::real is not distinct from band $$;

-- T5's result arrives (0-0): its fit-based truth can be checked against it when the unconfirmed closes are let in
set role service_role;
select pg_temp.ok(public.results_save(jsonb_build_object('done', jsonb_build_object('mt5', jsonb_build_array(0, 0, 0, 0, null)))) = 1, 'T5''s result saved');
-- T6 Cosenza – Bari: finished, read in full three hours before its kick-off and never again (no closing reading), SNAI never priced
select public.feed_save(jsonb_build_object('events', jsonb_build_array(jsonb_build_object('event_id', 'T6', 'home', 'Cosenza', 'away', 'Bari', 'league', 'Serie B',
  'commence_time', (now() - interval '1 hour')::text, 'match_id', 'mt6', 'near_at', (now() - interval '4 hours')::text, 'near_books', '["pinnacle"]'::jsonb)),
  'state', jsonb_build_object('why', 'due')));
reset role;
set role authenticated;
set request.jwt.claim.sub = '11111111-1111-1111-1111-111111111111';
create temp table pc_pg as select public.radar_page(7) as j;
create temp table pc_all as select public.radar_page(7, false) as j;
create temp table pc_sv as select * from public.snai_vs_close(now() - interval '7 days', now());

-- everything at the kick-off: only the confirmed closes (T1, T4); T5 is left out and counted
select pg_temp.ok((select (j ->> 'days')::int = 7 and (j ->> 'confirmed_only')::boolean and (j ->> 'left_out')::int = 1 from pc_pg), 'seven days, confirmed closes only, T5 left out and counted');
select pg_temp.ok((select (pg_temp.grp(j, 'a', 0, null, null, null, null) ->> 7)::int = (select count(*) from pc_sv where hours_before = 0 and confirmed)
                      and (pg_temp.grp(j, 'a', 0, null, null, null, null) ->> 6)::int = 2 from pc_pg), 'all prices at the kick-off: T1''s seven and T4''s three, from two matches');
select pg_temp.near((select (pg_temp.grp(j, 'a', 0, null, null, null, null) ->> 8)::double precision from pc_pg),
                    (select avg(clv) from pc_sv where hours_before = 0 and confirmed), 5e-6, 'the average CLV is the prices'' average');
-- the standard error, recomputed directly (not expanded): sqrt(G/(G−1) Σ_e (s_e − m k_e)²) / n
select pg_temp.near((select (pg_temp.grp(j, 'a', 0, null, null, null, null) ->> 9)::double precision from pc_pg),
  (with c as (select event_id, sum(clv) s, count(*) k from pc_sv where hours_before = 0 and confirmed group by event_id),
        m as (select sum(s) / sum(k) m, sum(k) n, count(*) g from c)
   select sqrt(m.g::double precision / (m.g - 1) * (select sum((c.s - m.m * c.k) ^ 2) from c)) / m.n from m), 5e-6,
  'the standard error counts each match once');
select pg_temp.near((select (pg_temp.grp(j, 'a', 0, null, null, null, null) ->> 10)::double precision from pc_pg),
                    (select avg(case when clv > 0 then 1.0 else 0.0 end) from pc_sv where hours_before = 0 and confirmed), 5e-5, 'the share beating the close');
select pg_temp.ok((select g ->> 11 = '7' and g ->> 12 = '3' from pc_pg, lateral (select pg_temp.grp(j, 'a', 0, null, null, null, null) as g) q),
                  'settled and won: T1''s seven prices settled (T4 has no result), three won');
select pg_temp.near((select (pg_temp.grp(j, 'a', 0, null, null, null, null) ->> 13)::double precision from pc_pg),
                    (select sum(p_fair) from pc_sv where hours_before = 0 and confirmed and won is not null), 1e-3, '… the wins the close expected, on the settled prices only');
select pg_temp.ok((select (pg_temp.grp(j, 'a', 0, null, null, null, null) ->> 7)::int = (select count(*) from pc_sv where hours_before = 0)
                      and (j ->> 'left_out')::int = 0 from pc_all), 'with the unconfirmed closes too: T5''s three prices join, nothing left out');

-- a league × market cell, a selection, a band
select pg_temp.ok((select g ->> 6 = '1' and g ->> 7 = '3' and g ->> 11 = '3' and g ->> 12 = '1' and g ->> 9 is null
                     from pc_pg, lateral (select pg_temp.grp(j, 'lm', 0, 1, null, 'Serie A', null) as g) q),
                  'Serie A 1X2 at the kick-off: T1''s three prices, all settled, the home win won; one match → no standard error');
select pg_temp.near((select (pg_temp.grp(j, 'lm', 0, 1, null, 'Serie A', null) ->> 13)::double precision from pc_pg), 1.0, 1e-3, '… the three fair chances add up to one expected win');
select pg_temp.ok((select g ->> 6 = '1' and g ->> 7 = '3' and g ->> 11 = '0' from pc_pg, lateral (select pg_temp.grp(j, 'lm', 0, 1, null, 'Serie B', null) as g) q)
                  and (select count(*) = 2 from pc_pg, jsonb_array_elements(j -> 'groups') g where g ->> 0 = 'lm' and g ->> 1 = '0' and g ->> 2 = '1'),
                  'Serie B 1X2: T4''s three prices, none settled; two league cells for the result market');
select pg_temp.ok((select g ->> 6 = '2' and g ->> 7 = '2' and g ->> 11 = '1' and g ->> 12 = '1'
                     from pc_pg, lateral (select pg_temp.grp(j, 's', 0, 1, 100001, null, null) as g) q),
                  'the home win: T1 and T4, only T1 settled (T4 has no result yet)');
select pg_temp.near((select (pg_temp.grp(j, 's', 0, 1, 100001, null, null) ->> 8)::double precision from pc_pg),
                    (select avg(clv) from pc_sv where hours_before = 0 and confirmed and code = 100001), 5e-6, '… its average CLV');
select pg_temp.ok((select pg_temp.grp(j, 'lmb', 0, 1, null, 'Serie A', 1.5) is not null and pg_temp.grp(j, 'mb', 0, 4, null, null, 1.5) is not null
                      and pg_temp.grp(j, 'lm', 0, 3250, null, 'Serie A', null) is not null from pc_pg),
                  'T1''s home win at 1.95 sits in the 1.50–1.99 band; GG at 1.80 too; the 2.5 line is its own market');
select pg_temp.ok((select pg_temp.grp(j, 'm', 0, 3150, null, null, null) is null from pc_pg), 'SNAI never priced the 1.5 line: no such group');
select pg_temp.ok((select g ->> 6 = '2' and g ->> 7 = '6' from pc_pg, lateral (select pg_temp.grp(j, 'mp', 24, 1, null, null, null) as g) q)
                  and (select count(*) filter (where g ->> 0 = 'mp' and (g ->> 1)::int > 24) = 0 and count(*) filter (where g ->> 0 = 'mp' and g ->> 1 = '0') > 0
                         from pc_pg, jsonb_array_elements(j -> 'groups') g),
                  'like for like: the result''s six prices of T1 and T4, priced at every checkpoint from 24 hours to the kick-off; nothing at 48');
select pg_temp.ok((select count(*) filter (where g ->> 0 = 'lmb') > 0 and count(*) filter (where g ->> 0 = 'lmb' and g ->> 1 <> '0') = 0 from pc_pg, jsonb_array_elements(j -> 'groups') g),
                  'the finest cells (league × market × band) only at the kick-off');

-- the checkpoints: SNAI's price as it stood then
select pg_temp.ok((select pg_temp.grp(j, 'a', 24, null, null, null, null) ->> 6 = '2' and pg_temp.grp(j, 'a', 48, null, null, null, null) is null from pc_pg),
                  '24 hours before: both matches had SNAI prices; 48 hours before: neither had been read');
select pg_temp.near((select (pg_temp.grp(j, 's', 3, 1, 100001, null, null) ->> 8)::double precision from pc_pg),
                    (select avg(clv) from pc_sv where hours_before = 3 and confirmed and code = 100001), 5e-6, 'the home win three hours before, at 2.10 on T1');

-- the calibration, the days, the sources, the dates
select pg_temp.ok((select sum((c ->> 2)::int) = 5 and sum((c ->> 4)::int) = 3 from pc_pg, jsonb_array_elements(j -> 'calib') c),
                  'calibration: T1''s result (three outcomes), over 2.5 and goal — no mirror sides, no double chances (T4 has no result); three won');
select pg_temp.ok((select jsonb_agg(jsonb_build_array((c ->> 1)::int, (c ->> 2)::int, (c ->> 4)::int) order by (c ->> 1)::int) from pc_pg, jsonb_array_elements(j -> 'calib') c)
                    = (select jsonb_agg(jsonb_build_array(b, n, w) order by b) from (select floor(p_fair * 10)::int b, count(*) n, count(*) filter (where won) w
                         from pc_sv where hours_before = 0 and confirmed and won is not null and (code / 100000 = 1 or code in (301502, 302502, 303502, 400001)) group by 1) q),
                  'each selection in its tenth of chance: counted and won as snai_vs_close says');
select pg_temp.ok((select bool_and((c ->> 1)::int between 0 and 9) and bool_and(c ->> 0 = 'sharp') from pc_pg, jsonb_array_elements(j -> 'calib') c),
                  'tenths of chance 0..9; every truth SNAI priced on T1 came from the sharp books (the fit gave only lines SNAI did not price)');
select pg_temp.ok((select sum((c ->> 2)::int) = 3 and sum((c ->> 4)::int) = 1 and sum((c ->> 3)::numeric) between 0.999 and 1.001
                     from pc_all, jsonb_array_elements(j -> 'calib') c where c ->> 0 = 'fit'),
                  'with the unconfirmed closes: T5''s home, draw and away from the Italian books'' fit, the draw won on 0-0, chances adding up to one');
select pg_temp.ok((select sum((x ->> 1)::int) = 5 and sum((x ->> 2)::int) = 2 and sum((x ->> 3)::int) = 2 and sum((x ->> 4)::int) = 2
                     from pc_pg, jsonb_array_elements(j -> 'daily') x),
                  'the days: five matches finished (T3 not yet), two closed (T6''s last full reading was hours before), two graded, two with a result (T1, T5)');
select pg_temp.ok((select sum((x ->> 3)::int) = 3 from pc_all, jsonb_array_elements(j -> 'daily') x), '… three graded with the unconfirmed close let in');
select pg_temp.ok((select jsonb_agg(s order by s ->> 0) = '[["betfair_ex_eu", 2], ["pinnacle", 1]]'::jsonb from pc_pg, jsonb_array_elements(j -> 'sources') s),
                  'the truth''s sources: the exchange on two matches (T1''s goal/no goal, T4), Pinnacle on T1');
select pg_temp.ok((select jsonb_agg(s order by s ->> 0) = '[["betfair_ex_eu", 2], ["fit:it", 1], ["pinnacle", 1]]'::jsonb from pc_all, jsonb_array_elements(j -> 'sources') s),
                  '… and the Italian books'' fit on T5 when it is let in');
select pg_temp.ok((select j ->> 'first_reading' is null and (j ->> 'first_close')::timestamptz = (select min(commence_time) from public.memory_events where event_id in ('T1', 'T4')) from pc_pg),
                  'the first closed match (no scan of every reading for the first one)');
select pg_temp.ok((select (j -> 'health' ->> 'matches')::int = 5 from pc_pg), 'the health check for the same window rides along');
select pg_temp.ok((select (public.radar_page(0) ->> 'days')::int = 1 and (public.radar_page(1000) ->> 'days')::int = 200 and (public.radar_page(null) ->> 'days')::int = 28),
                  'the window is kept between 1 and 200 days, 28 by default');
select pg_temp.ok((select jsonb_array_length(j -> 'groups') = (select count(*) from (select distinct g ->> 0, g ->> 1, g ->> 2, g ->> 3, g ->> 4, g ->> 5 from jsonb_array_elements(j -> 'groups') g) u) from pc_pg),
                  'every group appears once');

-- another account, the anonymous key
set request.jwt.claim.sub = '22222222-2222-2222-2222-222222222222';
select pg_temp.ok((select j -> 'groups' = '[]'::jsonb and j -> 'calib' = '[]'::jsonb and j -> 'daily' = '[]'::jsonb and j ->> 'first_close' is null
                          and (j -> 'health' ->> 'matches')::int = 0 from (select public.radar_page(28) as j) q), 'another account sees an empty page');
reset request.jwt.claim.sub;
reset role;
set role anon;
do $$ begin perform public.radar_page(28); raise exception 'FAIL: the anonymous key read the page'; exception when insufficient_privilege then null; end $$;
reset role;
select pg_temp.ok(not has_function_privilege('anon', 'public.radar_page(int, boolean)', 'execute') and has_function_privilege('authenticated', 'public.radar_page(int, boolean)', 'execute'),
                  'only a signed-in account may call it (and then sees only what row-level security lets it)');

-- ---------- the faster snai_vs_close against the first version, row for row, on hostile readings ----------
-- the first version (decision 98: DISTINCT ON over every checkpoint), kept here only to compare
create or replace function pg_temp.svc_old(since timestamptz default now() - interval '60 days', till timestamptz default now())
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
select now() - interval '3 hours' as hk \gset
set role service_role;
select public.feed_save(jsonb_build_object(
  'events', jsonb_build_array(
     jsonb_build_object('event_id', 'X1', 'home', 'Pisa', 'away', 'Spezia', 'league', 'Serie B', 'commence_time', :'hk', 'match_id', 'mx1',
                        'near_at', (:'hk'::timestamptz - interval '5 minutes')::text, 'near_books', '["snai","pinnacle"]'::jsonb),
     jsonb_build_object('event_id', 'X2', 'home', 'Bari', 'away', 'Modena', 'league', 'Serie B', 'commence_time', :'hk', 'match_id', 'mx2',
                        'near_at', (:'hk'::timestamptz - interval '5 minutes')::text, 'near_books', '["snai","pinnacle"]'::jsonb),
     jsonb_build_object('event_id', 'X3', 'home', 'Monza', 'away', 'Cesena', 'league', 'Serie B', 'commence_time', :'hk', 'match_id', 'mx3',
                        'near_at', (:'hk'::timestamptz - interval '5 minutes')::text, 'near_books', '["snai","pinnacle"]'::jsonb),
     jsonb_build_object('event_id', 'X4', 'home', 'AC Monza', 'away', 'Cesena FC', 'league', 'Serie B', 'commence_time', :'hk', 'match_id', 'mx3',
                        'near_at', (:'hk'::timestamptz - interval '5 minutes')::text, 'near_books', '["snai","pinnacle"]'::jsonb)),
  'ticks', jsonb_build_array(
     -- X1: exactly 48 and 24 hours before, a padlock exactly one hour before, a reading exactly at the kick-off and one after it
     jsonb_build_object('event_id', 'X1', 'book', 'snai', 'at', (:'hk'::timestamptz - interval '48 hours')::text, 'c', '[100001,100002,100003]'::jsonb, 'p', '[2.40,3.20,3.00]'::jsonb),
     jsonb_build_object('event_id', 'X1', 'book', 'snai', 'at', (:'hk'::timestamptz - interval '24 hours')::text, 'c', '[100001]'::jsonb, 'p', '[2.35]'::jsonb),
     jsonb_build_object('event_id', 'X1', 'book', 'snai', 'at', (:'hk'::timestamptz - interval '1 hour')::text, 'c', '[100002]'::jsonb, 'p', '[null]'::jsonb),
     jsonb_build_object('event_id', 'X1', 'book', 'snai', 'at', :'hk', 'c', '[100003]'::jsonb, 'p', '[2.90]'::jsonb),
     jsonb_build_object('event_id', 'X1', 'book', 'snai', 'at', (:'hk'::timestamptz + interval '20 minutes')::text, 'c', '[100001]'::jsonb, 'p', '[1.40]'::jsonb),
     jsonb_build_object('event_id', 'X1', 'book', 'pinnacle', 'at', (:'hk'::timestamptz - interval '5 minutes')::text, 'c', '[100001,100002,100003]'::jsonb, 'p', '[2.45,3.40,3.10]'::jsonb),
     -- X3 and X4: two SNAI events paired with one of Scudi's matches (mx3): one cluster
     jsonb_build_object('event_id', 'X3', 'book', 'snai', 'at', (:'hk'::timestamptz - interval '2 hours')::text, 'c', '[100001,100002,100003]'::jsonb, 'p', '[2.00,3.30,3.90]'::jsonb),
     jsonb_build_object('event_id', 'X3', 'book', 'pinnacle', 'at', (:'hk'::timestamptz - interval '5 minutes')::text, 'c', '[100001,100002,100003]'::jsonb, 'p', '[2.05,3.50,4.10]'::jsonb),
     jsonb_build_object('event_id', 'X4', 'book', 'snai', 'at', (:'hk'::timestamptz - interval '2 hours')::text, 'c', '[100001,100002,100003]'::jsonb, 'p', '[2.02,3.25,3.95]'::jsonb),
     jsonb_build_object('event_id', 'X4', 'book', 'pinnacle', 'at', (:'hk'::timestamptz - interval '5 minutes')::text, 'c', '[100001,100002,100003]'::jsonb, 'p', '[2.05,3.50,4.10]'::jsonb),
     -- X2: first read only one hour before
     jsonb_build_object('event_id', 'X2', 'book', 'snai', 'at', (:'hk'::timestamptz - interval '1 hour')::text, 'c', '[100001,100002,100003]'::jsonb, 'p', '[1.90,3.40,4.20]'::jsonb),
     jsonb_build_object('event_id', 'X2', 'book', 'pinnacle', 'at', (:'hk'::timestamptz - interval '5 minutes')::text, 'c', '[100001,100002,100003]'::jsonb, 'p', '[1.95,3.60,4.40]'::jsonb)),
  'state', jsonb_build_object('why', 'due')));
reset role;
select pg_temp.ok((select count(*) from (select * from pg_temp.svc_old(now() - interval '7 days', now()) except all select * from public.snai_vs_close(now() - interval '7 days', now())) a) = 0
                  and (select count(*) from (select * from public.snai_vs_close(now() - interval '7 days', now()) except all select * from pg_temp.svc_old(now() - interval '7 days', now())) a) = 0
                  and (select count(*) > 0 from public.snai_vs_close(now() - interval '7 days', now()) where event_id = 'X1'),
                  'the faster snai_vs_close gives the first version''s rows exactly, padlocks, checkpoints, kick-off and later readings included');
select pg_temp.ok((select price = 2.40::real from public.snai_vs_close() where event_id = 'X1' and code = 100001 and hours_before = 48)
                  and (select price = 2.35::real from public.snai_vs_close() where event_id = 'X1' and code = 100001 and hours_before = 24)
                  and not exists (select 1 from public.snai_vs_close() where event_id = 'X1' and code = 100002 and hours_before in (0, 1))
                  and (select price = 3.20::real from public.snai_vs_close() where event_id = 'X1' and code = 100002 and hours_before = 3)
                  and (select price = 2.90::real from public.snai_vs_close() where event_id = 'X1' and code = 100003 and hours_before = 0)
                  and not exists (select 1 from public.snai_vs_close() where price = 1.40::real)
                  and (select count(*) = 6 from public.snai_vs_close() where event_id = 'X2' and hours_before in (0, 1)) and not exists (select 1 from public.snai_vs_close() where event_id = 'X2' and hours_before > 1),
                  'a price read exactly on a checkpoint counts there; a padlock removes it from then on; a reading at the kick-off is the close; one after it never counts; nothing before the first reading');

-- the page on these: matches counted as Scudi's matches, the timing set like for like
create temp table pc_x as select * from public.snai_vs_close(now() - interval '7 days', now());
set role authenticated;
set request.jwt.claim.sub = '11111111-1111-1111-1111-111111111111';
create temp table pc_px as select public.radar_page(7) as j;
reset request.jwt.claim.sub;
reset role;
select pg_temp.ok((select (pg_temp.grp(j, 'a', 0, null, null, null, null) ->> 6)::int from pc_px)
                    = (select count(distinct coalesce(match_id, event_id)) from pc_x where hours_before = 0 and confirmed),
                  'X3 and X4, two SNAI events of one match, are one match in the page''s counts and standard errors');
select pg_temp.ok((select (pg_temp.grp(j, 'mp', 0, 1, null, null, null) ->> 7)::int from pc_px)
                    = (select count(*) from (select coalesce(match_id, event_id), code from pc_x where confirmed and hours_before <= 24 and code / 100000 = 1
                                              group by 1, 2 having count(*) = 6) q),
                  'the like-for-like set keeps only selections priced at every checkpoint up to 24 hours (not X2, X3, X4, read late)');
select 'page sql checks passed';
