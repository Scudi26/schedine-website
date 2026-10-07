# Scudi

A personal accumulator builder for SNAI. Every week it pulls bookmaker prices, works out the honest chance of
every pick from the sharpest books, and finds the slip that reaches a target multiplier (1.5x to 1000x) with the
highest chance of landing. Every slip it builds is graded from the final scores, whether placed or not.

Nothing here predicts football. Over 34,000 past matches the market's own probabilities beat every model we
tried, so the chances come from the market with the margin removed, and the job of the software is to lose
as little as possible to the margin: pick the cheapest legs, land just above the target, use the bonus.

## What runs where

| Piece | Where | When |
|---|---|---|
| `index.html` | GitHub Pages (this repository, root) | always on |
| `.github/workflows/weekly.yml` → `tools/weekly.py --mode auto` | GitHub Actions | every morning 09:00 UTC: full pull Tuesday and Friday (and any morning the stored week is empty), match-day refresh of the big leagues and national teams the other days (no credit spent when nothing kicks off within 18 hours) |
| `.github/workflows/grade.yml` → `tools/grade.py` | GitHub Actions | Tuesday and Friday 08:00 UTC, or by hand; final scores from ESPN (free), the odds feed only for what ESPN cannot settle; closing prices from football-data.co.uk (free, decision 85); goal and red-card minutes kept for the live model |
| `data/week.json`, `data/record.json` | written by the jobs, read by the site | |
| `data/history.json` | one snapshot of every match's chances per pull: price movement on the site, closing chance of each graded leg | written by the weekly job |
| `data/snai.json` | SNAI's prices, typed by hand (or pasted into the site) | before each matchweek |
| `.github/workflows/teams.yml` → `tools/teams.py` | GitHub Actions | Thursday 07:00 UTC, or by hand |
| `data/teams.json`, `data/players.json` | crests, squads, line-ups, season averages, transfers (ESPN public API) | written by the team job, read by the site |
| `lab/seasons.json` | three past seasons (2023-24 → 2025-26, 17 leagues): scores, half-time scores, Bet365 prices and each match's fitted score matrix, for the Lab | built once by `tools/lab_data.py`, uploaded with the site |
| `lab/style.json` | every team's seasons since 2005-06 in the 17 leagues (points, goals, shots, on target, corners, cards, home and away form, Elo, this season's expected goals): the "Season by season" blocks (decision 88) | built by `tools/style_data.py`, uploaded with the site; rebuild now and then for the current season |
| `lab/transfermarkt.json` | player profiles from the open transfermarkt-datasets project (CC0): preferred foot, market value and peak, contract end, sub-position (decision 86) | built by `tools/transfermarkt.py`, uploaded with the site; read by the team job |
| `extension/` → `scudi-snai-extension.zip` | the Scudi · SNAI Chrome extension (decision 91): reads every snai.it page you open and passes SNAI's prices to Scudi | installed once on the computer; the zip is rebuilt by `tools/pack_extension.py` |
| `supabase/` | the automatic SNAI prices (decision 92): a private store and the `snai-pull` function in your own Supabase project, fed by odss-api.com | every 10 minutes (pg_cron); spends a request only when worth it |
| `results/live_model.json` | the live model (decision 87): the goal rate by minute, the score-state and red-card multipliers, fitted on StatsBomb open data + Bet365 prices; copied into `index.html` as `LIVE_MODEL` | built by `tools/live_data.py` then `tools/live_fit.py` |

