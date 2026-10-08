"""Local end-to-end check of the automatic SNAI prices (decision 92), with nothing real involved:

- a throwaway Postgres (tests/sql/supabase_stub.sql + the migration) stands in for the Supabase project;
- this script serves, on 127.0.0.1:54321, the few Supabase endpoints the function and the site use (REST tables and
  rpc with the same roles and row-level security as Supabase, sign-in, the function's address) plus a stand-in for
  odss-api.com (SNAI-like events for the week's matches, with decoys) and for the site's data/week.json;
- the real Edge Function (supabase/functions/snai-pull/index.ts) runs under Deno, pointed at those.

    python3 tests/feed_local.py --pg /var/lib/postgresql/scudi-test          # the function's checks
    python3 tests/feed_local.py --pg … --serve                               # keep serving (for the site's browser test)

Needs Postgres 16 running on that socket directory (port 55432), Deno and psycopg. Not part of the default test run.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import threading
import time
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import psycopg
from psycopg.types.json import Jsonb

ROOT = Path(__file__).resolve().parents[1]
PORT = 54321
SECRET = "sb_secret_localtest"
PUBLISHABLE = "sb_publishable_localtest"
ODSS_KEY = "odss_live_localtest"
USERS = {"gianluca@example.com": ("11111111-1111-1111-1111-111111111111", "pw-owner"),
         "other@example.com": ("22222222-2222-2222-2222-222222222222", "pw-other")}
TABLES = {"book_events", "feed_state", "feed_log", "owners", "user_state", "push_subs", "notify_sent"}
STATE: dict = {"quota": 500, "odss_calls": [], "week": None, "events": [], "odss_status": 200, "week_reads": []}
NOW = datetime.now(timezone.utc).replace(second=0, microsecond=0)


def iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")


# ---------- the week and SNAI's list ----------
NAT_IT = {"Germany": "Germania", "Netherlands": "Olanda", "England": "Inghilterra", "Spain": "Spagna", "Faroe Islands": "Isole Faroe"}
CLUBS = [("Serie A", "Juventus", "Internazionale", "Juventus", "Inter"), ("Serie A", "AC Milan", "Napoli", "Milan", "Napoli"),
         ("Serie A", "Hellas Verona", "Bologna", "Verona", "Bologna"), ("Premier League", "Arsenal", "Chelsea", "Arsenal", "Chelsea"),
         ("Premier League", "Manchester City", "Liverpool", "Manchester City", "Liverpool"), ("La Liga", "Real Madrid", "Barcelona", "Real Madrid", "Barcellona"),
         ("Bundesliga", "Bayern Munich", "Borussia Dortmund", "Bayern Monaco", "Borussia Dortmund"), ("Ligue 1", "Paris Saint-Germain", "Marseille", "PSG", "Marsiglia"),
         ("Nations League", "Germany", "Netherlands", None, None), ("Nations League", "England", "Spain", None, None),
         ("Champions League", "Atletico Madrid", "Tottenham Hotspur", "Atletico Madrid", "Tottenham"), ("Serie B", "Sampdoria", "Palermo", "Sampdoria", "Palermo")]
HOURS = [2, 5, 20, 26, 30, 50, 75, 100, 125, 150, 170, 190]   # kick-offs from now: two within three hours, some beyond 48 h
FIXTURES = [("Serie B", "Empoli", "Palermo", "Empoli", "Palermo", 28), ("Championship", "West Bromwich Albion", "Birmingham City", "West Brom", "Birmingham", 29),
            ("Ligue 2", "Saint Etienne", "Rodez AF", "Saint-Etienne", "Rodez", 31), ("Eredivisie", "PSV Eindhoven", "Heerenveen", "PSV", "Heerenveen", 52),
            ("Süper Lig", "Kasimpasa SK", "Rizespor", None, None, 53)]   # the last: SNAI does not list it


def build_world() -> None:
    matches, events = [], []
    for i, (comp, home, away, sh, sa) in enumerate(CLUBS):
        k = NOW + timedelta(hours=HOURS[i])
        matches.append({"id": f"m{i}", "competition": comp, "kickoff": k.isoformat(), "home": home, "away": away})
        sh = sh or NAT_IT.get(home, home)
        sa = sa or NAT_IT.get(away, away)
        lg = {"Nations League": "UEFA Nations League", "Champions League": "UEFA Champions League", "La Liga": "LaLiga"}.get(comp, comp)
        events.append({"id": f"ev{i:02d}aa", "home": sh, "away": sa, "league": lg, "k": k, "true": f"m{i}", "p": 1.6 + i * 0.15})
        # decoys at the same kick-off: the youth teams, and a match elsewhere that only shares the time
        events.append({"id": f"ev{i:02d}u19", "home": sh + " U19", "away": sa + " U19", "league": "Primavera 1" if comp == "Serie A" else "UEFA Youth League", "k": k, "true": None, "p": 2.0})
        events.append({"id": f"ev{i:02d}xx", "home": f"Club {i} Norte", "away": f"Club {i} Sur", "league": "Primera B", "k": k, "true": None, "p": 2.4})
    # a match of the week whose only SNAI namesake starts an hour later (a time-zone slip would look like this):
    # never paired, reported
    slip = NOW + timedelta(hours=60)
    matches.append({"id": "mslip", "competition": "La Liga", "kickoff": slip.isoformat(), "home": "Sevilla", "away": "Valencia"})
    events.append({"id": "evslip", "home": "Siviglia", "away": "Valencia", "league": "LaLiga", "k": slip + timedelta(hours=1), "true": None, "p": 2.2})
    # a match the week does not have
    events.append({"id": "evnone", "home": "Boca Juniors", "away": "River Plate", "league": "Liga Profesional", "k": NOW + timedelta(hours=7), "true": None, "p": 2.6})
    # decision 94: the fixtures the weekly job has not priced yet (the smaller leagues before Friday); week.json lists the
    # priced matches among its fixtures too, and one fixture has no SNAI event at all
    fixtures = [dict(m) for m in matches[:2]]
    for j, (comp, home, away, sh, sa, hrs) in enumerate(FIXTURES):
        k = NOW + timedelta(hours=hrs)
        fixtures.append({"id": f"f{j}", "competition": comp, "kickoff": k.isoformat(), "home": home, "away": away, "priced_from": iso(NOW + timedelta(days=2))})
        if sh:
            events.append({"id": f"evf{j}", "home": sh, "away": sa, "league": comp, "k": k, "true": f"f{j}", "p": 2.0 + j * 0.2})
    fixtures.append({"id": "ffar", "competition": "Serie B", "kickoff": (NOW + timedelta(days=12)).isoformat(), "home": "Bari", "away": "Pisa"})   # beyond SNAI's eight days
    STATE["week"] = {"built_at": iso(NOW), "matches": matches, "fixtures": fixtures}
    STATE["events"] = events


IT_NAMES = {"Internazionale": "Inter", "AC Milan": "Milan", "Bayern Munich": "Bayern Monaco", "Paris Saint-Germain": "PSG", "Marseille": "Marsiglia",
            "Barcelona": "Barcellona", "Sevilla": "Siviglia", "Atletico Madrid": "Atletico Madrid", "Hellas Verona": "Verona"}


def site_world(path: Path) -> None:
    """SNAI's list for the site's own example week (for the browser test): every match with prices close to its chances
    (6% margin), Italian names where SNAI uses them, and a youth namesake at the same kick-off."""
    week = json.loads(path.read_text())
    events = []
    for i, m in enumerate(week["matches"]):
        ch = m.get("chances") or {}
        pr = {c: round(1 / (ch[c] * 1.06), 2) for c in ("1", "X", "2", "1X", "12", "X2", "U15", "O15", "U25", "O25", "U35", "O35", "GG", "NG") if ch.get(c)}
        k = datetime.fromisoformat(m["kickoff"].replace("Z", "+00:00"))
        home, away = IT_NAMES.get(m["home"], m["home"]), IT_NAMES.get(m["away"], m["away"])
        events.append({"id": f"sw{i:03d}", "home": home, "away": away, "league": m["competition"], "k": k, "true": m["id"], "prices": pr})
        events.append({"id": f"sw{i:03d}y", "home": home + " U19", "away": away + " U19", "league": "Youth", "k": k, "true": None, "p": 2.0})
    STATE["week"] = {"built_at": iso(NOW), "matches": [{k: m[k] for k in ("id", "competition", "kickoff", "home", "away")} for m in week["matches"]]}
    STATE["events"] = events


def live_world(path: Path) -> None:
    """Decision 94, for the browser test: a real week file (priced matches and fixtures). SNAI's list has every match and
    every fixture of the next eight days (prices from the week's chances, or invented for the fixtures), with Pinnacle
    beside it; one fixture has SNAI's prices but no sharp book (it stays a fixture, with SNAI's result prices), one is not
    on SNAI at all."""
    import random
    rnd = random.Random(94)
    week = json.loads(path.read_text())
    events, end = [], NOW + timedelta(days=8)
    def priced(ch: dict) -> dict:
        return {c: round(1 / (ch[c] * 1.06), 2) for c in ("1", "X", "2", "1X", "12", "X2", "U15", "O15", "U25", "O25", "U35", "O35", "GG", "NG") if ch.get(c)}
    for i, m in enumerate(week["matches"]):
        k = datetime.fromisoformat(m["kickoff"].replace("Z", "+00:00"))
        if k < NOW or k > end:
            continue
        events.append({"id": f"lm{i:03d}", "home": IT_NAMES.get(m["home"], m["home"]), "away": IT_NAMES.get(m["away"], m["away"]), "league": m["competition"], "k": k, "true": m["id"], "prices": priced(m.get("chances") or {})})
    ids = {m["id"] for m in week["matches"]}
    fx = [f for f in week.get("fixtures", []) if f["id"] not in ids and NOW < datetime.fromisoformat(f["kickoff"].replace("Z", "+00:00")) <= end]
    for j, f in enumerate(fx):
        k = datetime.fromisoformat(f["kickoff"].replace("Z", "+00:00"))
        if j == 1:
            STATE["not_on_snai"] = f["id"]
            continue
        h, d, o = rnd.uniform(0.3, 0.55), 0.27, rnd.uniform(0.42, 0.58)
        a = 1 - h - d
        ch = {"1": h, "X": d, "2": a, "1X": h + d, "12": h + a, "X2": d + a, "O25": o, "U25": 1 - o, "O15": min(0.9, o + 0.25), "U15": max(0.1, 0.75 - o), "GG": o + 0.03, "NG": 0.97 - o}
        ev = {"id": f"lf{j:03d}", "home": f["home"], "away": f["away"], "league": f["competition"], "k": k, "true": f["id"], "prices": priced(ch)}
        if j == 2:
            ev["nosharp"] = True
            STATE["no_sharp"] = f["id"]
        events.append(ev)
    STATE["week"] = {"built_at": week.get("built_at", iso(NOW)), "matches": [{k: m[k] for k in ("id", "competition", "kickoff", "home", "away")} for m in week["matches"]],
                     "fixtures": [{k: f.get(k) for k in ("id", "competition", "kickoff", "home", "away")} for f in week.get("fixtures", [])]}
    STATE["events"] = events


def records_for(ev: dict, markets: list[str]) -> list[dict]:
    base = {"event_id": ev["id"], "event": f'{ev["home"]} - {ev["away"]}', "sport": "calcio", "league": ev["league"], "home_team": ev["home"],
            "away_team": ev["away"], "commence_time": iso(ev["k"]), "line": None, "scope": None, "period": None, "state": "prematch", "score": None, "minute": None}
    lu = iso(NOW - timedelta(minutes=4))
    def sharp(outs: dict) -> dict:   # Pinnacle: SNAI's view of the match at a 2.5% margin (a sharp book's prices)
        if len(outs) < 2:
            return {}
        tot = sum(1 / v for v in outs.values())
        return {k: round(1 / ((1 / v) / tot * 1.025), 2) for k, v in outs.items()}
    book = lambda outs, **kw: [dict({"key": "snai", "country": "IT", "playable_it": True, "outcomes": outs, "last_update": lu}, **kw)] + \
        ([{"key": "pinnacle", "outcomes": sharp(outs), "last_update": lu}] if sharp(outs) and not ev.get("nosharp") else [])
    out = []
    if ev.get("prices") is not None:   # the browser test's world: prices from the week's chances
        P = ev["prices"]
        groups = [("1x2", None, {"HOME": "1", "DRAW": "X", "AWAY": "2"}), ("dc", None, {"1X": "1X", "12": "12", "X2": "X2"}), ("btts", None, {"YES": "GG", "NO": "NG"})]
        groups += [("ou", ln, {"UNDER": f"U{c}5", "OVER": f"O{c}5"}) for ln, c in ((1.5, 1), (2.5, 2), (3.5, 3))]
        for mk, ln, keys in groups:
            outs = {o: P[c] for o, c in keys.items() if c in P}
            if mk in markets and outs:
                out.append(dict(base, market=mk, line=ln, bookmakers=book(outs)))
        return out
    p = ev["p"]
    if "1x2" in markets:
        out.append(dict(base, market="1x2", bookmakers=book({"HOME": p, "DRAW": 3.4, "AWAY": round(6 / p, 2)})))
        out.append(dict(base, market="1x2", period="1T", bookmakers=book({"HOME": 2.9, "DRAW": 2.0, "AWAY": 4.5})))   # first half: never taken
    if "dc" in markets:
        out.append(dict(base, market="dc", bookmakers=book({"1X": 1.2, "12": 1.3, "X2": 1.9})))
    if "ou" in markets:
        for line, (u, o) in {0.5: (8.0, 1.06), 1.5: (3.6, 1.28), 2.5: (1.95, 1.85), 3.5: (1.4, 2.9), 4.5: (1.15, 5.2), 2.25: (1.8, 2.0)}.items():
            out.append(dict(base, market="ou", line=line, bookmakers=book({"UNDER": u, "OVER": o})))
        out.append(dict(base, market="ou", line=1.5, scope="home", bookmakers=book({"UNDER": 1.7, "OVER": 2.1})))   # a team total: never taken
    if "btts" in markets:
        if ev["id"] == "ev00aa":   # one suspended outcome (SNAI's padlock)
            out.append(dict(base, market="btts", bookmakers=book({"YES": 1.66}, suspended=["NO"])))
        else:
            out.append(dict(base, market="btts", bookmakers=book({"YES": 1.7, "NO": 2.05})))
    return out


def books() -> tuple[int, dict, dict]:
    """odss-api's list of books (GET /bookmakers): two sharp ones, Pinnacle and the Betfair exchange."""
    STATE["odss_calls"].append({"_path": "bookmakers"})
    if STATE["odss_status"] != 200:
        return STATE["odss_status"], {"error": "Chiave API non valida", "code": "auth_invalid"}, {}
    STATE["quota"] -= 1
    hdr = {"X-Quota-Limit": "500", "X-Quota-Remaining": str(STATE["quota"]), "X-Quota-Reset": str(20 * 86400)}
    return 200, {"count": 4, "bookmakers": [{"key": "snai", "country": "IT", "is_exchange": False}, {"key": "pinnacle", "country": "CW", "is_exchange": False},
                                            {"key": "betfair_ex", "country": "GB", "is_exchange": True}, {"key": "bet365", "country": "GB", "is_exchange": False}]}, hdr


