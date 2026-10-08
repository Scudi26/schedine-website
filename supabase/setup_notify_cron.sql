-- Scudi · notifications on the phone (decision 95): wake the scudi-notify function every minute.
-- Run once, after the migration …_sync_push.sql and after the function is deployed, with <project-ref> replaced by the
-- project's reference (the part before .supabase.co). It sends the same token as the price feed's cron (it lives only
-- in private.feed_config). Most wakes spend nothing: no placed slip on, no device, nothing read.
create extension if not exists pg_cron;
create extension if not exists pg_net with schema extensions;

select cron.unschedule('scudi-notify') where exists (select 1 from cron.job where jobname = 'scudi-notify');
select cron.schedule(
  'scudi-notify',
  '* * * * *',
  $$
  select net.http_post(
    url := 'https://<project-ref>.supabase.co/functions/v1/scudi-notify',
    headers := jsonb_build_object('Content-Type', 'application/json',
                                  'x-cron-token', (select cron_token from private.feed_config where id = 1)),
    body := '{}'::jsonb,
    timeout_milliseconds := 30000
  );
  $$
);

-- the last answers:
--   select created, status_code, left(content, 300) from net._http_response order by created desc limit 10;
-- what was sent:
--   select at, ref, title from public.notify_sent order by at desc limit 20;
