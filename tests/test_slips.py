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
