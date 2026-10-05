"""Player depth from the open Transfermarkt dataset (decision 86).

`transfermarkt-datasets` (github.com/dcaribou/transfermarkt-datasets, licence CC0 1.0 - OSSERVATO in the repository's
LICENSE on 2026-10-05) publishes Transfermarkt's player profiles as CSV: position and sub-position, preferred foot,
height, date of birth, market value (current and career peak, in euro), contract end, agent, nationality. We download
a dataset its maintainer publishes; Scudi never reads transfermarkt.com itself. Market values are Transfermarkt's
crowd-sourced estimates, not fees. The dataset's updates are paused since mid-July 2026 (its README: current to 6 July
2026, 2026-27 squads not covered), so the file is a snapshot of the summer of 2026 and says so ("as_of").

    python3 tools/transfermarkt.py                 # downloads players.csv.gz (4 MB) and writes lab/transfermarkt.json
    python3 tools/transfermarkt.py --csv players.csv.gz --as-of 2026-07-06

The output keeps only players whose club plays in a competition Scudi follows (about a quarter of the 50,000) with
short keys, so the team-data job can match them to ESPN's squads by date of birth and name (tools/teams.py, `enrich`).
"""

from __future__ import annotations

import argparse
import csv
import gzip
import io
import json
import re
import sys
import unicodedata
import urllib.request
from pathlib import Path

URL = "https://pub-e682421888d945d684bcae8890b0ec20.r2.dev/data/players.csv.gz"
UA = "scudi/0.2 (personal accumulator builder; github.com/Scudi26)"
# Transfermarkt's competition codes for the domestic leagues Scudi follows (the ESPN side is in scudi_slips/comps.py)
LEAGUES = {"IT1", "GB1", "ES1", "L1", "FR1", "IT2", "GB2", "GB3", "ES2", "L2", "FR2", "NL1", "PO1", "BE1", "TR1", "SC1", "GR1",
           "A1", "C1", "DK1", "SE1", "NO1"}
OUT = Path("lab/transfermarkt.json")


def norm_name(name: str) -> str:
    s = unicodedata.normalize("NFKD", name or "").encode("ascii", "ignore").decode().lower()
    return " ".join(re.sub(r"[^a-z ]+", " ", s).split())


def _int(v):
    try:
        return int(float(v))
    except (TypeError, ValueError):
        return None


def compact(rows, min_season: int = 2024) -> list[dict]:
    """The rows worth keeping, with short keys: id, name, dob, foot, height, position, sub-position, market value, peak
    value, contract end, competition (ESPN already has nationality and club)."""
    out = []
    for r in rows:
        if r.get("current_club_domestic_competition_id") not in LEAGUES:
            continue
        if (_int(r.get("last_season")) or 0) < min_season:
            continue
        rec = {"id": _int(r["player_id"]), "n": r.get("name") or f'{r.get("first_name", "")} {r.get("last_name", "")}'.strip(),
               "dob": (r.get("date_of_birth") or "")[:10] or None, "foot": (r.get("foot") or "").strip().lower() or None,
               "h": _int(r.get("height_in_cm")), "pos": r.get("position") or None, "sub": r.get("sub_position") or None,
               "v": _int(r.get("market_value_in_eur")), "pk": _int(r.get("highest_market_value_in_eur")),
               "c": (r.get("contract_expiration_date") or "")[:10] or None, "comp": r.get("current_club_domestic_competition_id")}
        out.append({k: v for k, v in rec.items() if v not in (None, "")})
    return out


def load_csv(path: str | None) -> list[dict]:
    if path:
        raw = Path(path).read_bytes()
    else:
        req = urllib.request.Request(URL, headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=120) as r:
            raw = r.read()
    if raw[:2] == b"\x1f\x8b":
        raw = gzip.decompress(raw)
    return list(csv.DictReader(io.StringIO(raw.decode("utf-8", "replace"))))


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", help="a local players.csv or players.csv.gz instead of the download")
    ap.add_argument("--out", default=str(OUT))
    ap.add_argument("--as-of", default="2026-07-06", help="the date the dataset is current to (its README)")
    ap.add_argument("--min-season", type=int, default=2024)
    a = ap.parse_args(argv)
    rows = load_csv(a.csv)
    players = compact(rows, a.min_season)
    out = {"source": "Transfermarkt data via the open transfermarkt-datasets project (CC0); market values are Transfermarkt's estimates",
           "as_of": a.as_of, "players": players}
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    Path(a.out).write_text(json.dumps(out, separators=(",", ":"), ensure_ascii=False))
    print(f"{len(rows)} players read, {len(players)} kept -> {a.out} ({Path(a.out).stat().st_size // 1024} KB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
