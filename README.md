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
| `.github/workflows/grade.yml` → `tools/grade.py` | GitHub Actions | Tuesday and Friday 08:00 UTC, or by hand; final scores from ESPN (free), the odds feed only for what ESPN cannot settle |
| `data/week.json`, `data/record.json` | written by the jobs, read by the site | |
| `data/history.json` | one snapshot of every match's chances per pull: price movement on the site, closing chance of each graded leg | written by the weekly job |
| `data/snai.json` | SNAI's prices, typed by hand (or pasted into the site) | before each matchweek |
| `.github/workflows/teams.yml` → `tools/teams.py` | GitHub Actions | Thursday 07:00 UTC, or by hand |
| `data/teams.json`, `data/players.json` | crests, squads, line-ups, season averages, transfers (ESPN public API) | written by the team job, read by the site |
| `lab/seasons.json` | three past seasons (2023-24 → 2025-26, 17 leagues): scores, half-time scores, Bet365 prices and each match's fitted score matrix, for the Lab | built once by `tools/lab_data.py`, uploaded with the site |

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
numbers, real shapes, tagged "example" in the header) until the job has run once.

Not available from any free source, so not shown: heatmaps, preferred foot, market values.

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

Example data never passes for real prices: the jobs discard a stored week that is a replay or is dated in the future,
and grading never looks at one (decision 76).

## Running the engine on a computer

```
pip install numpy scipy pandas pytest ruff
pytest -q            # 99 tests (they also run tests/js/engine.test.js with node)
python3 -m tools.weekly --from-file tests/feed_week_sample.json --now 2026-10-09T09:00:00Z   # no key needed
ODDS_API_KEY=... python3 -m tools.weekly                                                       # the real thing
python3 tools/snai.py    # SNAI's margins and the slips at SNAI's typed prices -> results/snai_<date>.json
python3 tools/teams.py   # team and player data from ESPN -> data/teams.json, data/players.json (incremental)
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
  estimated SNAI prices until pasted); "Aim for" from the highest chance to the best average return, with the
  trade-off chart for every multiplier; the budget split over 2-5 slips with no match in common, compared with the
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
- `scudi_slips/sistema.py` — the exact sistema maths the site mirrors (tests compare the two).
- `index.html` — the site; it reads `data/week.json`, `data/record.json`, `data/snai.json`, `data/teams.json` and
  `data/players.json` and falls back to example fixtures. Target multiplier from 1.5x to 1000x (by 0.5 to 5, by 5 to
  50, by 10 to 100, by 100 to 1000), the number of matches chosen by the optimiser (Auto, any number from 1 to 25; the
  exact best slip for the target, checked against brute force) or fixed by hand, country flags for national teams and
  leagues, a "Coming up" list of later fixtures,
  competitions grouped (big leagues, national teams, European cups, second divisions, more of Europe), a National
  teams slip when national teams play, English or Italian (the EN/IT switch in the header; remembered per browser); a match opens on an animated pitch with the last line-ups,
  season averages and style tags; players open with their bio and transfer history; teams with results and squad.
