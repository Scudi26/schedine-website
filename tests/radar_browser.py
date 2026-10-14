"""Click-through checks of the Radar screen (decision 99) in Chromium, against the local stand-in:

    python3 tests/radar_local.py --pg /var/lib/postgresql/scudi --days 28 &    # the store, on :54321
    python3 -m http.server 8765 --bind 127.0.0.1 &                              # the site, from the repository root
    python3 tests/radar_browser.py

The call is made only on the Radar, chips redraw without a new call, a new window or filter asks again (and replaces a
reading still running), the explanations open, Italian redraws, every screen still opens, and the store's errors (no
function yet, an expired sign-in, no answer, a statement timeout → 14 days) are each said plainly. Not part of the
default test run (needs Playwright's Chromium).
"""

from __future__ import annotations

import json
import sys

from playwright.sync_api import sync_playwright

SITE = "http://127.0.0.1:8765/index.html"
UID = "11111111-1111-1111-1111-111111111111"
SESSION = ("localStorage.setItem('scudi-feed-session', JSON.stringify({ access_token: 'tok-" + UID + "', refresh_token: 'ref-" + UID
           + "', expires_at: Date.now() + 3600e3, email: 'gianluca@example.com' }));")
INIT = ("window.SCUDI_FEED_CONF = { url: 'http://127.0.0.1:54321', key: 'sb_publishable_localtest' }; "
        "try { " + SESSION + " localStorage.setItem('scudi-lang', 'en'); } catch (e) {}")
RESULTS: list[tuple[bool, str]] = []


def ok(cond, msg: str) -> None:
    RESULTS.append((bool(cond), msg))
    print(("PASS " if cond else "FAIL ") + msg, flush=True)


def quiet(ctx) -> None:
    """no fonts, crests or ESPN from the sandbox: the Radar needs none of them"""
    for pat in ("**/fonts.googleapis.com/**", "**/fonts.gstatic.com/**", "**/a.espncdn.com/**", "**/site.web.api.espn.com/**", "**/site.api.espn.com/**"):
        ctx.route(pat, lambda r: r.abort())


def idle(pg) -> None:
    pg.wait_for_timeout(300)
    pg.wait_for_selector(".rd-head:not(.busy)", timeout=20000)


