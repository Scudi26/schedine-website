"""Choose one pick per match so the slip reaches the target multiplier with the best chance of landing.

Maximise  sum(log chance)  subject to  sum(log odds) >= log(target),  one pick per used match,
an exact number of legs, and optional rules per group of matches (a group is usually a league):
"at least 5 legs from Serie A", "at most 3 legs per league".

Solved by dynamic programming over a fine grid of log-odds, in two passes:
  1. each leg's log-odds rounded DOWN to the grid -> every slip found truly reaches the target (safe pass);
  2. rounded to the NEAREST grid point -> can find slips the safe pass just misses; its answer is kept
     only if its exact combined odds really reach the target and its chance is higher.
On real rounds (grid 0.001) the safe pass alone gives up about 0.3% of the hit chance on average against
a 20-times finer grid; the second pass recovers most of that. A returned slip ALWAYS reaches the target.

Exactness (decision 75): a third pass rounds every price UP. It can only overstate what is reachable, so its best
chance is an upper bound; when its slip really reaches the target it is the true optimum, otherwise the grid is made
finer (while the work stays small) until the slip found is within 0.01% of the bound. A last exact polish tries every
single-leg change. The number of legs can be free (auto_legs): any number up to `legs`, the best one wins, and
row_target(k) lets the target depend on the number of legs (SNAI's bonus counted toward it).
"""

from __future__ import annotations

import math
from collections.abc import Callable, Hashable, Mapping, Sequence
from dataclasses import dataclass

import numpy as np

from .picks import Pick

_NEG = -1e18


@dataclass(frozen=True)
class Slip:
    picks: tuple[Pick, ...]
    chance: float  # chance that every leg wins (legs are different matches: treated as independent)
    odds: float    # combined odds = product of the leg prices


def _step(src: np.ndarray, options: Sequence[Pick], grid: float, top: int, nearest):
    """Best value reachable by adding ONE pick from this match to every state of `src` (rows = legs used)."""
    rows, width = src.shape
    best = np.full(src.shape, _NEG)
    choice = np.full(src.shape, -1, dtype=np.int16)
    prev = np.zeros(src.shape, dtype=np.int32)
    cols = np.arange(width)
    row_idx = np.arange(rows - 1)
    for j, pick in enumerate(options):
        if pick.odds <= 1 or not (0 < pick.chance < 1):
            raise ValueError(f"bad pick {pick}")
        steps = math.log(pick.odds) / grid
        w = min(top, math.ceil(steps - 1e-9) if nearest == 2 else round(steps) if nearest else math.floor(steps + 1e-9))
        v = math.log(pick.chance)
        cand = src[:-1, : width - w] + v                  # lands exactly on bucket b + w
        dest = best[1:, w:]
        better = cand > dest
        dest[better] = cand[better]
        choice[1:, w:][better] = j
        prev[1:, w:][better] = np.broadcast_to(cols[: width - w], cand.shape)[better]
        if w > 0:                                          # overshoots: past the target counts as "reached"
            tail = src[:-1, width - w:]
            arg = tail.argmax(axis=1)
            val = tail[row_idx, arg] + v
            better = val > best[1:, top]
            best[1:, top][better] = val[better]
            choice[1:, top][better] = j
            prev[1:, top][better] = (width - w + arg)[better]
    return best, choice, prev


