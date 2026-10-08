-- Checks for the sync and notifications migration (decision 95), run on a local Postgres after supabase_stub.sql, every
-- migration and feed_checks.sql (which creates the two accounts: 1111… the owner, 2222… another account).
-- Every check raises an exception when it fails; the last line prints "sync sql checks passed".
\set ON_ERROR_STOP on
create or replace function pg_temp.ok(cond boolean, msg text) returns void language plpgsql as $$
begin if not coalesce(cond, false) then raise exception 'FAIL: %', msg; end if; end $$;

-- ---------- the owner's state, key by key, with the copy it was based on ----------
set role authenticated;
set request.jwt.claim.sub = '11111111-1111-1111-1111-111111111111';
create temp table r1 as select public.state_put('[{"key": "scudi-placed", "value": [{"id": 1}], "base": null, "device": "iPhone"},
                                                {"key": "scudi-prefs", "value": {"learn": true}, "base": null}]'::jsonb) as v;
select pg_temp.ok((select (v -> 0 ->> 'ok')::boolean and (v -> 1 ->> 'ok')::boolean from r1), 'two new keys stored');
select pg_temp.ok((select count(*) = 2 from public.user_state), 'the owner reads their two keys');
select pg_temp.ok((select device = 'iPhone' from public.user_state where key = 'scudi-placed'), 'the device is noted');
-- a write based on the stored copy goes through; one based on an older copy gets the stored copy back
create temp table r2 as select public.state_put(jsonb_build_array(jsonb_build_object('key', 'scudi-placed', 'value', '[{"id": 1}, {"id": 2}]'::jsonb,
                                                'base', (select v -> 0 ->> 'at' from r1)))) as v;
select pg_temp.ok((select (v -> 0 ->> 'ok')::boolean from r2), 'a write on the latest copy is stored');
select pg_temp.ok((select (v -> 0 ->> 'at')::timestamptz = updated_at from r2, public.user_state where key = 'scudi-placed'), 'its stamp is the stored one');
create temp table r3 as select public.state_put(jsonb_build_array(jsonb_build_object('key', 'scudi-placed', 'value', '[{"id": 9}]'::jsonb,
                                                'base', (select v -> 0 ->> 'at' from r1)))) as v;
select pg_temp.ok((select not (v -> 0 ->> 'ok')::boolean and v -> 0 -> 'value' = '[{"id": 1}, {"id": 2}]'::jsonb from r3), 'a write on an old copy gets the stored copy back');
select pg_temp.ok((select value = '[{"id": 1}, {"id": 2}]'::jsonb from public.user_state where key = 'scudi-placed'), 'and changes nothing');
create temp table r4 as select public.state_put('[{"key": "scudi-prefs", "value": {"learn": false}, "base": null}]'::jsonb) as v;
select pg_temp.ok((select not (v -> 0 ->> 'ok')::boolean from r4), 'a "new key" write on a stored key is refused');
do $$ begin
  begin perform public.state_put('[{"key": "not-scudi", "value": 1, "base": null}]'::jsonb); raise exception 'FAIL: a foreign key name was stored'; exception when check_violation then null; end;
  begin insert into public.user_state (user_id, key, value) values ('22222222-2222-2222-2222-222222222222', 'scudi-x', '1'); raise exception 'FAIL: the owner wrote for another account'; exception when insufficient_privilege then null; end;
  begin perform 1 from public.notify_sent; exception when insufficient_privilege then raise exception 'FAIL: the owner cannot read what was sent'; end;
  begin insert into public.notify_sent (user_id, ref) values ('11111111-1111-1111-1111-111111111111', 'x'); raise exception 'FAIL: the site wrote a sent alert'; exception when insufficient_privilege then null; end;
  begin perform public.notify_load(null); raise exception 'FAIL: the site could call notify_load'; exception when insufficient_privilege then null; end;
  begin perform public.notify_claim('11111111-1111-1111-1111-111111111111', '[]'); raise exception 'FAIL: the site could claim alerts'; exception when insufficient_privilege then null; end;
  begin perform 1 from private.push_keys; raise exception 'FAIL: the site could read the VAPID keys'; exception when insufficient_privilege then null; end;
  begin insert into public.push_subs (user_id, endpoint, p256dh, auth) values ('11111111-1111-1111-1111-111111111111', 'https://x', repeat('a', 87), repeat('b', 22)); raise exception 'FAIL: direct insert into push_subs'; exception when insufficient_privilege then null; end;
end $$;

-- ---------- devices ----------
select pg_temp.ok((public.push_add(jsonb_build_object('endpoint', 'https://web.push.apple.com/QGx1', 'keys', jsonb_build_object('p256dh', repeat('B', 87), 'auth', repeat('a', 22)), 'ua', 'iPhone')) ->> 'devices')::int = 1, 'a device added');
select pg_temp.ok((public.push_add(jsonb_build_object('endpoint', 'https://web.push.apple.com/QGx1', 'keys', jsonb_build_object('p256dh', repeat('C', 87), 'auth', repeat('a', 22)))) ->> 'devices')::int = 1, 'the same endpoint refreshed, not doubled');
select pg_temp.ok((select p256dh = repeat('C', 87) from public.push_subs), 'with its new keys');
do $$ begin
  begin perform public.push_add(jsonb_build_object('endpoint', 'http://evil', 'keys', jsonb_build_object('p256dh', repeat('B', 87), 'auth', repeat('a', 22)))); raise exception 'FAIL: a plain-http endpoint'; exception when check_violation then null; end;
  begin perform public.push_add(jsonb_build_object('endpoint', 'https://x', 'keys', jsonb_build_object('p256dh', 'short', 'auth', repeat('a', 22)))); raise exception 'FAIL: a malformed key'; exception when check_violation then null; end;
