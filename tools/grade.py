"""Grade every slip the weekly job built, from final scores, and keep the running record.

    ODDS_API_KEY=... python3 -m tools.grade --week data/week.json --record data/record.json
    python3 -m tools.grade --week ... --scores-file tests/scores_sample.json --now 2026-10-13T12:00:00Z   (replay)

Scores come from the same feed's scores endpoint (2 credits per competition per call, results up to 3 days back),
so the grading run must happen within three days of the last match. A slip is graded only when every leg's
match has a final score; a slip with a postponed match stays open. The record keeps, for every graded slip, the
chance Scudi promised and whether it landed, so expected and actual hits can be compared honestly over time.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scudi_slips import settles
from scudi_slips.feed import SPORT_KEYS
from tools.weekly import closing

API = "https://api.the-odds-api.com/v4/sports/{key}/scores"


def fetch_scores(comps: list[str], api_key: str, days_from: int = 3) -> dict[str, dict]:
    scores = {}
    for comp in comps:
        q = urllib.parse.urlencode({"apiKey": api_key, "daysFrom": days_from, "dateFormat": "iso"})
        req = urllib.request.Request(API.format(key=SPORT_KEYS[comp]) + "?" + q, headers={"User-Agent": "scudi/0.1"})
        with urllib.request.urlopen(req, timeout=60) as r:
            for ev in json.loads(r.read().decode("utf-8")):
                scores[ev["id"]] = ev
    return scores


def final_score(ev: dict) -> tuple[int, int] | None:
    if not ev.get("completed"):
        return None
    got = {s["name"]: int(s["score"]) for s in ev.get("scores") or []}
    if ev["home_team"] not in got or ev["away_team"] not in got:
        return None
    return got[ev["home_team"]], got[ev["away_team"]]


def grade(week: dict, scores: dict[str, dict], record: dict, now: datetime, history: dict | None = None) -> dict:
    done = {s["key"] for s in record.get("slips", [])}
    finals = {mid: final_score(ev) for mid, ev in scores.items()}
    comp_of = {m["id"]: m["competition"] for m in week.get("matches", [])}
    names = {m["id"]: f'{m["home"]} v {m["away"]}' for m in week.get("matches", [])}
    for slip in week.get("slips", []):
        key = f'{week["built_at"]}|{slip["name"]}|{slip["target"]}'
        if key in done:
            continue
        legs = []
        for p in slip["picks"]:
            fs = finals.get(p["match"])
            if fs is None:
                legs = None
                break
            won = settles(p["code"], fs[0], fs[1])
            leg = {"match": p["match"], "name": names.get(p["match"]), "competition": comp_of.get(p["match"]), "code": p["code"],
                   "chance": round(p["chance"], 4), "odds": p["odds"], "won": won, "score": f"{fs[0]}-{fs[1]}"}
            close = closing(history or {}, p["match"])
            if close and p["code"] in close.get("p", {}):
                leg["close_chance"] = close["p"][p["code"]]
                leg["clv"] = round(p["odds"] * close["p"][p["code"]] - 1, 4)   # >0: the price taken beat the last pre-kickoff view
            legs.append(leg)
        if legs is None:
            continue
        won = [x["won"] for x in legs]
        record.setdefault("slips", []).append({"key": key, "name": slip["name"], "target": slip["target"], "legs": slip["legs"],
                                               "chance": slip["chance"], "odds": slip["odds"], "bonus": slip["bonus"],
                                               "landed": all(won), "legs_won": sum(won), "graded_at": now.isoformat(), "leg_results": legs})
    graded = record.get("slips", [])
    exp = sum(s["chance"] for s in graded)
    record["summary"] = {"graded": len(graded), "expected_hits": round(exp, 2), "actual_hits": sum(s["landed"] for s in graded),
                         "by_name": {}}
    for s in graded:
        b = record["summary"]["by_name"].setdefault(s["name"], {"graded": 0, "expected": 0.0, "actual": 0})
        b["graded"] += 1
        b["expected"] = round(b["expected"] + s["chance"], 2)
        b["actual"] += int(s["landed"])
    return record


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--week", default="data/week.json")
    ap.add_argument("--record", default="data/record.json")
    ap.add_argument("--scores-file")
    ap.add_argument("--history", default="data/history.json")
    ap.add_argument("--now")
    a = ap.parse_args(argv)
    now = datetime.fromisoformat(a.now.replace("Z", "+00:00")) if a.now else datetime.now(timezone.utc)
    week = json.loads(Path(a.week).read_text())
    comps = sorted({m["competition"] for m in week["matches"]})
    if a.scores_file:
        scores = {ev["id"]: ev for ev in json.loads(Path(a.scores_file).read_text())}
    else:
        key = os.environ.get("ODDS_API_KEY")
        if not key:
            sys.exit("ODDS_API_KEY is not set")
        scores = fetch_scores(comps, key)
    rec_path = Path(a.record)
    record = json.loads(rec_path.read_text()) if rec_path.exists() else {}
    hist = json.loads(Path(a.history).read_text()) if Path(a.history).exists() else {}
    record = grade(week, scores, record, now, hist)
    rec_path.parent.mkdir(parents=True, exist_ok=True)
    rec_path.write_text(json.dumps(record, indent=1))
    print(record["summary"])


if __name__ == "__main__":
    main()
