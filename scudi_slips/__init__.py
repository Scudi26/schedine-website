"""Scudi slips: build the accumulator with the best chance of landing on a target multiplier.

Pipeline for one match:  bookmaker prices -> fair chances (devig) -> score matrix (matrix)
-> menu of picks with their chances (picks).  For one slip: choose one pick per match (solver),
then add the bookmaker's accumulator bonus (bonus).
"""

from .bonus import snai_bonus
from .devig import power_devig
from .matrix import MarketView, fit_market, score_matrix
from .picks import PICKS, SLIP_MENU, Pick, menu, settles
from .solver import Slip, solve

__all__ = [
    "PICKS",
    "SLIP_MENU",
    "MarketView",
    "Pick",
    "Slip",
    "fit_market",
    "menu",
    "power_devig",
    "score_matrix",
    "settles",
    "snai_bonus",
    "solve",
]
