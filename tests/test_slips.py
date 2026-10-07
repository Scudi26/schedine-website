import itertools
import math
import random

import pytest

from scudi_slips import PICKS, SLIP_MENU, Pick, fit_market, menu, power_devig, score_matrix, settles, snai_bonus, solve
from scudi_slips.matrix import safe_rho


# ---------- devig ----------
def test_devig_sums_to_one_and_takes_more_from_longshots():
    prices = [1.50, 4.20, 7.00]
    fair = power_devig(prices)
    assert sum(fair) == pytest.approx(1.0, abs=1e-9)
    cut = [1 / p - f for p, f in zip(prices, fair)]
    assert all(c > 0 for c in cut)
    # relative margin removed grows with the price
    rel = [c / (1 / p) for c, p in zip(cut, prices)]
    assert rel[0] < rel[1] < rel[2]


def test_devig_without_margin_is_plain_normalisation():
    assert power_devig([2.0, 2.0]) == pytest.approx([0.5, 0.5])


@pytest.mark.parametrize("bad", [[1.0, 2.0], [0.5, 3.0], [float("nan"), 2.0], [2.0]])
def test_devig_rejects_bad_prices(bad):
    with pytest.raises(ValueError):
        power_devig(bad)


# ---------- score matrix ----------
def test_matrix_is_a_distribution_and_matches_the_website_numbers():
    m = score_matrix(1.62, 0.92, -0.06)
    assert m.sum() == pytest.approx(1.0)
    assert (m >= 0).all()
    home = sum(m[h, a] for h in range(10) for a in range(10) if h > a)
    draw = sum(m[h, a] for h in range(10) for a in range(10) if h == a)
    assert round(home, 2) == 0.53 and round(draw, 2) == 0.26  # as shown in mockup v1


def test_matrix_mirror_symmetry():
    a, b = score_matrix(1.4, 0.9, -0.05), score_matrix(0.9, 1.4, -0.05)
    assert a == pytest.approx(b.T)


def test_safe_rho_keeps_lopsided_matches_valid():
    m = score_matrix(3.4, 0.3, -0.5)   # 1 + 3.4 * -0.5 would be negative without clipping
    assert (m >= 0).all()
    assert safe_rho(3.4, 0.3, -0.5) == pytest.approx(-0.999 / 3.4)
    assert safe_rho(2.0, 2.0, 0.9) == pytest.approx(0.999 / 4)
    assert safe_rho(1.5, 1.1, -0.06) == -0.06


@pytest.mark.parametrize("probs", [(0.55, 0.25, 0.20, 0.52), (0.30, 0.29, 0.41, 0.44), (0.78, 0.15, 0.07, 0.66), (0.20, 0.24, 0.56, 0.58)])
def test_fit_reproduces_the_market(probs):
    view = fit_market(*probs)
    assert view.fit_error < 0.004
    assert 0 < view.p_over15 < 1 and view.p_over15 > view.p_over25
    assert view.p_under35 > 1 - view.p_over25
    assert 0 < view.p_btts < view.p_over15


def test_fit_rejects_nonsense():
    with pytest.raises(ValueError):
        fit_market(0.5, 0.3, 0.3, 0.5)


# ---------- picks ----------
def test_every_pick_settles_correctly_on_every_scoreline():
    for h, a in itertools.product(range(6), repeat=2):
        assert settles("1", h, a) == (h > a)
        assert settles("1X", h, a) == (not settles("2", h, a))
        assert settles("X2", h, a) == (not settles("1", h, a))
        assert settles("12", h, a) == (not settles("X", h, a))
        assert settles("O25", h, a) == (not settles("U25", h, a))
        assert settles("GG", h, a) == (not settles("NG", h, a))
        assert settles("O15", h, a) == (h + a >= 2)
        assert settles("U35", h, a) == (h + a <= 3)


def test_complementary_chances_add_up():
    v = fit_market(0.48, 0.27, 0.25, 0.49)
    c = {code: t.chance(v) for code, t in PICKS.items()}
    assert c["1X"] + c["2"] == pytest.approx(1)
    assert c["O25"] + c["U25"] == pytest.approx(1)
    assert c["GG"] + c["NG"] == pytest.approx(1)   # the shift moves both by the same amount


def test_menu_applies_floor_and_allowed_list():
    v = fit_market(0.70, 0.18, 0.12, 0.60)
    offered = {"1": 1.36, "1X": 1.08, "O15": 1.18, "O25": 1.57, "X": 5.0}
    got = {p.code for p in menu("m1", v, offered, min_odds=1.25)}
    assert got == {"1", "O25", "X"}
    assert {p.code for p in menu("m1", v, offered, allowed={"1", "1X"})} == {"1"}
    with pytest.raises(KeyError):
        menu("m1", v, {"ZZ": 2.0})


def test_both_teams_score_offered_with_shift_but_not_its_opposite():
    v = fit_market(0.45, 0.27, 0.28, 0.52)
    offered = {"GG": 1.80, "NG": 1.95, "1": 2.10}
    got = {p.code: p for p in menu("m1", v, offered)}
    assert set(got) == {"GG", "1"}
    assert got["GG"].chance == pytest.approx(v.p_btts + 0.015)
    assert {p.code for p in menu("m1", v, offered, allowed=set(PICKS))} == {"GG", "NG", "1"}
    assert "NG" not in SLIP_MENU and "O15" in SLIP_MENU and "GG" in SLIP_MENU


# ---------- SNAI bonus ----------
def test_snai_bonus_table():
    assert snai_bonus([1.3] * 4) == 0
    assert snai_bonus([1.3] * 5) == pytest.approx(0.0350, abs=1e-4)
    assert snai_bonus([1.3] * 9) == pytest.approx(0.1877, abs=1e-4)
    assert snai_bonus([1.3] * 10) == pytest.approx(0.2293, abs=1e-4)
    assert snai_bonus([1.3] * 20) == pytest.approx(0.7340, abs=1e-4)
    assert snai_bonus([1.3] * 30) == pytest.approx(1.4460, abs=2e-4)
    assert snai_bonus([1.3] * 40) == snai_bonus([1.3] * 30)


def test_snai_bonus_ignores_legs_under_the_floor():
    assert snai_bonus([1.3] * 9 + [1.24]) == pytest.approx(0.1877, abs=1e-4)
    assert snai_bonus([1.25] * 10) == pytest.approx(0.2293, abs=1e-4)


# ---------- solver ----------
def _random_menus(rng, n):
    menus = []
    for i in range(n):
        opts = []
        for j in range(rng.randint(3, 6)):
            chance = rng.uniform(0.25, 0.8)
            odds = round(max(1.25, (1 / chance) * rng.uniform(0.92, 0.97)), 2)
            opts.append(Pick(f"m{i}", f"p{j}", chance, odds))
        menus.append(opts)
    return menus


def _brute(menus, target, legs):
    best = None
    n = len(menus)
    for used in itertools.combinations(range(n), legs):
        for combo in itertools.product(*[menus[i] for i in used]):
            odds = math.prod(p.odds for p in combo)
            if odds >= target:
                chance = math.prod(p.chance for p in combo)
                if best is None or chance > best:
                    best = chance
    return best


@pytest.mark.parametrize("seed", range(12))
def test_solver_matches_brute_force_and_always_reaches_target(seed):
    rng = random.Random(seed)
    n = rng.randint(4, 6)
    legs = n if seed % 2 == 0 else n - 2
    menus = _random_menus(rng, n)
    target = rng.uniform(4, 14)
    best = _brute(menus, target, legs)
    slip = solve(menus, target, legs=legs, grid=0.0001)
    if best is None:
        assert slip is None
        return
    assert slip is not None
    assert slip.odds >= target
    assert len(slip.picks) == legs
    assert len({p.match_id for p in slip.picks}) == legs
    assert slip.chance <= best * (1 + 1e-12)
    assert slip.chance >= best * 0.99


def test_solver_returns_none_when_target_is_out_of_reach():
    menus = [[Pick("a", "1", 0.7, 1.3)], [Pick("b", "1", 0.7, 1.3)]]
    assert solve(menus, 5.0) is None


def test_solver_forces_locked_matches_into_a_partial_slip():
    menus = [[Pick("a", "1", 0.80, 1.20)], [Pick("b", "1", 0.30, 3.00)], [Pick("c", "1", 0.75, 1.30)], [Pick("d", "1", 0.74, 1.31)]]
    free = solve(menus, 1.5, legs=2)
    assert {p.match_id for p in free.picks} == {"a", "c"}  # the two likeliest that still reach 1.5
    locked = solve(menus, 1.5, legs=2, must_use=[False, True, False, False])
    assert "b" in {p.match_id for p in locked.picks}


def test_solver_rejects_bad_input():
    good = [[Pick("a", "1", 0.5, 1.9)]]
    with pytest.raises(ValueError):
        solve(good, 0.9)
    with pytest.raises(ValueError):
        solve(good, 2, legs=3)
    with pytest.raises(ValueError):
        solve([[Pick("a", "1", 1.2, 1.9)]], 1.5)


# ---------- solver with league rules ----------
def _brute_rules(menus, target, legs, groups, limits, default_max, forced):
    best = None
    n = len(menus)
    for used in itertools.combinations(range(n), legs):
        if any(f and i not in used for i, f in enumerate(forced)):
            continue
        counts = {}
        for i in used:
            counts[groups[i]] = counts.get(groups[i], 0) + 1
        ok = True
        for g in set(groups):
            lo, hi = limits.get(g, (0, default_max))
            c = counts.get(g, 0)
            if c < lo or (hi is not None and c > hi):
                ok = False
        if not ok:
            continue
        for combo in itertools.product(*[menus[i] for i in used]):
            if math.prod(p.odds for p in combo) >= target:
                chance = math.prod(p.chance for p in combo)
                if best is None or chance > best:
                    best = chance
    return best


@pytest.mark.parametrize("seed", range(16))
def test_solver_with_league_rules_matches_brute_force(seed):
    rng = random.Random(100 + seed)
    n = rng.randint(6, 8)
    legs = rng.randint(3, 5)
    menus = _random_menus(rng, n)
    groups = [rng.choice(["ita", "eng", "esp"]) for _ in range(n)]
    limits = {}
    if seed % 3 != 2:
        limits["ita"] = (rng.randint(0, 2), rng.choice([None, 2, 3]))
    default_max = rng.choice([None, 2, 3]) if seed % 2 else None
    forced = [False] * n
    if seed % 4 == 0:
        forced[rng.randrange(n)] = True
    target = rng.uniform(4, 12)
    best = _brute_rules(menus, target, legs, groups, limits, default_max, forced)
    slip = solve(menus, target, legs=legs, groups=groups, group_limits=limits, default_group_max=default_max, must_use=forced, grid=0.0001)
    if best is None:
        assert slip is None
        return
    assert slip is not None and slip.odds >= target and len(slip.picks) == legs
    used = {p.match_id for p in slip.picks}
    assert len(used) == legs
    for i, f in enumerate(forced):
        assert (not f) or f"m{i}" in used
    counts = {}
    for p in slip.picks:
        g = groups[int(p.match_id[1:])]
        counts[g] = counts.get(g, 0) + 1
    for g in set(groups):
        lo, hi = limits.get(g, (0, default_max))
        assert counts.get(g, 0) >= lo
        assert hi is None or counts.get(g, 0) <= hi
    assert slip.chance <= best * (1 + 1e-12)
    assert slip.chance >= best * 0.995


def test_league_minimum_changes_the_slip():
    # the two safest matches are English; asking for two Italian legs must push them out
    menus = [[Pick("m0", "1", 0.80, 1.22)], [Pick("m1", "1", 0.78, 1.25)], [Pick("m2", "1", 0.60, 1.60)], [Pick("m3", "1", 0.58, 1.65)]]
    groups = ["eng", "eng", "ita", "ita"]
    free = solve(menus, 1.4, legs=2, groups=groups)
    assert {p.match_id for p in free.picks} == {"m0", "m1"}
    ruled = solve(menus, 1.4, legs=2, groups=groups, group_limits={"ita": (2, None)})
    assert {p.match_id for p in ruled.picks} == {"m2", "m3"}
    assert solve(menus, 1.4, legs=2, groups=groups, group_limits={"ita": (3, None)}) is None
    capped = solve(menus, 1.4, legs=2, groups=groups, default_group_max=1)
    assert sorted(groups[int(p.match_id[1:])] for p in capped.picks) == ["eng", "ita"]


def test_empty_menu_means_the_match_is_left_out():
    menus = [[Pick("m0", "1", 0.7, 1.4)], [], [Pick("m2", "1", 0.6, 1.6)]]
    slip = solve(menus, 2.0, legs=2)
    assert {p.match_id for p in slip.picks} == {"m0", "m2"}
    assert solve(menus, 2.0, legs=2, must_use=[False, True, False]) is None


def test_refine_pass_never_returns_a_slip_under_the_target():
    rng = random.Random(5)
    for _ in range(40):
        menus = _random_menus(rng, 6)
        target = rng.uniform(5, 30)
        for refine in (False, True):
            slip = solve(menus, target, grid=0.004, refine=refine)   # a coarse grid makes rounding errors large
            assert slip is None or slip.odds >= target
        safe, both = solve(menus, target, grid=0.004, refine=False), solve(menus, target, grid=0.004)
        if safe is not None:
            assert both is not None and both.chance >= safe.chance


# ---------- consensus ----------
from datetime import datetime, timedelta  # noqa: E402

from scudi_slips.consensus import BookMarket, best_price, consensus  # noqa: E402