end $$;
select pg_temp.ok((public.push_add(jsonb_build_object('endpoint', 'https://fcm.googleapis.com/fcm/send/x2', 'keys', jsonb_build_object('p256dh', repeat('D', 87), 'auth', repeat('e', 22)))) ->> 'devices')::int = 2, 'a second device');
select pg_temp.ok((public.push_remove('https://fcm.googleapis.com/fcm/send/x2') ->> 'devices')::int = 1, 'a device removed');

-- ---------- another account sees and writes nothing ----------
set request.jwt.claim.sub = '22222222-2222-2222-2222-222222222222';
select pg_temp.ok((select count(*) = 0 from public.user_state), 'another account reads no state');
select pg_temp.ok((select count(*) = 0 from public.push_subs), 'another account reads no device');
do $$ begin
  begin perform public.state_put('[{"key": "scudi-x", "value": 1, "base": null}]'::jsonb); raise exception 'FAIL: another account stored state'; exception when insufficient_privilege then null; end;
  begin perform public.push_add(jsonb_build_object('endpoint', 'https://x/y', 'keys', jsonb_build_object('p256dh', repeat('B', 87), 'auth', repeat('a', 22)))); raise exception 'FAIL: another account added a device'; exception when insufficient_privilege then null; end;
end $$;
reset request.jwt.claim.sub;
reset role;
set role anon;
do $$ begin
  begin perform 1 from public.user_state; raise exception 'FAIL: anon read state'; exception when insufficient_privilege then null; end;
  begin perform public.state_put('[]'::jsonb); raise exception 'FAIL: anon called state_put'; exception when insufficient_privilege then null; end;
end $$;
reset role;

-- ---------- the notify function (secret key) ----------
set role service_role;
create temp table l1 as select public.notify_load(null) as v;
select pg_temp.ok((select not (v ->> 'cron_ok')::boolean from l1), 'no token, no cron');
select pg_temp.ok((select v ->> 'owner' = '11111111-1111-1111-1111-111111111111' from l1), 'the owner found');
select pg_temp.ok((select v -> 'state' -> 'scudi-placed' = '[{"id": 1}, {"id": 2}]'::jsonb and v -> 'state' -> 'scudi-prefs' is null from l1), 'only the keys the alerts need');
select pg_temp.ok((select jsonb_array_length(v -> 'subs') = 1 and v -> 'keys' = 'null'::jsonb from l1), 'one device, no keys yet');
select pg_temp.ok((public.notify_keys_init('PUB1', '{"d": "x"}') ->> 'public_key') = 'PUB1', 'the key pair stored');
select pg_temp.ok((public.notify_keys_init('PUB2', '{"d": "y"}') ->> 'public_key') = 'PUB1', 'a second pair never replaces the first');
select pg_temp.ok((public.notify_claim('11111111-1111-1111-1111-111111111111', '[{"ref": "goal:1:1-0", "title": "Goal"}, {"ref": "ft:1"}]')) = '["goal:1:1-0", "ft:1"]'::jsonb, 'two new alerts claimed');
select pg_temp.ok((public.notify_claim('11111111-1111-1111-1111-111111111111', '[{"ref": "goal:1:1-0"}, {"ref": "goal:1:2-0"}]')) = '["goal:1:2-0"]'::jsonb, 'an alert already sent is not claimed again');
select pg_temp.ok((select jsonb_array_length(v -> 'sent') = 3 from (select public.notify_load(null) as v) x), 'the recent alerts come with the load');
select public.notify_result((select id from public.push_subs limit 1), false, false);
select pg_temp.ok((select fails = 1 from public.push_subs), 'a failure counted');
select public.notify_result((select id from public.push_subs limit 1), true, false);
select pg_temp.ok((select fails = 0 and last_ok is not null from public.push_subs), 'a delivery resets it');
select public.notify_result((select id from public.push_subs limit 1), false, true);
select pg_temp.ok((select count(*) = 0 from public.push_subs), 'a device the push service no longer knows is removed');
select public.notify_memo_save('{"1:0": {"h": 2, "a": 1}}');
select public.notify_memo_save('{"1:0": {"h": 2, "a": 1}, "1:1": {"h": 0, "a": 0}}');
select pg_temp.ok((select v -> 'memo' -> '1:1' ->> 'h' = '0' from (select public.notify_load(null) as v) x), 'the memo kept, the second save replacing the first');
reset role;
select pg_temp.ok((public.notify_load((select cron_token from private.feed_config)) ->> 'cron_ok')::boolean, 'the cron token is accepted');
set role authenticated;
set request.jwt.claim.sub = '11111111-1111-1111-1111-111111111111';
do $$ begin
  begin perform public.notify_memo_save('{}'); raise exception 'FAIL: the site could write the memo'; exception when insufficient_privilege then null; end;
  begin perform 1 from private.notify_memo; raise exception 'FAIL: the site could read the memo'; exception when insufficient_privilege then null; end;
end $$;
reset request.jwt.claim.sub;
reset role;
select 'sync sql checks passed';
