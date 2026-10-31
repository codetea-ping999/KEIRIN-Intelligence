"""M1: line-aware sequential logit (Plackett-Luce with a line-follow term).

Each stage picks the next finisher with softmax(w . x_j + gamma * follows_j), where
follows_j = 1 when rider j sits directly behind the previous finisher in the same line.
This keeps exacta/trifecta probabilities correlated through the line instead of
multiplying independent win rates.

PRIOR_WEIGHTS are hand-set domain priors, not fitted values. `fit` shrinks toward them
(L2) so small hand-entered datasets do not overfit; accuracy claims require
`evaluation.walk_forward` on real results.
"""

import math
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from itertools import permutations
from statistics import fmean, pstdev

from keirin_intelligence.racecard import RaceCard, RaceResult, Velodrome

FEATURES = (
    "score_z", "line_strength_z", "leader", "bante", "third", "solo", "nige",
    "bank_nige", "bank_chaser", "wind_nige", "wind_chaser", "wet_nige", "local", "nige_lowclass",
)
PARAMS = (*FEATURES, "follow")

PRIOR_WEIGHTS: dict[str, float] = {
    "score_z": 0.6,
    "line_strength_z": 0.25,
    "leader": 0.05,
    "bante": 0.3,
    "third": -0.2,
    "solo": -0.35,
    "nige": 0.0,
    # Venue / weather / class terms start small: the source boards disagree on several of
    # them (rain, cant), so the data must earn any larger weight.
    "bank_nige": 0.15,  # short minashi straight (<50m) favours front-runners
    "bank_chaser": 0.10,  # long straight (>50m) lets chasers (追) finish
    "wind_nige": -0.15,  # back-straight headwind tires the front-runner (per 5 m/s)
    "wind_chaser": 0.10,
    "wet_nige": 0.0,
    "local": 0.10,  # home-prefecture rider
    "nige_lowclass": 0.10,  # front-running survives more often in A-class
    "follow": 0.7,
}
SCORE_ONLY_WEIGHTS: dict[str, float] = {name: 0.0 for name in PARAMS} | {"score_z": 0.6}


def _bare(prefecture: str) -> str:
    return prefecture if prefecture == "北海道" else prefecture.rstrip("都府県")


def race_features(
    card: RaceCard, venues: dict[str, Velodrome] | None = None
) -> dict[int, dict[str, float]]:
    venue = (venues or {}).get(card.venue)
    straight = venue.straight_m if venue else None
    bank = (50.0 - straight) / 10.0 if straight is not None else 0.0
    wind = (card.back_wind_mps or 0.0) / 5.0
    wet = 1.0 if card.wet else 0.0
    scores = [e.score for e in card.entries]
    mean, sd = fmean(scores), max(pstdev(scores), 1.0)
    line_mean = {
        line[0].line_group: fmean(e.score for e in line) for line in card.lines()
    }
    line_size = {line[0].line_group: len(line) for line in card.lines()}
    out = {}
    for e in card.entries:
        size = line_size[e.line_group]
        out[e.car_number] = {
            "score_z": (e.score - mean) / sd,
            "line_strength_z": (line_mean[e.line_group] - mean) / sd,
            "leader": float(size >= 2 and e.line_pos == 1),
            "bante": float(size >= 2 and e.line_pos == 2),
            "third": float(e.line_pos >= 3),
            "solo": float(size == 1),
            "nige": float(e.style == "逃"),
            "bank_nige": bank * float(e.style == "逃"),
            "bank_chaser": -bank * float(e.style == "追"),
            "wind_nige": wind * float(e.style == "逃"),
            "wind_chaser": wind * float(e.style == "追"),
            "wet_nige": wet * float(e.style == "逃"),
            "local": float(venue is not None and _bare(e.prefecture) == _bare(venue.prefecture)),
            "nige_lowclass": float(e.style == "逃" and e.rider_class.startswith("A")),
        }
    return out


def _follows(card: RaceCard) -> dict[int, int]:
    """car -> car of the rider directly in front of it in the same line."""
    front = {}
    for line in card.lines():
        for ahead, behind in zip(line, line[1:], strict=False):
            front[behind.car_number] = ahead.car_number
    return front


@dataclass(frozen=True)
class RacePrediction:
    race_id: str
    win: dict[int, float]
    top2: dict[int, float]
    top3: dict[int, float]
    exacta: dict[tuple[int, int], float]
    trifecta: dict[tuple[int, int, int], float]

    def ranked(self) -> list[int]:
        return sorted(self.win, key=lambda c: (-self.win[c], c))