def test_consensus_weights_sharp_books_more():
    soft = BookMarket("bet365", [1.80, 3.60, 4.50])
    sharp = BookMarket("pinnacle", [2.00, 3.50, 3.90])
    c = consensus([soft, sharp])
    assert c.books_used == 2 and c.books_dropped == 0
    assert sum(c.probs) == pytest.approx(1.0)
    only_soft = consensus([soft]).probs
    only_sharp = consensus([sharp]).probs
    # the blend sits between the two, closer to the sharp book (weight 3 vs 1)
    assert min(only_soft[0], only_sharp[0]) < c.probs[0] < max(only_soft[0], only_sharp[0])
    assert abs(c.probs[0] - only_sharp[0]) < abs(c.probs[0] - only_soft[0])
    assert c.sharp_share == pytest.approx(0.75)


def test_consensus_drops_stale_and_broken_books():
    now = datetime(2026, 10, 10, 12, 0)
    fresh = BookMarket("bet365", [1.80, 3.60, 4.50], updated=now - timedelta(hours=2))
    stale = BookMarket("bwin", [1.20, 5.00, 9.00], updated=now - timedelta(days=4))
    broken = BookMarket("x", [1.0, 3.0, 3.0])
    arb = BookMarket("y", [3.0, 3.0, 3.5])   # margin negative: not a real market
    c = consensus([fresh, stale, broken, arb], now=now)
    assert c.books_used == 1 and c.books_dropped == 3
    assert c.probs == pytest.approx(tuple(power_devig([1.80, 3.60, 4.50])))
    assert consensus([stale], now=now) is None


def test_consensus_rejects_mismatched_outcomes():
    with pytest.raises(ValueError):
        consensus([BookMarket("a", [1.9, 1.9]), BookMarket("b", [1.8, 3.5, 4.0])])


def test_best_price():
    assert best_price({"snai": 1.74, "bet365": 1.82, "sisal": 1.78}) == ("bet365", 1.82)
    assert best_price({}) is None


# ---------- feed ----------
import json  # noqa: E402
from datetime import timezone  # noqa: E402
from pathlib import Path  # noqa: E402

from scudi_slips.feed import price_feed  # noqa: E402


def _sample():
    return json.loads((Path(__file__).parent / "feed_sample.json").read_text())


def test_feed_prices_good_matches_and_counts_every_guard():
    now = datetime(2026, 10, 9, 10, 0, tzinfo=timezone.utc)
    window_end = datetime(2026, 10, 13, 0, 0, tzinfo=timezone.utc)
    matches, g = price_feed(_sample(), now, window_end)
    assert [m.home for m in matches] == ["Genoa", "Inter"]
    assert g.kept == 2 and g.started == 1 and g.outside_window == 1 and g.too_few_books == 1
    assert g.books_dropped == 1          # the stale book on Genoa
    genoa, inter = matches
    assert genoa.books_used == 4 and genoa.sharp_share > 0.5
    assert genoa.fit_error < 0.001
    assert set(genoa.chances) == set(SLIP_MENU)                  # every offered pick type, new markets included (decision 78)
    assert abs(genoa.chances["1"] + genoa.chances["X"] + genoa.chances["2"] - 1) < 1e-9
    # estimates come from ordinary books only (Unibet, William Hill), never from the sharp ones
    assert genoa.estimate["1"] == pytest.approx((2.50 + 2.55) / 2)
    assert genoa.estimate["1X"] == pytest.approx(math.floor(1 / (1 / 2.525 + 1 / 3.15) * 100 + 1e-9) / 100)
    assert genoa.best["1"] == ("betfair_ex_eu", 2.66)
    # Inter has no totals market: goals picks are withheld, result picks stay
    assert g.no_totals == 1
    assert "O25" not in inter.chances and "1" in inter.chances and "1X" in inter.estimate


def test_feed_requires_a_sharp_book_when_asked():
    now = datetime(2026, 10, 9, 10, 0, tzinfo=timezone.utc)
    sample = _sample()
    sample["Serie A"][0]["bookmakers"] = [b for b in sample["Serie A"][0]["bookmakers"] if b["key"] not in ("pinnacle", "betfair_ex_eu")]
    matches, g = price_feed(sample, now, datetime(2026, 10, 13, tzinfo=timezone.utc), need_sharp=True)
    assert [m.home for m in matches] == ["Inter"] and g.no_sharp == 1


def test_feed_drops_a_match_the_matrix_cannot_reproduce():
    now = datetime(2026, 10, 9, 10, 0, tzinfo=timezone.utc)
    sample = _sample()
    ev = sample["Serie A"][0]
    for b in ev["bookmakers"]:                     # a huge favourite with a tiny over-2.5 chance: no score matrix fits
        for m in b["markets"]:
            if m["key"] == "h2h":
                for o in m["outcomes"]:
                    o["price"] = {"Genoa": 1.05, "Fiorentina": 30.0, "Draw": 15.0}[o["name"]]
            if m["key"] == "totals":
                for o in m["outcomes"]:
                    o["price"] = 8.0 if o["name"] == "Over" else 1.06
    matches, g = price_feed(sample, now, datetime(2026, 10, 13, tzinfo=timezone.utc), max_fit_error=0.005)
    assert g.bad_fit == 1 and all(m.home != "Genoa" for m in matches)


# ---------- weekly job + grading, end to end on a synthetic feed ----------
from tools.grade import grade  # noqa: E402
from tools.weekly import preset_slips  # noqa: E402


def _synthetic_feed(rng, n=10, comp="Serie A", day="2026-10-10"):
    events = []
    for i in range(n):
        ph = rng.uniform(0.3, 0.7)
        pd_ = rng.uniform(0.2, 0.3)
        pa = 1 - ph - pd_
        po = rng.uniform(0.45, 0.6)
        books = []
        for bk, margin in (("pinnacle", 0.025), ("unibet_eu", 0.06), ("williamhill", 0.07)):
            books.append({"key": bk, "last_update": f"{day}T08:00:00Z", "markets": [
                {"key": "h2h", "outcomes": [{"name": f"H{i}", "price": round(1 / (ph * (1 + margin)), 2)}, {"name": f"A{i}", "price": round(1 / (pa * (1 + margin)), 2)}, {"name": "Draw", "price": round(1 / (pd_ * (1 + margin)), 2)}]},
                {"key": "totals", "outcomes": [{"name": "Over", "price": round(1 / (po * (1 + margin)), 2), "point": 2.5}, {"name": "Under", "price": round(1 / ((1 - po) * (1 + margin)), 2), "point": 2.5}]}]})
        events.append({"id": f"{comp[:2]}{i}", "commence_time": f"{day}T{13 + i % 8:02d}:00:00Z", "home_team": f"H{i}", "away_team": f"A{i}", "bookmakers": books})
    return {comp: events}


def test_weekly_presets_and_grading_end_to_end():
    rng = random.Random(3)
    now = datetime(2026, 10, 9, 10, 0, tzinfo=timezone.utc)
    matches, g = price_feed(_synthetic_feed(rng), now, now + timedelta(days=5))
    assert g.kept == 10 and g.books_dropped == 0
    slips = preset_slips(matches, now)
    names = {s["name"] for s in slips}
    assert "Serie A" in names and "Top 5 leagues" in names
    for s in slips:
        assert s["odds"] >= s["target"] and len(s["picks"]) == s["legs"] and 1 <= s["legs"] <= 25   # the number of legs is free
        assert all(p["odds"] >= 1.25 for p in s["picks"])
        assert 0 < s["chance"] < 0.2
    week = {"built_at": now.isoformat(), "slips": slips}
    # scores: home wins 2-0 everywhere -> every '1', '1X', '12', 'O15', 'U35', 'NG'-type leg wins; over 2.5 / under 2.5 split
    scores = {m.id: {"id": m.id, "completed": True, "home_team": m.home, "away_team": m.away, "scores": [{"name": m.home, "score": "2"}, {"name": m.away, "score": "0"}]} for m in matches}
    rec = grade(week, scores, {}, now + timedelta(days=4))
    assert rec["summary"]["graded"] == len(slips)
    assert abs(rec["summary"]["expected_hits"] - sum(s["chance"] for s in slips)) < 0.01
    for s in rec["slips"]:
        assert 0 <= s["legs_won"] <= s["legs"] and s["landed"] == (s["legs_won"] == s["legs"])
    # an incomplete match keeps its slips open, and grading twice never double-counts
    scores[matches[0].id]["completed"] = False
    rec2 = grade(week, scores, json.loads(json.dumps(rec)), now + timedelta(days=4))
    assert rec2["summary"]["graded"] == rec["summary"]["graded"]
    fresh = grade(week, scores, {}, now + timedelta(days=4))
    assert fresh["summary"]["graded"] < len(slips)


# ---------- season simulator ----------
from scudi_slips.season import SeasonOutlook, SlipPlan, simulate  # noqa: E402


def test_season_simulator_matches_the_arithmetic():
    plan = SlipPlan(chance=1 / 33, payout=31.0, stake=5, per_week=1)
    o = simulate([plan], weeks=38, sims=40000)
    assert isinstance(o, SeasonOutlook)
    assert o.slips == 38 and o.staked == 190
    assert o.expected_hits == pytest.approx(38 / 33)
    assert o.expected_profit == pytest.approx(38 * (31 * 5 / 33) - 190)
    # a losing season is the common case at these odds: no hit at all in about (1-1/33)^38 = 31% of seasons
    assert abs(o.chance_of_zero_hits - (1 - 1 / 33) ** 38) < 0.02
    assert o.profit_p5 == -190 and o.profit_p95 > 0
    assert 0 < o.longest_dry_run_p50 <= 38 and o.longest_dry_run_p90 >= o.longest_dry_run_p50
    assert o.hits_p5 <= o.expected_hits <= o.hits_p95


def test_season_simulator_rejects_bad_plans():
    with pytest.raises(ValueError):
        simulate([], weeks=10)
    with pytest.raises(ValueError):
        simulate([SlipPlan(1.2, 30, 5)], weeks=10)


# ---------- team data job (tools/teams.py) on synthetic ESPN-shaped responses ----------
def _espn_sample():
    import json
    from pathlib import Path

    from tools.sample_espn import make

    feed = json.loads(Path(__file__).with_name("feed_week_sample.json").read_text())
    return feed, make(feed, seed=3)


def test_teams_job_builds_squads_lineups_and_averages_and_is_incremental():
    from datetime import datetime, timezone

    from tools.teams import FULL, build, replay_fetch

    feed, rec = _espn_sample()
    now = datetime(2026, 10, 8, 9, 0, tzinfo=timezone.utc)
    teams, players, budget = build(replay_fetch(rec), FULL, {}, {}, now)
    names = {n for evs in feed.values() for e in evs for n in (e["home_team"], e["away_team"])}
    from tools.sample_espn import REGISTRY
    from tools.teams import find_team
    everyone = [t for rows in REGISTRY.values() for t in rows]
    distinct = {(find_team(n, everyone) or {"id": n})["id"] for n in names}   # "Man City" and "Manchester City" are one club
    assert len(teams["teams"]) == len(distinct)
    for t in teams["teams"].values():
        assert len(t["players"]) == 23 and t["avg"]["matches"] == 5 * len(t["comps"]) and 0 < t["avg"]["possession"] < 100
        assert len(t["last"]["xi"]) == 11 and t["last"]["xi"][0]["slot"] == 1 and t["formation"] in t["formations"]
        assert len(t["form"]) == 5 and set(t["form"]) <= set("WDL")
        assert t["key"] and t["logo"]
    assert len(players["players"]) == len(distinct) * 23
    assert budget.failed == 0
    # second run: nothing refetched except the lists, rosters and schedules
    teams2, players2, budget2 = build(replay_fetch(rec), FULL, teams, players, now)
    assert budget2.calls < budget.calls / 3
    for k, t in teams2["teams"].items():
        assert t["avg"] == teams["teams"][k]["avg"] and t["last"] == teams["teams"][k]["last"]
    assert players2["players"] == players["players"]


def test_teams_job_survives_a_failing_endpoint_and_a_request_cap():
    from datetime import datetime, timezone

    from tools.teams import build, replay_fetch

    _feed, rec = _espn_sample()
    broken = {u: v for u, v in rec.items() if "/summary?" not in u}   # every match summary fails
    teams, _players, budget = build(replay_fetch(broken), ["Serie A"], {}, {}, datetime(2026, 10, 8, tzinfo=timezone.utc), transfers=False)
    assert budget.failed > 0 and len(teams["teams"]) == 20
    assert all(t["avg"]["matches"] == 0 and t["players"] for t in teams["teams"].values())
    teams, _players, budget = build(replay_fetch(rec), ["Serie A"], {}, {}, datetime(2026, 10, 8, tzinfo=timezone.utc), max_calls=30)
    assert budget.calls == 30 and len(teams["teams"]) == 20


def test_team_name_key_drops_accents_and_club_words():
    from tools.teams import norm

    assert norm("FC Internazionale Milano") == "internazionale milano"
    assert norm("Bayern München") == "bayern munchen"
    assert norm("Paris Saint-Germain") == norm("Paris Saint Germain") == "paris saint germain"
    assert norm("AS Roma") == "roma" and norm("SSC Napoli") == "napoli"


