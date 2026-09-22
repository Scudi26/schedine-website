# Scudi

A personal accumulator builder for SNAI. Every week it pulls bookmaker prices, works out the honest chance of
every pick from the sharpest books, and finds the slip that reaches a target multiplier (25x–50x) with the
highest chance of landing. Every slip it builds is graded from the final scores, whether placed or not.

Nothing here predicts football. Over 34,000 past matches the market's own probabilities beat every model we
tried, so the chances come from the market with the margin removed, and the job of the software is to lose
as little as possible to the margin: pick the cheapest legs, land just above the target, use the bonus.

## What runs where

| Piece | Where | When |
|---|---|---|
| `index.html` | GitHub Pages (this repository, root) | always on |
| `.github/workflows/weekly.yml` → `tools/weekly.py` | GitHub Actions | Friday and Tuesday 09:00 UTC, or by hand |
| `.github/workflows/grade.yml` → `tools/grade.py` | GitHub Actions | Tuesday and Friday 08:00 UTC, or by hand |
| `data/week.json`, `data/record.json` | written by the jobs, read by the site | |
| `data/snai.json` | SNAI's prices, typed by hand (or pasted into the site) | before each matchweek |
| `.github/workflows/teams.yml` → `tools/teams.py` | GitHub Actions | Thursday 07:00 UTC, or by hand |
| `data/teams.json`, `data/players.json` | crests, squads, line-ups, season averages, transfers (ESPN public API) | written by the team job, read by the site |

Prices come from The Odds API (free plan, 500 credits a month; a matchweek uses about 25). The key lives only in
the repository secret `ODDS_API_KEY`. SNAI is not in any feed: its prices are typed by hand, either into the
site (remembered in the browser) or into `data/snai.json` (key = date, home, away; codes 1 X 2 1X X2 12 O25 U25
GG NG, plus O15 U35 when read). The site shows feed chances at SNAI's prices wherever the two meet.

Team and player data come from ESPN's public site API through `tools/teams.py`: no key, no published limits, but
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

## Running the engine on a computer

```
pip install numpy scipy pandas pytest ruff
pytest -q            # 64 tests
python3 -m tools.weekly --from-file tests/feed_week_sample.json --now 2026-10-09T09:00:00Z   # no key needed
ODDS_API_KEY=... python3 -m tools.weekly                                                       # the real thing
python3 tools/snai.py    # SNAI's margins and the slips at SNAI's typed prices -> results/snai_<date>.json
python3 tools/teams.py   # team and player data from ESPN -> data/teams.json, data/players.json (incremental)
python3 tools/sample_espn.py   # example team data (invented) in the same shapes, for the site without the job
```

The backtests (`tools/backtest.py`, `variants.py`, `rules.py`, `pool.py`, `btts.py`, `exam.py`) need the free
file `huggingface.co/datasets/xgabora/club-football-match-data` saved as `data/Matches.csv` (45 MB, not
committed). Their results are in `results/`. The go-live exam and its pre-registration are in `docs/strategy/`.

## Layout

- `scudi_slips/` — the engine: `devig` (margin removal), `consensus` (many books → one view), `matrix`
  (score matrix fitted to the market), `picks` (what can be bet and how it settles), `solver` (the exact
  optimiser with league rules), `bonus` (SNAI's accumulator bonus), `feed` (odds feed → priced matches, with
  guards), `season` (season simulator).
- `tools/` — the jobs and the backtests.
- `tests/` — the tests, including brute-force checks of the optimiser and replay fixtures for the feed.
- `index.html` — the site; it reads `data/week.json`, `data/record.json`, `data/snai.json`, `data/teams.json` and
  `data/players.json` and falls back to example fixtures. Target multiplier from 5x to 1000x (by 5 to 50, by 10 to
  100, by 100 to 1000), up to 25 matches on a slip; a match opens on an animated pitch with the last line-ups,
  season averages and style tags; players open with their bio and transfer history; teams with results and squad.