def main_flow(br) -> None:
    ctx = br.new_context(viewport={"width": 1360, "height": 900})
    ctx.add_init_script(INIT)
    quiet(ctx)
    calls: list[dict] = []
    ctx.on("request", lambda r: calls.append(json.loads(r.post_data or "{}")) if "/rpc/radar_page" in r.url else None)
    pg = ctx.new_page()
    errs: list[str] = []
    pg.on("pageerror", lambda e: errs.append(str(e)) if "espn" not in str(e) else None)
    pg.goto(SITE + "#today")
    pg.wait_for_timeout(2500)
    ok(len(calls) == 0, "the page call is not made until the Radar is opened")
    pg.click(".tabs a[data-view=radar]")
    pg.wait_for_selector(".rd-body", timeout=15000)
    ok(len(calls) == 1 and calls[0] == {"days": 28, "confirmed_only": True}, f"opening the Radar asks for 28 days, confirmed closes: {calls}")
    big0 = pg.text_content(".rd-big b")
    pg.click("[data-rd-h='24']")
    pg.wait_for_timeout(300)
    ok(pg.get_attribute("[data-rd-h='24']", "aria-pressed") == "true" and "24h before" in pg.text_content(".rd-cost .eyebrow") and len(calls) == 1,
       "a checkpoint chip redraws without a new call")
    ok(pg.text_content(".rd-big b") != big0, f"… and the headline changes: {big0} → {pg.text_content('.rd-big b')}")
    pg.click("[data-rd-h='0']")
    n4 = pg.locator(".rd-mh").count()
    pg.click("[data-rd-more]")
    pg.wait_for_timeout(200)
    ok(n4 == 4 and pg.locator(".rd-mh").count() == 6, "the 1.5 and 3.5 lines add two columns")
    pg.click("[data-rd-more]")
    pg.click(".rd-cell[data-rd-cell^='Serie A|1']")
    pg.wait_for_timeout(300)
    ok(pg.locator(".rd-detail").count() == 1 and "Serie A" in pg.text_content(".rd-detail h3") and pg.locator(".rd-detail .rd-line .pt").count() == 7,
       "a map cell opens its detail with seven checkpoints")
    pg.click("[data-rd-close]")
    pg.wait_for_timeout(200)
    ok(pg.locator(".rd-detail").count() == 0, "… and closes")
    pg.locator(".rd-blip .dot").first.click(force=True)   # the halo pulses: the dot is the stable target
    pg.wait_for_timeout(500)
    ok(pg.locator(".rd-detail").count() == 1, "a blip on the scope opens the same detail")
    pg.click(".rd-tile[data-rd-band='4']")
    pg.wait_for_timeout(400)
    ok(pg.get_attribute(".rd-bands [data-rd-band='4']", "aria-pressed") == "true" and "GG" in pg.text_content(".rd-bands"),
       "a market tile switches the bands panel to that market")
    pg.click("[data-rd-days='60']")
    idle(pg)
    ok(calls[-1] == {"days": 60, "confirmed_only": True} and pg.get_attribute("[data-rd-days='60']", "aria-pressed") == "true", "the 60-day window asks again")
    pg.click("[data-rd-conf]")
    idle(pg)
    ok(calls[-1] == {"days": 60, "confirmed_only": False} and "left out" not in pg.text_content(".rd-foot"), "the unconfirmed closes come in when asked, nothing left out")
    pg.click("[data-rd-conf]")
    idle(pg)
    ok("left out" in pg.text_content(".rd-foot"), "with confirmed closes only the left-out matches are counted")
    pg.click("[data-explain=rdMap]")
    pg.wait_for_timeout(500)
    ok(pg.is_visible("#explain") and "margin map" in pg.text_content("#xTitle").lower(), "the i opens its explanation")
    pg.keyboard.press("Escape")
    pg.wait_for_timeout(400)
    for k in ("rdGate", "rdCost", "rdTiming", "rdBands", "rdPockets", "rdCalib"):
        pg.click(f"[data-explain={k}]")
        pg.wait_for_timeout(350)
        t = pg.text_content("#explain .xbody") or ""
        ok(len(t) > 150, f"explanation {k} has its text ({len(t)} chars)")
        pg.keyboard.press("Escape")
        pg.wait_for_timeout(300)
    pg.click(".lang [data-lang=it]")
    pg.wait_for_timeout(700)
    ok("Quanto costa SNAI" in pg.text_content(".rd-cost") and "La mappa del margine" in pg.text_content(".rd-map"), "switching to Italian redraws the Radar in Italian")
    pg.click(".lang [data-lang=en]")
    pg.wait_for_timeout(500)
    for v in ("today", "slips", "matches", "live", "record", "lab", "radar"):
        pg.click(f".tabs a[data-view={v}]")
        pg.wait_for_timeout(1300)
        ok(pg.evaluate("document.body.dataset.screen") == v and not pg.is_hidden("#v-" + v), f"screen {v} opens")
    ok(len(calls) == 4, f"coming back within ten minutes reuses the reading ({len(calls)} calls)")
    pg.click("[data-rd-refresh]")
    idle(pg)
    ok(len(calls) == 5, "Refresh asks again")
    ok(not errs, f"no page errors: {errs[:3]}")
    ctx.close()


