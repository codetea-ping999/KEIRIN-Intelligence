import math
from pathlib import Path

from keirin_intelligence.model import PRIOR_WEIGHTS, LineAwareModel, uniform_prediction
from keirin_intelligence.racecard import load_cards
from keirin_intelligence.synth import synthetic_history

CARD = load_cards(Path(__file__).resolve().parents[1] / "data" / "templates")["EXAMPLE-0001"]


def test_probabilities_are_coherent():
    pred = LineAwareModel().predict(CARD)
    assert math.isclose(sum(pred.win.values()), 1.0)
    assert math.isclose(sum(pred.exacta.values()), 1.0)
    assert math.isclose(sum(pred.trifecta.values()), 1.0)
    assert math.isclose(sum(pred.top3.values()), 3.0)
    for car in pred.win:
        assert pred.win[car] <= pred.top2[car] <= pred.top3[car] <= 1.0 + 1e-12


def test_line_follow_term_links_exacta_to_line():
    no_follow = LineAwareModel(PRIOR_WEIGHTS | {"follow": 0.0}).predict(CARD)
    follow = LineAwareModel().predict(CARD)
    # 1 rides directly behind 4 in the 4-1-6 line
    assert follow.exacta[(4, 1)] > no_follow.exacta[(4, 1)]


def test_uniform_baseline_sums_to_one():
    pred = uniform_prediction(CARD)
    assert math.isclose(sum(pred.trifecta.values()), 1.0)


def test_fit_moves_toward_true_weights():
    truth = LineAwareModel(PRIOR_WEIGHTS | {"score_z": 1.4, "follow": 1.4})
    cards, results = synthetic_history(400, seed=3, truth=truth)
    fitted = LineAwareModel().fit([(cards[r], results[r]) for r in results], iterations=150)
    assert fitted.weights["score_z"] > PRIOR_WEIGHTS["score_z"] + 0.3
    assert fitted.weights["follow"] > PRIOR_WEIGHTS["follow"] + 0.3