def odss(query: dict) -> tuple[int, dict, dict]:
    q = {k: v[0] for k, v in query.items()}
    q["_path"] = "odds"
    STATE["odss_calls"].append(q)
    if STATE["odss_status"] != 200:
        return STATE["odss_status"], {"error": "Chiave API non valida", "code": "auth_invalid"}, {}
    STATE["quota"] -= 1
    hdr = {"X-Quota-Limit": "500", "X-Quota-Remaining": str(STATE["quota"]), "X-Quota-Reset": str(20 * 86400), "RateLimit": "limit=30, remaining=29, reset=59"}
    markets = q.get("market", "1x2").split(",")
    if "event_id" in q:
        ids = set(q["event_id"].split(","))
        evs = [e for e in STATE["events"] if e["id"] in ids]
    else:
        lo, hi = q.get("commence_from"), q.get("commence_to")
        evs = [e for e in STATE["events"] if (not lo or iso(e["k"]) >= lo) and (not hi or iso(e["k"]) <= hi)]
    recs = [r for e in sorted(evs, key=lambda e: e["id"]) for r in records_for(e, markets)]
    limit = int(q.get("limit") or 500)
    start = int(q["after"]) if q.get("after") else 0
    page = recs[start:start + limit]
    nxt = str(start + limit) if start + limit < len(recs) else None
    return 200, {"count": len(recs), "returned": len(page), "limit": limit, "state": "prematch", "odds": page, "next_after": nxt}, hdr


