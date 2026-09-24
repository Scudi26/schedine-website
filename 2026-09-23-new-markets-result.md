# New markets — result (run once, 2026-09-23)

Pre-registration: [2026-09-23-new-markets.md](../2026-09-23-new-markets.md). Raw numbers per pick type and band:
`results/markets.json` (built by `python tools/markets.py all`; the priced-matches cache it writes,
`results/priced_markets.pkl`, is 23 MB and is not stored).

## Verdict

**72 new pick types pass** in the check seasons (2017-18 → 2023-24, 42,055 matches) and again in the confirm
seasons (2024-25 → 2025-26, 11,900 matches). They are offered on the site, and only from a printed chance of 30% up, the
range where they were judged. 17 types are not offered.

First-half matrix (fixed on the fit seasons): expected goals 0.434 × full time, low-score correction -0.04.

| Market | Types checked | Offered | Worst gap (offered, judged bands) | Picks judged, offered types (check + confirm) |
|---|---|---|---|---|
| multigol | 13 | 13 | 1.5 pts | 656,134 |
| team goals | 14 | 10 | 2.9 pts | 523,783 |
| combo | 37 | 30 | 3.9 pts | 988,150 |
| handicap | 12 | 8 | 1.9 pts | 222,390 |
| first half | 13 | 11 | 3.6 pts | 507,106 |

Every gap above 2.5 points sits in a band of 150–499 picks, where the pass mark is 4 points.

## Not offered, and why

- **AO05** — confirm seasons, 85–97% band: promised 88.6%, happened 92.1% (642 picks) — too cautious
- **AO15** — check 55–85%: 63.0% promised, 65.7% happened (2,458 picks); confirm the same way
- **HU05** — excluded upfront (a team not scoring); fit seasons already 5.7 pts too kind
- **AU05** — excluded upfront (a team not scoring); fit seasons 5.3 pts too kind
- **1+NG** — excluded upfront (needs a team not to score); fit seasons 6.1 pts too kind
- **X+GG** — never reaches 30%: nothing to judge
- **2+U35** — confirm 30–55%: 35.9% promised, 38.8% happened (2,066 picks)
- **2+NG** — excluded upfront (needs a team not to score)
- **NG+U25** — excluded upfront (needs a team not to score)
- **NG+O15** — excluded upfront; also 3.8–4.1 pts too kind in every season block
- **1X+MG1-3** — check 55–85%: 57.2% promised, 60.0% happened (2,290 picks)
- **XH-1** — fit seasons 30–55%: 30.6% promised, 38.9% happened; "exactly by one" handicaps set aside
- **XH+1** — almost never reaches 30%
- **XH-2** — never reaches 30%
- **XH+2** — never reaches 30%
- **1T1** — confirm 55–85%: 61.3% promised, 65.9% happened (543 picks)
- **1TGG** — almost never reaches 30%

The pattern is the one already seen for "not both score" (decision 60): the score matrix gives a little too little
weight to both teams scoring, so every pick that needs a team to stay at zero is too kind, and picks that need goals
from the weaker side (away over 0.5 / 1.5) are too cautious.

## What this does not show

- SNAI's own prices for these markets: no free file has them. The site starts from a typical margin (multigol 9%,
  combo 11%, team goals / handicap / first half 8.5%, a little more on long prices) and learns SNAI's real margins
  from the pages pasted into it. Until then, the "est." prices are estimates, and a new-market pick is chosen only
  when its estimated price makes it cheaper than a classic pick.
- The consensus of many bookmakers (the file has Bet365 only) and the Champions League.
- Whether the new markets make slips more likely at the same multiplier: that depends on SNAI's real margins, which
  the live record will show.
