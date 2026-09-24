# New markets (multigol, combo, handicap, team goals, first half) — pre-registration

Written 2026-09-23, after looking only at the fit seasons (2005-06 → 2016-17) and before the check or confirm
seasons were opened for these pick types. Run once, in this order: check, then confirm.

## Data

The free file huggingface.co/datasets/xgabora/club-football-match-data (built from football-data.co.uk), 17
divisions: Serie A, Premier League, La Liga, Bundesliga, Ligue 1, Serie B, Championship, League One, La Liga 2,
2. Bundesliga, Ligue 2, Eredivisie, Primeira Liga, Belgian Pro League, Süper Lig, Scottish Premiership, Greek
Super League. Bet365 result and over/under 2.5 prices, margin removed by the power method, fitted to the
Dixon–Coles score matrix exactly as the live site does (fit error ≤ 0.01). Final and half-time scores.

- fit: 2005-06 → 2016-17 (71,589 matches)
- check: 2017-18 → 2023-24 (42,055 matches)
- confirm: 2024-25 → 2025-26 (11,900 matches; these seasons were used before for the classic picks' exam,
  never for these pick types)
- 2026-27 stays sealed for the live record.

## The model (fixed now, from the fit seasons)

- Full-time picks: the full-time score matrix of the match (the same one the site uses for every pick).
- First-half picks: a second Dixon–Coles matrix with expected goals 0.434 × the full-time ones and a low-score
  correction of −0.040 (maximum likelihood on the fit seasons' half-time scores; separate home and away shares
  gave 0.433 / 0.435 and no better fit).
- Every new pick type gets a two-number calibration correction p' = sigmoid(a + b·logit(p)), fitted by maximum
  likelihood on the fit seasons. A combo's corrected chance is capped at the smaller chance of its two parts.
- Left out before any check, because the fit seasons already show them too kind by 3.6 to 8 points: every pick
  that needs a team NOT to score (NG, 1+NG, 2+NG, NG+U25, NG+O15, home or away "fails to score"). Same cause as
  "not both score" (decision 60): the matrix underrates both teams scoring.

## Pass marks (as in the go-live exam of 2026-09-22)

For each pick type and each band of printed chance — 30–55%, 55–85%, 85–97% —
|promised − happened| ≤ 2.5 points where the band has at least 500 picks, ≤ 4 points where it has 150–499;
fewer than 150 picks: reported, not judged.

A pick type is offered on the site only if it passes every judged band in the check seasons AND in the confirm
seasons. A type that fails is not offered and its result is published with the rest.

## Not tested here (cannot be, with this file)

SNAI's own prices for these markets (no free historical file has them: the site starts from an assumed margin per
market group and learns SNAI's real margins from the pages pasted into it); the consensus of many books; the
Champions League.