def test_every_sample_week_team_resolves_to_a_real_espn_team():
    import json
    from pathlib import Path

    from tools.teams import find_team

    reg = json.loads((Path(__file__).parents[1] / "data" / "espn_teams.json").read_text())["competitions"]
    everyone = [t for rows in reg.values() for t in rows]
    feed = json.loads(Path(__file__).with_name("feed_week_sample.json").read_text())
    missing = sorted({n for evs in feed.values() for e in evs for n in (e["home_team"], e["away_team"]) if find_team(n, everyone) is None})
    assert missing == ["Nantes", "Wolfsburg"]   # not in the 2026-27 top flights; the sample feed's fixture lists outside Serie A and the CL are invented
    assert find_team("Inter", everyone)["id"] == 110 and find_team("Inter Milan", everyone)["id"] == 110 and find_team("Milan", everyone)["id"] == 103
    assert find_team("Paris Saint Germain", everyone)["id"] == 160 and find_team("Bodo/Glimt", everyone)["id"] == 2980
    assert find_team("Athletic Bilbao", everyone)["id"] == 93 and find_team("Man City", everyone)["id"] == 382
    assert find_team("Nowhere United", everyone) is None


# ---------- match-day pulls, price history and closing chances (decision 73) ----------
def _week_from(matches, now, slips=None):
    from tools.weekly import match_record
    return {"built_at": now.isoformat(), "window_days": 6.0, "matches": [match_record(m) for m in matches], "slips": slips or []}


def test_history_snapshots_and_closing_chance():
    from tools.weekly import add_snapshots, closing, match_record

    rng = random.Random(3)
    t0 = datetime(2026, 10, 9, 9, 0, tzinfo=timezone.utc)
    m0, _ = price_feed(_synthetic_feed(rng), t0, t0 + timedelta(days=5))
    hist = add_snapshots({}, [match_record(m) for m in m0], t0)
    assert len(hist) == len(m0) >= 8 and all(len(h["snaps"]) == 1 for h in hist.values())
    t1 = t0 + timedelta(hours=2)                       # a later pull the same morning: one more snapshot each
    hist = add_snapshots(hist, [match_record(m) for m in m0], t1)
    assert all(len(h["snaps"]) == 2 for h in hist.values())
    hist = add_snapshots(hist, [match_record(m) for m in m0], t1)   # the same pull twice replaces, never duplicates
    assert all(len(h["snaps"]) == 2 for h in hist.values())
    m1 = m0
    after = t1 + timedelta(days=3)                     # kicked off: no new snapshot, the last one is the closing view
    hist = add_snapshots(hist, [match_record(m) for m in m1], after)
    assert all(len(h["snaps"]) == 2 for h in hist.values())
    mid = m1[0].id
    assert closing(hist, mid)["t"] == t1.isoformat() and closing(hist, "nope") is None
    assert add_snapshots(hist, [], after + timedelta(days=11)) == {}   # old matches are dropped


def test_late_pull_refreshes_only_upcoming_matches_and_keeps_the_slips():
    from tools.weekly import comps_due, match_record, merge_late

    t0 = datetime(2026, 10, 9, 9, 0, tzinfo=timezone.utc)
    feed = _synthetic_feed(random.Random(3), comp="Serie A", day="2026-10-10")
    feed.update(_synthetic_feed(random.Random(4), comp="Premier League", day="2026-10-12"))
    m0, _ = price_feed(feed, t0, t0 + timedelta(days=6))
    old = _week_from(m0, t0, slips=[{"name": "kept"}])
    t1 = datetime(2026, 10, 10, 9, 0, tzinfo=timezone.utc)
    assert comps_due(old, t1, 18) == ["Serie A"]         # Premier League plays in two days: not refreshed, no credit spent
    assert comps_due(old, datetime(2026, 10, 13, 9, 0, tzinfo=timezone.utc), 18) == []
    t_mid = datetime(2026, 10, 10, 15, 30, tzinfo=timezone.utc)   # some Serie A matches have kicked off (13:00-15:00)
    fresh_feed = _synthetic_feed(random.Random(9), comp="Serie A", day="2026-10-10")
    m1, g = price_feed(fresh_feed, t_mid, t_mid + timedelta(days=6))
    assert g.started > 0
    merged = merge_late(old, [match_record(m) for m in m1], ["Serie A"], t_mid)
    assert merged["slips"] == [{"name": "kept"}] and merged["refreshed"] == ["Serie A"]
    ids_old = [m["id"] for m in old["matches"]]
    assert sorted(m["id"] for m in merged["matches"]) == sorted(ids_old)   # nothing lost: started matches keep their prices
    by_id = {m["id"]: m for m in merged["matches"]}
    started = [m for m in old["matches"] if m["competition"] == "Serie A" and datetime.fromisoformat(m["kickoff"]) <= t_mid]
    assert started and all(by_id[m["id"]] == m for m in started)
    upcoming = [m.id for m in m1]
    assert upcoming and all(by_id[i]["chances"] == match_record(next(x for x in m1 if x.id == i))["chances"] for i in upcoming)
    pl = [m for m in old["matches"] if m["competition"] == "Premier League"]
    assert all(by_id[m["id"]] == m for m in pl)


def test_graded_legs_carry_outcome_and_closing_value():
    from tools.weekly import add_snapshots

    rng = random.Random(3)
    now = datetime(2026, 10, 9, 10, 0, tzinfo=timezone.utc)
    matches, _ = price_feed(_synthetic_feed(rng), now, now + timedelta(days=5))
    slips = preset_slips(matches, now)
    week = _week_from(matches, now, slips)
    hist = add_snapshots({}, week["matches"], now)
    scores = {m.id: {"id": m.id, "completed": True, "home_team": m.home, "away_team": m.away, "scores": [{"name": m.home, "score": "1"}, {"name": m.away, "score": "1"}]} for m in matches}
    rec = grade(week, scores, {}, now + timedelta(days=4), hist)
    s = rec["slips"][0]
    assert len(s["leg_results"]) == s["legs"] and sum(x["won"] for x in s["leg_results"]) == s["legs_won"]
    for leg in s["leg_results"]:
        assert leg["score"] == "1-1" and leg["competition"] == "Serie A" and " v " in leg["name"]
        assert "clv" in leg and abs(leg["clv"] - (leg["odds"] * leg["close_chance"] - 1)) < 1e-3
    no_hist = grade(week, scores, {}, now + timedelta(days=4))
    assert "clv" not in no_hist["slips"][0]["leg_results"][0]


def test_weekly_main_auto_mode_replays_full_then_late(tmp_path):
    from tools.weekly import main

    feed = _synthetic_feed(random.Random(3), comp="Serie A", day="2026-10-10")
    feed.update(_synthetic_feed(random.Random(4), comp="Premier League", day="2026-10-12"))
    f = tmp_path / "feed.json"
    f.write_text(json.dumps(feed))
    out, hist = tmp_path / "week.json", tmp_path / "history.json"
    args = ["--from-file", str(f), "--out", str(out), "--history", str(hist), "--mode", "auto", "--comps", "Serie A", "Premier League"]
    assert main([*args, "--now", "2026-10-09T09:00:00Z"]) == 0          # Friday: full
    full = json.loads(out.read_text())
    n_sa = sum(m["competition"] == "Serie A" for m in full["matches"])
    assert full["slips"] and n_sa >= 8 and len(full["matches"]) >= 16
    assert main([*args, "--now", "2026-10-10T09:00:00Z"]) == 0          # Saturday: late, Serie A only
    late = json.loads(out.read_text())
    assert late["refreshed"] == ["Serie A"] and late["slips"] == full["slips"] and len(late["matches"]) == len(full["matches"])
    h = json.loads(hist.read_text())
    assert sum(len(v["snaps"]) == 2 for v in h.values()) == n_sa         # Serie A has two snapshots, Premier League one
    before = out.read_text()
    assert main([*args, "--now", "2026-10-14T09:00:00Z"]) == 0          # Wednesday: nothing due, nothing written
    assert out.read_text() == before


def test_team_job_builds_league_tables_and_falls_back_to_the_other_espn_host():
    from datetime import datetime, timezone

    from tools.teams import build, replay_fetch

    _feed, rec = _espn_sample()
    moved = {u.replace("https://site.web.api.espn.com/", "https://site.api.espn.com/", 1) if "/teams/" in u and u.endswith("/schedule") else u: v
             for u, v in rec.items()}   # schedules only answer on the other host: the job must still find them
    teams, _players, budget = build(replay_fetch(moved), ["Serie A"], {}, {}, datetime(2026, 10, 8, tzinfo=timezone.utc), transfers=False)
    table = teams["tables"]["Serie A"]
    assert len(table) == 20 and [r["pos"] for r in table] == list(range(1, 21))
    assert all(r["p"] == 5 and r["w"] + r["d"] + r["l"] == 5 and r["pts"] == 3 * r["w"] + r["d"] for r in table)
    assert all(r["home"]["p"] + r["away"]["p"] == r["p"] for r in table)
    assert sum(r["gf"] for r in table) == sum(r["ga"] for r in table)          # every goal scored is a goal conceded
    keys = [(-r["pts"], -(r["gf"] - r["ga"]), -r["gf"]) for r in table]
    assert keys == sorted(keys)
    assert budget.failed == 0
    t = next(iter(teams["teams"].values()))
    assert all(r["comp"] == "Serie A" for r in t["results"])


def test_team_job_drops_matches_espn_does_not_list_and_never_starts_from_the_example_file():
    """Incident 2026-10-05: the live runs had grown out of the example data/teams.json, so Milan showed 10 matches, 5 of them
    invented, and pass completion averaged a fraction (0.8) with a percentage (85). Now: (a) a stored file whose header says
    "example" is ignored; (b) a stored record without per-match data is rebuilt; (c) a stored match that ESPN's schedule for
    that competition does not list is dropped and leaves the averages; (d) pass completion is a percentage."""
    import copy
    from datetime import datetime, timezone

    from tools.teams import build, replay_fetch

    _feed, rec = _espn_sample()
    now = datetime(2026, 10, 8, tzinfo=timezone.utc)
    teams, _p, b0 = build(replay_fetch(rec), ["Serie A"], {}, {}, now, transfers=False)
    key, t = next(iter(teams["teams"].items()))
    assert t["avg"]["matches"] == 5 and len(t["matches"]) == 5 and "sums" not in t
    assert all(50 <= m["s"]["pass_pct"] <= 100 for m in t["matches"].values())        # the sample prints percentages already
    # (a) the example header: everything is fetched again, nothing of the stored record survives
    example = copy.deepcopy(teams)
    example["source"] = "example data: real teams, crests and colours; invented squads, results and transfers, in ESPN's shapes"
    example["teams"][key]["matches"]["400999"] = {"d": "2026-09-12", "c": "Serie A", "h": True, "v": "Nobody", "vi": "1", "gf": 9, "ga": 0, "s": {"pass_pct": 85}}
    again, _p, b1 = build(replay_fetch(rec), ["Serie A"], example, {"source": example["source"]}, now, transfers=False)
    assert "400999" not in again["teams"][key]["matches"] and again["teams"][key]["avg"] == t["avg"] and b1.calls == b0.calls
    # (b) a legacy record (sums, no per-match store) is rebuilt from scratch
    legacy = copy.deepcopy(teams)
    tl = legacy["teams"][key]
    tl.pop("matches")
    tl["sums"] = {"matches": 10, "events": ["400006", "400033"], "pass_pct": 428, "pass_pct_n": 10}
    tl["avg"] = {"matches": 10, "pass_pct": 42.8, "record": "3-4-3"}
    again, _p, b2 = build(replay_fetch(rec), ["Serie A"], legacy, {}, now, transfers=False)
    assert again["teams"][key]["avg"] == t["avg"] and "sums" not in again["teams"][key]
    assert b2.calls == 1 + 20 + 20 + 5 + 5                 # list, rosters, schedules; only that team's 5 matches and line-ups again
    # (c) a stored match the schedule does not list is dropped; the real ones are not fetched again
    stale = copy.deepcopy(teams)
    stale["teams"][key]["matches"]["400033"] = {"d": "2026-09-12", "c": "Serie A", "h": False, "v": "AS Roma", "vi": "104", "gf": 1, "ga": 2, "s": {"pass_pct": 85, "shots": 30}}
    stale["teams"][key]["last"] = {"date": "2026-09-12T18:45Z", "event": "400033", "formation": "4-4-2", "xi": []}
    again, _p, b3 = build(replay_fetch(rec), ["Serie A"], stale, {}, now, transfers=False)
    a = again["teams"][key]
    assert "400033" not in a["matches"] and a["avg"] == t["avg"] and a["results"] == t["results"] and a["form"] == t["form"]
    assert a["last"] == t["last"] and b3.calls < b0.calls / 2                      # the stale "last" line-up is replaced by a real one
    assert all(r["event"] != "400033" for r in a["results"]) and a["by_comp"]["Serie A"]["all"]["p"] == 5
    assert again["tables"]["Serie A"] == teams["tables"]["Serie A"]
    # (e) a run stopped by the request cap stores only matches with summary and line-up; the next run completes them
    part, _p, bp = build(replay_fetch(rec), ["Serie A"], {}, {}, now, transfers=False, max_calls=31)
    tp = part["teams"][key]
    assert bp.calls == 31 and 0 < len(tp["matches"]) < 5 and all("f" in m for m in tp["matches"].values())
    full_again, _p, _bf = build(replay_fetch(rec), ["Serie A"], part, {}, now, transfers=False)
    assert full_again["teams"][key]["avg"] == t["avg"] and full_again["teams"][key]["last"] == t["last"]
    assert all("f" in m for m in full_again["teams"][key]["matches"].values())
    # (f) an empty schedule answer drops nothing; a team no longer listed in a competition loses that competition's matches
    empty = {u: ({"events": []} if u.endswith("/schedule") else v) for u, v in rec.items()}
    kept, _p, _b = build(replay_fetch(empty), ["Serie A"], teams, {}, now, transfers=False)
    assert kept["teams"][key]["avg"] == t["avg"] and kept["teams"][key]["last"] == t["last"]
    gone = copy.deepcopy(teams)
    gone["teams"][key]["matches"]["400777"] = {"d": "2025-05-01", "c": "Serie B", "h": True, "v": "Old", "vi": "9", "gf": 1, "ga": 0, "s": {"shots": 30}}
    gone["teams"][key]["comps"].append("Serie B")
    gone["teams"][key]["light"] = {"Serie B": {"rec": {"all": {"p": 1, "w": 1, "d": 0, "l": 0, "gf": 1, "ga": 0}, "home": {"p": 1, "w": 1, "d": 0, "l": 0, "gf": 1, "ga": 0}, "away": {"p": 0, "w": 0, "d": 0, "l": 0, "gf": 0, "ga": 0}}, "results": []}}
    rolled, _p, _b = build(replay_fetch(rec), ["Serie A"], gone, {}, now, transfers=False)   # Serie B not fetched this run: untouched
    assert "400777" in rolled["teams"][key]["matches"] and "Serie B" in rolled["teams"][key]["comps"]
    recB = dict(rec)
    recB[next(u for u in rec if u.endswith("/teams") and "ita.1" in u).replace("ita.1", "ita.2")] = {"sports": [{"leagues": [{"teams": []}]}]}
    rolled, _p, _b = build(replay_fetch(recB), ["Serie A", "Serie B"], gone, {}, now, transfers=False)   # Serie B fetched, the team is not in it
    assert "400777" not in rolled["teams"][key]["matches"] and "Serie B" not in rolled["teams"][key]["comps"] and "Serie B" not in rolled["teams"][key].get("light", {})
    assert rolled["teams"][key]["avg"] == t["avg"]
    # (d) ESPN's passPct as a fraction becomes a percentage; accurate / total passes win when both are listed
    from tools.teams import _match
    comp = {"homeAway": "home", "score": {"value": 2}, "team": {"id": "1", "displayName": "A"}}
    oth = {"homeAway": "away", "score": {"value": 0}, "team": {"id": "2", "displayName": "B"}}
    summ = {"boxscore": {"teams": [{"team": {"id": "1"}, "statistics": [{"name": "passPct", "displayValue": "0.8"}, {"name": "totalShots", "displayValue": "12"}]}]}}
    assert _match(summ, "9", "1", comp, oth, "2026-10-01T18:45Z", "Serie A")["s"] == {"pass_pct": 80.0, "shots": 12.0}
    summ = {"boxscore": {"teams": [{"team": {"id": "1"}, "statistics": [{"name": "passPct", "displayValue": "0.8"}, {"name": "accuratePasses", "displayValue": "412"}, {"name": "totalPasses", "displayValue": "500"}]}]}}
    assert _match(summ, "9", "1", comp, oth, "2026-10-01T18:45Z", "Serie A")["s"] == {"pass_pct": 82.4}


