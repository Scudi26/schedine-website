"""Score matrix: the chance of every scoreline, fitted to what the market says about one match."""

from __future__ import annotations

import math
from dataclasses import dataclass
from functools import cached_property

import numpy as np
from scipy.optimize import least_squares

MAX_GOALS = 10  # scorelines 0..9 for each side; the mass beyond is negligible and renormalised
# First half: a second Dixon–Coles matrix with 0.434 of each side's full-time expected goals and a low-score correction
# of -0.040 (maximum likelihood on the half-time scores of 71,589 matches, 2005-06 to 2016-17; tools/markets.py).
HALF_SHARE = 0.434
HALF_RHO = -0.040
_FACT = np.array([math.factorial(i) for i in range(MAX_GOALS)], dtype=float)
_K = np.arange(MAX_GOALS)
_H, _A = np.meshgrid(_K, _K, indexing="ij")
_HOME, _DRAW, _AWAY = _H > _A, _H == _A, _H < _A
_TOTAL = _H + _A


def safe_rho(lh: float, la: float, rho: float) -> float:
    """Keep the Dixon–Coles low-score correction inside the range where every chance stays >= 0."""
    hi = min(1.0 / (lh * la), 1.0) * 0.999   # keeps 1 - lh*la*rho and 1 - rho non-negative
    lo = -min(1.0 / lh, 1.0 / la) * 0.999    # keeps 1 + lh*rho and 1 + la*rho non-negative
    return max(lo, min(hi, rho))


def score_matrix(lh: float, la: float, rho: float = -0.06) -> np.ndarray:
    """Dixon–Coles matrix m[h, a] from the two expected-goals numbers and the low-score correction."""
    if not (lh > 0 and la > 0 and math.isfinite(lh) and math.isfinite(la)):
        raise ValueError(f"expected goals must be positive and finite: {lh}, {la}")
    rho = safe_rho(lh, la, rho)
    ph = np.exp(-lh) * lh**_K / _FACT
    pa = np.exp(-la) * la**_K / _FACT
    m = np.outer(ph, pa)
    m[0, 0] *= 1 - lh * la * rho
    m[0, 1] *= 1 + lh * rho
    m[1, 0] *= 1 + la * rho
    m[1, 1] *= 1 - rho
    return m / m.sum()


@dataclass(frozen=True)
class MarketView:
    """Everything the slip builder needs to know about one match, in fair (margin-free) terms."""

    p_home: float
    p_draw: float
    p_away: float
    p_over25: float
    lh: float
    la: float
    rho: float
    matrix: np.ndarray
    fit_error: float  # largest gap between the market's chances and the fitted matrix

    @property
    def p_over15(self) -> float:
        return float(self.matrix[_TOTAL >= 2].sum())

    @property
    def p_under35(self) -> float:
        return float(self.matrix[_TOTAL <= 3].sum())

    @property
    def p_btts(self) -> float:
        return float(self.matrix[1:, 1:].sum())

    @cached_property
    def half(self) -> np.ndarray:
        """The first-half score matrix (see HALF_SHARE)."""
        return score_matrix(self.lh * HALF_SHARE, self.la * HALF_SHARE, HALF_RHO)


def _summary(m: np.ndarray) -> np.ndarray:
    return np.array([m[_HOME].sum(), m[_DRAW].sum(), m[_AWAY].sum(), m[_TOTAL >= 3].sum()])


def fit_market(p_home: float, p_draw: float, p_away: float, p_over25: float) -> MarketView:
    """Find the score matrix that reproduces the market's result and over/under 2.5 chances."""
    target = np.array([p_home, p_draw, p_away, p_over25], dtype=float)
    if not np.all((target > 0) & (target < 1)) or abs(p_home + p_draw + p_away - 1) > 1e-6:
        raise ValueError(f"not a valid set of fair chances: {target}")

    def resid(x: np.ndarray) -> np.ndarray:
        return _summary(score_matrix(x[0], x[1], x[2])) - target

    total = 2.7 if p_over25 <= 0 else max(1.2, min(4.5, 1.6 + 2.2 * p_over25))
    tilt = 0.5 + 0.9 * (p_home - p_away)
    x0 = np.array([max(0.2, total * min(0.9, max(0.1, tilt))), 0.0, -0.05])
    x0[1] = max(0.2, total - x0[0])
    sol = least_squares(resid, x0, bounds=([0.05, 0.05, -0.30], [6.0, 6.0, 0.20]), xtol=1e-10, ftol=1e-12)
    lh, la, rho = (float(v) for v in sol.x)
    m = score_matrix(lh, la, rho)
    return MarketView(p_home, p_draw, p_away, p_over25, lh, la, safe_rho(lh, la, rho), m,
                      float(np.abs(_summary(m) - target).max()))


def view_from(lh: float, la: float, rho: float = -0.06) -> MarketView:
    """A market view rebuilt from a stored matrix (expected goals and low-score correction), e.g. a price-history snapshot."""
    m = score_matrix(lh, la, rho)
    ph, pd_, pa, po = (float(x) for x in _summary(m))
    return MarketView(ph, pd_, pa, po, lh, la, safe_rho(lh, la, rho), m, 0.0)