def error_flows(br) -> None:
    def answer(code: int, body: dict):
        return lambda r: r.fulfill(status=code, content_type="application/json", body=json.dumps(body))
    cases = [(404, {"code": "PGRST202", "message": "Could not find the function public.radar_page(confirmed_only, days) in the schema cache"}, "20261013180000_radar_page.sql"),
             (401, {"message": "JWT expired"}, "Sign in again"),
             (502, {"message": "bad gateway"}, "did not answer")]
    for code, body, want in cases:
        ctx = br.new_context(viewport={"width": 390, "height": 844})
        ctx.add_init_script(INIT)
        quiet(ctx)
        ctx.route("**/rpc/radar_page", answer(code, body))
        pg = ctx.new_page()
        pg.goto(SITE + "#radar")
        pg.wait_for_selector(".rd-lock:not(.rd-loading)", timeout=15000)
        ok(want in pg.text_content(".rd-lock"), f"store answering {code} → {want!r} shown")
        ctx.close()
    # a statement timeout on 28 days is asked again on 14
    ctx = br.new_context(viewport={"width": 390, "height": 844})
    ctx.add_init_script(INIT)
    quiet(ctx)
    seen: list[dict] = []

    def slow(r):
        b = json.loads(r.request.post_data or "{}")
        seen.append(b)
        if b.get("days") == 28:
            r.fulfill(status=500, content_type="application/json", body=json.dumps({"code": "57014", "message": "canceling statement due to statement timeout"}))
        else:
            r.continue_()
    ctx.route("**/rpc/radar_page", slow)
    pg = ctx.new_page()
    pg.goto(SITE + "#radar")
    pg.wait_for_selector(".rd-body", timeout=15000)
    ok([x.get("days") for x in seen] == [28, 14] and "14 days shown" in pg.text_content(".rd-foot") and pg.get_attribute("[data-rd-days='14']", "aria-pressed") == "true",
       f"a timeout on 28 days is retried on 14 and said so: {seen}")
    ctx.close()


def race_flows(br) -> None:
    """a slow reading that times out after a newer one was asked for changes nothing; a failed reading keeps the last one, says so"""
    ctx = br.new_context(viewport={"width": 1360, "height": 900})
    ctx.add_init_script(INIT)
    quiet(ctx)

    def slow60(r):
        b = json.loads(r.request.post_data or "{}")
        if b.get("days") == 60:
            import time
            time.sleep(1.5)
            r.fulfill(status=500, content_type="application/json", body=json.dumps({"code": "57014", "message": "canceling statement due to statement timeout"}))
        else:
            r.continue_()
    ctx.route("**/rpc/radar_page", slow60)
    pg = ctx.new_page()
    pg.goto(SITE + "#radar")
    pg.wait_for_selector(".rd-body", timeout=15000)
    pg.click("[data-rd-days='60']")
    pg.wait_for_timeout(100)
    pg.click("[data-rd-days='28']")
    pg.wait_for_timeout(3500)
    ok(pg.get_attribute("[data-rd-days='28']", "aria-pressed") == "true" and "14 days shown" not in pg.text_content(".rd-foot") and pg.locator(".rd-warn").count() == 0,
       "60 days asked, then 28: the late timeout of the first changes nothing")
    ctx.close()
    ctx = br.new_context(viewport={"width": 390, "height": 844})
    ctx.add_init_script(INIT)
    quiet(ctx)
    ctx.route("**/rpc/radar_page", lambda r: r.fulfill(status=502, content_type="application/json", body="{}") if json.loads(r.request.post_data or "{}").get("days") == 60 else r.continue_())
    pg = ctx.new_page()
    pg.goto(SITE + "#radar")
    pg.wait_for_selector(".rd-body", timeout=15000)
    big = pg.text_content(".rd-big b")
    pg.click("[data-rd-days='60']")
    pg.wait_for_selector(".rd-warn", timeout=10000)
    ok(pg.get_attribute("[data-rd-days='28']", "aria-pressed") == "true" and pg.text_content(".rd-big b") == big and "28 days" in pg.text_content(".rd-warn"),
       "a failed 60-day reading: the 28-day one stays, its chip pressed, and the page says so")
    ctx.close()


def main() -> int:
    with sync_playwright() as p:
        br = p.chromium.launch()
        main_flow(br)
        error_flows(br)
        race_flows(br)
        br.close()
    bad = [m for c, m in RESULTS if not c]
    print(f"\n{len(RESULTS) - len(bad)}/{len(RESULTS)} passed")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
