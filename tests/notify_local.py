"""Local end-to-end check of the phone notifications (decision 95), with nothing real involved:

- a throwaway Postgres with every migration stands in for the Supabase project (as in tests/feed_local.py, whose
  stand-in server this reuses: REST tables and rpc with Supabase's roles and row-level security, sign-in);
- the same server stands in for ESPN (scoreboards and a match page with line-ups), for the site's data/teams.json and for
  a push service: every message it receives is decrypted here with the device's private key, as a phone would;
- the real Edge Function (supabase/functions/scudi-notify/index.ts, or the dashboard's one-file copy with SCUDI_FN) runs
  under Deno, pointed at those.

    python3 tests/notify_local.py --pg /var/lib/postgresql/scudi-test

Needs Postgres 16 on that socket directory (port 55432), Deno, psycopg and cryptography. Not part of the default run.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import hmac
import json
import os
import subprocess
import sys
import threading
import time
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from http.server import ThreadingHTTPServer
from pathlib import Path
from zoneinfo import ZoneInfo

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import encode_dss_signature
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

sys.path.insert(0, str(Path(__file__).resolve().parent))
import feed_local as F

ROOT = F.ROOT
OWNER, OTHER = F.USERS["gianluca@example.com"][0], F.USERS["other@example.com"][0]
NOW = datetime.now(timezone.utc).replace(second=0, microsecond=0)
ROME = ZoneInfo("Europe/Rome")
W: dict = {"boards": {}, "summaries": {}, "teams": None, "push": [], "push_status": {}, "espn_reads": [], "summary_reads": [], "teams_reads": 0}


def b64u(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


def unb64u(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ---------- a phone: its keys, and what it reads from a push ----------
class Device:
    def __init__(self, name: str):
        self.name = name
        self.key = ec.generate_private_key(ec.SECP256R1())
        self.pub = self.key.public_key().public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)
        self.auth = os.urandom(16)

    def sub(self) -> dict:
        return {"endpoint": f"http://127.0.0.1:{F.PORT}/push/{self.name}", "keys": {"p256dh": b64u(self.pub), "auth": b64u(self.auth)}, "ua": "test phone"}

    def read(self, body: bytes) -> dict:
        salt, rs, idlen = body[:16], int.from_bytes(body[16:20], "big"), body[20]
        as_pub, ct = body[21:21 + idlen], body[21 + idlen:]
        assert rs == 4096 and idlen == 65
        ecdh = self.key.exchange(ec.ECDH(), ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), as_pub))
        hk = lambda salt_, ikm, info, n: hmac.new(hmac.new(salt_, ikm, hashlib.sha256).digest(), info + b"\x01", hashlib.sha256).digest()[:n]
        ikm = hk(self.auth, ecdh, b"WebPush: info\x00" + self.pub + as_pub, 32)
        cek, nonce = hk(salt, ikm, b"Content-Encoding: aes128gcm\x00", 16), hk(salt, ikm, b"Content-Encoding: nonce\x00", 12)
        plain = AESGCM(cek).decrypt(nonce, ct, None)
        assert plain.endswith(b"\x02")
        return json.loads(plain[:-1].decode())


DEVICES = {"phone": Device("phone"), "ipad": Device("ipad")}


# ---------- ESPN: the matches on the owner's slips ----------
def espn_ev(eid, home, away, kick, state="pre", period=0, clock="0'", h=0, a=0, details=None):
    name = {"pre": "STATUS_SCHEDULED", "in": "STATUS_SECOND_HALF", "post": "STATUS_FULL_TIME"}[state]
    return {"id": eid, "date": iso(kick), "name": f"{away[1]} at {home[1]}", "competitions": [{
        "status": {"period": period, "displayClock": clock, "type": {"name": name, "state": state, "completed": state == "post", "shortDetail": "FT" if state == "post" else ""}},
        "competitors": [{"homeAway": "home", "score": str(h), "team": {"id": home[0], "displayName": home[1]}},
                        {"homeAway": "away", "score": str(a), "team": {"id": away[0], "displayName": away[1]}}],
        "details": details or []}]}


def goal(team, clock, who=""):
    return {"scoringPlay": True, "shootout": False, "ownGoal": False, "clock": {"displayValue": clock}, "team": {"id": team},
            "athletesInvolved": [{"displayName": who, "shortName": who}] if who else []}


K_LIVE, K_DONE, K_LOST, K_SOON = NOW - timedelta(minutes=72), NOW - timedelta(minutes=130), NOW - timedelta(minutes=150), NOW + timedelta(minutes=50)


def rome_day(dt: datetime) -> str:
    return dt.astimezone(ROME).strftime("%Y%m%d")


def world(score_live=(1, 0), final=False) -> None:
    evs = [espn_ev("401", ("110", "Internazionale"), ("111", "Juventus"), K_LIVE, "post" if final else "in", 2, "90'+5'" if final else "67'", *score_live,
                   [goal("110", "67'", "Lautaro Martínez")] + ([goal("110", "80'")] if score_live[0] > 1 else []) + ([goal("111", "88'")] if score_live[1] else [])),
           espn_ev("402", ("104", "AS Roma"), ("112", "Lazio"), K_DONE, "post", 2, "90'+4'", 2, 1, [goal("104", "12'"), goal("112", "40'"), goal("104", "77'")]),
           espn_ev("403", ("105", "Atalanta"), ("239", "Torino"), K_LOST, "post", 2, "90'+2'", 0, 1, [goal("239", "55'")]),
           espn_ev("404", ("114", "Napoli"), ("103", "AC Milan"), K_SOON)]
    W["boards"] = {}
    for e in evs:
        W["boards"].setdefault(("ita.1", rome_day(datetime.fromisoformat(e["date"].replace("Z", "+00:00")))), []).append(e)
    xi = lambda ids, names: [{"starter": True, "athlete": {"id": str(i), "displayName": n, "lastName": n.split(" ", 1)[1]}} for i, n in zip(ids, names)]
    W["summaries"]["404"] = {"rosters": [
        {"homeAway": "home", "team": {"id": "114", "displayName": "Napoli"}, "roster": xi(range(1, 12), ["Alex Meret", "Giovanni Di Lorenzo", "Amir Rrahmani", "Alessandro Buongiorno", "Mathías Olivera", "Frank Anguissa", "Stanislav Lobotka", "Scott McTominay", "Matteo Politano", "Romelu Lukaku", "David Neres"])},
        {"homeAway": "away", "team": {"id": "103", "displayName": "AC Milan"}, "roster": xi(range(21, 32), ["Mike Maignan", "Kyle Walker", "Fikayo Tomori", "Strahinja Pavlovic", "Theo Hernandez", "Youssouf Fofana", "Tijjani Reijnders", "Christian Pulisic", "Rafael Leao", "Alvaro Morata", "Ruben Loftus-Cheek"])}]}
    W["teams"] = {"teams": {"114": {"id": "114", "last": {"xi": [{"id": i} for i in [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 12]]}, "players": [{"id": 12, "short": "K. Kvaratskhelia"}, {"id": 11, "short": "D. Neres"}]}}}


def leg(mid, home, away, th, ta, kick, code, p):
    return {"mid": mid, "home": home, "away": away, "th": th, "ta": ta, "lg": "Serie A", "kick": iso(kick), "code": code, "label": code, "p": p, "p0": p,
            "odds": round(1 / p, 2), "lh": 1.5, "la": 1.1, "rho": -0.05}


SLIPS = [{"id": 101, "name": "Serie A Sunday", "stake": 5, "pays": 12.5, "odds": 12.5, "at": iso(NOW - timedelta(days=1)), "legs": [
            leg("m1", "Inter", "Juventus", "110", "111", K_LIVE, "1X", 0.75), leg("m2", "Roma", "Lazio", "104", "112", K_DONE, "O15", 0.72),
            leg("m3", "Napoli", "Milan", "114", "103", K_SOON, "1", 0.45)]},
         {"id": 102, "name": "Two legs", "stake": 2, "pays": 3.1, "odds": 3.1, "at": iso(NOW - timedelta(days=1)), "legs": [
            leg("m1", "Inter", "Juventus", "110", "111", K_LIVE, "GG", 0.55), leg("m4", "Atalanta", "Torino", "105", "239", K_LOST, "1", 0.6)]},
         {"id": 103, "name": "Settled long ago", "stake": 1, "pays": 2, "settled": True, "settledAt": iso(NOW - timedelta(days=3)), "legs": [
            leg("m9", "A", "B", "1", "2", NOW - timedelta(days=3), "1", 0.5)]}]


class H(F.H):
    def do_GET(self):
        u = urllib.parse.urlsplit(self.path)
        q = urllib.parse.parse_qs(u.query)
        parts = u.path.strip("/").split("/")
        if parts[0] == "espn" and len(parts) == 3:
            if parts[2] == "scoreboard":
                key = (parts[1], (q.get("dates") or [""])[0])
                W["espn_reads"].append(key)
                return self.send(200, {"events": W["boards"].get(key, [])})
            if parts[2] == "summary":
                ev = (q.get("event") or [""])[0]
                W["summary_reads"].append(ev)
                return self.send(200, W["summaries"].get(ev, {"rosters": []}))
        if u.path == "/site/data/teams.json":
            W["teams_reads"] += 1
            return self.send(200, W["teams"])
        if u.path == "/push-log":   # --serve: what each device received, decrypted (for the site's browser test)
            return self.send(200, pushes(int((q.get("since") or ["0"])[0])))
        if u.path == "/devices":
            return self.send(200, {k: v.sub() for k, v in DEVICES.items()})
        return super().do_GET()

    def do_POST(self):
        u = urllib.parse.urlsplit(self.path)
        if u.path.startswith("/push/"):
            dev = u.path.split("/")[2]
            n = int(self.headers.get("Content-Length") or 0)
            W["push"].append({"dev": dev, "headers": {k.lower(): v for k, v in self.headers.items()}, "body": self.rfile.read(n)})
            return self.send(W["push_status"].get(dev, 201), None)
        if u.path == "/functions/v1/scudi-notify":
            n = int(self.headers.get("Content-Length") or 0)
            data = self.rfile.read(n) if n else b"{}"
            fwd = {k: v for k, v in self.headers.items() if k.lower() in ("authorization", "apikey", "content-type", "x-cron-token")}
            req = urllib.request.Request("http://127.0.0.1:8000/", data=data, headers=fwd, method="POST")
            try:
                with urllib.request.urlopen(req, timeout=60) as r:
                    return self.send(r.status, r.read())
            except urllib.error.HTTPError as e:
                return self.send(e.code, e.read())
        return super().do_POST()


def start_function() -> subprocess.Popen:
    env = dict(os.environ, SUPABASE_URL=f"http://127.0.0.1:{F.PORT}", SUPABASE_SECRET_KEYS=json.dumps({"default": F.SECRET}),
               SCUDI_SITE_URL=f"http://127.0.0.1:{F.PORT}/site/", ESPN_BASE_URL=f"http://127.0.0.1:{F.PORT}/espn", NO_COLOR="1")
    fn = os.environ.get("SCUDI_FN") or str(ROOT / "supabase/functions/scudi-notify/index.ts")
    p = subprocess.Popen(["deno", "run", "--allow-net", "--allow-env", fn], env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    for _ in range(150):
        try:
            urllib.request.urlopen(urllib.request.Request("http://127.0.0.1:8000/", method="OPTIONS"), timeout=1)
            return p
        except Exception:
            time.sleep(0.2)
    raise RuntimeError("the function did not start: " + (p.stdout.read(3000).decode() if p.stdout else ""))


def call(body: dict | None = None, headers: dict | None = None) -> tuple[int, dict]:
    req = urllib.request.Request(f"http://127.0.0.1:{F.PORT}/functions/v1/scudi-notify", data=json.dumps(body or {}).encode(),
                                 headers=dict({"Content-Type": "application/json"}, **(headers or {})), method="POST")
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return r.status, json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"{}")


def as_user(uid: str) -> dict:
    return {"apikey": F.PUBLISHABLE, "Authorization": f"Bearer tok-{uid}"}


def site_rpc(uid: str, fn: str, body: dict):
    req = urllib.request.Request(f"http://127.0.0.1:{F.PORT}/rest/v1/rpc/{fn}", data=json.dumps(body).encode(), headers=dict({"Content-Type": "application/json"}, **as_user(uid)), method="POST")
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return r.status, json.loads(r.read() or b"null")
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"null")


def put_state(key: str, value) -> None:
    rows = F.sql("select updated_at from public.user_state where key = %s", key)
    base = rows[0][0].isoformat() if rows else None
    code, r = site_rpc(OWNER, "state_put", {"items": [{"key": key, "value": value, "base": base, "device": "test"}]})
    assert code == 200 and r[0]["ok"], (code, r)


def pushes(since: int) -> list[dict]:
    out = []
    for p in W["push"][since:]:
        dev = DEVICES[p["dev"]]
        out.append(dict(dev=p["dev"], headers=p["headers"], **dev.read(p["body"])))
    return out


check = F.check


def checks() -> None:
    token = F.sql("select cron_token from private.feed_config")[0][0]
    cron = {"x-cron-token": token}
    code, r = call({}, {"x-cron-token": "nope" * 10})
    check(code == 401, f"a wrong cron token is refused ({code})")
    code, r = call({"action": "key"})
    check(code == 401, f"no sign-in: refused ({code})")
    code, r = call({"action": "key"}, as_user(OTHER))
    check(code == 401, f"another account: refused ({code})")
    code, r = call({}, cron)
    check(code == 200 and r.get("why") == "no-device", f"a wake with no device does nothing: {r}")
    check(not W["espn_reads"], "… and reads nothing from ESPN")

    # the owner's device subscribes: the public key first (made on the first call, the same after)
    code, k1 = call({"action": "key"}, as_user(OWNER))
    _, k2 = call({"action": "key"}, as_user(OWNER))
    check(code == 200 and k1.get("key") and k1["key"] == k2.get("key") and len(unb64u(k1["key"])) == 65, f"the public key, stable: {k1.get('key', '')[:12]}…")
    check(F.sql("select count(*) from private.push_keys")[0][0] == 1, "one key pair stored")
    code, r = site_rpc(OWNER, "push_add", {"sub": DEVICES["phone"].sub()})
    check(code == 200 and r.get("devices") == 1, f"the phone registered: {r}")
    code, r = site_rpc(OTHER, "push_add", {"sub": DEVICES["ipad"].sub()})
    check(code == 403, f"another account cannot register a device ({code})")

    # a test message reaches the phone, signed with the stored key
    n0 = len(W["push"])
    code, r = call({"action": "test"}, as_user(OWNER))
    got = pushes(n0)
    check(code == 200 and r.get("delivered") == 1 and len(got) == 1 and got[0]["title"] == "Scudi", f"the test message, decrypted on the phone: {[(g['title'], g['body']) for g in got]}")
    auth = got[0]["headers"].get("authorization", "")
    tok, _, kpart = auth[len("vapid t="):].partition(", k=")
    h64, c64, s64 = tok.split(".")
    pub = ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), unb64u(kpart))
    sig = unb64u(s64)
    try:
        pub.verify(encode_dss_signature(int.from_bytes(sig[:32], "big"), int.from_bytes(sig[32:], "big")), f"{h64}.{c64}".encode(), ec.ECDSA(hashes.SHA256()))
        ok_sig = True
    except Exception:
        ok_sig = False
    claims = json.loads(unb64u(c64))
    check(ok_sig and kpart == k1["key"] and claims["aud"] == f"http://127.0.0.1:{F.PORT}" and claims["sub"].startswith("https://"), f"VAPID: signature verified, aud {claims['aud']}")
    check(got[0]["headers"].get("content-encoding") == "aes128gcm" and got[0]["headers"].get("urgency") == "high", "aes128gcm, urgent")

    # the slips arrive from the site (synced), and the cron wakes
    put_state("scudi-placed", SLIPS)
    world()
    n0 = len(W["push"])
    code, r = call({}, cron)
    got = pushes(n0)
    titles = sorted(g["title"] for g in got)
    check(code == 200 and r.get("slips") == 2 and r.get("boards") == 1, f"two slips on, one scoreboard read: {r}")
    check(any(t.startswith("Goal 67' · Internazionale 1–0 Juventus") for t in titles), f"the goal: {titles}")
    check(any(t == "Full time · AS Roma 2–1 Lazio" for t in titles) and any(t == "Full time · Atalanta 0–1 Torino" for t in titles), "both final whistles")
    lu = [g for g in got if g["title"].startswith("Line-ups · Napoli – Milan")]
    check(len(lu) == 1 and "Not starting from the last XI: K. Kvaratskhelia." in lu[0]["body"] and "Napoli: Meret, Di Lorenzo" in lu[0]["body"], f"the line-ups, with who is out: {lu[:1]}")
    check(lu and lu[0]["url"].endswith("#matches") and W["summary_reads"] == ["404"] and W["teams_reads"] == 1, "read once: ESPN's match page and the team data")
    goal_msg = next((g for g in got if g["title"].startswith("Goal")), {})
    check("Lautaro Martínez" in goal_msg.get("body", "") and "“Two legs” is out." in goal_msg.get("body", "") and goal_msg.get("url", "").endswith("#live"), f"the goal's body: {goal_msg.get('body')!r}")
    check(len(got) == 4 and not any(g["title"].startswith("One leg left") for g in got), f"four messages, no hedge yet ({len(got)})")
    sent = F.sql("select count(*) from public.notify_sent where user_id = %s", OWNER)[0][0]
    check(sent == 4, f"what was sent is recorded (not the test): {sent}")
    memo = F.sql("select memo from private.notify_memo")[0][0]
    check(sorted(memo) == ["101:1", "102:1"] and memo["101:1"]["h"] == 2, f"the final scores remembered: {sorted(memo)}")

    # the next wake: nothing new, nothing twice, ESPN's match page not read again
    n0, reads = len(W["push"]), len(W["summary_reads"])
    code, r = call({}, cron)
    check(code == 200 and len(W["push"]) == n0 and r.get("sent") == 0, f"a second wake sends nothing again: {r}")
    check(len(W["summary_reads"]) == reads, "the line-ups are not read again")

    # Inter 2-0, in Italian; the phone has gone (410) and is removed; the iPad still gets it
    code, r = site_rpc(OWNER, "push_add", {"sub": DEVICES["ipad"].sub()})
    check(code == 200 and r.get("devices") == 2, "a second device")
    put_state("scudi-notify", {"on": True, "lang": "it", "lineups": True, "goals": True, "cards": True, "results": True, "hedge": True})
    W["push_status"]["phone"] = 410
    world(score_live=(2, 0))
    n0 = len(W["push"])
    code, r = call({}, cron)
    got = pushes(n0)
    ipad = [g for g in got if g["dev"] == "ipad"]
    check(len(ipad) == 1 and ipad[0]["title"].startswith("Gol 80' · Internazionale 2–0 Juventus") and "in vantaggio" in ipad[0]["body"], f"the second goal, in Italian: {[g['title'] for g in got]}")
    check(F.sql("select count(*) from public.push_subs")[0][0] == 1 and F.sql("select count(*) from public.push_subs where endpoint like '%%/phone'")[0][0] == 0, "the phone the push service no longer knows is removed")

    # Inter-Juventus ends 1-1: slip A has one leg left (Napoli-Milan, not started) → the hedge, from SNAI's price in the store
    F.sql("""insert into public.book_events (event_id, home, away, league, commence_time, m, match_id)
             values ('ev-m3', 'Napoli', 'Milan', 'Serie A', %s, '[[3,0,1,2.05],[3,0,2,3.4],[3,0,3,3.9],[28319,0,3,1.62]]', 'm3')""", K_SOON)
    put_state("scudi-notify", {"on": True, "lang": "en"})
    world(score_live=(1, 1), final=True)
    n0 = len(W["push"])
    code, r = call({}, cron)
    got = pushes(n0)
    hg = [g for g in got if g["title"] == "One leg left · “Serie A Sunday”"]
    P, H = 5 * 12.5, 5 * 12.5 / 1.62
    check(len(hg) == 1 and f"Cover it: €{H:.2f} on X2 at SNAI's 1.62 → €62.50 whatever happens (€{P - 5 - H:.2f} profit locked)" in hg[0]["body"], f"one leg left, with the hedge: {[g['body'] for g in hg]}")
    check(any(g["title"] == "Full time · Internazionale 1–1 Juventus" for g in got), "and the final whistle")

    # switched off: nothing read, nothing sent
    put_state("scudi-notify", {"on": False})
    n0, e0 = len(W["push"]), len(W["espn_reads"])
    code, r = call({}, cron)
    check(code == 200 and r.get("why") == "off" and len(W["push"]) == n0 and len(W["espn_reads"]) == e0, f"switched off: {r}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pg", required=True, help="Postgres socket directory (port 55432)")
    ap.add_argument("--serve", action="store_true", help="no checks: the stand-ins and the function keep running (the site's browser test)")
    a = ap.parse_args()
    F.fresh_db(a.pg)
    # the stand-in push service is plain http on this machine: let the test's endpoints in (the real table wants https)
    F.sql("alter table public.push_subs drop constraint push_subs_endpoint_check")
    F.sql("alter table public.push_subs add constraint push_subs_endpoint_check check (endpoint ~ '^(https://|http://127\\.0\\.0\\.1:)')")
    srv = ThreadingHTTPServer(("127.0.0.1", F.PORT), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    fn = start_function()
    try:
        if a.serve:
            world()
            print("serving on 127.0.0.1:54321 (function on 8000) — Ctrl+C to stop", flush=True)
            while True:
                time.sleep(3600)
        checks()
    finally:
        fn.terminate()
        srv.shutdown()
        try:
            out = fn.stdout.read().decode(errors="replace") if fn.stdout else ""
            if out.strip():
                print("--- function output ---\n" + out[-3000:])
        except Exception:
            pass
    bad = [m for ok, m in F.RESULTS if not ok]
    print(f"\n{len(F.RESULTS) - len(bad)}/{len(F.RESULTS)} passed")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
