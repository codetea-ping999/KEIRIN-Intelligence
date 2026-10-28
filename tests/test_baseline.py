import math

import pytest

from keirin_intelligence.baseline import expected_roi, ordered_pair_probability, rating_softmax
from keirin_intelligence.domain import RiderEntry


def example():
    return [RiderEntry(1, "A", 100), RiderEntry(2, "B", 90), RiderEntry(3, "C", 80)]


def test_softmax_is_normalized_and_ordered():
    probs = rating_softmax(example())
    assert math.isclose(sum(probs.values()), 1.0)
    assert probs[1] > probs[2] > probs[3]


def test_plackett_luce_exacta_probabilities_sum_to_one():
    probs = rating_softmax(example())
    total = sum(ordered_pair_probability(probs, i, j) for i in probs for j in probs if i != j)
    assert math.isclose(total, 1.0, rel_tol=1e-12)


def test_reject_duplicate_car_numbers():
    with pytest.raises(ValueError, match="duplicate"):
        rating_softmax([RiderEntry(1, "A", 80), RiderEntry(1, "B", 90)])


def test_reject_invalid_ticket():
    with pytest.raises(ValueError):
        ordered_pair_probability({1: 0.6, 2: 0.4}, 1, 1)


def test_expected_roi_math_and_input_checks():
    assert expected_roi(0.2, 6.0) == pytest.approx(0.2)
    with pytest.raises(ValueError):
        expected_roi(0.2, 0)
