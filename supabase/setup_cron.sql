-- Scudi · automatic SNAI prices (decision 92): wake the snai-pull function every 10 minutes.
-- Run once, after the migration and after the function is deployed, with <project-ref> replaced by the project's
-- reference (the part before .supabase.co). The token the cron sends lives only in private.feed_config: it is read at
-- each run and never leaves the database except towards the function. Most wakes spend nothing: the function decides
-- (night, quota, kick-offs) whether a request to odss-api.com is worth it now.
create extension if not exists pg_cron;
create extension if not exists pg_net with schema extensions;

select cron.unschedule('scudi-snai-pull') where exists (select 1 from cron.job where jobname = 'scudi-snai-pull');
select cron.schedule(
  'scudi-snai-pull',
  '*/10 * * * *',
  $$
  select net.http_post(
    url := 'https://<project-ref>.supabase.co/functions/v1/snai-pull',
    headers := jsonb_build_object('Content-Type', 'application/json',
                                  'x-cron-token', (select cron_token from private.feed_config where id = 1)),
    body := '{}'::jsonb,
    timeout_milliseconds := 60000
  );
  $$
);

-- pg_net keeps answers for 6 hours; to look at the last ones:
--   select created, status_code, left(content, 300) from net._http_response order by created desc limit 10;
-- the feed's own record:
--   select * from public.feed_state;  select * from public.feed_log order by id desc limit 20;
