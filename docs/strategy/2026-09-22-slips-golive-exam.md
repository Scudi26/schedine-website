# Go-live exam for the slip builder — pre-registration

Written 2026-09-22, before the sealed seasons were looked at for this question. Run once.

## What is being tested

The two claims the site makes: (1) the chance Scudi prints for a pick is honest, and (2) a slip built by the
optimiser lands as often as the chance it prints. Everything was developed on 2005-06 → 2023-24 (decisions 52,
57, and the both-teams-score shift in tools/btts.py fitted on 2005-06 → 2016-17 and checked on 2017-18 → 2023-24).

## Data

The free file huggingface.co/datasets/xgabora/club-football-match-data, seasons **2024-25 and 2025-26**, the five
top leagues (I1, E0, SP1, D1, F1): Bet365 pre-match prices and final scores. These two seasons were opened once
before for a different question (the sharp-reference line-shopping exam, decision 39, which used Pinnacle and UK
books' opening/closing prices); nothing about the calibration of Bet365-derived chances or the slip builder was
looked at then. 2026-27 stays sealed for live tracking.

Chances: Bet365 result and over/under 2.5 prices, margin removed by the power method, fitted to the score matrix;
double chance, over 1.5, under 3.5 and both-teams-score (+0.015) from the matrix. Prices: as in tools/backtest.py.

## Pass marks (fixed now)

1. **Calibration.** For each offered pick type (1, X, 2, 1X, X2, 12, O15, O25, U25, U35, GG), picks with a printed
   chance between 55% and 85%: |promised − happened| ≤ 2.5 points where the band has at least 500 picks, ≤ 4 points
   where it has 150–499 picks; types with fewer than 150 picks in the band are reported, not judged.
   The draw (X) is expected to have no picks in the band and is exempt.
2. **Slips.** Top-5 best-ten slip and Serie A all-ten slip at 25x and 50x over every weekend/round of the two seasons
   (~75 weekends, ~75 rounds): actual hits within 2 standard deviations of expected hits, for each of the four series,
   where the standard deviation is sqrt(Σ p(1−p)).
3. **Rules table.** Top-5 weekends, 25x, 6 / 8 / 10 legs, "everything" menu: predicted "1 in N" within 25% of the
   development value (29.4 / 30.6 / 33.2) — a check that the structure findings carry over, not a calibration test.

PASS = 1 and 2 hold. If 1 fails for one pick type, that type is removed from the menu and the exam counts as a
pass for the rest. If 2 fails, the builder is not used with real money until the cause is found.

## Not tested here (cannot be, with this file)

SNAI's own prices; the consensus of many books (the live feed); Champions League matches.