# ---------- sistema bets ----------
def test_sistema_straight_equals_the_accumulator_and_errors_add_chances():
    from scudi_slips.sistema import plan

    legs = [(0.72, 1.30), (0.74, 1.30), (0.68, 1.44), (0.61, 1.60), (0.75, 1.27), (0.75, 1.25), (0.75, 1.27), (0.62, 1.57), (0.60, 1.57), (0.72, 1.30)]
    straight = plan(legs, 10, 10.0)
    p_all = math.prod(p for p, _ in legs)
    odds = math.prod(o for _, o in legs)
    assert straight.tickets == 1 and abs(straight.chance_any - p_all) < 1e-12
    assert abs(straight.average_return - p_all * odds) < 1e-9 and straight.outcomes[0].pays_min == pytest.approx(10 * odds)
    one = plan(legs, 9, 10.0)
    assert one.tickets == 10 and abs(one.per_ticket - 1.0) < 1e-12 and one.min_stake == 2.0
    assert one.chance_any > straight.chance_any * 3                     # one error allowed: far likelier to get something back
    assert abs(sum(o.chance for o in one.outcomes) - one.chance_any) < 1e-12
    # all ten win: each 9-leg ticket pays its own odds, and the ten tickets together pay (sum over tickets of prod odds)
    all_win = one.outcomes[0]
    assert all_win.pays_min == pytest.approx(sum(odds / o for _, o in legs) * 1.0)
    # exactly one loses: one ticket survives, the one without that leg
    one_lost = one.outcomes[1]
    assert one_lost.pays_min == pytest.approx(min(odds / o for _, o in legs)) and one_lost.pays_max == pytest.approx(max(odds / o for _, o in legs))
    # average return equals the elementary-symmetric shortcut
    e9 = sum(math.prod(p * o for j, (p, o) in enumerate(legs) if j != i) for i in range(10))
    assert one.average_return == pytest.approx(e9 * (1.0 / 10.0) * 10 / 10.0)
    two = plan(legs, 8, 45 * 0.05)
    assert two.tickets == 45 and two.min_stake == pytest.approx(2.25) and two.chance_any > one.chance_any


def test_sistema_bonus_switch_and_limits():
    from scudi_slips.sistema import plan

    legs = [(0.7, 1.35)] * 8
    off, on = plan(legs, 7, 8.0), plan(legs, 7, 8.0, bonus_on=True)
    assert on.average_return == pytest.approx(off.average_return * 1.035 ** 3)
    with pytest.raises(ValueError):
        plan(legs, 9, 1.0)
    with pytest.raises(ValueError):
        plan([(0.7, 1.3)] * 20, 15, 10.0)


# ---------- v10: more competitions, cheaper pulls, free grading (decision 74) ----------

def test_registry_is_consistent_and_discovers_national_friendlies_only():
    from scudi_slips.comps import BY_KEY, COMPETITIONS, GROUP_ORDER, discovered
    from scudi_slips.feed import SPORT_KEYS

    assert len({c.name for c in COMPETITIONS}) == len({c.odds for c in COMPETITIONS}) == len(COMPETITIONS)
    assert all(c.group in GROUP_ORDER for c in COMPETITIONS) and SPORT_KEYS == {c.name: c.odds for c in COMPETITIONS}
    assert {"Serie B", "Championship", "League One", "Süper Lig", "Belgian Pro League", "Eliteserien", "Nations League", "World Cup", "Euro"} <= {c.name for c in COMPETITIONS}
    assert "soccer_uefa_nations_league" in BY_KEY
    fr = discovered({"key": "soccer_international_friendlies", "title": "International Friendlies", "active": True, "has_outrights": False})
    assert fr and fr.group == "national" and fr.espn == "fifa.friendly"
    assert discovered({"key": "soccer_fifa_world_cup_womens", "title": "FIFA Women's World Cup", "has_outrights": False}) is None
    assert discovered({"key": "soccer_fifa_world_cup_winner", "title": "World Cup Winner", "has_outrights": True}) is None
    assert discovered({"key": "soccer_epl", "title": "EPL"}) is None                      # already in the registry
    assert discovered({"key": "soccer_brazil_campeonato", "title": "Brazil Série A"}) is None  # not a national-team competition


def test_window_runs_to_the_next_tuesday_or_friday_morning():
    from tools.weekly import days_to_reset, window_end

    utc = timezone.utc
    assert window_end(datetime(2026, 10, 9, 9, 0, tzinfo=utc)) == datetime(2026, 10, 13, 6, 0, tzinfo=utc)    # Friday -> Tuesday
    assert window_end(datetime(2026, 10, 13, 9, 0, tzinfo=utc)) == datetime(2026, 10, 16, 6, 0, tzinfo=utc)   # Tuesday -> Friday
    assert window_end(datetime(2026, 9, 23, 9, 0, tzinfo=utc)) == datetime(2026, 9, 25, 6, 0, tzinfo=utc)     # Wednesday -> Friday
    assert window_end(datetime(2026, 10, 15, 20, 0, tzinfo=utc)) == datetime(2026, 10, 20, 6, 0, tzinfo=utc)  # Thursday night -> Tuesday
    from scudi_slips.comps import BY_NAME
    from tools.weekly import comp_end, first_pull
    fri, tue = datetime(2026, 10, 9, 9, 0, tzinfo=utc), datetime(2026, 10, 13, 9, 0, tzinfo=utc)
    sa, sb, nl = BY_NAME["Serie A"], BY_NAME["Serie B"], BY_NAME["Nations League"]
    assert comp_end(sa, tue, window_end(tue)) == tue + timedelta(days=8)          # big leagues: 8 days ahead at every pull
    assert comp_end(nl, tue, window_end(tue)) == tue + timedelta(days=8)
    assert comp_end(sb, tue, window_end(tue)) == window_end(tue)                  # others on Tuesday: to Friday morning
    assert comp_end(sb, fri, window_end(fri)) == fri + timedelta(days=8)          # everyone on Friday
    wed = datetime(2026, 9, 23, 9, 0, tzinfo=utc)
    assert first_pull(datetime(2026, 10, 10, 13, 0, tzinfo=utc), sa, wed) == datetime(2026, 10, 6, 9, 0, tzinfo=utc)   # Serie A Sat 10 Oct: Tuesday 6 Oct
    assert first_pull(datetime(2026, 10, 10, 13, 0, tzinfo=utc), sb, wed) == datetime(2026, 10, 9, 9, 0, tzinfo=utc)   # Serie B: that Friday
    assert first_pull(datetime(2026, 10, 14, 13, 0, tzinfo=utc), sb, wed) == datetime(2026, 10, 9, 9, 0, tzinfo=utc)   # its Wednesday game: same Friday
    assert days_to_reset(datetime(2026, 9, 22, 9, 0, tzinfo=utc)) == 9 and days_to_reset(datetime(2026, 12, 31, 23, 0, tzinfo=utc)) == 1


class _FakeFeed:
    """The odds feed's interface over recorded events, counting calls and credits the way the feed does."""

    def __init__(self, events, active, remaining=400, fail=()):
        from scudi_slips.comps import BY_NAME
        self.events, self.active, self.remaining, self.fail, self.calls, self.by_key = events, active, remaining, set(fail), [], {BY_NAME[n].odds: n for n in events if n in BY_NAME}
        self.by_key.update({k: n for n, k in active.items() if n not in BY_NAME})

    def __call__(self, path, params):
        self.calls.append((path, dict(params)))
        if path.endswith("/events"):                     # the fixture list: free
            name = self.by_key.get(path.split("/")[1])
            lo, hi = params["commenceTimeFrom"], params["commenceTimeTo"]
            return [{k: v for k, v in e.items() if k != "bookmakers"} for e in self.events.get(name, []) if lo <= e["commence_time"] <= hi], {}
        if path == "":
            return [{"key": k, "active": True, "has_outrights": False, "title": n} for n, k in self.active.items()], {"x-requests-remaining": str(self.remaining)}
        key = path.split("/")[1]
        name = self.by_key.get(key)
        if name in self.fail:
            raise RuntimeError("HTTP 500: boom")
        lo, hi = params["commenceTimeFrom"], params["commenceTimeTo"]
        evs = [e for e in self.events.get(name, []) if lo <= e["commence_time"] <= hi]
        cost = 2 if evs else 0
        self.remaining -= cost
        return evs, {"x-requests-remaining": str(self.remaining), "x-requests-used": str(500 - self.remaining), "x-requests-last": str(cost)}


def _national_feed():
    feed = _synthetic_feed(random.Random(5), n=8, comp="Nations League", day="2026-09-24")
    for i, e in enumerate(feed["Nations League"]):
        e["id"] = f"nl{i}"
    feed.update(_synthetic_feed(random.Random(6), n=6, comp="Serie B", day="2026-09-26"))
    feed.update(_synthetic_feed(random.Random(7), n=6, comp="League One", day="2026-09-26"))
    feed.update(_synthetic_feed(random.Random(8), n=6, comp="Serie A", day="2026-10-10"))   # after the window: must not be paid for
    return feed


def test_full_pull_spends_only_on_competitions_with_matches_in_the_window(tmp_path):
    from scudi_slips.comps import BY_NAME
    from tools.weekly import main

    feed = _national_feed()
    active = {n: BY_NAME[n].odds for n in ("Serie A", "Nations League", "Serie B", "League One", "Premier League")}
    active["International Friendlies"] = "soccer_international_friendlies"
    fake = _FakeFeed(feed, active)
    out, hist = tmp_path / "week.json", tmp_path / "history.json"
    assert main(["--out", str(out), "--history", str(hist), "--mode", "auto", "--now", "2026-09-23T09:00:00Z"], get=fake) == 0   # empty store: full
    w = json.loads(out.read_text())
    called = [p for p, _ in fake.calls if p.endswith("/odds")]
    assert len(called) == len(active)                               # one odds call per competition in season, La Liga (not active) never called
    ends = {p.split("/")[1]: q["commenceTimeTo"] for p, q in fake.calls if p.endswith("/odds")}
    assert ends["soccer_uefa_nations_league"] == ends["soccer_italy_serie_a"] == "2026-10-01T09:00:00Z"   # 8 days for the big ones
    assert ends["soccer_italy_serie_b"] == "2026-09-25T06:00:00Z"                                          # the rest: to Friday
    fx = {f["competition"]: f for f in w["fixtures"]}
    assert {"Serie A", "Serie B", "League One"} <= set(fx)          # every later match is listed, free of charge
    assert fx["Serie A"]["priced_from"] == "2026-10-06T09:00:00+00:00" and fx["Serie B"]["priced_from"] == "2026-09-25T09:00:00+00:00"
    assert all(f["priced_from"] is None for f in w["fixtures"] if f["competition"] == "Nations League")   # in the window but held back by the guards
    spent = {p["name"]: p["credits"] for p in w["pulled"]}
    assert spent["Nations League"] == 2 and spent["Serie A"] == 0 and spent["Serie B"] == 0 and spent["International Friendlies"] == 0
    assert {m["competition"] for m in w["matches"]} == {"Nations League"} and len(w["matches"]) == w["guard"]["kept"] >= 6
    comp = {c["name"]: c for c in w["competitions"]}
    assert w["credits"]["remaining"] == "398" and comp["Nations League"]["group"] == "national" and comp["Nations League"]["espn"] == "uefa.nations"
    assert [c["name"] for c in w["competitions"]][:2] == ["Serie A", "Nations League"]      # listed in the site's order, fixtures included
    assert {s["name"] for s in w["slips"]} == {"National teams"}      # one competition: no "All competitions" copy of it
    order = [p["name"] for p in w["pulled"]]
    assert order.index("Serie A") < order.index("Nations League") < order.index("Serie B") < order.index("League One")


