"""Read the SNAI prices typed into data/snai.json, measure SNAI's margins, and build slips at those prices.

Until the consensus feed runs, the chances are SNAI's own prices de-vigged (decision 71): a single soft book,
so the hit chances are indicative, not the calibrated ones the exam checked. Once data/week.json exists for the
same matches, the site merges both (feed chances, SNAI prices); this tool is the offline check.

    python tools/snai.py                       # data/snai.json -> results/snai_<read_at>.json
    python tools/snai.py --file other.json --legs 10 8 7 6 --targets 25 30 40 50
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scudi_slips import PICKS, SLIP_MENU, Pick, fit_market, power_devig, snai_bonus, solve

MARKETS = {"result": ("1", "X", "2"), "double chance": ("1X", "X2", "12"), "over/under 2.5": ("O25", "U25"), "both score": ("GG", "NG")}
MIN_ODDS = 1.25


def price_snai(key: str, prices: dict[str, float]):
    """Chances for one match from SNAI's own 1X2 and over/under 2.5, and the cost of every pick SNAI offers."""
    p1, px, p2 = power_devig([prices["1"], prices["X"], prices["2"]])
    p_over = power_devig([prices["O25"], prices["U25"]])[0] if "O25" in prices and "U25" in prices else 0.5
    view = fit_market(p1, px, p2, p_over)
    chances = {code: PICKS[code].chance(view) for code in PICKS}
    cost = {code: round(chances[code] * price - 1, 4) for code, price in prices.items() if code in chances}
    return {"key": key, "chances": chances, "offered": prices, "cost": cost, "fit_error": view.fit_error, "lh": view.lh, "la": view.la}


def margins(prices: dict[str, float]) -> dict[str, float]:
    """Overround of each two- or three-way market: sum of 1/price minus one. The three double-chance picks are not one
    market, so their dearness is reported as the median pick cost against the de-vigged result chances instead."""
    out = {}
    for name, codes in MARKETS.items():
        if name == "double chance":
            continue
        if all(c in prices for c in codes):
            out[name] = round(sum(1 / prices[c] for c in codes) - 1, 4)
    return out


def build(priced: list[dict], legs: int, target: float):
    menus = [[Pick(m["key"], c, m["chances"][c], p) for c, p in m["offered"].items() if c in SLIP_MENU and p >= MIN_ODDS] for m in priced]
    slip = solve(menus, target, legs=legs)
    if slip is None:
        return None
    bonus = snai_bonus([p.odds for p in slip.picks])
    return {"legs": legs, "target": target, "odds": round(slip.odds, 2), "pays": round(slip.odds * (1 + bonus), 2), "bonus": round(bonus, 4),
            "chance": round(slip.chance, 5), "one_in": round(1 / slip.chance, 1), "return": round(slip.chance * slip.odds * (1 + bonus), 3),
            "picks": [[p.match_id, p.code, p.odds, round(p.chance, 3)] for p in slip.picks]}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--file", default="data/snai.json")
    ap.add_argument("--legs", type=int, nargs="+", default=[10, 8, 7, 6])
    ap.add_argument("--targets", type=float, nargs="+", default=[25, 30, 40, 50])
    ap.add_argument("--out", default=None)
    a = ap.parse_args()
    data = json.loads(Path(a.file).read_text())
    priced = [price_snai(k, v) for k, v in data["prices"].items()]
    print(f"{len(priced)} matches read {data.get('read_at', '?')}")

    by_market = {name: [] for name in MARKETS if name != "double chance"}
    for m in priced:
        for name, v in margins(m["offered"]).items():
            by_market[name].append(v)
    by_pick = {code: [m["cost"][code] for m in priced if code in m["cost"]] for code in PICKS}
    dc = [c for code in MARKETS["double chance"] for c in by_pick[code]]
    report = {"read_at": data.get("read_at"), "matches": len(priced),
              "margin_median": {k: round(statistics.median(v), 4) for k, v in by_market.items() if v},
              "double_chance_cost_median": round(statistics.median(dc), 4) if dc else None,
              "pick_cost_median": {k: round(statistics.median(v), 4) for k, v in by_pick.items() if v},
              "slips": {}}
    print("margins", report["margin_median"], "| double chance cost", report["double_chance_cost_median"])
    print("pick cost", report["pick_cost_median"])
    for legs in a.legs:
        for target in a.targets:
            s = build(priced, legs, target)
            if s:
                report["slips"][f"{legs}-{int(target)}"] = s
                print(f"{legs} legs {target:g}x: odds {s['odds']} pays {s['pays']}x, 1 in {s['one_in']}, return {s['return']}")
    out = Path(a.out or f"results/snai_{data.get('read_at', 'latest')}.json")
    out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps(report, indent=1))
    print("wrote", out)


if __name__ == "__main__":
    main()
