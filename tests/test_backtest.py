from datetime import date, timedelta

import pytest

from keirin_intelligence.backtest import (
    backtest,
    chronological_split,
    load_win_odds,
    market_prediction,
    temper,
)
from keirin_intelligence.model import LineAwareModel
from keirin_intelligence.synth import synthetic_history

# 12 races/day from 2026-01-01: 480 races -> 40 days
CARDS, RESULTS = synthetic_history(480, seed=3)
TRAIN_END, CALIB_END = date(2026, 1, 21), date(2026, 1, 31)


def test_split_is_chronological_and_keeps_races_whole():
    split = chronological_split(CARDS, RESULTS, TRAIN_END, CALIB_END)
    assert max(c.race_date for c in split.train) < TRAIN_END
    assert min(c.race_date for c in split.calibration) >= TRAIN_END
    assert max(c.race_date for c in split.calibration) < CALIB_END
    assert min(c.race_date for c in split.test) >= CALIB_END
    assert len(split.train) + len(split.calibration) + len(split.test) == 480


def test_empty_period_is_an_error():
    with pytest.raises(ValueError, match="test period"):
        chronological_split(CARDS, RESULTS, TRAIN_END, date(2027, 1, 1))


def test_fit_sees_only_train_and_report_is_complete(monkeypatch):
    seen = []
    original = LineAwareModel.fit

    def spy(self, data, **kwargs):
        seen.extend(card.race_date for card, _ in data)
        return original(self, data, iterations=10)

    monkeypatch.setattr(LineAwareModel, "fit", spy)
    results = dict(RESULTS)
    results.pop("SYN-00479")  # one race without a result
    report = backtest(CARDS, results, train_end=TRAIN_END, calib_end=CALIB_END)
    assert seen and max(seen) < TRAIN_END
    assert report["evidence"] == "BACKTEST"
    assert report["periods"]["test"]["from"] == CALIB_END.isoformat()
    assert report["races_without_result"] == 1 and report["missing_result_rate"] > 0
    names = {m["model"]: m for m in report["metrics"]}
    assert {"M1_fitted", "M1_calibrated", "score_only", "uniform"} <= set(names)
    assert names["M1_calibrated"]["win_log_loss"] < names["uniform"]["win_log_loss"]
    assert sum(b["n"] for b in report["calibration"]["bins"]) == sum(
        len(CARDS[r].entries) for r in CARDS if CARDS[r].race_date >= CALIB_END and r in results)
    assert 0 <= report["calibration"]["ece"] < 0.2
    assert report["market"]["test_races_with_odds"] == 0


def test_temperature_one_is_identity():
    pred = LineAwareModel().predict(next(iter(CARDS.values())))
    tempered = temper(pred, 1.0)
    assert all(abs(tempered.win[c] - pred.win[c]) < 1e-12 for c in pred.win)


def test_market_baseline_uses_only_pre_cutoff_odds(tmp_path):
    card = CARDS["SYN-00470"]
    cars = [e.car_number for e in card.entries]
    before = card.betting_cutoff_at - timedelta(minutes=5)
    after = card.betting_cutoff_at + timedelta(minutes=1)
    rows = ["race_id,car,win_odds,observed_at"]
    rows += [f"{card.race_id},{c},{2.0 + i},{before.isoformat()}" for i, c in enumerate(cars)]
    rows.append(f"{card.race_id},{cars[0]},99.0,{after.isoformat()}")  # after cutoff: ignored
    path = tmp_path / "odds.csv"
    path.write_text("\n".join(rows) + "\n", encoding="utf-8")
    odds = load_win_odds(path, CARDS)
    assert odds[card.race_id][cars[0]] == 2.0
    market = market_prediction(card, odds[card.race_id])
    assert abs(sum(market.win.values()) - 1) < 1e-9 and market.ranked()[0] == cars[0]
    assert market_prediction(card, {cars[0]: 2.0}) is None  # incomplete odds
    report = backtest(CARDS, RESULTS, train_end=TRAIN_END, calib_end=CALIB_END, odds=odds,
                      fit_kwargs={"iterations": 5})
    assert report["market"]["test_races_with_odds"] == 1
    assert [m["model"] for m in report["market"]["metrics"]] == [
        "market", "M1_calibrated_on_market_races"]
