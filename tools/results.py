"""Final scores of every match and fixture Scudi lists, for the value radar's memory (decision 98, phase 1 step 1.3).

The private store (Supabase) keeps every SNAI and sharp-book price of the matches it pairs (decision 96); to judge those
prices it needs each match's result. The store cannot read ESPN by itself without new set-up, and the daily price job
already runs on GitHub with ESPN working, so the job settles the results and writes them into data/week.json under
"results"; the store's function reads week.json every time it changes and saves them (public.match_results), keyed by
Scudi's match id, which is the id the store already keeps for every paired event.

    results = {"at": <when>, "done": {match id: [home, away, ht home | null, ht away | null, kick-off]},
               "watch": {match id: [competition, home, away, kick-off]}}

Every match and fixture of the week that kicks off within WATCH_AHEAD days is watched; once it has been over for
AFTER, ESPN's scoreboard is asked (one request per competition, the grader's own matching: kick-off ±3 h and names,
90-minute score, half time from the goal minutes). A match ESPN has not settled stays watched for WATCH_DAYS after its
kick-off (postponed ones then drop out: no result is ever invented); a settled one stays in the file KEEP_DAYS, long
enough for the store to have read it many times (the store keeps it for good). Results are public facts; nothing from
the private store ever comes back into this file.
"""

from __future__ import annotations

import time
from datetime import datetime, timedelta

from scudi_slips.comps import BY_NAME

AFTER = timedelta(hours=2, minutes=15)     # a match is asked about this long after its kick-off
WATCH_AHEAD = timedelta(days=3)            # matches and fixtures enter the watch list this close to their kick-off
WATCH_DAYS = 10                            # an unsettled match is asked about for this long, then dropped
KEEP_DAYS = 14                             # a settled match stays in week.json this long after its kick-off
BUDGET_S = 180                             # ESPN is asked for at most this long a run (it never delays the prices by more)


def _when(s: str) -> datetime | None:
    try:
        return datetime.fromisoformat(str(s).replace("Z", "+00:00"))
    except ValueError:
        return None


def slugs_of(week: dict) -> dict[str, str | None]:
    out = {c["name"]: c.get("espn") for c in week.get("competitions", []) if isinstance(c, dict) and c.get("name")}
    out.update({n: c.espn for n, c in BY_NAME.items()})
    return out


def update(prev: dict | None, week: dict, now: datetime, fetch=None, budget_s: float = BUDGET_S) -> tuple[dict, list[str]]:
    """The new results section from the stored one and the week; `fetch` reads ESPN (None: no network, only the watch
    list and the pruning are updated)."""
    from tools.grade import espn_finals  # here, not at the top: tools.grade imports tools.weekly, which imports this

    prev = prev if isinstance(prev, dict) else {}
    done = {k: v for k, v in (prev.get("done") or {}).items() if isinstance(v, list) and len(v) == 5}
    watch = {k: v for k, v in (prev.get("watch") or {}).items() if isinstance(v, list) and len(v) == 4}
    notes: list[str] = []
    for it in list(week.get("matches") or []) + list(week.get("fixtures") or []):
        mid, ko = it.get("id"), _when(it.get("kickoff", ""))
        if not mid or ko is None or mid in done or not it.get("home") or not it.get("away"):
            continue
        if ko - now <= WATCH_AHEAD and now - ko <= timedelta(days=WATCH_DAYS):
            watch[mid] = [it.get("competition", ""), it["home"], it["away"], it["kickoff"]]
    due = [{"id": k, "competition": v[0], "home": v[1], "away": v[2], "kickoff": v[3]} for k, v in watch.items()
           if (_when(v[3]) or now) + AFTER <= now]
    if due and fetch is not None:
        end = time.monotonic() + budget_s

        def timed(url: str):
            if time.monotonic() > end:
                raise TimeoutError("the run's time for ESPN is spent")
            return fetch(url)
        finals, fnotes = espn_finals(timed, due, slugs_of(week))
        notes += fnotes
        for mid, fs in finals.items():
            ht = (fs[2], fs[3]) if len(fs) == 4 else (None, None)
            done[mid] = [int(fs[0]), int(fs[1]), ht[0], ht[1], watch[mid][3]]
            watch.pop(mid, None)
        notes.append(f"results: {len(finals)} of {len(due)} finished matches settled from ESPN")
    gone = [k for k, v in watch.items() if (_when(v[3]) or now) < now - timedelta(days=WATCH_DAYS)]
    for k in gone:
        watch.pop(k)
    if gone:
        notes.append(f"results: {len(gone)} matches never settled in {WATCH_DAYS} days (postponed or not on ESPN), dropped")
    done = dict(sorted((k, v) for k, v in done.items() if (_when(v[4]) or now) >= now - timedelta(days=KEEP_DAYS)))
    watch = dict(sorted(watch.items()))
    same = done == (prev.get("done") or {}) and watch == (prev.get("watch") or {})
    return {"at": prev.get("at") if same and prev.get("at") else now.isoformat(), "done": done, "watch": watch}, notes