Prices come from The Odds API (free plan, 500 credits a month). The key lives only in the repository secret
`ODDS_API_KEY`. Competitions (decision 74, `scudi_slips/comps.py`): the big five leagues and the Champions League;
national teams (Nations League, World Cup and Euro qualifiers, World Cup, Euro, and any friendlies window the feed
lists); Europa and Conference League; Serie B, Championship, League One, La Liga 2, 2. Bundesliga, Ligue 2; and the top
flights of the Netherlands, Portugal, Belgium, Turkey, Scotland, Austria, Switzerland, Denmark, Sweden, Norway and
Greece. Not available: Ukraine (not in the free feed) and Poland (no free team data or scores).
How the credits last (decision 75): the big leagues, the Champions League and national teams are priced 8 days ahead at
every full pull (Tuesday and Friday); on Friday every competition is priced 8 days ahead; on Tuesday the others are priced to
Friday morning. The feed is asked only for competitions in season (the list is free) and only for matches in that window
(a call that returns nothing is free), so a competition costs 2 credits only when it has a match in the window. A priced
match that the next pull does not cover keeps its last prices. Every later match of the next 21 days is listed anyway,
from the feed's free events list, with the day its prices will arrive (the site's "Coming up" panel). Core and
national-team competitions are always pulled; the others only while the credits left cover about 7 a day to the monthly
reset. A typical month is about 400-430 credits; each pull records what it spent and skipped in `data/week.json`, and
the site shows the credits left. SNAI is not in any feed: its prices are typed by hand, either into the site (remembered in the browser) or into `data/snai.json` (key = date, home, away; codes 1 X 2 1X X2 12 O25 U25
GG NG, plus O15 U35 when read). Pasted into the site, SNAI's other tabs are read too, one at a time, from their column
headers (Multigol, Combo, Handicap, 1° tempo, U/O casa and ospite); every price pasted teaches the site SNAI's real margin
on that kind of pick. Easier (decision 79): "Read SNAI prices" → drop or paste a **screenshot** of SNAI's list; the browser
reads it (Tesseract.js, loaded once from cdn.jsdelivr.net; the picture never leaves the browser), matches the rows to the
week's matches, and shows each row next to its piece of the picture to check and correct before use. The site shows feed chances at SNAI's prices wherever the two meet.

Team and player data come from ESPN's public site API through `tools/teams.py` (full depth for the big leagues and the
Champions League; crests, squads, results, form and tables for everything else): no key, no published limits, but
unofficial, so the job is polite (one request every 0.25 s) and the site works without the files (the pitch and the
squads simply do not appear). If ESPN ever refuses the GitHub runner, run `python3 tools/teams.py` on a computer and
upload `data/teams.json` and `data/players.json` by hand. The repository ships example team data (invented squads and
numbers, real shapes, tagged "example" in the header) until the job has run once; the job never starts from that file
(incident 2026-10-05: it had, and invented matches were counted for a month). Every finished match is stored one by one
and checked against ESPN's schedule on every run; what ESPN no longer lists is dropped and the averages are recomputed.
With `lab/transfermarkt.json` in the repository, every squad player is matched by birthday and name to Transfermarkt's
profile (market value and peak, preferred foot, contract end — Transfermarkt's estimates, through the open
transfermarkt-datasets project, current to July 2026 while that project's updates are paused).

Closing prices (decision 85): football-data.co.uk publishes, within days of each round, the closing 1 X 2 and over/under
2.5 prices (Betfair Exchange, Bet365, market average) and the expected goals of every match of sixteen of the leagues
here. The grader measures every leg's CLV against that closing market (margin removed, score matrix fitted, the pick
priced); a leg the file does not carry yet is "pending" and settles on the last price pull after 12 days; the Champions
League, the other cups and national teams always use the last pull. The Record screen says how many legs are measured
against the real closing price.

The live model (decision 87): the chance of a pick during the match follows the goals still to come minute by minute,
with the goal rate of a level eleven-a-side match through the ninety minutes and its stoppage time, more goals for a
side that trails (one goal down about 14% more, two or more down 23%; one up 6%), fewer for a side with a player sent
off (a third less) and more for its opponent (80% more), fitted on 1,136 league matches with pre-match prices (StatsBomb
open data: Serie A, Premier League and Ligue 1 2015-16; Bet365 prices from football-data.co.uk). Red cards come from
ESPN's match details. The simulation draws its goals at the same rates. Data: StatsBomb (github.com/statsbomb/open-data).

Not available from any free source, so not shown: heatmaps.

## Setting it up (once)

