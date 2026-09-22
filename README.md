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

Prices come from The Odds API (free plan, 500 credits a month; a matchweek uses about 25). The key lives only in
the repository secret `ODDS_API_KEY`. SNAI is not in any feed: its prices are typed into the site by hand and
remembered.

## Setting it up (once)

1. Create the repository `scudi` on GitHub as **public** (GitHub Pages is free only for public repositories),
   with no README, then upload every file and folder of this tree, including the hidden `.github`, `.gitignore`
   and `.nojekyll` (on a Mac press ⌘⇧. in Finder to show hidden files before dragging them in).
2. **Settings → Secrets and variables → Actions → New repository secret**: name `ODDS_API_KEY`, value = the key
   from the-odds-api.com.
3. **Settings → Pages → Build and deployment**: source "Deploy from a branch", branch `main`, folder `/ (root)`,
   Save. The site appears at `https://<your-user>.github.io/scudi/` a minute later.
4. **Actions** tab → "weekly slips" → **Run workflow**. When it finishes, reload the site: the tag in the header
   changes from "Example prices" to "Prices pulled …".
   If the run fails at the "commit" step, go to **Settings → Actions → General → Workflow permissions** and choose
   "Read and write permissions".

## Running the engine on a computer

```
pip install numpy scipy pandas pytest ruff
pytest -q            # 64 tests
python3 -m tools.weekly --from-file tests/feed_week_sample.json --now 2026-10-09T09:00:00Z   # no key needed
ODDS_API_KEY=... python3 -m tools.weekly                                                       # the real thing
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
- `index.html` — the site; it reads `data/week.json` and `data/record.json` and falls back to example fixtures.