def test_optional_competitions_wait_when_credits_run_low_and_errors_do_not_lose_the_rest(tmp_path):
    from scudi_slips.comps import BY_NAME
    from tools.weekly import main

    feed = _national_feed()
    active = {n: BY_NAME[n].odds for n in ("Nations League", "Serie B", "League One")}
    out, hist = tmp_path / "week.json", tmp_path / "history.json"
    fake = _FakeFeed(feed, active, remaining=40)                    # 25 Sep: 6 days to reset x 7 = 42 held back
    assert main(["--out", str(out), "--history", str(hist), "--mode", "full", "--now", "2026-09-25T09:00:00Z"], get=fake) == 0
    w = json.loads(out.read_text())
    assert [p["name"] for p in w["pulled"]] == ["Nations League"]
    assert w["skipped"] == {"Serie B": "saving credits for the big leagues", "League One": "saving credits for the big leagues"}
    fake = _FakeFeed(feed, active, remaining=400, fail={"Nations League"})
    assert main(["--out", str(out), "--history", str(hist), "--mode", "full", "--now", "2026-09-25T09:00:00Z"], get=fake) == 0
    w = json.loads(out.read_text())
    assert {m["competition"] for m in w["matches"]} == {"Serie B", "League One"} and any("Nations League" in n for n in w["notes"])
    before = out.read_text()
    fake = _FakeFeed(feed, active, fail={"Nations League", "Serie B", "League One"})
    assert main(["--out", str(out), "--history", str(hist), "--mode", "full", "--now", "2026-09-25T09:00:00Z"], get=fake) == 1
    assert out.read_text() == before                                # nothing pulled at all: the site keeps what it had


def test_match_day_refresh_covers_big_leagues_and_national_teams_only(tmp_path):
    from scudi_slips.comps import BY_NAME
    from tools.weekly import main

    feed = _national_feed()
    feed["Nations League"] = [dict(e, commence_time=e["commence_time"].replace("2026-09-24", "2026-09-26")) for e in feed["Nations League"]]
    active = {n: BY_NAME[n].odds for n in ("Nations League", "Serie B")}
    out, hist = tmp_path / "week.json", tmp_path / "history.json"
    assert main(["--out", str(out), "--history", str(hist), "--mode", "full", "--now", "2026-09-25T09:00:00Z"], get=_FakeFeed(feed, active)) == 0
    full = json.loads(out.read_text())
    assert {m["competition"] for m in full["matches"]} == {"Nations League", "Serie B"}
    fake = _FakeFeed(feed, active)
    assert main(["--out", str(out), "--history", str(hist), "--mode", "auto", "--now", "2026-09-26T09:00:00Z"], get=fake) == 0   # Saturday
    late = json.loads(out.read_text())
    assert [p for p, _ in fake.calls] == ["/soccer_uefa_nations_league/odds"] and late["refreshed"] == ["Nations League"]
    assert late["slips"] == full["slips"] and len(late["matches"]) == len(full["matches"])


def test_full_pull_carries_the_replaced_weeks_slips_for_grading(tmp_path):
    from tools.grade import main as grade_main
    from tools.weekly import main

    feed = _national_feed()
    active = {"Nations League": "soccer_uefa_nations_league"}
    out, hist, rec = tmp_path / "week.json", tmp_path / "history.json", tmp_path / "record.json"
    assert main(["--out", str(out), "--history", str(hist), "--mode", "full", "--now", "2026-09-23T09:00:00Z"], get=_FakeFeed(feed, active)) == 0
    first = json.loads(out.read_text())
    assert first["slips"]
    assert main(["--out", str(out), "--history", str(hist), "--mode", "full", "--now", "2026-09-25T09:00:00Z"], get=_FakeFeed({}, active)) == 0
    second = json.loads(out.read_text())
    assert second["matches"] == [] and second["pending"][0]["built_at"] == first["built_at"] and second["pending"][0]["slips"] == first["slips"]
    # ESPN scoreboard: every Nations League match 1-0 to the home side, names spelled as ESPN spells them
    events = [{"id": str(900 + i), "date": m["kickoff"].replace("+00:00", "Z"), "competitions": [{"status": {"type": {"completed": True, "state": "post", "name": "STATUS_FULL_TIME"}},
               "competitors": [{"homeAway": "home", "score": "1", "team": {"displayName": m["home"] + " FC"}}, {"homeAway": "away", "score": "0", "team": {"displayName": m["away"]}}]}]}
              for i, m in enumerate(first["matches"])]
    calls = []

    def espn(url):
        calls.append(url)
        assert "uefa.nations/scoreboard?dates=20260923-20260925" in url
        return {"events": events}
    grade_main(["--week", str(out), "--record", str(rec), "--history", str(hist), "--now", "2026-09-25T10:00:00Z"], fetch=espn)
    r = json.loads(rec.read_text())
    assert len(calls) == 1 and r["summary"]["graded"] == len(first["slips"])
    assert all(x["score"] == "1-0" for s in r["slips"] for x in s["leg_results"])


def test_espn_settles_on_ninety_minutes_and_matches_national_team_spellings():
    from tools.grade import espn_final, same_team

    assert same_team("Czech Republic", "Czechia") == 2 and same_team("Turkey", "Türkiye") == 2 and same_team("Ireland", "Republic of Ireland") == 2
    assert same_team("Bosnia & Herzegovina", "Bosnia-Herzegovina") == 2 and same_team("Bosnia and Herzegovina", "Bosnia-Herzegovina") == 2
    assert same_team("Inter", "Internazionale") == 2 and same_team("Germany", "Netherlands") == 0
    ev = lambda name, h, a, lines=None: {"competitions": [{"status": {"type": {"completed": True, "name": name}}, "competitors": [
        {"homeAway": "home", "score": str(h), "linescores": [{"value": v} for v in (lines or [])[0::2]]},
        {"homeAway": "away", "score": str(a), "linescores": [{"value": v} for v in (lines or [])[1::2]]}]}]}
    assert espn_final(ev("STATUS_FULL_TIME", 2, 1)) == (2, 1)
    assert espn_final(ev("STATUS_FINAL_AET", 2, 1, [1, 0, 0, 1, 1, 0])) == (1, 1)     # 1-1 after 90 minutes, 2-1 after extra time
    assert espn_final(ev("STATUS_FINAL_PEN", 1, 1)) is None                            # no periods listed: left open
    postponed = ev("STATUS_POSTPONED", 0, 0)
    postponed["competitions"][0]["status"]["type"]["completed"] = False
    assert espn_final(postponed) is None



def test_espn_extra_time_and_shootouts_from_the_goal_list_on_real_boards():
    """Real ESPN boards (decision 80): a day's scoreboard lists no periods for extra-time matches, so the 90-minute score
    comes from the goals up to 90'+stoppage; shoot-out kicks are not goals; an own goal counts for the side it helps."""
    from tools.grade import espn_final, espn_half

    boards = {e["name"]: e for e in json.loads((Path(__file__).parent / "js" / "espn_live_sample.json").read_text())}
    nor = boards["England at Norway"]                     # 1-2 after extra time, 1-1 after 90 minutes
    assert espn_final(nor) == (1, 1) and espn_half(nor, (1, 1)) == (1, 1)
    ger = boards["Paraguay at Germany"]                   # 1-1, lost on penalties
    assert espn_final(ger) == (1, 1) and espn_half(ger, (1, 1)) == (0, 1)
    aus = boards["Egypt at Australia"]                    # 1-1 with an own goal, then penalties
    assert espn_final(aus) == (1, 1) and espn_half(aus, (1, 1)) == (0, 1)
    fro = boards["Como at Frosinone"]                     # 2-0, the second at 45'+3'
    assert espn_final(fro) == (2, 0) and espn_half(fro, (2, 0)) == (2, 0)
    broken = json.loads(json.dumps(nor))
    broken["competitions"][0]["details"] = broken["competitions"][0]["details"][:1]
    assert espn_final(broken) is None                     # the goals do not add up: left open

def test_light_team_data_for_other_leagues_uses_only_rosters_and_schedules():
    from tools.teams import SITE, WEB, build, replay_fetch

    slug = "ita.2"
    rec, names = {}, ["Palermo", "Sampdoria", "Bari", "Spezia"]
    rec[f"{SITE.format(slug=slug)}/teams"] = {"sports": [{"leagues": [{"teams": [{"team": {"id": str(700 + i), "displayName": n, "abbreviation": n[:3].upper(), "logos": []}} for i, n in enumerate(names)]}]}]}
    games = [(0, 1, 2, 0), (2, 3, 1, 1), (0, 2, 0, 1), (1, 3, 3, 2)]
    for i in range(len(names)):
        tid = str(700 + i)
        rec[f"{WEB.format(slug=slug)}/teams/{tid}/roster"] = {"athletes": [{"id": str(9000 + 10 * i + k), "displayName": f"Player {i}{k}", "position": {"abbreviation": "M", "displayName": "Midfielder"},
                                                                            "headshot": {"href": "x"}, "flag": {"href": "y"}} for k in range(3)]}
        evs = []
        for g, (h, a, gh, ga) in enumerate(games):
            if i in (h, a):
                evs.append({"id": str(5000 + g), "date": f"2026-09-{10 + g:02d}T18:00Z", "competitions": [{"status": {"type": {"completed": True}}, "competitors": [
                    {"homeAway": "home", "score": {"value": gh}, "team": {"id": str(700 + h), "displayName": names[h]}},
                    {"homeAway": "away", "score": {"value": ga}, "team": {"id": str(700 + a), "displayName": names[a]}}]}]})
        rec[f"{SITE.format(slug=slug)}/teams/{tid}/schedule"] = {"events": evs}
    now = datetime(2026, 9, 22, tzinfo=timezone.utc)
    teams, players, budget = build(replay_fetch(rec), ["Serie B"], {}, {}, now)
    assert budget.failed == 0 and budget.calls == 1 + 2 * len(names) and players["players"] == {}     # no summaries, lineups or transfers
    table = teams["tables"]["Serie B"]
    assert [r["pts"] for r in table] == [4, 3, 3, 1] and sum(r["p"] for r in table) == 2 * len(games)
    pal = next(t for t in teams["teams"].values() if t["name"] == "Palermo")
    assert pal["form"] == "WL" and pal["avg"]["record"] == "1-0-1" and "photo" not in pal["players"][0] and not pal.get("full")
    again, _p, _b = build(replay_fetch(rec), ["Serie B"], teams, players, now)                          # rebuilt, never counted twice
    assert again["tables"]["Serie B"] == table


# ---------- v10.1: any number of legs, exactly optimal (decision 75) ----------

def _brute_any(menus, need, must=None, groups=None, mins=None):
    best = None
    n = len(menus)

    def rec(i, picks, idx):
        nonlocal best
        if i == n:
            if not picks or (must and any(f and j not in idx for j, f in enumerate(must))):
                return
            if mins and any(sum(groups[j] == g for j in idx) < lo for g, lo in mins.items()):
                return
            ch, od = math.prod(p.chance for p in picks), math.prod(p.odds for p in picks)
            if od >= need(len(picks)) and (best is None or ch > best[0]):
                best = (ch, od, len(picks))
            return
        rec(i + 1, picks, idx)
        for p in menus[i]:
            rec(i + 1, [*picks, p], [*idx, i])
    rec(0, [], [])
    return best


def test_free_number_of_legs_is_exactly_optimal_against_brute_force():
    rng = random.Random(21)
    for case in range(120):
        menus = _random_menus(rng, 5 + case % 2)
        target = [1.5, 2, 3, 5, 8, 15, 30][case % 7]
        bonus = case % 3 == 0
        need = (lambda k, t=target: t / (1 + snai_bonus_n(k))) if bonus else (lambda k, t=target: t)
        must = [i == 1 for i in range(len(menus))] if case % 5 == 0 else None
        groups = [i % 2 for i in range(len(menus))] if case % 4 == 0 else None
        mins = {0: 2} if groups else None
        slip = solve(menus, target, grid=0.004, auto_legs=True, row_target=need if bonus else None, must_use=must, groups=groups,
                     group_limits={0: (2, None)} if groups else None)
        best = _brute_any(menus, need, must, groups, mins)
        if best is None:
            assert slip is None
            continue
        assert slip is not None and slip.odds >= need(len(slip.picks)) * (1 - 1e-12)
        assert slip.chance == pytest.approx(best[0], rel=1e-9), (case, slip, best)


def snai_bonus_n(k):
    return 1.035 ** (min(k, 30) - 4) - 1 if k >= 5 else 0.0


def test_fixed_legs_are_now_exact_too_even_on_a_coarse_grid():
    rng = random.Random(8)
    for _ in range(40):
        menus = _random_menus(rng, 6)
        target = rng.uniform(3, 30)
        legs = rng.randint(2, 5)
        slip = solve(menus, target, legs=legs, grid=0.01)
        best = _brute_any(menus, lambda k, t=target, L=legs: t if k == L else float("inf"))
        if best is None:
            assert slip is None
        else:
            assert slip is not None and slip.odds >= target and slip.chance == pytest.approx(best[0], rel=1e-9)