def solve(menus: Sequence[Sequence[Pick]], target: float, legs: int | None = None, grid: float = 0.001,
          must_use: Sequence[bool] | None = None, groups: Sequence[Hashable] | None = None,
          group_limits: Mapping[Hashable, tuple[int, int | None]] | None = None,
          default_group_max: int | None = None, refine: bool = True, auto_legs: bool = False,
          row_target: Callable[[int], float] | None = None) -> Slip | None:
    """menus[i] = usable picks for match i (an empty menu means the match cannot be used).

    legs            how many matches to use (default: all of them); with auto_legs, the most it may use
    must_use[i]     True forces match i into the slip (locked picks)
    groups[i]       label of match i (its league); needed for the two rules below
    group_limits    {label: (min legs, max legs or None)}
    default_group_max  cap on legs from any group without its own entry ("at most 3 per league")
    refine          also run the nearest-rounding pass and the exactness check (see the module note)
    auto_legs       the number of legs is free: 1 to `legs` (default: floor(ln target / ln 1.25) + 1, capped by the matches)
    row_target      with auto_legs: the target for a slip of k legs (default: `target` for every k)
    Returns None when no combination satisfies everything.
    """
    n = len(menus)
    if auto_legs:
        usable = sum(1 for m in menus if m)
        cap = legs if legs is not None else math.floor(math.log(target) / math.log(1.25)) + 1 + sum(bool(f) for f in (must_use or []))
        legs = min(cap, usable, n)
        if legs < 1:
            return None
    need = (lambda k: row_target(k)) if (auto_legs and row_target) else (lambda k: target)

    def reaches(slip):
        return slip is not None and slip.odds >= need(len(slip.picks)) * (1 - 1e-12)

    def better(a, b):
        return a if reaches(a) and (b is None or a.chance > b.chance) else b

    def once(mode, g):
        return _solve_once(menus, target, legs, g, must_use, groups, group_limits, default_group_max, mode, auto_legs, row_target)

    best = once(False, grid)
    if refine:
        best = better(once(True, grid), best)
        g, picks_n = grid, sum(len(m) for m in menus)
        for _ in range(8):
            up = once(2, g)
            if up is None:
                break
            if reaches(up):
                best = better(up, best)
                break
            if best is not None and (up.chance - best.chance) / up.chance < 1e-4:
                break
            # a grid fine enough that this slip (just under its target) can no longer pass for one that reaches it
            short = math.log(need(len(up.picks))) - math.log(up.odds)
            g_next = min(g / 3, 0.9 * short / (len(up.picks) + 1))
            if ((legs or n) + 1) * math.ceil(math.log(target) / g_next) * max(picks_n, 1) > 3e7:
                break
            g = g_next
            best = better(once(False, g), best)
            best = better(once(True, g), best)
    if best is not None:
        best = _polish(best, menus, need, must_use, groups, group_limits, default_group_max, auto_legs)
    return best


def _keeps_rules(idx: list[int], menus, must_use, groups, group_limits, default_group_max) -> bool:
    if must_use is not None and any(f and i not in idx for i, f in enumerate(must_use)):
        return False
    if groups is None:
        return True
    count: dict = {}
    for i in idx:
        count[groups[i]] = count.get(groups[i], 0) + 1
    limits = dict(group_limits or {})
    for g, c in count.items():
        hi = limits.get(g, (0, default_group_max))[1]
        if hi is not None and c > hi:
            return False
    return all(count.get(g, 0) >= lo for g, (lo, _hi) in limits.items())


def _polish(slip: Slip, menus, need, must_use, groups, group_limits, default_group_max, auto_legs) -> Slip:
    """Exact local search: change one leg at a time (another pick of the same match, or a pick of an unused match) or drop
    one leg; keep a change when the slip still reaches its target, keeps the rules and is likelier."""
    where = {id(p): i for i, m in enumerate(menus) for p in m}
    cur = [(where[id(p)], p) for p in slip.picks]
    chance = math.prod(p.chance for _, p in cur)
    for _ in range(20):
        improved = False
        used = {i for i, _ in cur}
        for pos, (i0, p0) in enumerate(cur):
            for i, menu in enumerate(menus):
                if i != i0 and i in used:
                    continue
                for p in menu:
                    if p is p0:
                        continue
                    nxt = [*cur[:pos], (i, p), *cur[pos + 1:]]
                    ch = math.prod(q.chance for _, q in nxt)
                    od = math.prod(q.odds for _, q in nxt)
                    ok = _keeps_rules([j for j, _ in nxt], menus, must_use, groups, group_limits, default_group_max)
                    if ch > chance * (1 + 1e-12) and od >= need(len(nxt)) * (1 - 1e-12) and ok:
                        cur, chance, improved = nxt, ch, True
                        break
                if improved:
                    break
            if improved:
                break
        if not improved and auto_legs:
            for pos in range(len(cur)):
                less = cur[:pos] + cur[pos + 1:]
                ok = bool(less) and _keeps_rules([j for j, _ in less], menus, must_use, groups, group_limits, default_group_max)
                if ok and math.prod(q.odds for _, q in less) >= need(len(less)) * (1 - 1e-12):
                    cur, chance, improved = less, math.prod(q.chance for _, q in less), True
                    break
        if not improved:
            break
    cur.sort(key=lambda t: t[0])
    picks = tuple(p for _, p in cur)
    return Slip(picks, math.prod(p.chance for p in picks), math.prod(p.odds for p in picks))


