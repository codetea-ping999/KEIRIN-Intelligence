"""Chronological train / calibration / test backtest with baselines (Issue #7).

Races are split by date, never shuffled: the model is fitted on the train period only,
a single temperature is fitted on the calibration period only, and every metric is
computed on the untouched test period. Baselines: uniform, competition score only, and
the betting market (pre-cutoff win odds) where odds were entered.
See docs/BACKTEST_POLICY.md. Results here are BACKTEST evidence, not SHADOW or live.
"""

import csv
import math
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

from keirin_intelligence.domain import require_aware
from keirin_intelligence.evaluation import Scoreboard
from keirin_intelligence.model import (
    SCORE_ONLY_WEIGHTS,
    LineAwareModel,
    RacePrediction,
    uniform_prediction,
)
from keirin_intelligence.racecard import RaceCard, RaceResult, Velodrome

TEMPERATURES = tuple(round(0.5 + 0.05 * i, 2) for i in range(51))  # 0.50 .. 3.00
CALIBRATION_BINS = 10


@dataclass(frozen=True)
class Split:
    train: list[RaceCard]
    calibration: list[RaceCard]
    test: list[RaceCard]


def chronological_split(
    cards: dict[str, RaceCard], results: dict[str, RaceResult], train_end: date, calib_end: date
) -> Split:
    """train: race_date < train_end; calibration: [train_end, calib_end); test: >= calib_end.
    Whole races stay together; only races with a recorded finishing order whose card was
    observed and entered before the betting cutoff are used."""
    if not train_end < calib_end:
        raise ValueError("train_end must be before calib_end")
    labelled = sorted((c for r, c in cards.items() if results.get(r) and results[r].order
                       and _known_before_cutoff(c)),
                      key=lambda c: (c.race_date, c.race_id))
    split = Split(
        [c for c in labelled if c.race_date < train_end],
        [c for c in labelled if train_end <= c.race_date < calib_end],
        [c for c in labelled if c.race_date >= calib_end],
    )
    for name in ("train", "calibration", "test"):
        if not getattr(split, name):
            raise ValueError(f"{name} period has no labelled races")
    return split


def _known_before_cutoff(card: RaceCard) -> bool:
    """A card observed or entered at/after its cutoff could carry post-race information."""
    return card.observed_at < card.betting_cutoff_at and card.entered_at < card.betting_cutoff_at


def temper(pred: RacePrediction, temperature: float) -> RacePrediction:
    """Win probabilities p_i^(1/T), renormalised (T > 1 flattens, T < 1 sharpens)."""
    logs = {c: math.log(max(p, 1e-12)) / temperature for c, p in pred.win.items()}
    top = max(logs.values())
    exp = {c: math.exp(v - top) for c, v in logs.items()}
    total = sum(exp.values())
    return RacePrediction(pred.race_id, {c: v / total for c, v in exp.items()}, {}, {}, {}, {})


def fit_temperature(preds: list[RacePrediction], results: dict[str, RaceResult]) -> float:
    def loss(t: float) -> float:
        return sum(-math.log(max(temper(p, t).win.get(results[p.race_id].order[0], 0.0), 1e-12))
                   for p in preds)
    return min(TEMPERATURES, key=loss)


