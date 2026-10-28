"""Transparent, intentionally uncalibrated rating baseline for synthetic fixtures.

This is not a commercially validated predictor; it illustrates probability
normalization and ordered ticket mathematics. Real performance requires OOS evaluation.
"""

import math
from collections.abc import Sequence

from keirin_intelligence.domain import RiderEntry


def rating_softmax(entries: Sequence[RiderEntry], temperature: float = 10.0) -> dict[int, float]:
    """Produce race-normalized experimental scores, not calibrated true win probabilities."""
    if len(entries) < 2:
        raise ValueError("at least two riders required")
    if len({r.car_number for r in entries}) != len(entries):
        raise ValueError("duplicate car numbers")
    if not math.isfinite(temperature) or temperature <= 0:
        raise ValueError("temperature must be positive and finite")
    if any(not math.isfinite(r.rating) for r in entries):
        raise ValueError("ratings must be finite")
    max_rating = max(r.rating for r in entries)
    weights = [math.exp((r.rating - max_rating) / temperature) for r in entries]
    total = sum(weights)
    return {r.car_number: w / total for r, w in zip(entries, weights, strict=True)}


def ordered_pair_probability(probabilities: dict[int, float], first: int, second: int) -> float:
    """Plackett-Luce exacta probability for DISTINCT riders (illustrative baseline)."""
    if first == second or first not in probabilities or second not in probabilities:
        raise ValueError("first and second must be different existing cars")
    if len(probabilities) < 2:
        raise ValueError("at least 2 entries needed")
    if any(p < 0 or p > 1 or not math.isfinite(p) for p in probabilities.values()):
        raise ValueError("probabilities must be finite in [0,1]")
    if not math.isclose(sum(probabilities.values()), 1.0, abs_tol=1e-8):
        raise ValueError("probabilities must sum to one")
    p_first = probabilities[first]
    remaining = 1 - p_first
    if remaining <= 0:
        raise ValueError("degenerate probability: second place undefined")
    return p_first * probabilities[second] / remaining


def expected_roi(probability: float, decimal_odds: float) -> float:
    """Illustrative expected net ROI using total-return decimal odds."""
    if not math.isfinite(probability) or not 0 <= probability <= 1:
        raise ValueError("probability must lie in [0,1]")
    if not math.isfinite(decimal_odds) or decimal_odds <= 0:
        raise ValueError("decimal_odds must be positive")
    return probability * decimal_odds - 1.0
