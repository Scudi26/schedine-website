"""Cases for the feed's own pricing (decision 94): the weekly job's de-vig, consensus and score-matrix fit, computed in
Python, so tests/js/feed.test.mjs can check that the snai-pull function (logic.mjs) gets the same numbers.

    python3 tests/make_fit_cases.py            # rewrite tests/js/fit_cases.json
    python3 tests/make_fit_cases.py --check    # exit 1 if the file no longer matches the Python code (pytest runs this)
"""

from __future__ import annotations

import json
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scudi_slips.consensus import BookMarket, consensus
from scudi_slips.devig import power_devig
from scudi_slips.matrix import _summary, fit_market, score_matrix

OUT = Path(__file__).resolve().parent / "js" / "fit_cases.json"


def build() -> dict:
    rnd = random.Random(94)
    devig, fits, cons = [], [], []
    for _ in range(25):
        n = rnd.choice([2, 3])
        prices = [round(rnd.uniform(1.15, 9.0), 2) for _ in range(n)]
        if sum(1 / p for p in prices) < 1:
            prices = [round(p * 0.85, 2) for p in prices]
        devig.append({"prices": prices, "fair": [round(x, 10) for x in power_devig(prices)]})
    # markets as books price them: from a Dixon-Coles matrix with ordinary expected goals, the over chance a little off
    for _ in range(60):
        lh, la, rho = rnd.uniform(0.5, 2.8), rnd.uniform(0.4, 2.2), rnd.uniform(-0.2, 0.05)
        h, d, a, o = (float(x) for x in _summary(score_matrix(lh, la, rho)))
        o = min(0.9, max(0.1, o + rnd.uniform(-0.01, 0.01)))
        v = fit_market(h, d, a, o)
        fits.append({"p": [h, d, a, o], "lh": v.lh, "la": v.la, "rho": v.rho, "err": v.fit_error})
    # markets no matrix can reproduce (a draw far too unlikely): both fits miss by more than the 0.01 allowed
    for _ in range(8):
        h = rnd.uniform(0.35, 0.6)
        d = rnd.uniform(0.06, 0.1)
        v = fit_market(h, d, 1 - h - d, rnd.uniform(0.35, 0.6))
        fits.append({"p": [h, d, 1 - h - d, v.p_over25], "lh": v.lh, "la": v.la, "rho": v.rho, "err": v.fit_error})
    for _ in range(10):
        books = []
        for key in rnd.sample(["pinnacle", "betfair_ex_eu", "matchbook", "onexbet"], rnd.choice([1, 2, 3])):
            base = [rnd.uniform(1.6, 5.5) for _ in range(3)]
            books.append({"book": key, "prices": [round(x, 2) for x in base]})
        c = consensus([BookMarket(b["book"], b["prices"]) for b in books])
        cons.append({"books": books, "probs": None if c is None else [round(x, 10) for x in c.probs]})
    return {"devig": devig, "fit": fits, "consensus": cons}


def main(argv: list[str]) -> int:
    text = json.dumps(build(), indent=1) + "\n"
    if "--check" in argv:
        ok = OUT.exists() and OUT.read_text() == text
        print("fit cases up to date" if ok else "fit cases OUT OF DATE: run python3 tests/make_fit_cases.py")
        return 0 if ok else 1
    OUT.write_text(text)
    print(f"{OUT.name}: {len(text) // 1024} KB")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