def test_presets_choose_their_own_number_of_legs():
    rng = random.Random(3)
    now = datetime(2026, 10, 9, 10, 0, tzinfo=timezone.utc)
    matches, _ = price_feed(_synthetic_feed(rng), now, now + timedelta(days=5))
    slips = preset_slips(matches, now)
    assert slips and all(s["legs"] == len(s["picks"]) and s["odds"] >= s["target"] for s in slips)
    assert len({s["legs"] for s in slips}) >= 1 and all(1 <= s["legs"] <= 25 for s in slips)


def test_a_priced_match_the_next_pull_does_not_cover_keeps_its_prices(tmp_path):
    from scudi_slips.comps import BY_NAME
    from tools.weekly import main

    feed = _synthetic_feed(random.Random(9), n=4, comp="Serie B", day="2026-10-16")    # a Friday-night round, a week ahead
    active = {"Serie B": BY_NAME["Serie B"].odds}
    out, hist = tmp_path / "week.json", tmp_path / "history.json"
    assert main(["--out", str(out), "--history", str(hist), "--mode", "full", "--now", "2026-10-09T09:00:00Z"], get=_FakeFeed(feed, active)) == 0
    fri = json.loads(out.read_text())
    assert fri["matches"] and all(m["priced_at"].startswith("2026-10-09") for m in fri["matches"])
    fake = _FakeFeed(feed, active)
    assert main(["--out", str(out), "--history", str(hist), "--mode", "full", "--now", "2026-10-13T09:00:00Z"], get=fake) == 0   # Tuesday
    tue = json.loads(out.read_text())
    assert {m["id"] for m in tue["matches"]} == {m["id"] for m in fri["matches"]}          # kept, not dropped
    assert all(m["priced_at"].startswith("2026-10-09") for m in tue["matches"])            # with the day their prices are from
    assert next(p for p in fake.calls if p[0].endswith("/odds"))[1]["commenceTimeTo"] == "2026-10-16T06:00:00Z"   # and no credit spent on them


def test_example_prices_in_the_stored_week_are_cleaned_out_and_never_graded(tmp_path):
    """The live incident of 22 September: a real week that had kept 52 matches priced 'on 9 October' (the repository's
    sample file) and carried 16 sample slips as pending."""
    from tools.grade import weeks_of
    from tools.weekly import main, sanitize

    real = datetime(2026, 9, 22, 16, 45, tzinfo=timezone.utc)
    week = {"built_at": real.isoformat(), "matches": [
        {"id": "nl1", "competition": "Nations League", "kickoff": "2026-09-25T18:45:00+00:00", "home": "Italy", "away": "Belgium", "priced_at": real.isoformat(), "chances": {}, "estimate": {}},
        {"id": "sa1", "competition": "Serie A", "kickoff": "2026-10-10T13:00:00+00:00", "home": "Genoa", "away": "Fiorentina", "priced_at": "2026-10-09T09:00:00+00:00", "chances": {}, "estimate": {}}],
        "slips": [], "fixtures": [], "competitions": [],
        "pending": [{"built_at": "2026-10-09T09:00:00+00:00", "slips": [{"name": "Serie A", "target": 25, "picks": [{"match": "sa1"}]}], "matches": []}]}
    clean, notes = sanitize(week, datetime(2026, 9, 23, 9, 0, tzinfo=timezone.utc))
    assert [m["id"] for m in clean["matches"]] == ["nl1"] and clean["pending"] == [] and len(notes) == 2
    assert sanitize({"built_at": "2026-10-09T09:00:00+00:00", "matches": [{"id": "x"}]}, datetime(2026, 9, 23, tzinfo=timezone.utc))[0] == {}
    assert sanitize({"built_at": "2026-09-01T09:00:00+00:00", "example": True}, datetime(2026, 9, 23, tzinfo=timezone.utc))[0] == {}
    # the morning run with nothing due still rewrites the file without them
    out, hist = tmp_path / "week.json", tmp_path / "history.json"
    out.write_text(json.dumps(week))
    assert main(["--out", str(out), "--history", str(hist), "--mode", "late", "--now", "2026-09-23T09:00:00Z"], get=_FakeFeed({}, {})) == 0
    stored = json.loads(out.read_text())
    assert [m["id"] for m in stored["matches"]] == ["nl1"] and stored["pending"] == []
    # and grading never looks at a week built after the grading time, nor at a replay
    assert [w["built_at"] for w in weeks_of(week, datetime(2026, 9, 25, tzinfo=timezone.utc))] == [real.isoformat()]
    assert weeks_of(dict(week, example=True), datetime(2026, 12, 1, tzinfo=timezone.utc)) == []


def test_team_data_job_needs_no_numpy_and_stops_in_time(tmp_path):
    """Incident 2026-09-23: the team data job runs on a bare Python (no numpy or scipy) and failed at import because
    tools/teams.py loaded the whole scudi_slips package. It must import without them, and a run stops and saves before
    the GitHub job's timeout."""
    import subprocess
    import sys
    import time as _time
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    block = ("import sys, importlib.abc\n"
             "class Block(importlib.abc.MetaPathFinder):\n"
             "    def find_spec(self, name, path, target=None):\n"
             "        if name.split('.')[0] in ('numpy', 'scipy'):\n"
             "            raise ModuleNotFoundError(name)\n"
             "sys.meta_path.insert(0, Block())\n"
             f"sys.argv = ['teams.py', '--help']\n"
             f"import runpy; runpy.run_path({str(root / 'tools' / 'teams.py')!r}, run_name='__main__')\n")
    r = subprocess.run([sys.executable, "-c", block], capture_output=True, text=True, cwd=tmp_path)
    assert r.returncode == 0, r.stderr
    assert "--max-minutes" in r.stdout

    from tools.teams import Budget
    b = Budget(10**6, max_minutes=0.0005)
    assert not b.spent()
    _time.sleep(0.05)
    assert b.spent()
    assert not Budget(5).spent() and Budget(0).spent()


# ---------- decision 78: new markets, first-half model, sharp view, book spread, half-time grading ----------
from scudi_slips.matrix import HALF_RHO, HALF_SHARE, view_from  # noqa: E402
from scudi_slips.picks import CLASSIC_MENU, CORR, FULL_TIME_MENU, MASKS, NOT_OFFERED  # noqa: E402


def test_new_pick_types_settle_as_named():
    cases = {  # code: [(h, a, won)]
        "MG1-3": [(0, 0, False), (1, 0, True), (2, 1, True), (2, 2, False)], "MG2-4": [(1, 0, False), (1, 1, True), (3, 1, True), (3, 2, False)],
        "HO05": [(0, 3, False), (1, 0, True)], "HU15": [(1, 4, True), (2, 0, False)], "AU25": [(0, 2, True), (0, 3, False)],
        "HMG1-2": [(0, 1, False), (2, 5, True), (3, 0, False)], "1+O15": [(1, 0, False), (2, 0, True), (1, 1, False)],
        "X2+U35": [(1, 1, True), (0, 4, False), (2, 1, False)], "GG+O25": [(1, 1, False), (2, 1, True)], "12+MG2-4": [(2, 0, True), (1, 1, False), (5, 0, False)],
        "1H-1": [(2, 0, True), (1, 0, False)], "2H-1": [(1, 0, False), (1, 1, True)], "1H+1": [(0, 0, True), (0, 1, False)],
        "2H+1": [(0, 2, True), (0, 1, False)], "2H-2": [(2, 0, False), (1, 0, True), (0, 3, True)], "1H+2": [(0, 1, True), (0, 2, False)],
    }
    for code, rows in cases.items():
        for h, a, won in rows:
            assert settles(code, h, a) is won, (code, h, a)
    assert settles("1TO05", 0, 0, 0, 0) is False and settles("1TO05", 3, 2, 1, 0) is True
    assert settles("1TX", 2, 0, 0, 0) is True and settles("1TX2", 2, 0, 1, 0) is False
    with pytest.raises(ValueError):
        settles("1TU15", 1, 1)                          # a first-half pick needs the half-time score


def test_menus_offer_only_checked_types():
    assert CLASSIC_MENU <= SLIP_MENU and not (SLIP_MENU & NOT_OFFERED) and "NG" in NOT_OFFERED
    assert all(not PICKS[c].half for c in FULL_TIME_MENU) and {"1TO05", "1TU15"} <= SLIP_MENU - FULL_TIME_MENU
    assert all(c in CORR for c in SLIP_MENU - CLASSIC_MENU)     # every new offered type carries its fitted correction
    assert len(SLIP_MENU) == 83


def test_new_chances_are_consistent_with_the_matrix():
    for probs in [(0.5, 0.27, 0.23, 0.52), (0.72, 0.18, 0.10, 0.60), (0.20, 0.30, 0.50, 0.40), (0.34, 0.33, 0.33, 0.45)]:
        v = fit_market(*probs)
        ch = {c: PICKS[c].chance(v) for c in PICKS}
        assert all(0 < p < 1 for p in ch.values())
        for c, pt in PICKS.items():   # every mask agrees with its settle rule
            assert all(MASKS[c][h, a] == bool(pt.wins(h, a)) for h in range(6) for a in range(6))
            if pt.parts:
                assert ch[c] <= min(ch[x] for x in pt.parts) + 1e-12
        assert ch["MG1-3"] < ch["MG1-4"] < ch["MG1-5"] < ch["MG1-6"]
        assert abs(ch["HO05"] - float(v.matrix[1:, :].sum())) < 0.02        # a light correction only
        half = score_matrix(v.lh * HALF_SHARE, v.la * HALF_SHARE, HALF_RHO)
        assert abs(float(half[0, 0]) - (1 - float(half.sum()) + float(half[0, 0]))) < 1 and abs(half.sum() - 1) < 1e-9
        assert ch["1TO05"] < ch["O15"] and ch["1TU15"] > ch["U25"] - 0.3


def test_view_from_rebuilds_the_same_matrix():
    v = fit_market(0.48, 0.27, 0.25, 0.51)
    w = view_from(v.lh, v.la, v.rho)
    assert abs(w.p_home - 0.48) < 1e-4 and abs(w.p_over25 - 0.51) < 1e-4
    assert all(abs(PICKS[c].chance(v) - PICKS[c].chance(w)) < 2e-4 for c in SLIP_MENU)


def test_feed_carries_sharp_view_spread_and_new_estimates():
    from scudi_slips.feed import ASSUMED_MARGIN, assumed_price
    now = datetime(2026, 10, 9, 10, 0, tzinfo=timezone.utc)
    matches, _ = price_feed(_sample(), now, datetime(2026, 10, 13, 0, 0, tzinfo=timezone.utc))
    genoa, inter = matches
    assert set(genoa.sharp) == {"1", "X", "2", "O25"} and abs(sum(genoa.sharp[k] for k in "1X2") - 1) < 1e-9
    assert set(genoa.spread) >= {"1", "X", "2", "1X", "X2", "12", "O25", "U25"} and all(0 <= x < 0.2 for x in genoa.spread.values())
    for code in ("MG1-3", "1X+U35", "1H-1", "HO05", "1TU15"):
        assert genoa.estimate[code] == assumed_price(genoa.chances[code], PICKS[code].group)
        assert genoa.estimate[code] * genoa.chances[code] < 1 / (1 + ASSUMED_MARGIN[PICKS[code].group]) + 0.01
    assert set(inter.chances) == {"1", "X", "2", "1X", "X2", "12"}   # no totals: only the result picks
    assert -0.3 <= genoa.rho <= 0.2


def test_weekly_snapshot_keeps_the_matrix_and_the_sharp_view():
    from tools.grade import closing_chance
    from tools.weekly import add_snapshots, match_record
    now = datetime(2026, 10, 9, 10, 0, tzinfo=timezone.utc)
    matches, _ = price_feed(_sample(), now, datetime(2026, 10, 13, 0, 0, tzinfo=timezone.utc))
    rec = match_record(matches[0])
    assert "rho" in rec and rec["sharp"] and rec["spread"]
    hist = add_snapshots({}, [rec], now)
    snap = hist[rec["id"]]["snaps"][0]
    assert snap["x"] == [rec["lh"], rec["la"], rec["rho"]] and snap["s"] == rec["sharp"]
    assert closing_chance(snap, "1") == snap["p"]["1"]
    assert abs(closing_chance(snap, "MG1-3") - rec["chances"]["MG1-3"]) < 2e-3


def _espn_event(goals, final=(2, 1), home_id="10", away_id="20"):
    return {"competitions": [{"status": {"type": {"completed": True, "name": "STATUS_FULL_TIME"}},
                              "competitors": [{"homeAway": "home", "team": {"id": home_id}, "score": str(final[0])},
                                              {"homeAway": "away", "team": {"id": away_id}, "score": str(final[1])}],
                              "details": [{"scoringPlay": True, "team": {"id": t}, "clock": {"displayValue": c}, "ownGoal": og} for t, c, og in goals]}]}


def test_half_time_score_from_espn_goal_minutes():
    from tools.grade import espn_final, espn_half
    ev = _espn_event([("10", "14'", False), ("20", "45'+3'", False), ("10", "46'", False)])
    assert espn_final(ev) == (2, 1) and espn_half(ev, (2, 1)) == (1, 1)            # 45'+3' is still the first half
    og = _espn_event([("10", "20'", True), ("10", "70'", False)], final=(1, 1))    # an own goal credited to the scorer's club
    assert espn_half(og, (1, 1)) == (0, 1)
    assert espn_half(_espn_event([("10", "20'", False)], final=(2, 0)), (2, 0)) is None   # goals missing: not guessed
    assert espn_half(_espn_event([], final=(0, 0)), (0, 0)) == (0, 0)