class LineAwareModel:
    def __init__(
        self, weights: dict[str, float] | None = None, venues: dict[str, Velodrome] | None = None
    ) -> None:
        # Weights saved before a feature existed load with that feature switched off.
        given = PRIOR_WEIGHTS if weights is None else weights
        self.weights = {name: 0.0 for name in PARAMS} | given
        self.venues = venues

    def _utilities(self, feats: dict[int, dict[str, float]]) -> dict[int, float]:
        return {c: sum(self.weights[k] * x[k] for k in FEATURES) for c, x in feats.items()}

    def _stage(
        self, base: dict[int, float], front: dict[int, int], remaining: Iterable[int], prev: int | None
    ) -> dict[int, float]:
        follow = self.weights["follow"]
        util = {c: base[c] + (follow if prev is not None and front.get(c) == prev else 0.0)
                for c in remaining}
        top = max(util.values())
        exp = {c: math.exp(u - top) for c, u in util.items()}
        total = sum(exp.values())
        return {c: v / total for c, v in exp.items()}

    def predict(self, card: RaceCard) -> RacePrediction:
        base = self._utilities(race_features(card, self.venues))
        front = _follows(card)
        cars = sorted(base)
        win = self._stage(base, front, cars, None)
        exacta: dict[tuple[int, int], float] = {}
        trifecta: dict[tuple[int, int, int], float] = {}
        for a in cars:
            second = self._stage(base, front, [c for c in cars if c != a], a)
            for b, pb in second.items():
                exacta[(a, b)] = win[a] * pb
                if len(cars) < 3:
                    continue
                third = self._stage(base, front, [c for c in cars if c not in (a, b)], b)
                for c, pc in third.items():
                    trifecta[(a, b, c)] = exacta[(a, b)] * pc
        top2 = {c: sum(p for (a, b), p in exacta.items() if c in (a, b)) for c in cars}
        top3 = {c: sum(p for combo, p in trifecta.items() if c in combo) for c in cars}
        return RacePrediction(card.race_id, win, top2, top3, exacta, trifecta)

    def log_likelihood(self, card: RaceCard, result: RaceResult, depth: int = 3) -> float:
        base = self._utilities(race_features(card, self.venues))
        front = _follows(card)
        remaining = set(base)
        prev, total = None, 0.0
        for car in result.order[:depth]:
            if car not in remaining:
                break
            total += math.log(self._stage(base, front, remaining, prev)[car])
            remaining.discard(car)
            prev = car
        return total

    def fit(
        self,
        data: Sequence[tuple[RaceCard, RaceResult]],
        *,
        l2: float = 2.0,
        lr: float = 0.5,
        iterations: int = 300,
        depth: int = 3,
    ) -> "LineAwareModel":
        """Maximum a posteriori fit (Gaussian prior centred on current weights)."""
        prior = [self.weights[k] for k in PARAMS]
        w = list(prior)
        dims = range(len(PARAMS))
        # Each stage's candidate vectors are fixed by the card, so build them once.
        stages: list[tuple[list[tuple[float, ...]], int]] = []
        for card, result in data:
            feats, front = race_features(card, self.venues), _follows(card)
            remaining, prev = sorted(feats), None
            for car in result.order[:depth]:
                if car not in remaining:
                    break
                xs = [(*(feats[c][k] for k in FEATURES),
                       float(prev is not None and front.get(c) == prev)) for c in remaining]
                stages.append((xs, remaining.index(car)))
                remaining = [c for c in remaining if c != car]
                prev = car
        n = max(len(data), 1)
        for _ in range(iterations):
            grad = [-l2 * (w[d] - prior[d]) / n for d in dims]
            for xs, chosen in stages:
                util = [sum(wd * xd for wd, xd in zip(w, x, strict=True)) for x in xs]
                top = max(util)
                exp = [math.exp(u - top) for u in util]
                total = sum(exp)
                for d in dims:
                    expected = sum(e * x[d] for e, x in zip(exp, xs, strict=True)) / total
                    grad[d] += (xs[chosen][d] - expected) / n
            w = [w[d] + lr * grad[d] for d in dims]
        return LineAwareModel(dict(zip(PARAMS, w, strict=True)), self.venues)


def uniform_prediction(card: RaceCard) -> RacePrediction:
    cars = [e.car_number for e in card.entries]
    n = len(cars)
    win = {c: 1 / n for c in cars}
    exacta = {pair: 1 / (n * (n - 1)) for pair in permutations(cars, 2)}
    trifecta = {t: 1 / (n * (n - 1) * (n - 2)) for t in permutations(cars, 3)} if n >= 3 else {}
    return RacePrediction(card.race_id, win, {c: 2 / n for c in cars},
                          {c: min(3 / n, 1.0) for c in cars}, exacta, trifecta)
