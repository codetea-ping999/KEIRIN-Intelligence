"""Fictional race cards + results drawn from a known model, for tests and the demo.

Every rider here is invented ("架空"); nothing in this module is real data.
"""

import random
from datetime import UTC, date, datetime, timedelta

from keirin_intelligence.model import LineAwareModel, _follows, race_features
from keirin_intelligence.racecard import CardEntry, RaceCard, RaceResult

PREFS = ("東京", "千葉", "静岡", "大阪", "福岡", "宮城", "愛知")
FORMATIONS = ((3, 3, 1), (3, 2, 2), (2, 2, 2, 1), (4, 3), (3, 2, 1, 1))


def synthetic_card(rng: random.Random, race_id: str, day: date) -> RaceCard:
    sizes = rng.choice(FORMATIONS)
    cars = rng.sample(range(1, 8), 7)
    entries, i = [], 0
    for group, size in enumerate(sizes, start=1):
        for pos in range(1, size + 1):
            entries.append(CardEntry(
                car_number=cars[i], name=f"架空選手{race_id[-3:]}-{cars[i]}",
                rider_class=rng.choice(("S1", "S2", "A1")), prefecture=rng.choice(PREFS),
                score=round(rng.gauss(95, 6), 2),
                style="逃" if pos == 1 and size >= 2 else ("両" if size == 1 else "追"),
                line_group=group, line_pos=pos,
            ))
            i += 1
    cutoff = datetime(day.year, day.month, day.day, 6, 0, tzinfo=UTC)
    return RaceCard(race_id, day, "架空バンク", 7, "F1", cutoff, "SYNTHETIC",
                    cutoff - timedelta(hours=20), cutoff - timedelta(hours=19), tuple(entries))


def sample_result(rng: random.Random, card: RaceCard, model: LineAwareModel) -> RaceResult:
    base = model._utilities(race_features(card))
    front = _follows(card)
    remaining, order, prev = set(base), [], None
    while remaining:
        probs = model._stage(base, front, remaining, prev)
        cars = sorted(probs)
        car = rng.choices(cars, weights=[probs[c] for c in cars])[0]
        order.append(car)
        remaining.discard(car)
        prev = car
    return RaceResult(card.race_id, tuple(order))


def synthetic_history(
    n_races: int, seed: int = 7, truth: LineAwareModel | None = None, races_per_day: int = 12
):
    rng = random.Random(seed)
    truth = truth or LineAwareModel()
    cards, results = {}, {}
    start = date(2026, 1, 1)
    for k in range(n_races):
        card = synthetic_card(rng, f"SYN-{k:05d}", start + timedelta(days=k // races_per_day))
        cards[card.race_id] = card
        results[card.race_id] = sample_result(rng, card, truth)
    return cards, results