# ---------- Supabase, the little that is used ----------
def db():
    return psycopg.connect(STATE["dsn"], autocommit=True)


def role_of(headers) -> tuple[str, str | None]:
    """service_role for the secret key; authenticated with the token's user for a signed-in call; else anon"""
    key = headers.get("apikey") or ""
    auth = headers.get("Authorization") or ""
    if key == SECRET and not auth:
        return "service_role", None
    m = re.match(r"Bearer tok-([0-9a-f-]{36})$", auth)
    if key == PUBLISHABLE and m:
        return "authenticated", m.group(1)
    if key in (PUBLISHABLE, SECRET):
        return "anon", None
    raise PermissionError("no valid apikey")


def run_as(role: str, uid: str | None, sql: str, args: tuple = ()):
    with db() as c, c.transaction():
        c.execute(f"set local role {role}")
        if uid:
            c.execute("select set_config('request.jwt.claim.sub', %s, true)", (uid,))
        cur = c.execute(sql, args)
        return cur.fetchall() if cur.description else None


def rest_get(table: str, query: dict, role: str, uid: str | None):
    if table not in TABLES:
        raise ValueError("unknown table")
    cols = (query.pop("select", ["*"])[0]).split(",")
    if cols != ["*"] and not all(re.fullmatch(r"[a-z_]+", c) for c in cols):
        raise ValueError("bad select")
    where, args, order, limit = [], [], "", ""
    for k, vs in query.items():
        v = vs[0]
        if k == "order":
            col, _, d = v.partition(".")
            order = f" order by {col} {'desc' if d == 'desc' else 'asc'}" if re.fullmatch(r"[a-z_]+", col) else ""
            continue
        if k == "limit":
            limit = f" limit {int(v)}"
            continue
        if not re.fullmatch(r"[a-z_]+", k):
            raise ValueError("bad filter")
        op, _, val = v.partition(".")
        if op == "in":   # in.("a","b") or in.(a,b)
            items = [x.strip().strip('"') for x in val.strip("()").split(",") if x.strip()]
            where.append(f"{k}::text = any(%s)")
            args.append(items)
            continue
        sqlop = {"eq": "=", "gt": ">", "gte": ">=", "lt": "<", "lte": "<="}.get(op)
        if not sqlop:
            raise ValueError("bad op")
        where.append(f"{k} {sqlop} %s")
        args.append(val)
    sel = ", ".join(cols) if cols != ["*"] else "*"
    sql = f"select coalesce(json_agg(t), '[]'::json) from (select {sel} from public.{table}{' where ' + ' and '.join(where) if where else ''}{order}{limit}) t"
    return run_as(role, uid, sql, tuple(args))[0][0]