def load_win_odds(path: Path, cards: dict[str, RaceCard]) -> dict[str, dict[int, float]]:
    """odds.csv: race_id,car,win_odds,observed_at. Only odds observed BEFORE the betting
    cutoff are kept (the latest per car); later rows are ignored as look-ahead."""
    latest: dict[tuple[str, int], tuple[datetime, float]] = {}
    with path.open(encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            race_id, car = row["race_id"].strip(), int(row["car"])
            observed = datetime.fromisoformat(row["observed_at"].strip())
            require_aware(observed, "observed_at")
            card = cards.get(race_id)
            if card is None or observed >= card.betting_cutoff_at:
                continue
            odds = float(row["win_odds"])
            if not math.isfinite(odds) or odds <= 0:
                raise ValueError(f"{race_id} car {car}: win_odds must be a positive number")
            if (race_id, car) not in latest or observed > latest[(race_id, car)][0]:
                latest[(race_id, car)] = (observed, odds)
    out: dict[str, dict[int, float]] = {}
    for (race_id, car), (_, odds) in latest.items():
        out.setdefault(race_id, {})[car] = odds
    return out


def market_prediction(card: RaceCard, odds: dict[int, float]) -> RacePrediction | None:
    """Implied win probabilities 1/odds, normalised (removes the takeout). None if incomplete."""
    cars = [e.car_number for e in card.entries]
    if any(c not in odds for c in cars):
        return None
    inv = {c: 1 / odds[c] for c in cars}
    total = sum(inv.values())
    return RacePrediction(card.race_id, {c: v / total for c, v in inv.items()}, {}, {}, {}, {})


@dataclass
class Calibration:
    bins: list[dict]
    ece: float


def calibration_table(preds: list[RacePrediction], results: dict[str, RaceResult]) -> Calibration:
    """Reliability table over every (race, car) win probability in the test period."""
    sums = [[0.0, 0, 0] for _ in range(CALIBRATION_BINS)]  # predicted sum, wins, count
    for p in preds:
        winner = results[p.race_id].order[0]
        for car, prob in p.win.items():
            b = min(int(prob * CALIBRATION_BINS), CALIBRATION_BINS - 1)
            sums[b][0] += prob
            sums[b][1] += car == winner
            sums[b][2] += 1
    total = sum(s[2] for s in sums) or 1
    bins, ece = [], 0.0
    for i, (psum, wins, n) in enumerate(sums):
        if not n:
            continue
        mean_p, freq = psum / n, wins / n
        ece += n / total * abs(mean_p - freq)
        bins.append({"bin": f"{i / CALIBRATION_BINS:.1f}-{(i + 1) / CALIBRATION_BINS:.1f}",
                     "n": n, "mean_predicted": round(mean_p, 4), "observed": round(freq, 4)})
    return Calibration(bins, round(ece, 4))


def _period(cards: list[RaceCard]) -> dict:
    return {"from": cards[0].race_date.isoformat(), "to": cards[-1].race_date.isoformat(),
            "races": len(cards)}


def backtest(
    cards: dict[str, RaceCard],
    results: dict[str, RaceResult],
    *,
    train_end: date,
    calib_end: date,
    odds: dict[str, dict[int, float]] | None = None,
    venues: dict[str, Velodrome] | None = None,
    fit_kwargs: dict | None = None,
) -> dict:
    split = chronological_split(cards, results, train_end, calib_end)
    model = LineAwareModel(venues=venues).fit(
        [(c, results[c.race_id]) for c in split.train], **(fit_kwargs or {}))
    temperature = fit_temperature([model.predict(c) for c in split.calibration], results)

    boards = {name: Scoreboard(name) for name in
              ("M1_fitted", "M1_calibrated", "score_only", "uniform")}
    score_only = LineAwareModel(SCORE_ONLY_WEIGHTS, venues)
    calibrated: list[RacePrediction] = []
    market_board, market_model_board = Scoreboard("market"), Scoreboard("M1_calibrated_on_market_races")
    for card in split.test:
        result = results[card.race_id]
        raw = model.predict(card)
        cal = temper(raw, temperature)
        calibrated.append(cal)
        boards["M1_fitted"].add(raw, result)
        boards["M1_calibrated"].add(cal, result)
        boards["score_only"].add(score_only.predict(card), result)
        boards["uniform"].add(uniform_prediction(card), result)
        market = market_prediction(card, (odds or {}).get(card.race_id, {}))
        if market is not None:
            market_board.add(market, result)
            market_model_board.add(cal, result)

    unlabelled = [r for r in cards if not (results.get(r) and results[r].order)]
    late_cards = [r for r, c in cards.items() if not _known_before_cutoff(c)]
    report = {
        "evidence": "BACKTEST",
        "periods": {"train": _period(split.train), "calibration": _period(split.calibration),
                    "test": _period(split.test)},
        "retrain_boundaries": [train_end.isoformat()],
        "calibration_boundary": calib_end.isoformat(),
        "temperature": temperature,
        "races_total": len(cards),
        "races_without_result": len(unlabelled),
        "missing_result_rate": round(len(unlabelled) / max(len(cards), 1), 4),
        "excluded_entered_after_cutoff": len(late_cards),
        "metrics": [b.summary() for b in boards.values()],
        "calibration": calibration_table(calibrated, results).__dict__,
        "market": {
            "test_races_with_odds": market_board.races,
            "odds_coverage": round(market_board.races / len(split.test), 4),
            "metrics": ([market_board.summary(), market_model_board.summary()]
                        if market_board.races else []),
        },
    }
    return report