def test_first_half_legs_wait_for_the_half_time_score():
    week = {"built_at": "2026-10-09T10:00:00+00:00", "matches": [{"id": "m1", "competition": "Serie A", "home": "A", "away": "B"}],
            "slips": [{"name": "t", "target": 2, "legs": 1, "chance": 0.7, "odds": 1.4, "bonus": 0, "picks": [{"match": "m1", "code": "1TO05", "chance": 0.7, "odds": 1.4}]}]}
    now = datetime(2026, 10, 12, tzinfo=timezone.utc)
    assert grade(week, {"m1": (2, 0)}, {}, now).get("slips", []) == []            # final known, half-time not: waits
    rec = grade(week, {"m1": (2, 0, 1, 0)}, {}, now)
    assert rec["slips"][0]["landed"] is True and rec["slips"][0]["leg_results"][0]["half"] == "1-0"


def test_lab_data_rows_are_compact_and_complete():
    import pandas as pd

    from tools.lab_data import EPOCH, build
    df = pd.DataFrame([
        {"Division": "I1", "date": pd.Timestamp("2024-09-01"), "season": 2024, "HomeTeam": "Inter", "AwayTeam": "Milan", "FTHome": 2, "FTAway": 1,
         "HTHome": 1, "HTAway": 1, "OddHome": 1.8, "OddDraw": 3.6, "OddAway": 4.5, "Over25": 1.7, "Under25": 2.1, "lh": 1.61, "la": 1.02, "rho": -0.05, "fit_err": 0.0},
        {"Division": "I1", "date": pd.Timestamp("2026-09-01"), "season": 2026, "HomeTeam": "Roma", "AwayTeam": "Lazio", "FTHome": 0, "FTAway": 0,
         "HTHome": 0, "HTAway": 0, "OddHome": 2.2, "OddDraw": 3.2, "OddAway": 3.4, "Over25": 2.0, "Under25": 1.8, "lh": 1.2, "la": 1.0, "rho": -0.05, "fit_err": 0.0},
        {"Division": "E0", "date": pd.Timestamp("2025-01-11"), "season": 2024, "HomeTeam": "Arsenal", "AwayTeam": "Spurs", "FTHome": 3, "FTAway": 0,
         "HTHome": None, "HTAway": None, "OddHome": 1.5, "OddDraw": 4.4, "OddAway": 6.5, "Over25": 1.6, "Under25": 2.3, "lh": 2.0, "la": 0.8, "rho": -0.04, "fit_err": 0.0}])
    out = build(df)
    assert out["seasons"] == ["2023-24", "2024-25", "2025-26"] and len(out["matches"]) == 2       # 2026-27 stays sealed
    inter = out["matches"][0]
    assert inter[0] == (pd.Timestamp("2024-09-01").date() - EPOCH).days and out["comps"][inter[1]] == "Serie A"
    assert out["teams"][inter[2]] == "Inter" and inter[4:8] == [2, 1, 1, 1] and inter[8:11] == [1610, 1020, -50] and inter[11] == 180
    assert out["matches"][1][6:8] == [-1, -1] and len(inter) == len(out["fields"])                 # no half-time score: -1


def test_page_engine_in_node():
    """The page's own slip maths (index.html), checked in Node: exact optimiser against brute force for every objective,
    the trade-off, prudence and signals weights, learned corrections, first-half settlement and the SNAI reader."""
    import shutil
    import subprocess
    node = shutil.which("node")
    if not node:
        pytest.skip("node is not installed")
    r = subprocess.run([node, "tests/js/engine.test.js"], capture_output=True, text=True, timeout=300)
    assert r.returncode == 0, r.stdout + r.stderr


# ---------- closing line from football-data.co.uk (decision 85) ----------
def _fd_sample() -> str:
    from pathlib import Path

    return Path(__file__).with_name("football_data_sample.csv").read_text(encoding="utf-8")


def test_closing_rows_are_matched_by_names_and_day_and_fitted_to_the_closing_market():
    from scudi_slips.closing import ClosingSource, closing_prices, closing_view, find_row, parse_csv, season_code, xg

    rows = parse_csv(_fd_sample())
    assert len(rows) == 9 and rows[0]["Div"] == "I1"
    ko = datetime(2026, 9, 20, 18, 45, tzinfo=timezone.utc)                        # 19:45 UK, the file's own time
    row = find_row(rows, "AC Milan", "Lecce", ko)                                   # the odds feed's spellings
    assert row and row["HomeTeam"] == "Milan" and row["FTHG"] == "3"
    assert find_row(rows, "Milan", "Lecce", ko) is row and find_row(rows, "Inter Milan", "AS Roma", ko) is None      # wrong way round
    assert find_row(rows, "AS Roma", "Inter Milan", datetime(2026, 9, 19, 16, 0, tzinfo=timezone.utc))["AwayTeam"] == "Inter"
    assert find_row(rows, "AC Milan", "Lecce", ko + timedelta(days=3)) is None    # another day: not this match
    assert find_row(rows, "AC Milan", "Lecce", ko - timedelta(hours=20)) is row    # late kick-off read on the UK day after
    prices, label = closing_prices(row)
    assert label == "betfair" and prices == {"1": 1.26, "X": 6.8, "2": 16.0, "O25": 1.63, "U25": 2.56}
    view, label2, _ = closing_view(row)
    assert label2 == "betfair" and abs(view.p_home + view.p_draw + view.p_away - 1) < 1e-9 and view.p_home > 0.75
    assert view.fit_error < 0.01 and 0.55 < view.p_over25 < 0.65
    assert xg(row) == (2.19, 0.21)
    # no Betfair columns: the market average, then Bet365
    r2 = {k: v for k, v in row.items() if not k.startswith("BFEC")}
    assert closing_prices(r2)[1] == "average"
    r3 = {k: v for k, v in r2.items() if not k.startswith("AvgC")}
    assert closing_prices(r3)[1] == "bet365"
    assert closing_prices({k: v for k, v in r3.items() if not k.startswith("B365C")}) is None
    assert season_code(datetime(2026, 9, 20)) == "2627" and season_code(datetime(2027, 5, 1)) == "2627" and season_code(datetime(2027, 8, 1)) == "2728"
    calls = []

    def fetch(url):
        calls.append(url)
        if "/I1.csv" not in url:
            raise OSError("boom")
        return _fd_sample()
    src = ClosingSource(fetch)
    assert src.covers("Serie A") and not src.covers("Champions League") and not src.covers("Nations League")
    assert src.find("Serie A", "AC Milan", "Lecce", ko)["HomeTeam"] == "Milan"
    assert src.find("Serie A", "Juventus", "Atalanta", ko)["FTAG"] == rows[7]["FTAG"]
    assert src.find("Premier League", "Arsenal", "Chelsea", ko) is None and src.notes and "Premier League" in src.notes[0]
    assert src.find("Premier League", "Arsenal", "Chelsea", ko) is None and len(src.notes) == 1   # asked once per run
    assert len([u for u in calls if "I1" in u]) == 1 and calls[0].endswith("/2627/I1.csv")


def test_graded_legs_use_the_real_closing_price_where_the_files_carry_the_match():
    from scudi_slips.closing import ClosingSource
    from scudi_slips.devig import power_devig
    from tools.grade import fill_pending, grade, summarise

    def fetch(url):
        if "/I1.csv" in url:
            return _fd_sample()
        raise OSError("not there")
    ko = "2026-09-20T18:45:00+00:00"
    ko2 = "2026-09-20T16:00:00+00:00"
    week = {"built_at": "2026-09-18T09:00:00+00:00",
            "matches": [{"id": "m1", "competition": "Serie A", "kickoff": ko, "home": "AC Milan", "away": "Lecce"},
                        {"id": "m2", "competition": "Nations League", "kickoff": ko2, "home": "Italy", "away": "Estonia"},
                        {"id": "m3", "competition": "Premier League", "kickoff": ko2, "home": "Arsenal", "away": "Chelsea"}],
            "slips": [{"name": "Test", "target": 5, "legs": 3, "chance": 0.2, "odds": 5.1, "bonus": 0.0,
                       "picks": [{"match": "m1", "code": "1", "chance": 0.74, "odds": 1.30}, {"match": "m2", "code": "O25", "chance": 0.55, "odds": 1.8},
                                 {"match": "m3", "code": "X2", "chance": 0.6, "odds": 1.6}]}]}
    hist = {"m1": {"kickoff": ko, "snaps": [{"t": "2026-09-20T09:00:00+00:00", "p": {"1": 0.70}}]},
            "m2": {"kickoff": ko2, "snaps": [{"t": "2026-09-20T09:00:00+00:00", "p": {"O25": 0.52}}]},
            "m3": {"kickoff": ko2, "snaps": [{"t": "2026-09-20T09:00:00+00:00", "p": {"X2": 0.58}}]}}
    now = datetime(2026, 9, 22, 8, 0, tzinfo=timezone.utc)
    rec = grade(week, {"m1": (3, 0), "m2": (2, 1), "m3": (1, 1)}, {}, now, hist, ClosingSource(fetch))
    legs = {leg["match"]: leg for leg in rec["slips"][0]["leg_results"]}
    close_home = power_devig([1.26, 6.8, 16.0])[0]
    assert legs["m1"]["close_source"] == "close:betfair" and abs(legs["m1"]["close_chance"] - close_home) < 0.01
    assert legs["m1"]["pull_chance"] == 0.70 and legs["m1"]["pull_clv"] == round(1.30 * 0.70 - 1, 4)
    assert abs(legs["m1"]["clv"] - (1.30 * legs["m1"]["close_chance"] - 1)) < 1e-3 and legs["m1"]["close_odds"] == 1.26 and legs["m1"]["xg"] == [2.19, 0.21]
    assert legs["m2"]["close_source"] == "last_pull" and legs["m2"]["close_chance"] == 0.52 and "xg" not in legs["m2"]
    assert legs["m3"]["close_source"] == "pending" and legs["m3"]["close_chance"] == 0.58 and legs["m3"]["kickoff"] == ko2   # file failed: waits
    assert rec["summary"]["closing"] == {"legs": 3, "close": 1, "pending": 1, "last_pull": 1,
                                         "avg_clv": round((legs["m1"]["clv"] + legs["m2"]["clv"] + legs["m3"]["clv"]) / 3, 4),
                                         "avg_clv_close": round(legs["m1"]["clv"], 4)}
    # a later run: the Premier League file now carries the match -> the pending leg is filled in
    def fetch2(url):
        if "/E0.csv" in url:
            return _fd_sample().replace("Milan,Lecce", "Arsenal,Chelsea").replace("20/09/2026,19:45", "20/09/2026,17:00")
        return fetch(url)
    changed = fill_pending(rec, ClosingSource(fetch2), now + timedelta(days=2))
    rec = summarise(rec)
    legs = {leg["match"]: leg for leg in rec["slips"][0]["leg_results"]}
    assert changed == 1 and legs["m3"]["close_source"] == "close:betfair" and legs["m3"]["pull_chance"] == 0.58
    assert legs["m3"]["close_chance"] != 0.58 and rec["summary"]["closing"]["close"] == 2 and rec["summary"]["closing"]["pending"] == 0
    # a pending leg older than 12 days settles on the pull when the file is there without the match; while the file cannot be
    # downloaded at all it keeps waiting, whatever its age
    legs["m3"]["close_source"], legs["m3"]["close_chance"], legs["m3"]["clv"] = "pending", 0.58, legs["m3"]["pull_clv"]
    assert fill_pending(rec, ClosingSource(fetch), now + timedelta(days=13)) == 0 and legs["m3"]["close_source"] == "pending"
    assert fill_pending(rec, ClosingSource(lambda url: _fd_sample()), now + timedelta(days=13)) == 1 and legs["m3"]["close_source"] == "last_pull"
    # no source at all (replay / --no-closing): every leg is "last_pull"
    plain = grade(week, {"m1": (3, 0), "m2": (2, 1), "m3": (1, 1)}, {}, now, hist)
    assert {leg["close_source"] for leg in plain["slips"][0]["leg_results"]} == {"last_pull"}


