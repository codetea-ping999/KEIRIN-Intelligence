"""Chronological walk-forward evaluation (docs/BACKTEST_POLICY.md).

Races are grouped by month; the model for month M is fitted only on races dated
before M, so no result is ever used to predict itself or an earlier race.
"""

import math
from collections.abc import Callable
from dataclasses import dataclass, field

from keirin_intelligence.model import (
    SCORE_ONLY_WEIGHTS,
    LineAwareModel,
    RacePrediction,
    uniform_prediction,
)
from keirin_intelligence.racecard import RaceCard, RaceResult

TRIFECTA_TOP_N = 6


@dataclass
class Scoreboard:
    name: str
    races: int = 0
    log_loss: float = 0.0
    brier: float = 0.0
    top1_win: int = 0
    top1_in_top3: int = 0
    exacta_top1: int = 0
    trifecta_topn: int = 0
    trifecta_races: int = 0
    per_race: list[dict] = field(default_factory=list)

    def add(self, pred: RacePrediction, result: RaceResult) -> None:
        winner = result.order[0]
        p_winner = max(pred.win.get(winner, 0.0), 1e-12)
        self.races += 1
        self.log_loss += -math.log(p_winner)
        self.brier += sum((p - (c == winner)) ** 2 for c, p in pred.win.items())
        favourite = pred.ranked()[0]
        self.top1_win += favourite == winner
        self.top1_in_top3 += favourite in result.order[:3]
        if len(result.order) >= 2 and pred.exacta:
            best_pair = max(pred.exacta, key=pred.exacta.get)
            self.exacta_top1 += best_pair == tuple(result.order[:2])
        if len(result.order) >= 3 and pred.trifecta:
            self.trifecta_races += 1
            top = sorted(pred.trifecta, key=pred.trifecta.get, reverse=True)[:TRIFECTA_TOP_N]
            self.trifecta_topn += tuple(result.order[:3]) in top
        self.per_race.append({"race_id": pred.race_id, "p_winner": p_winner,
                              "favourite": favourite, "winner": winner})

    def summary(self) -> dict[str, float | int | str]:
        n = max(self.races, 1)
        return {
            "model": self.name,
            "races": self.races,
            "win_log_loss": round(self.log_loss / n, 4),
            "win_brier": round(self.brier / n, 4),
            "honmei_win_rate": round(self.top1_win / n, 4),
            "honmei_top3_rate": round(self.top1_in_top3 / n, 4),
            "exacta_top1_hit": round(self.exacta_top1 / n, 4),
            f"trifecta_top{TRIFECTA_TOP_N}_hit": round(
                self.trifecta_topn / max(self.trifecta_races, 1), 4
            ),
        }


def walk_forward(
    cards: dict[str, RaceCard],
    results: dict[str, RaceResult],
    *,
    min_train_races: int = 100,
    fit_kwargs: dict | None = None,
) -> list[Scoreboard]:
    """Evaluate M1 (refit monthly), M1 priors only, score-only and uniform baselines."""
    labelled = sorted(
        (cards[r] for r in results if r in cards and results[r].order),
        key=lambda c: (c.race_date, c.race_id),
    )
    boards = {name: Scoreboard(name) for name in
              ("M1_walk_forward", "M1_prior_only", "score_only", "uniform")}
    fixed: dict[str, Callable[[RaceCard], RacePrediction]] = {
        "M1_prior_only": LineAwareModel().predict,
        "score_only": LineAwareModel(SCORE_ONLY_WEIGHTS).predict,
        "uniform": uniform_prediction,
    }
    model, fitted_for = LineAwareModel(), None
    for i, card in enumerate(labelled):
        month = (card.race_date.year, card.race_date.month)
        if month != fitted_for:
            history = [(c, results[c.race_id]) for c in labelled[:i]
                       if (c.race_date.year, c.race_date.month) < month]
            model = (LineAwareModel().fit(history, **(fit_kwargs or {}))
                     if len(history) >= min_train_races else LineAwareModel())
            fitted_for = month
        result = results[card.race_id]
        boards["M1_walk_forward"].add(model.predict(card), result)
        for name, predict in fixed.items():
            boards[name].add(predict(card), result)
    return list(boards.values())