def rpc(fn: str, body: dict, role: str, uid: str | None):
    if not re.fullmatch(r"[a-z_]+", fn):
        raise ValueError("bad fn")
    names = list(body.keys())
    if not all(re.fullmatch(r"[a-z_]+", n) for n in names):
        raise ValueError("bad args")
    params = ", ".join(f"{n} => %s" for n in names)
    vals = tuple(Jsonb(v) if isinstance(v, dict | list) else v for v in body.values())
    rows = run_as(role, uid, f"select public.{fn}({params})", vals)
    v = rows[0][0]
    return None if v == "" else v


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):  # quiet
        pass

    def send(self, code: int, body, headers: dict | None = None):
        data = b"" if body is None else (body if isinstance(body, bytes) else json.dumps(body).encode())
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "authorization, apikey, content-type, x-client-info, x-cron-token")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_OPTIONS(self):
        self.send(204, None)

    def body(self) -> dict:
        n = int(self.headers.get("Content-Length") or 0)
        return json.loads(self.rfile.read(n) or b"{}") if n else {}

    def do_GET(self):
        u = urllib.parse.urlsplit(self.path)
        q = urllib.parse.parse_qs(u.query, keep_blank_values=True)
        try:
            if u.path in ("/odss/api/v1/odds", "/odss/api/v1/bookmakers"):
                if self.headers.get("x-api-key") != ODSS_KEY and STATE["odss_status"] == 200:
                    return self.send(401, {"error": "Chiave API mancante", "code": "auth_missing"})
                code, body, hdr = odss(q) if u.path.endswith("/odds") else books()
                return self.send(code, body, hdr)
            if u.path == "/site/data/week.json":
                raw = json.dumps(STATE["week"], sort_keys=True)
                tag = '"' + hashlib.md5(raw.encode()).hexdigest() + '"'
                STATE["week_reads"].append(self.headers.get("If-None-Match") == tag)
                if self.headers.get("If-None-Match") == tag:
                    return self.send(304, None, {"ETag": tag})
                return self.send(200, STATE["week"], {"ETag": tag})
            if u.path == "/auth/v1/user":
                m = re.match(r"Bearer tok-([0-9a-f-]{36})$", self.headers.get("Authorization") or "")
                if not m or self.headers.get("apikey") not in (SECRET, PUBLISHABLE):
                    return self.send(401, {"msg": "invalid JWT"})
                return self.send(200, {"id": m.group(1)})
            if u.path.startswith("/rest/v1/"):
                role, uid = role_of(self.headers)
                return self.send(200, rest_get(u.path[9:], q, role, uid))
        except PermissionError as e:
            return self.send(401, {"message": str(e)})
        except psycopg.errors.InsufficientPrivilege as e:
            return self.send(403, {"message": str(e).splitlines()[0]})
        except Exception as e:
            return self.send(400, {"message": str(e).splitlines()[0]})
        self.send(404, {"message": "not found"})

    def do_POST(self):
        u = urllib.parse.urlsplit(self.path)
        q = urllib.parse.parse_qs(u.query)
        try:
            if u.path.startswith("/rest/v1/rpc/"):
                role, uid = role_of(self.headers)
                return self.send(200, rpc(u.path[13:], self.body(), role, uid))
            if u.path == "/auth/v1/token":
                b = self.body()
                if self.headers.get("apikey") != PUBLISHABLE:
                    return self.send(401, {"msg": "No API key found in request"})
                if q.get("grant_type") == ["password"]:
                    hit = USERS.get(b.get("email", ""))
                    if not hit or hit[1] != b.get("password"):
                        return self.send(400, {"error": "invalid_grant", "error_description": "Invalid login credentials"})
                    uid = hit[0]
                elif q.get("grant_type") == ["refresh_token"]:
                    m = re.match(r"ref-([0-9a-f-]{36})$", b.get("refresh_token", ""))
                    if not m:
                        return self.send(400, {"error": "invalid_grant", "error_description": "Invalid Refresh Token"})
                    uid = m.group(1)
                else:
                    return self.send(400, {"error": "unsupported_grant_type"})
                email = next(e for e, v in USERS.items() if v[0] == uid)
                return self.send(200, {"access_token": f"tok-{uid}", "token_type": "bearer", "expires_in": 3600, "expires_at": int(time.time()) + 3600,
                                       "refresh_token": f"ref-{uid}", "user": {"id": uid, "email": email}})
            if u.path == "/auth/v1/logout":
                return self.send(204, None)
            if u.path == "/functions/v1/snai-pull":
                n = int(self.headers.get("Content-Length") or 0)
                data = self.rfile.read(n) if n else b"{}"
                fwd = {k: v for k, v in self.headers.items() if k.lower() in ("authorization", "apikey", "content-type", "x-cron-token")}
                req = urllib.request.Request("http://127.0.0.1:8000/", data=data, headers=fwd, method="POST")
                try:
                    with urllib.request.urlopen(req, timeout=60) as r:
                        return self.send(r.status, r.read())
                except urllib.error.HTTPError as e:
                    return self.send(e.code, e.read())
        except PermissionError as e:
            return self.send(401, {"message": str(e)})
        except psycopg.errors.InsufficientPrivilege as e:
            return self.send(403, {"message": str(e).splitlines()[0]})
        except Exception as e:
            return self.send(400, {"message": str(e).splitlines()[0]})
        self.send(404, {"message": "not found"})