def _solve_once(menus, target, legs, grid, must_use, groups, group_limits, default_group_max, nearest,
                auto_legs=False, row_target=None) -> Slip | None:
    n = len(menus)
    k_legs = n if legs is None else legs
    if not (1 <= k_legs <= n):
        raise ValueError(f"legs must be between 1 and {n}")
    if target <= 1:
        raise ValueError("target must be greater than 1")
    all_in = k_legs >= n and not auto_legs
    forced = [all_in] * n if must_use is None else [bool(f) or all_in for f in must_use]
    labels = list(groups) if groups is not None else [None] * n
    if len(labels) != n:
        raise ValueError("groups must have one label per match")
    limits = dict(group_limits or {})

    # contiguous segments, one per label, in first-appearance order
    segments: dict[Hashable, list[int]] = {}
    for i, lab in enumerate(labels):
        segments.setdefault(lab, []).append(i)

    top = math.ceil(math.log(target) / grid)
    width = top + 1
    cols = np.arange(width)
    cur = np.full((k_legs + 1, width), _NEG)
    cur[0, 0] = 0.0
    trail: list[tuple] = []   # what is needed to walk back from the final state to the picks

    for lab, members in segments.items():
        lo, hi = limits.get(lab, (0, default_group_max))
        hi = min(len(members), k_legs) if hi is None else min(hi, len(members), k_legs)
        lo = max(lo, 0)
        if lo > hi:
            return None
        if lo == 0 and hi >= min(len(members), k_legs):       # no rule bites: plain pass, match by match
            for i in members:
                best, choice, prev = _step(cur, menus[i], grid, top, nearest)
                base = np.full(cur.shape, _NEG) if forced[i] else cur
                take = best > base
                nxt = np.where(take, best, base)
                trail.append(("plain", i, np.where(take, choice, -1).astype(np.int16), np.where(take, prev, cols)))
                cur = nxt
            continue
        # a rule bites: also track how many legs this group has used so far (layer j)
        layers = [cur] + [np.full(cur.shape, _NEG) for _ in range(hi)]
        for i in members:
            steps = [_step(layers[j], menus[i], grid, top, nearest) for j in range(hi)]
            new_layers = [np.full(cur.shape, _NEG) if forced[i] else layers[0]]
            choice_stack = np.full((hi + 1, *cur.shape), -1, dtype=np.int16)
            prev_stack = np.zeros((hi + 1, *cur.shape), dtype=np.int32)
            for j in range(hi):
                best, choice, prev = steps[j]
                base = np.full(cur.shape, _NEG) if forced[i] else layers[j + 1]
                take = best > base
                new_layers.append(np.where(take, best, base))
                choice_stack[j + 1] = np.where(take, choice, -1)
                prev_stack[j + 1] = prev
            layers = new_layers
            trail.append(("layer", i, choice_stack, prev_stack))
        stack = np.stack(layers[lo: hi + 1])
        jstar = stack.argmax(axis=0)
        cur = np.take_along_axis(stack, jstar[None], axis=0)[0]
        trail.append(("close", None, (jstar + lo).astype(np.int16), None))

    end_k, end_b = k_legs, top
    if auto_legs:   # the best number of legs whose slip reaches its own target
        best_v = _NEG
        for kk in range(1, k_legs + 1):
            need = top if row_target is None else min(top, max(0, math.ceil(math.log(row_target(kk)) / grid)))
            bb = int(np.argmax(cur[kk, need:])) + need
            if cur[kk, bb] > best_v:
                best_v, end_k, end_b = cur[kk, bb], kk, bb
        if best_v < _NEG / 2:
            return None
    elif cur[k_legs, top] < _NEG / 2:
        return None
    picks: list[Pick] = []
    k, b, j = end_k, end_b, 0
    for kind, i, choice, prev in reversed(trail):
        if kind == "close":
            j = int(choice[k, b])
        elif kind == "plain":
            c = int(choice[k, b])
            if c >= 0:
                picks.append(menus[i][c])
                b = int(prev[k, b])
                k -= 1
        else:
            c = int(choice[j, k, b])
            if c >= 0:
                picks.append(menus[i][c])
                b = int(prev[j, k, b])
                k -= 1
                j -= 1
    picks.reverse()
    order = {id(p): n for n, p in enumerate(q for m in menus for q in m)}
    picks.sort(key=lambda p: order[id(p)])
    chance = math.prod(p.chance for p in picks)
    odds = math.prod(p.odds for p in picks)
    return Slip(tuple(picks), chance, odds)
