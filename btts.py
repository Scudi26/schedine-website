"""Can both-teams-score picks be rescued with a calibration correction?

The score matrix assumes the two teams' goals are (almost) independent, and that underrates "both teams score"
(decision 52: promised 59.1%, happened 60.2%; "not both" 58.7% -> 55.0%). Here a two-parameter correction
p' = sigmoid(a + b * logit(p)) is fitted on 2005-06 to 2016-17 and then checked, untouched, on 2017-18 to 2023-24.
Same check for over 1.5 and under 3.5, whose chances also come from the matrix.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
from scipy.optimize import minimize

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scudi_slips import settles
from tools.backtest import OUT, load

CODES = ["GG", "NG", "O15", "U35"]


def logit(p):
    p = np.clip(p, 1e-6, 1 - 1e-6)
    return np.log(p / (1 - p))


def sigmoid(x):
    return 1 / (1 + np.exp(-x))


def fit(pred, won):
    x = logit(pred)

    def nll(ab):
        q = np.clip(sigmoid(ab[0] + ab[1] * x), 1e-9, 1 - 1e-9)
        return -np.sum(won * np.log(q) + (1 - won) * np.log(1 - q))

    r = minimize(nll, [0.0, 1.0], method="Nelder-Mead", options={"xatol": 1e-6, "fatol": 1e-6})
    return float(r.x[0]), float(r.x[1])


def report(pred, won, offered=None):
    band = (pred >= 0.55) & (pred <= 0.85)
    rec = {"n": len(pred), "band_n": int(band.sum()), "band_predicted": round(float(pred[band].mean()), 4), "band_actual": round(float(won[band].mean()), 4)}
    if offered is not None:
        rec["band_flat_return"] = round(float((won[band] * offered[band]).mean()), 4)
    buckets = []
    for lo in np.arange(0.5, 0.9, 0.05):
        m = (pred >= lo) & (pred < lo + 0.05)
        if m.sum() >= 150:
            buckets.append([round(float(lo), 2), int(m.sum()), round(float(pred[m].mean()), 3), round(float(won[m].mean()), 3)])
    rec["buckets"] = buckets
    return rec


def main():
    df = load()
    priced = {int(k): v for k, v in json.loads((OUT / "priced.json").read_text()).items()}
    ids = np.array(sorted(priced))
    season = df.loc[ids, "season"].to_numpy()
    fit_mask, val_mask = season <= 2016, season >= 2017
    out = {"fit_seasons": "2005-06 to 2016-17", "validation_seasons": "2017-18 to 2023-24", "codes": {}}
    for code in CODES:
        pred = np.array([priced[i]["chances"][code] for i in ids])
        won = np.array([settles(code, df.at[i, "FTHome"], df.at[i, "FTAway"]) for i in ids], dtype=float)
        a, b = fit(pred[fit_mask], won[fit_mask])
        corrected = sigmoid(a + b * logit(pred))
        rec = {"a": round(a, 4), "b": round(b, 4),
               "validation_raw": report(pred[val_mask], won[val_mask]),
               "validation_corrected": report(corrected[val_mask], won[val_mask]),
               "fit_raw": report(pred[fit_mask], won[fit_mask]),
               "fit_corrected": report(corrected[fit_mask], won[fit_mask])}
        out["codes"][code] = rec
        v = rec["validation_raw"]
        c = rec["validation_corrected"]
        print(f"{code}: a={a:+.3f} b={b:.3f} | validation band raw {v['band_predicted']:.3f} -> {v['band_actual']:.3f} (n={v['band_n']}) | corrected {c['band_predicted']:.3f} -> {c['band_actual']:.3f} (n={c['band_n']})")
    (OUT / "btts.json").write_text(json.dumps(out, indent=1))


if __name__ == "__main__":
    main()