# ---------- set-up ----------
def fresh_db(sock: str) -> None:
    admin = f"host={sock} port=55432 user=postgres dbname=postgres"
    with psycopg.connect(admin, autocommit=True) as c:
        c.execute("drop database if exists scudi_feed with (force)")
        c.execute("create database scudi_feed")
    STATE["dsn"] = f"host={sock} port=55432 user=postgres dbname=scudi_feed"
    with psycopg.connect(STATE["dsn"], autocommit=True) as c:
        c.execute((ROOT / "tests/sql/supabase_stub.sql").read_text())
        for mig in sorted((ROOT / "supabase/migrations").glob("*.sql")):   # every migration, in order
            c.execute(mig.read_text())
        for email, (uid, _) in USERS.items():   # the owner signs up first
            c.execute("insert into auth.users (id, email) values (%s, %s)", (uid, email))


def start_function(odss_key: str) -> subprocess.Popen:
    env = dict(os.environ, SUPABASE_URL=f"http://127.0.0.1:{PORT}", SUPABASE_SECRET_KEYS=json.dumps({"default": SECRET}),
               ODSS_API_KEY=odss_key, ODSS_BASE_URL=f"http://127.0.0.1:{PORT}/odss/api/v1", SCUDI_SITE_URL=f"http://127.0.0.1:{PORT}/site/", NO_COLOR="1")
    fn = os.environ.get("SCUDI_FN") or str(ROOT / "supabase/functions/snai-pull/index.ts")   # or the dashboard's one-file copy
    p = subprocess.Popen(["deno", "run", "--allow-net", "--allow-env", fn], env=env,
                         stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    for _ in range(100):
        try:
            urllib.request.urlopen(urllib.request.Request("http://127.0.0.1:8000/", method="OPTIONS"), timeout=1)
            return p
        except Exception:
            time.sleep(0.2)
    raise RuntimeError("the function did not start: " + (p.stdout.read(2000).decode() if p.stdout else ""))


def call(headers: dict | None = None) -> tuple[int, dict]:
    req = urllib.request.Request(f"http://127.0.0.1:{PORT}/functions/v1/snai-pull", data=b"{}", headers=dict({"Content-Type": "application/json"}, **(headers or {})), method="POST")
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return r.status, json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"{}")


