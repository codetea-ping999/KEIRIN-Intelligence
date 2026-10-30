from datetime import date

from keirin_intelligence.evaluation import walk_forward
from keirin_intelligence.model import LineAwareModel
from keirin_intelligence.synth import synthetic_history


def test_walk_forward_only_trains_on_earlier_months(monkeypatch):
    # 2 races/day from 2026-01-01 -> January, February and part of March
    cards, results = synthetic_history(150, seed=5, races_per_day=2)
    seen = []
    original = LineAwareModel.fit

    def spy(self, data, **kwargs):
        seen.append(max(card.race_date for card, _ in data))
        return original(self, data, iterations=5)

    monkeypatch.setattr(LineAwareModel, "fit", spy)
    boards = walk_forward(cards, results, min_train_races=50)
    assert seen == [date(2026, 1, 31), date(2026, 2, 28)]
    assert all(board.races == 150 for board in boards)


def test_model_beats_uniform_on_synthetic_truth():
    cards, results = synthetic_history(200, seed=11)
    summary = {b.name: b.summary() for b in walk_forward(cards, results, min_train_races=10**9)}
    assert summary["M1_prior_only"]["win_log_loss"] < summary["uniform"]["win_log_loss"]
