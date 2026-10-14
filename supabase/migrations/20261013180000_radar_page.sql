-- Phase 1.5 of the value radar (decision 99): everything the private "SNAI vs the close" page draws, in one call.
-- Run once in the SQL editor after 20261013120000_results_truth.sql. Nothing is stored: the page reads it live.
--   select public.radar_page(28);                 -- the last 28 days, closes confirmed by a reading in the last 30 minutes
--   select public.radar_page(28, false);          -- the same, with the unconfirmed closes too
-- The site calls it signed in (POST /rest/v1/rpc/radar_page); like every table under it, it answers only the owner.
--
-- What it returns (one JSON object):
--   groups  SNAI's prices against the close, grouped seven ways, at every checkpoint (0 = the kick-off; 1, 3, 6, 12, 24,
--           48 hours before), one array per group:
--             [kind, hours, market, selection, league, band, matches, prices, average CLV, its standard error,
--              share beating the close, settled, won, expected wins]
--           kind  a = everything, l = league, m = market, s = selection, lm = league × market, mb = market × SNAI price
--                 band, lmb = league × market × band (at the kick-off only), mp = market, only the selections SNAI had
--                 priced at every checkpoint 24, 12, 6, 3, 1 hours before and at the kick-off (like for like); market 1 = 1X2, 2 = double chance, 3150 / 3250 / 3350 =
--                 under/over 1.5 / 2.5 / 3.5, 4 = goal/no goal; selection = the memory's packed code; band = the lower
--                 edge of SNAI's price band (1, 1.5, 2, 3, 5)
--           The standard error counts each of Scudi's matches once (its prices move together; two SNAI events paired
--           with one match count as one), so a group with many prices from a few matches is not mistaken for a sure thing.
--   calib   the closing fair chances against the results: the result's three outcomes and one side of each two-way
--           market (over, goal), so no selection is its own mirror; double chances left out (they repeat the result):
--             [truth from: sharp | fit, tenth of chance 0..9, selections, chance summed, won]
--   daily   per London day: [day, matches finished, close confirmed, graded against the close, with a result]
--   sources the truth's source at the kick-off: [source, matches]
--   health  public.radar_health(days) for the same window (the gate's numbers by league)
--   first_close, left_out (matches graded only on an unconfirmed close, left out), days, at

-- SNAI against the close, about twice as fast, the same rows (checked row for row on two months of simulated matches,
-- and on padlocks, readings on a checkpoint, at and after the kick-off in tests/sql/page_checks.sql):
-- each price carries the time of the next one, so a checkpoint's price is found without sorting every price seven times,
-- and the settlement is written out instead of calling public.settles() once a row. The page below and snai_map use it.
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
  ), sn as (   -- each SNAI price with the time of the next one for the same selection
    select v.event_id, v.code, v.at, v.price, ev.commence_time as k, lead(v.at) over (partition by v.event_id, v.code order by v.at) as nxt
      from ev join public.price_ticks_v v on v.event_id = ev.event_id and v.book = 'snai' and v.at <= ev.commence_time
  ), cp(h) as (values (0), (1), (3), (6), (12), (24), (48)
  ), asof as (   -- the price standing at each checkpoint: read by then, and not replaced before it
    select sn.event_id, sn.code, cp.h, sn.price, sn.at
      from sn cross join cp
     where sn.at <= sn.k - make_interval(hours => cp.h)
       and (sn.nxt is null or sn.nxt > sn.k - make_interval(hours => cp.h))
  )
  select ev.event_id, ev.league, ev.home, ev.away, ev.commence_time, ev.match_id, a.code, a.h, a.price, a.at, tr.p, tr.source,
         round(a.price::numeric, 2)::double precision * tr.p - 1,
         case a.code / 100000   -- public.settles(code, h, a), written out: a function with its own search_path is never inlined, and calling it 90,000 times cost a second
           when 1 then case a.code % 10 when 1 then r.ft_h > r.ft_a when 2 then r.ft_h = r.ft_a when 3 then r.ft_h < r.ft_a end
           when 2 then case a.code % 10 when 1 then r.ft_h >= r.ft_a when 2 then r.ft_h <> r.ft_a when 3 then r.ft_h <= r.ft_a end
           when 3 then case a.code % 10 when 1 then (r.ft_h + r.ft_a) * 100 < (a.code % 100000) / 10 when 2 then (r.ft_h + r.ft_a) * 100 > (a.code % 100000) / 10 end
           when 4 then case a.code % 10 when 1 then r.ft_h > 0 and r.ft_a > 0 when 2 then not (r.ft_h > 0 and r.ft_a > 0) end
         end,
         coalesce(ev.near_at between ev.commence_time - interval '30 minutes' and ev.commence_time, false)
    from asof a
    join ev on ev.event_id = a.event_id
    join tr on tr.event_id = a.event_id and tr.code = a.code
    left join public.match_results r on r.match_id = ev.match_id
   where a.price is not null
   order by ev.commence_time, ev.event_id, a.code, a.h;