def sql(q: str, *a):
    with psycopg.connect(STATE["dsn"], autocommit=True) as c:
        cur = c.execute(q, a)
        return cur.fetchall() if cur.description else None


RESULTS: list[tuple[bool, str]] = []


def check(cond, msg: str) -> None:
    RESULTS.append((bool(cond), msg))
    print(("PASS " if cond else "FAIL ") + msg, flush=True)


def checks() -> None:
    token = sql("select cron_token from private.feed_config")[0][0]
    code, r = call({"x-cron-token": "nope" * 10})
    check(code == 403, f"a wrong cron token is refused ({code})")
    code, r = call()
    check(code == 401, f"a call with no sign-in and no token is refused ({code})")

    code, r = call({"x-cron-token": token})
    check(code == 200 and r.get("pulled") and r.get("status") == "ok", f"the first wake by day pulls: {r}")
    calls = STATE["odss_calls"]
    check(len(calls) == 3 and calls[0]["_path"] == "bookmakers" and calls[1].get("market") == "1x2" and calls[1].get("sport") == "calcio" and "event_id" in calls[2],
          f"three requests: odss-api's list of books (once a week), SNAI's list (1X2), then the prices by event id ({[c.get('_path') + ':' + str(c.get('market')) for c in calls]})")
    check(calls[1].get("bookmakers") == "snai" and calls[2].get("bookmakers") == "snai,pinnacle,betfair_ex,bet365", f"the list asks SNAI only, the prices SNAI and the reference books ({calls[2].get('bookmakers')})")
    check(all(ODSS_KEY not in json.dumps(c) for c in calls), "the key never travels in the address")
    rows = {r[0]: r for r in sql("select event_id, match_id, m, full_at, odds_at, fit from public.book_events")}
    true = {e["id"]: e["true"] for e in STATE["events"] if e["true"]}
    check(set(true) <= set(rows), f"every one of the week's matches and fixtures has its SNAI event ({len(set(true) & set(rows))}/{len(true)})")
    check(all(rows[i][1] == m for i, m in true.items() if i in rows), "each paired with the right match or fixture")
    check(not any(i.endswith("u19") for i in rows) and "evslip" not in rows and "evnone" not in rows, f"no youth team, no hour-late namesake, no match outside the week ({sorted(i for i in rows if i not in true)})")
    check(all(rows[f"evf{j}"][1] == f"f{j}" for j in range(4)), "the fixtures not priced yet (Serie B, Championship, Ligue 2, Eredivisie) are paired too")
    m0 = rows["ev00aa"][2]
    codes = {(x[0], x[1], x[2]) for x in m0}
    check({(3, 0, 1), (3, 0, 2), (3, 0, 3), (28319, 0, 1), (28319, 0, 2), (28319, 0, 3), (18, 0, 1), (18, 0, 2)} <= codes and {(7989, ln, oc) for ln in (50, 150, 250, 350, 450) for oc in (1, 2)} <= codes,
          "all four markets in SNAI's codes, every half-goal line")
    check(not any(x[0] == 7989 and x[1] == 225 for x in m0) and len(m0) == 3 + 3 + 10 + 2, f"no first-half, team-total or Asian line slipped in ({len(m0)} prices)")
    check(next(x for x in m0 if x[0] == 18 and x[2] == 2)[3] is None, "SNAI's suspended No Goal is a padlock (null)")
    check(next(x for x in m0 if x[0] == 3 and x[2] == 1)[3] == 1.6, "the 1 is SNAI's price, not Pinnacle's")
    check(all(r[3] is not None for r in rows.values()), "every paired event got its full markets in the first pull")
    # decision 94: Scudi's own chances from the sharp book, for every paired event
    sys.path.insert(0, str(ROOT))
    from scudi_slips.devig import power_devig
    from scudi_slips.matrix import fit_market
    fit0 = rows["ev00aa"][5]
    pin = lambda outs: {k: round(1 / ((1 / v) / sum(1 / x for x in outs.values()) * 1.025), 2) for k, v in outs.items()}
    p1x2 = pin({"HOME": 1.6, "DRAW": 3.4, "AWAY": round(6 / 1.6, 2)})
    pou = pin({"UNDER": 1.95, "OVER": 1.85})
    fair = power_devig([p1x2["HOME"], p1x2["DRAW"], p1x2["AWAY"]])
    over = power_devig([pou["OVER"], pou["UNDER"]])[0]
    ref = fit_market(fair[0], fair[1], fair[2], over)
    check(all(r[5] for r in rows.values()), f"every paired event has Scudi's own chances from the sharp book ({sum(1 for r in rows.values() if r[5])}/{len(rows)})")
    check(fit0 and fit0["books"] == ["pinnacle"] and fit0["goals"] is True and abs(fit0["p"][0] - fair[0]) < 1e-4 and abs(fit0["p"][3] - over) < 1e-4,
          f"from Pinnacle's prices, de-vigged as the weekly job does ({fit0 and fit0['p']} vs {[round(x, 4) for x in fair]}, {over:.4f})")
    check(abs(fit0["lh"] - ref.lh) < 2e-3 and abs(fit0["la"] - ref.la) < 2e-3 and fit0["err"] <= 0.01, f"the same expected goals as scudi_slips.matrix.fit_market ({fit0['lh']}, {fit0['la']} vs {ref.lh:.4f}, {ref.la:.4f})")
    st = sql("select quota_remaining, quota_limit, last_status, last_requests, discovered_at is not null, matched, of_matches, diag, events, busy_until from public.feed_state")[0]
    check(st[0] == STATE["quota"] and st[1] == 500, f"the quota comes from odss-api's headers ({st[0]} left)")
    check(st[2] == "ok" and st[3] == 3 and st[4] and st[9] is None, "state: ok, three requests, list read, lease freed")
    check(st[5] == len(CLUBS) + 4 and st[6] == len(CLUBS) + 1 + 5, f"{st[5]} of {st[6]} matches and fixtures paired (Sevilla - Valencia has no SNAI event at its kick-off, Kasimpasa - Rizespor none at all)")
    dg = st[7] or {}
    check(any("Sevilla" in d["match"] and d["offMin"] == 60 for d in dg.get("timezone", [])), f"its namesake an hour late is reported for checking: {dg.get('timezone')}")
    un = {u["match"]: u for u in dg.get("unpaired", [])}
    check(set(un) == {"Sevilla - Valencia", "Kasimpasa SK - Rizespor"} and un["Sevilla - Valencia"]["snai"]["offMin"] == 60 and un["Kasimpasa SK - Rizespor"]["snai"] is None and un["Kasimpasa SK - Rizespor"]["priced"] is False,
          f"what was not paired is listed, with SNAI's nearest namesake or none ({list(un)})")
    check(dg.get("books", {}).get("sharp") == ["pinnacle", "betfair_ex", "bet365"] and dg["books"].get("v") == 4 and len(dg["books"].get("all", [])) == 4 and dg.get("by_comp", {}).get("Serie B") == [2, 2] and dg.get("leagues", {}).get("Serie A", 0) >= 3 and dg.get("priced") == [len(CLUBS), len(CLUBS) + 1],
          f"the sharp books, the pairing per competition and SNAI's list by league are recorded ({dg.get('books')}, {dg.get('by_comp', {}).get('Serie B')})")
    check(dg.get("fit", {}).get("fitted") == len(rows), f"the fits are counted ({dg.get('fit')})")
    log = sql("select kind, requests, status from public.feed_log order by id")
    check(log[-1] == ("list+prices", 3, "ok"), f"the log has the pull: {log[-1]}")

    n = len(STATE["odss_calls"])
    code, r = call({"x-cron-token": token})
    check(code == 200 and not r.get("pulled") and r.get("why") in ("waiting", "night"), f"ten minutes later nothing is spent ({r.get('why')})")
    check(len(STATE["odss_calls"]) == n, "no request went out")
    check(STATE["week_reads"][-1] is True, "Scudi's list was asked for only if changed, and it had not changed")
    # decision 94: Scudi's list gets a new fixture (the Friday pull, a new day in the window): SNAI's list is read at once
    kf = NOW + timedelta(hours=40)
    STATE["week"]["fixtures"].append({"id": "fnew", "competition": "Championship", "kickoff": kf.isoformat(), "home": "Watford", "away": "Burnley"})
    STATE["events"].append({"id": "evfnew", "home": "Watford", "away": "Burnley", "league": "Championship", "k": kf, "true": "fnew", "p": 2.3})
    code, r = call({"x-cron-token": token})
    new_calls = STATE["odss_calls"][n:]
    check(code == 200 and r.get("pulled") and sql("select why from public.feed_state")[0][0] == "new-matches" and [c["_path"] for c in new_calls] == ["odds", "odds"] and new_calls[0].get("market") == "1x2",
          f"a new fixture in Scudi's list: SNAI's list is read at once, then the prices ({r}, {[c.get('market') for c in new_calls]})")
    got = sql("select match_id, fit is not null from public.book_events where event_id = 'evfnew'")
    check(got == [("fnew", True)], f"and the new fixture is paired, with its own chances ({got})")
    n = len(STATE["odss_calls"])
    code, r = call({"x-cron-token": token})
    check(not r.get("pulled") and len(STATE["odss_calls"]) == n, f"the next wake has nothing new: nothing spent ({r.get('why')})")
    true = {e["id"]: e["true"] for e in STATE["events"] if e["true"]}

    code, r = call({"apikey": PUBLISHABLE, "Authorization": "Bearer tok-22222222-2222-2222-2222-222222222222"})
    check(code == 401, "another account cannot press Update now")
    owner = {"apikey": PUBLISHABLE, "Authorization": "Bearer tok-11111111-1111-1111-1111-111111111111"}
    code, r = call(owner)
    check(code == 200 and not r.get("pulled") and r.get("why") == "just-pulled", f"the owner's Update now right after a pull waits three minutes ({r.get('why')})")
    sql("update private.feed_config set settings = '{\"manualGapMin\": 0}'")
    STATE["events"][0]["p"] = 1.75   # SNAI moved Juventus' price
    code, r = call(owner)
    check(code == 200 and r.get("pulled") and r.get("requests") == 1, f"the owner's Update now: one request, prices only ({r})")
    p1 = next(x for x in sql("select m from public.book_events where event_id = 'ev00aa'")[0][0] if x[0] == 3 and x[2] == 1)[3]
    check(p1 == 1.75, f"the moved price is stored ({p1})")
    check(sql("select last_kind from public.feed_state")[0][0] == "manual", "the pull is logged as manual")

    STATE["odss_status"] = 401
    code, r = call(owner)
    st = sql("select last_status, backoff_until > now() + interval '5 hours' from public.feed_state")[0]
    check(r.get("status") == "bad-key" and st == ("bad-key", True), f"a refused key is reported and the feed waits six hours ({r}, {st})")
    code, r = call({"x-cron-token": token})
    check(not r.get("pulled") and r.get("why") == "backoff", "meanwhile the cron spends nothing")
    STATE["odss_status"] = 200
    sql("update public.feed_state set backoff_until = null")

    # what the site sees, through the same REST and row-level security
    rows_owner = rest_get("book_events", {"select": ["event_id,m"]}, "authenticated", USERS["gianluca@example.com"][0])
    rows_other = rest_get("book_events", {"select": ["event_id,m"]}, "authenticated", USERS["other@example.com"][0])
    check(len(rows_owner) == len(true) and rows_other == [], f"the owner reads {len(rows_owner)} events, another account none")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pg", required=True, help="Postgres socket directory (port 55432)")
    ap.add_argument("--serve", action="store_true", help="after the checks, keep serving for the site's browser test")
    ap.add_argument("--week", help="no checks: SNAI's list built from this week file (the site's example week), one cron pull, then serve")
    ap.add_argument("--week-live", help="no checks: SNAI's list (and Pinnacle) for a real week file's matches and fixtures, one cron pull, then serve")
    a = ap.parse_args()
    fresh_db(a.pg)
    if a.week_live:
        live_world(Path(a.week_live))
        a.week = a.week_live
    elif a.week:
        site_world(Path(a.week))
    else:
        build_world()
    srv = ThreadingHTTPServer(("127.0.0.1", PORT), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    fn = start_function(ODSS_KEY)
    try:
        if a.week:
            print("first pull:", call({"x-cron-token": sql("select cron_token from private.feed_config")[0][0]}), flush=True)
            print("world:", json.dumps({k: STATE.get(k) for k in ("not_on_snai", "no_sharp")}), "events:", len(STATE["events"]), flush=True)
            a.serve = True
        else:
            checks()
        if a.serve:
            sql("update private.feed_config set settings = '{\"manualGapMin\": 0}'")
            print("serving on 127.0.0.1:54321 — Ctrl+C to stop", flush=True)
            while True:
                time.sleep(3600)
    finally:
        fn.terminate()
        srv.shutdown()
    bad = [m for ok, m in RESULTS if not ok]
    print(f"\n{len(RESULTS) - len(bad)}/{len(RESULTS)} passed")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