1. Create a **public** repository on GitHub (GitHub Pages is free only for public repositories; the name is free,
   it only sets the site's address), with no README. Unzip `scudi-repo.zip`, open the unzipped folder, select
   everything inside it (including `.github`, `.gitignore` and `.nojekyll`; on a Mac press ⌘⇧. in Finder to show
   hidden files) and drag it onto the repository's "uploading an existing file" page, then commit to `main`.
2. **Settings → Secrets and variables → Actions → New repository secret**: name `ODDS_API_KEY`, value = the key
   from the-odds-api.com.
3. **Settings → Pages → Build and deployment**: source "Deploy from a branch", branch `main`, folder `/ (root)`,
   Save. The site appears at `https://<your-user>.github.io/<repository>/` a minute later.
4. **Actions** tab → "weekly slips" → **Run workflow**. When it finishes, reload the site: the tag in the header
   changes from "Example prices" to "Prices pulled …". Then "team data" → **Run workflow** (15–25 minutes the first
   time, a few minutes afterwards): the header's "Team data · example" becomes "Team data <date>".
   If the run fails at the "commit" step, go to **Settings → Actions → General → Workflow permissions** and choose
   "Read and write permissions".

## On the phone, like an app (decision 76)

The site has six screens (decision 78): **Today** (next kick-off with a countdown, slips in play, credits, three
recommended slips at 5x, 25x and 100x with no match in common), **Slips** (the builder), **Matches** (every priced match
of the week plus the fixtures still to price), **Live** (placed slips, followed on match day), **Record** (graded record,
"Is it working?", what Scudi has learned, season simulator) and **Lab** (your rules on three past seasons, plus this
week's data, credits and tests). On a phone they sit in a tab bar at the bottom. Light, dark or automatic with the phone:
the switch in the header. To install it: open the
site in Safari (iPhone) → Share → "Add to Home Screen", or in Chrome (Android) → menu → "Install app". It then opens full
screen with the Scudi icon. `sw.js` keeps a copy for when there is no connection but always asks the network first, so a
new upload or a new price pull shows straight away. `manifest.webmanifest` and `icons/` (made by `tools/make_icons.py`)
describe the app.

Crests: clubs the team-data job has not covered yet get their crest from ESPN's public team list, read by the browser
(one request per league, kept a week). National teams show their flag (drawn in the page).

## The look (decision 89: "Notturna")

One design system in the page's stylesheet: a stadium at night. Tokens for the night ground, lit surfaces, hairlines,
the coin gold (a metallic gradient on the key numbers and the main action), the competition accents and the semantic
green/red, with a light theme of the same tokens ("Giorno") chosen by the phone or in Settings. Floodlights sweep from the
top corners, the pitch breathes green at the bottom, a star field and a film grain sit behind everything (all still under
reduced motion). Phone first: a floating glass dock for the six screens, bottom sheets for the match, team and player
views and for the explanations; the desktop widens the same components and keeps a lit tab rail in the header. The
brand mark — a gold shield with a night field and a coin — is drawn in SVG in the page, in the launch splash and in the
app icons (`tools/make_icons.py`); the wordmark dots its i with the coin. Nothing in the engine, the data files or the
jobs changed for the look: every id and class the scripts rely on is kept.

Example data never passes for real prices: the jobs discard a stored week that is a replay or is dated in the future,
and grading never looks at one (decision 76).

## SNAI's prices without typing (decisions 91, 92 and 94)

Two ways, both reading SNAI and nothing else, neither ever clicking, betting or logging in on snai.it:

- **The extension** (computer; Chrome, Edge or Brave). Settings → "Read SNAI prices" → "Live from snai.it" explains the
  four steps: download `scudi-snai-extension.zip` from the site, unzip, `chrome://extensions` → Developer mode → "Load
  unpacked". From then on every snai.it page with prices sends them to every open Scudi tab a few seconds after SNAI
  changes them, from several tabs at once and after a reload, with a small card on SNAI's page saying what it read. The
  prices are exactly SNAI's (the page you see). The older bookmark still works without the extension.
- **The automatic feed** (computer and phone, nothing open). odss-api.com publishes SNAI's prices, with a delay of a few
  minutes, 500 requests a month on its free plan. Its licence is for your own use only, so the prices cannot go into this
  public repository or onto a page open to anyone: they live in a Supabase project of your own, behind a sign-in. The
  `snai-pull` function wakes every 10 minutes and decides whether a request is worth it: never at night (00:30-08:00
  Rome), about every 40 minutes in the three hours before one of the week's kick-offs, every couple of hours otherwise,
  spread so that the month's quota lasts to its reset (25 requests are kept for "Update now"). Twice a day it reads
  SNAI's whole football list (1X2 only, one request) to pair SNAI's events with the week's matches (same kick-off, names
  or competition alike, Italian names included); the other pulls ask for the 1X2, double chance, under/over and goal/no
  goal of those events by id (one request for up to 150 matches). The prices are stored in SNAI's own codes, so the site
  reads them exactly as it reads SNAI's page (same matching, same checks). A price read later on SNAI's page, from a
  screenshot or typed always wins over an older automatic one. Settings → "Automatic SNAI prices": sign in, last pull,
  requests left, next pull, Update now, sign out.

Setting up the feed (once): a free Supabase organisation and project; `supabase/migrations/…_snai_feed.sql` (tables,
row-level security: only the first account created in the project reads anything; the function's calls closed to the
site's keys); the function deployed from `supabase/functions/snai-pull` with `verify_jwt = false` (`supabase/config.toml`:
it checks its callers itself); the odss-api key added by hand in the dashboard (Edge Functions → Secrets →
`ODSS_API_KEY`) and nowhere else; one user created in the dashboard (Authentication → Users → Add user, auto-confirmed),
then sign-ups switched off; `supabase/setup_cron.sql` run with the project's reference; the project's address and
publishable key written into `index.html` (`FEED_PROJECT`; both public by design). What the feed did is in the
`feed_state` and `feed_log` tables. Tests: `tests/js/feed.test.mjs` (the planner over a simulated month, the pairing, the
codes), `tests/sql/feed_checks.sql` and `tests/feed_local.py` (the real function under Deno against the real tables on a
local Postgres, with stand-ins for odss-api and Supabase's endpoints).

### Every league, from the private store (decision 94)

The weekly job prices the big leagues 8 days ahead but the smaller ones (Serie B, Championship, Ligue 2, the other
second divisions and European leagues) only from Friday's pull, to stay inside The Odds API's free 500 credits. The feed
now fills that gap without spending any of them:

- it pairs SNAI's events with the week's **fixtures** too (the matches not priced yet), with tighter name matching (both
  names alike, one very alike, or one alike in a league with the competition's words; Italian club names such as PSG,
  Lipsia, Siviglia known);
- it reads SNAI's list again as soon as `data/week.json` has a match or fixture it has not seen (Friday's pull, a new day
  in the window), checking the file every 10 minutes with an ETag (no odss-api request when nothing changed);
- the requests that bring SNAI's prices also bring the **reference books'** (Pinnacle, the exchanges, then big
  international books such as bet365 and William Hill — never an Italian book; their keys come from odss-api's list of
  books, read once a week), and the function fits Scudi's own chances to them with the weekly job's method (power de-vig, sharp-weighted consensus, Dixon–Coles matrix fitted to 1X2 and over/under 2.5;
  `tests/js/fit_cases.json` holds Python's numbers and the tests compare). The fit is stored in `book_events.fit`
  (`supabase/migrations/…_sharp_fit.sql`), private like the rest: odss-api's licence is for internal use;
- a fit needs Pinnacle's result price or two usable books (failing that, three of the big Italian books other than SNAI,
  marked "Italian books" on the site); the reasons a match got none are counted in
  `feed_state.diag.fit` (with examples);
- what could not be paired is recorded (`feed_state.diag.unpaired`, with SNAI's nearest namesake), with SNAI's list by
  league and the pairing per competition; Settings shows it under "Not found on SNAI".

On a device signed in to the store, the page adds those fixtures as matches before it is built ("Pinnacle" tag in the
Matches list; the match sheet says where the chances come from): every view and slip counts them, with SNAI's own prices
from the same store. A fixture SNAI prices but no sharp book does shows SNAI's result prices in "Coming up". Without the
sign-in the site is exactly the public one.

## Running the engine on a computer

```
pip install numpy scipy pandas pytest ruff
pytest -q            # 114 tests (they also run tests/js/engine.test.js with node)
python3 -m tools.weekly --from-file tests/feed_week_sample.json --now 2026-10-09T09:00:00Z   # no key needed
ODDS_API_KEY=... python3 -m tools.weekly                                                       # the real thing
python3 tools/snai.py    # SNAI's margins and the slips at SNAI's typed prices -> results/snai_<date>.json
python3 tools/teams.py   # team and player data from ESPN -> data/teams.json, data/players.json (incremental)
python3 tools/transfermarkt.py   # players.csv.gz from the open transfermarkt-datasets -> lab/transfermarkt.json (the team job reads it)
python3 tools/style_data.py      # data/Matches.csv + this season's football-data.co.uk files -> lab/style.json (season by season)
python3 tools/live_data.py       # StatsBomb open data: goal and red-card minutes of ~1,700 matches -> results/live_events.json
python3 tools/live_fit.py        # the live model -> results/live_model.json (then copy LIVE_MODEL into index.html)
python3 tools/sample_espn.py   # example team data (invented) in the same shapes, for the site without the job
python3 tools/markets.py all   # the new markets' calibration check (needs data/Matches.csv) -> results/markets.json
python3 tools/lab_data.py      # the Lab's seasons (needs data/Matches.csv) -> lab/seasons.json
```

The backtests (`tools/backtest.py`, `variants.py`, `rules.py`, `pool.py`, `btts.py`, `exam.py`) need the free
file `huggingface.co/datasets/xgabora/club-football-match-data` saved as `data/Matches.csv` (45 MB, not
committed). Their results are in `results/`. The go-live exam, the new markets' check and their pre-registrations
are in `docs/strategy/`.

## Layout

- `scudi_slips/` — the engine: `devig` (margin removal), `consensus` (many books → one view), `matrix`
  (score matrix fitted to the market), `picks` (what can be bet and how it settles), `solver` (the exact
  optimiser with league rules), `bonus` (SNAI's accumulator bonus), `feed` (odds feed → priced matches, with
  guards), `season` (season simulator).
- `tools/` — the jobs and the backtests.
- `tests/` — the tests, including brute-force checks of the optimiser and replay fixtures for the feed.
- Site features (decision 73): price movement per match; paste SNAI's page to read all its prices at once, margin per
  pick and a "where SNAI is cheapest" board; the slip as a *sistema* (1 to 3 errors) with the chance and payout of
  each outcome; "Mark as placed" saves the slip in the browser, a live tracker follows it on match day from ESPN's
  public scores and settles it; the match preview adds the league table, home/away records, last five, injuries;
  the player card adds percentiles against his position; "Is it working?" charts calibration, money against the
  range chance allows, leaks by pick type and league, timing against the pre-kickoff price and near misses.
  Placed slips live in the browser: "Back up my slips" / "Restore" moves them between devices.
- Site features (decision 78): more pick types from the same score matrix (multigol, team goals, combos, handicap,
  first half; only the 72 types that passed the check of `docs/strategy/2026-09-23-new-markets.md`, from 30% up, at
  estimated SNAI prices until pasted); "Aim for" the highest chance or the best average return (decision 84: two
  choices, and a ladder of what each multiplier gives back); the budget split over 2-5 slips with no match in common, compared with the
  single slip and the sistema; "How Scudi judges chances": prudent (penalise picks the books disagree on), learn from
  the record (per pick type and competition, only for systematic errors), market signals (price movement between pulls,
  Pinnacle and Betfair first, and starters out) with "play now or wait"; the slip as a ticket image to share; team
  colours and the two teams side by side; confetti when a slip lands and a buzz at a goal in the live tracker.
- Site features (decision 79): SNAI prices read from a screenshot; the Live screen opens on "Simulate a matchday" (any
  slip, recommended or placed: goals drawn from each match's expected goals, the slip's chance minute by minute on a log
  chart, legs green/red with their live chance, goals that mattered, pause / to the end / again, a counter of runs), with a
  Simulate button under every slip; every panel has a one-line explanation and an "i" that opens the full explanation
  with the numbers on screen (English and Italian); the builder's four steps are numbered; numbers count up, panels
  rise into view, cards tilt, a soft aurora behind the page (all off with reduced motion).
- Live for real slips (decision 80): the chart and the goals are saved in the browser and rebuilt every minute from the
  minute of each goal ESPN lists, so closing or reloading the page loses nothing and the minutes it was closed are filled
  in; the scores are read again as soon as the page is back in view; a match that went to extra time is settled on its
  90-minute score (site and grader), shoot-out kicks are not goals; the live chance starts from the pick's own chance and
  hands over to the score as the match runs out; a slip over several days squeezes the idle hours into a band.
- Today (decision 81): the next kick-off and the slips in play; three recommended slips (5x, 25x, 100x) and under them the
  Mega Bomba (a whole round of one competition on one slip at 250x, 1,000x or 5,000x, €2, capped at SNAI's €10,000);
  SNAI's five best and five worst real prices by margin (1 − price × chance). The price-download credits, theme and
  language are in Settings (the gear in the top bar).
- Speed (decision 82): the optimiser extends only the cells no other cell beats (exact, 3–5x faster); the explorer, trade-off
  chart, portfolio and other slip cards are computed in idle moments while "Slips" is on screen; the screenshot reader starts
  when its drawer opens and reads overlapping bands of the picture with one recogniser per spare core, then matches rows by
  names, kick-off time and prices.
- SNAI live (decision 83): on a computer, "Read SNAI prices" → "Live from snai.it" gives a button to drag to the bookmarks
  bar. Clicked on snai.it (a competition's list), it reads SNAI's own page (SNAI's event numbers, names, kick-off and each
  price button's market code), opens Scudi in a new tab and sends the prices there; while SNAI's tab stays open it reads
  again every 5 seconds and sends what changed. Nothing is clicked, typed or downloaded on SNAI; a small card at the bottom
  left of SNAI's page shows what is read and stops it. Scudi matches each row once (names, exact kick-off, prices; youth and
  women's teams never), then by SNAI's event number; padlocked prices are taken away. On the phone (SNAI's app) the
  screenshot reader stays.
- Season by season (decision 88): on a team page and in the side-by-side view, each team's last seasons from
  `lab/style.json` (points a game, goals, shots and shots on target for and against, expected goals this season) and, for
  the current season, its attack and defence against the league average in shots on target.
- The player card (decision 86) shows preferred foot, market value, peak value and contract end from Transfermarkt's
  open dataset when the team job found the player there (four of five big-league players).
- What each multiplier gives back (decision 84): on "Slips", one row per multiplier (2x to 500x and the slip's own) with
  the likeliest slip's average return for every €1 played (chance × pay-out, SNAI bonus included) as a bar, its chance,
  matches and SNAI's cut; tap a row to use that multiplier. Under it, "Most likely" or "Best average return", each with
  its own chance and return at this multiplier, and a sentence on whether they differ.
- `scudi_slips/sistema.py` — the exact sistema maths the site mirrors (tests compare the two).
- `index.html` — the site; it reads `data/week.json`, `data/record.json`, `data/snai.json`, `data/teams.json` and
  `data/players.json` and falls back to example fixtures. Target multiplier from 1.5x to 1000x (by 0.5 to 5, by 5 to
  50, by 10 to 100, by 100 to 1000), the number of matches chosen by the optimiser (Auto, any number from 1 to 25; the
  exact best slip for the target, checked against brute force) or fixed by hand, country flags for national teams and
  leagues, a "Coming up" list of later fixtures,
  competitions grouped (big leagues, national teams, European cups, second divisions, more of Europe), a National
  teams slip when national teams play, English or Italian (the EN/IT switch in the header; remembered per browser); a match opens on an animated pitch with the last line-ups,
  season averages and style tags; players open with their bio and transfer history; teams with results and squad.