end;
$$;

create or replace function public.radar_page(days int default 28, confirmed_only boolean default true) returns jsonb
language plpgsql stable set search_path = '' as $$
#variable_conflict use_variable
declare
  d int := greatest(1, least(coalesce(days, 28), 200));
  v_since timestamptz := now() - make_interval(days => greatest(1, least(coalesce(days, 28), 200)));
  v_only boolean := coalesce(confirmed_only, true);
  v_out jsonb;
begin
  with x as materialized (
    select coalesce(v.match_id, v.event_id) as event_id, v.event_id as ev, v.league, v.code, v.hours_before as h, v.clv, v.won, v.p_fair, v.source, v.confirmed,
           case v.code / 100000 when 3 then 3000 + (v.code % 100000) / 10 else v.code / 100000 end as mk,
           (case when v.price < 1.5 then 1 when v.price < 2 then 1.5 when v.price < 3 then 2 when v.price < 5 then 3 else 5 end)::real as band
      from public.snai_vs_close(v_since, now()) v
  ), y as materialized (
    select x.* from x where x.confirmed or not v_only
  ), pr as (   -- the selections SNAI had priced at every checkpoint from 24 hours before to the kick-off: the timing chart's like-for-like set
    select y.event_id, y.code from y where y.h <= 24 group by y.event_id, y.code having count(*) = 6
  ), e as (   -- one line per match inside each group: its prices' CLV summed (s) and counted (k)
    select 'a'::text as g, y.h, null::int as mk, null::int as code, null::text as league, null::real as band, y.event_id,
           count(*) as k, sum(y.clv) as s, count(*) filter (where y.clv > 0) as b, count(y.won) as st, count(*) filter (where y.won) as w,
           sum(y.p_fair) filter (where y.won is not null) as ex
      from y group by y.h, y.event_id
    union all
    select 'l', y.h, null, null, y.league, null, y.event_id, count(*), sum(y.clv), count(*) filter (where y.clv > 0), count(y.won),
           count(*) filter (where y.won), sum(y.p_fair) filter (where y.won is not null)
      from y group by y.h, y.league, y.event_id
    union all
    select 'm', y.h, y.mk, null, null, null, y.event_id, count(*), sum(y.clv), count(*) filter (where y.clv > 0), count(y.won),
           count(*) filter (where y.won), sum(y.p_fair) filter (where y.won is not null)
      from y group by y.h, y.mk, y.event_id
    union all
    select 's', y.h, y.mk, y.code, null, null, y.event_id, count(*), sum(y.clv), count(*) filter (where y.clv > 0), count(y.won),
           count(*) filter (where y.won), sum(y.p_fair) filter (where y.won is not null)
      from y group by y.h, y.mk, y.code, y.event_id
    union all
    select 'lm', y.h, y.mk, null, y.league, null, y.event_id, count(*), sum(y.clv), count(*) filter (where y.clv > 0), count(y.won),
           count(*) filter (where y.won), sum(y.p_fair) filter (where y.won is not null)
      from y group by y.h, y.mk, y.league, y.event_id
    union all
    select 'mb', y.h, y.mk, null, null, y.band, y.event_id, count(*), sum(y.clv), count(*) filter (where y.clv > 0), count(y.won),
           count(*) filter (where y.won), sum(y.p_fair) filter (where y.won is not null)
      from y group by y.h, y.mk, y.band, y.event_id
    union all
    select 'lmb', y.h, y.mk, null, y.league, y.band, y.event_id, count(*), sum(y.clv), count(*) filter (where y.clv > 0), count(y.won),
           count(*) filter (where y.won), sum(y.p_fair) filter (where y.won is not null)
      from y where y.h = 0 group by y.h, y.mk, y.league, y.band, y.event_id   -- the finest cells at the kick-off only (the page's pockets)
    union all
    select 'mp', y.h, y.mk, null, null, null, y.event_id, count(*), sum(y.clv), count(*) filter (where y.clv > 0), count(y.won),
           count(*) filter (where y.won), sum(y.p_fair) filter (where y.won is not null)
      from y join pr on pr.event_id = y.event_id and pr.code = y.code where y.h <= 24 group by y.h, y.mk, y.event_id
  ), gq as (
    select e.g, e.h, e.mk, e.code, e.league, e.band, count(*) as ng, sum(e.k) as n, sum(e.s) as s, sum(e.s * e.s) as ss,
           sum(e.s * e.k) as sk, sum(e.k * e.k)::double precision as kk, sum(e.b) as b, sum(e.st) as st, sum(e.w) as w, sum(e.ex) as ex
      from e group by e.g, e.h, e.mk, e.code, e.league, e.band
  ), gr as (   -- the average, and its standard error with the matches as clusters: sqrt(G/(G−1) · Σ(s − m·k)²) / n
    select gq.*, gq.s / gq.n as m,
           case when gq.ng > 1 then sqrt(greatest(0, gq.ng::double precision / (gq.ng - 1)
                  * (gq.ss - 2 * (gq.s / gq.n) * gq.sk + (gq.s / gq.n) ^ 2 * gq.kk))) / gq.n end as se
      from gq
  ), fl as (   -- each finished match of the window: closed, graded, with a result
    select me.event_id, (me.commence_time at time zone 'Europe/London')::date as day,
           coalesce(me.near_at between me.commence_time - interval '30 minutes' and me.commence_time, false) as closed,
           exists (select 1 from public.match_results r where r.match_id = me.match_id) as res
      from public.memory_events me
     where me.commence_time >= v_since and me.commence_time <= now()
  ), graded as (
    select distinct y.ev from y where y.h = 0
  )
  select jsonb_build_object(
    'days', d,
    'confirmed_only', v_only,
    'at', now(),
    'first_close', (select min(me.commence_time) from public.memory_events me
                     where me.near_at between me.commence_time - interval '30 minutes' and me.commence_time and me.commence_time <= now()),
    'left_out', (select count(distinct x.event_id) from x where x.h = 0 and not x.confirmed and v_only),
    'groups', coalesce((select jsonb_agg(jsonb_build_array(gr.g, gr.h, gr.mk, gr.code, gr.league, gr.band, gr.ng, gr.n,
                                 round(gr.m::numeric, 5), round(gr.se::numeric, 5), round((gr.b::double precision / gr.n)::numeric, 4),
                                 gr.st, gr.w, round(gr.ex::numeric, 3))
                               order by gr.g, gr.h, gr.mk nulls first, gr.code nulls first, gr.league nulls first, gr.band nulls first) from gr), '[]'::jsonb),
    'calib', coalesce((select jsonb_agg(jsonb_build_array(c.src, c.bucket, c.n, round(c.sp::numeric, 3), c.w) order by c.src, c.bucket) from (
                 select case when y.source like 'fit%' then 'fit' else 'sharp' end as src, least(9, floor(y.p_fair * 10))::int as bucket,
                        count(*) as n, sum(y.p_fair) as sp, count(*) filter (where y.won) as w
                   from y where y.h = 0 and y.won is not null and (y.code / 100000 = 1 or y.code in (301502, 302502, 303502, 400001))
                  group by 1, 2) c), '[]'::jsonb),
    'daily', coalesce((select jsonb_agg(jsonb_build_array(q.day, q.matches, q.closed, q.graded, q.res) order by q.day) from (
                 select fl.day, count(*) as matches, count(*) filter (where fl.closed) as closed,
                        count(*) filter (where g.ev is not null) as graded, count(*) filter (where fl.res) as res
                   from fl left join graded g on g.ev = fl.event_id group by fl.day) q), '[]'::jsonb),
    'sources', coalesce((select jsonb_agg(jsonb_build_array(z.source, z.n) order by z.n desc, z.source) from (
                 select y.source, count(distinct y.event_id) as n from y where y.h = 0 group by y.source) z), '[]'::jsonb),
    'health', public.radar_health(d)
  ) into v_out;
  return v_out;
end;
$$;

revoke all on function public.radar_page(int, boolean) from public, anon;
grant execute on function public.radar_page(int, boolean) to authenticated;
revoke all on function public.snai_vs_close(timestamptz, timestamptz) from public, anon;
grant execute on function public.snai_vs_close(timestamptz, timestamptz) to authenticated;