# ---------- Transfermarkt depth (decision 86) ----------
def test_transfermarkt_file_is_compact_and_players_match_espn_by_birthday_and_name():
    import json
    from pathlib import Path

    from tools.teams import enrich, load_transfermarkt, tm_match
    from tools.transfermarkt import compact

    rows = [{"player_id": "406625", "name": "Lautaro Martínez", "last_season": "2026", "current_club_domestic_competition_id": "IT1", "date_of_birth": "1997-08-22 00:00:00",
             "foot": "right", "height_in_cm": "174", "position": "Attack", "sub_position": "Centre-Forward", "market_value_in_eur": "85000000",
             "highest_market_value_in_eur": "110000000", "contract_expiration_date": "2029-06-30 00:00:00", "current_club_name": "Inter Milan"},
            {"player_id": "1", "name": "Old Timer", "last_season": "2015", "current_club_domestic_competition_id": "IT1", "date_of_birth": "1980-01-01 00:00:00"},
            {"player_id": "2", "name": "Far Away", "last_season": "2026", "current_club_domestic_competition_id": "BRA1", "date_of_birth": "2000-01-01 00:00:00"},
            {"player_id": "3", "name": "Marco Rossi", "last_season": "2026", "current_club_domestic_competition_id": "IT1", "date_of_birth": "1997-08-22 00:00:00", "foot": "left"},
            {"player_id": "4", "name": "Luca Rossi", "last_season": "2026", "current_club_domestic_competition_id": "IT1", "date_of_birth": "1997-08-22 00:00:00", "foot": "both"}]
    kept = compact(rows)
    assert [p["id"] for p in kept] == [406625, 3, 4]                       # old seasons and other continents left out
    assert kept[0] == {"id": 406625, "n": "Lautaro Martínez", "dob": "1997-08-22", "foot": "right", "h": 174, "pos": "Attack", "sub": "Centre-Forward",
                       "v": 85000000, "pk": 110000000, "c": "2029-06-30", "comp": "IT1"}
    path = Path("/tmp") / "tm_test.json"
    path.write_text(json.dumps({"as_of": "2026-07-06", "players": kept}))
    tm = load_transfermarkt(path)
    assert tm["n"] == 3 and tm["as_of"] == "2026-07-06"
    assert tm_match({"name": "Lautaro Martinez", "dob": "1997-08-22"}, tm)["id"] == 406625         # accent dropped, same birthday
    assert tm_match({"name": "L. Martínez", "short": "L. Martínez", "dob": "1997-08-22"}, tm)["id"] == 406625
    assert tm_match({"name": "Lautaro Martinez", "dob": "1997-08-23"}, tm) is None               # a different birthday never matches
    assert tm_match({"name": "Rossi", "dob": "1997-08-22"}, tm) is None                           # two Rossi born that day: none chosen
    assert tm_match({"name": "Marco Rossi", "dob": "1997-08-22"}, tm)["id"] == 3
    assert tm_match({"name": "Somebody Else", "dob": "1997-08-22"}, tm) is None
    squad = [{"id": 9, "name": "Lautaro Martínez", "dob": "1997-08-22", "tm": {"v": 1}}, {"id": 10, "name": "Nobody", "dob": "1999-01-01", "tm": {"v": 2}}]
    assert enrich(squad, tm) == 1
    assert squad[0]["tm"] == {"v": 85000000, "pk": 110000000, "foot": "right", "c": "2029-06-30", "sub": "Centre-Forward", "h": 174, "id": 406625}
    assert tm_match({"name": "Juan de Rossi", "dob": "1997-08-22"}, tm) is None                       # a particle is not a shared name
    assert "tm" not in squad[1]                                                                   # a stale match is removed, never kept
    assert enrich(squad, None) == 0 and load_transfermarkt(Path("/tmp/does-not-exist.json")) is None


def test_transfermarkt_depth_reaches_most_of_a_real_big_league_squad():
    """On the real lab/transfermarkt.json (when present) and ESPN's real Serie A rosters recorded in data/espn_teams.json's
    season, four of five big-league players were matched on 2026-10-05; the test guards the matcher against regressions
    with a lower bar on a stored slice of real names."""
    from pathlib import Path

    from tools.teams import load_transfermarkt, tm_match

    tm = load_transfermarkt()
    if not tm:
        import pytest
        pytest.skip("lab/transfermarkt.json not built in this checkout")
    real = [("Lautaro Martínez", "1997-08-22"), ("Nicolò Barella", "1997-02-07"), ("Mike Maignan", "1995-07-03"), ("Dusan Vlahovic", "2000-01-28"),
            ("Khvicha Kvaratskhelia", "2001-02-12"), ("Erling Haaland", "2000-07-21"), ("Kylian Mbappé", "1998-12-20"), ("Harry Kane", "1993-07-28"),
            ("Jude Bellingham", "2003-06-29"), ("Lamine Yamal", "2007-07-13")]
    hits = [tm_match({"name": n, "dob": d}, tm) for n, d in real]
    assert sum(1 for h in hits if h) >= 8 and all(h is None or h.get("v") for h in hits)
    assert Path("lab/transfermarkt.json").stat().st_size < 2_500_000


# ---------- the live model (decision 87) ----------
def test_live_model_file_is_sane_and_the_chain_hands_back_the_pre_match_goals_at_kickoff():
    from scudi_slips.live import chance, expected_goals_at_kickoff, model, steps

    m = model()
    assert len(m["bins"]) == 18 and all(0.5 < f < 1.5 for f in m["bins"]) and m["bins"][0] < m["bins"][-1]      # a slow start
    assert m["stoppage"]["1"]["len"] < m["stoppage"]["2"]["len"] and m["red"]["own"] < 1 < m["red"]["opp"]
    assert m["state"]["trail1"] > 1 and m["state"]["trail2"] > m["state"]["trail1"] and m["fit"]["matches"] > 1000
    eh, ea = expected_goals_at_kickoff(1.5, 1.1)
    assert abs(eh + ea - 2.6) < 0.03                                              # the scale keeps the total honest
    assert len(steps(False, 0)) == 45 + 1 + 45 + 1 and len(steps(True, 60)) == 30 + 1 and len(steps(False, 30, True)) == 15 + 1
    assert steps(False, 46)[0] == (18, pytest.approx(max(0.3, m["stoppage"]["1"]["len"] - 1)))                 # in first-half stoppage
    p0 = chance("1", 1.5, 1.0, 0, 0, 0, False)
    assert 0.44 < p0 < 0.50
    assert chance("1", 1.5, 1.0, 1, 0, 90, True) > 0.9 > chance("1", 1.5, 1.0, 0, 1, 60, True) > chance("1", 1.5, 1.0, 0, 1, 85, True)
    assert chance("1", 1.5, 1.0, 0, 1, 60, True, reds=(0, 1)) > 2 * chance("1", 1.5, 1.0, 0, 1, 60, True)       # the other side a man short
    assert chance("1", 1.5, 1.0, 0, 1, 60, True, reds=(1, 0)) < chance("1", 1.5, 1.0, 0, 1, 60, True)
    assert chance("1", 1.5, 1.0, 2, 0, 90, True, finished=True) == 1.0 and chance("X", 1.5, 1.0, 2, 0, 90, True, finished=True) == 0.0
    assert chance("1TO05", 1.5, 1.0, 0, 0, 30, False) < chance("1TO05", 1.5, 1.0, 0, 0, 10, False) < chance("O15", 1.5, 1.0, 0, 0, 10, False)
    assert chance("1TO05", 1.5, 1.0, 1, 0, 30, False, hh=1, ha=0) == 1.0 and chance("1TO05", 1.5, 1.0, 0, 0, 60, True) == 0.0


def test_page_live_chance_equals_python_live_model():
    """index.html's inplay and scudi_slips.live.chance are the same chain: checked on random scores, minutes, halves, red cards
    and pick types (full time and first half), to 1e-9."""
    import json
    import shutil
    import subprocess

    from scudi_slips.live import chance
    from scudi_slips.picks import SLIP_MENU

    node = shutil.which("node")
    if not node:
        pytest.skip("node is not installed")
    rng = random.Random(7)
    codes = sorted(SLIP_MENU)
    cases = []
    for _ in range(60):
        second = rng.random() < 0.5
        minute = rng.randint(46, 93) if second else rng.randint(0, 47)
        cases.append({"code": rng.choice(codes), "lh": round(rng.uniform(0.6, 2.6), 3), "la": round(rng.uniform(0.5, 2.0), 3), "h": rng.randint(0, 3), "a": rng.randint(0, 3),
                      "minute": minute, "period": 2 if second else 1, "rh": int(rng.random() < 0.15), "ra": int(rng.random() < 0.15), "ht": False})
    cases.append({"code": "O25", "lh": 1.4, "la": 1.1, "h": 1, "a": 1, "minute": 45, "period": 1, "rh": 0, "ra": 0, "ht": True})
    want = []
    for c in cases:
        second = c["period"] >= 2 or (c["minute"] > 45 and c["period"] != 1 and not c["ht"])
        hh, ha = (c["h"], c["a"]) if (second or c["ht"]) else (None, None)
        want.append(chance(c["code"], c["lh"], c["la"], c["h"], c["a"], c["minute"], second, False, hh, ha, (c["rh"], c["ra"]), c["ht"]))
    script = """
const fs=require('fs'),vm=require('vm');const html=fs.readFileSync('index.html','utf8');
const a=html.indexOf('/* ===== Scudi slip maths'), b=html.indexOf("if (typeof module !== 'undefined') module.exports = Scudi;");
const ctx={module:{},console}; vm.runInNewContext(html.slice(a,b)+'\\nthis.Scudi = Scudi;',ctx); const S=ctx.Scudi;
const cases=JSON.parse(process.argv[1]);
console.log(JSON.stringify(cases.map(c => { const second = c.period >= 2 || (c.minute > 45 && c.period !== 1 && !c.ht); const hh = (second || c.ht) ? c.h : null, ha = (second || c.ht) ? c.a : null;
  return S.inplay(c.code, c.lh, c.la, c.h, c.a, c.minute, false, hh, ha, { period: c.period, ht: c.ht, rh: c.rh, ra: c.ra }); })));
"""
    r = subprocess.run([node, "-e", script, json.dumps(cases)], capture_output=True, text=True, timeout=120)
    assert r.returncode == 0, r.stderr
    got = json.loads(r.stdout)
    assert len(got) == len(want) and max(abs(g - w) for g, w in zip(got, want)) < 1e-9
    assert any(0 < w < 1 for w in want) and sum(1 for c, w in zip(cases, want) if c["rh"] or c["ra"]) > 5


def test_graded_matches_leave_their_goal_and_red_card_minutes_for_the_live_model():
    import json
    from pathlib import Path

    from tools.grade import espn_finals, espn_reds, timeline

    evs = json.loads((Path(__file__).parent / "js" / "espn_live_sample.json").read_text())
    fio = next(e for e in evs if e["name"] == "Napoli at Fiorentina")
    comp = fio["competitions"][0]
    comp["details"].append({"redCard": True, "scoringPlay": False, "clock": {"displayValue": "77'"}, "team": {"id": comp["competitors"][1]["team"]["id"]}})
    assert espn_reds(fio) == [(comp["competitors"][1]["homeAway"], 77)]
    m = {"id": "m1", "competition": "Serie A", "kickoff": fio["date"].replace("Z", "+00:00"), "home": "Fiorentina", "away": "Napoli"}
    tl = timeline(m, fio, (1, 1))
    assert tl["ft"] == [1, 1] and len(tl["goals"]) == 2 and all(g[0] in "ha" and 0 < g[1] <= 95 for g in tl["goals"]) and tl["reds"] == [[comp["competitors"][1]["homeAway"][0], 77]]
    tls = {}
    finals, _notes = espn_finals(lambda url: {"events": [fio]}, [m], {"Serie A": "ita.1"}, tls)
    assert finals["m1"][:2] == (1, 1) and tls["m1"] == tl


def test_extension_download_is_the_extension_folder():
    """scudi-snai-extension.zip (the site's download, decision 91) is rebuilt from extension/ whenever a file changes."""
    import subprocess
    import sys
    root = Path(__file__).resolve().parents[1]
    r = subprocess.run([sys.executable, "tools/pack_extension.py", "--check"], cwd=root, capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr


# ---------- automatic SNAI prices (decision 92) ----------
def test_snai_feed_logic_in_node():
    """The snai-pull function's pure part: odss-api records to SNAI's codes, SNAI's events to Scudi's matches, the
    request planner over a simulated month (quota kept, nights skipped, pre-match gaps under an hour)."""
    import shutil
    import subprocess
    node = shutil.which("node")
    if not node:
        pytest.skip("node is not installed")
    r = subprocess.run([node, "tests/js/feed.test.mjs"], capture_output=True, text=True, timeout=300)
    assert r.returncode == 0, r.stdout + r.stderr


def test_snai_feed_end_to_end_locally():
    """The real Edge Function under Deno against the real migration on a local Postgres, with odss-api and Supabase's
    endpoints served by tests/feed_local.py. Runs only where SCUDI_PG names a Postgres socket directory (port 55432)."""
    import os
    import shutil
    import subprocess
    import sys
    pg = os.environ.get("SCUDI_PG")
    if not pg or not shutil.which("deno"):
        pytest.skip("set SCUDI_PG to a local Postgres 16 socket directory, with Deno installed")
    root = Path(__file__).resolve().parents[1]
    r = subprocess.run([sys.executable, "tests/feed_local.py", "--pg", pg], cwd=root, capture_output=True, text=True, timeout=300)
    assert r.returncode == 0, r.stdout[-3000:] + r.stderr[-2000:]


def test_snai_feed_store_is_private():
    """The migration's promises, read in its text: row-level security on every table, reading only for the owner, the
    function's calls closed to the site's keys, and no key or price ever in the repository."""
    root = Path(__file__).resolve().parents[1]
    sql = (root / "supabase/migrations/20261006120000_snai_feed.sql").read_text()
    for t in ("owners", "book_events", "feed_state", "feed_log"):
        assert f"alter table public.{t} enable row level security;" in sql
    assert sql.count("using ((select public.is_owner()))") == 3
    assert "from public, anon, authenticated;\ngrant execute on function public.feed_load(text), public.feed_claim(), public.feed_tick(jsonb), public.feed_save(jsonb) to service_role;" in sql
    fn = (root / "supabase/functions/snai-pull/index.ts").read_text()
    assert "Deno.env.get('ODSS_API_KEY')" in fn and "x-api-key" in fn
    for p in [*root.joinpath("supabase").rglob("*"), root / "index.html"]:
        if p.is_file():
            txt = p.read_text(errors="ignore")
            assert "odss_live_" not in txt.replace("odss_live_…", ""), p   # no odss-api key anywhere
            assert "sb_secret_" not in txt.replace("'sb_'", "").replace("sb_secret_…", ""), p


def test_dashboard_function_is_the_two_file_function():
    """supabase/dashboard/snai-pull.ts (one file, for Supabase's dashboard editor) is rebuilt whenever the function changes."""
    import subprocess
    import sys
    root = Path(__file__).resolve().parents[1]
    r = subprocess.run([sys.executable, "tools/pack_function.py", "--check"], cwd=root, capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
