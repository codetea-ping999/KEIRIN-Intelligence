"""As-of feature store: only what was observed AND ingested before the prediction time (#6).

Every snapshot carries `observed_at` (published by the provider) and `ingested_at`
(entered our store). A prediction at time t may only see snapshots with both <= t, and
only the latest such version of each record. Car changes, withdrawals and line changes
arrive as new versions, so the card is rebuilt exactly as it was knowable at t.
Rider history counts only races whose betting cutoff was before t and whose result
had been ingested by t.
"""

from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime

from keirin_intelligence.domain import require_aware
from keirin_intelligence.etl import Store
from keirin_intelligence.governance import GateRejected
from keirin_intelligence.model import race_features
from keirin_intelligence.racecard import CardEntry, RaceCard, Velodrome

HISTORY_FEATURES = ("hist_starts", "hist_win_rate", "hist_top3_rate")


@dataclass(frozen=True)
class Snapshot:
    kind: str  # race / entry / result
    key: str
    version: int
    payload: dict
    observed_at: datetime
    ingested_at: datetime
    source_id: str
    synthetic: bool = False

    def __post_init__(self) -> None:
        require_aware(self.observed_at, "observed_at")
        require_aware(self.ingested_at, "ingested_at")

    def known_at(self, t: datetime) -> bool:
        return self.observed_at <= t and self.ingested_at <= t


class AsOfStore:
    def __init__(self, snapshots: list[Snapshot]) -> None:
        self._by_key: dict[tuple[str, str], list[Snapshot]] = defaultdict(list)
        self._race_keys: dict[str, set[tuple[str, str]]] = defaultdict(set)
        for s in snapshots:
            self._by_key[(s.kind, s.key)].append(s)
            self._race_keys[s.payload["race_id"]].add((s.kind, s.key))
        for versions in self._by_key.values():
            versions.sort(key=lambda s: (s.observed_at, s.ingested_at, s.version))

    @classmethod
    def from_etl(cls, store: Store) -> "AsOfStore":
        return cls([
            Snapshot(r["kind"], r["natural_key"], r["version"], r["payload"],
                     datetime.fromisoformat(r["observed_at"]),
                     datetime.fromisoformat(r["ingested_at"]), r["source_id"],
                     bool(r["synthetic"]))
            for r in store.records()
        ])

    def as_of(self, kind: str, key: str, t: datetime) -> Snapshot | None:
        require_aware(t, "t")
        known = [s for s in self._by_key.get((kind, key), []) if s.known_at(t)]
        return known[-1] if known else None

    def _race_rows(self, race_id: str, kind: str, t: datetime) -> list[Snapshot]:
        keys = sorted(k for k in self._race_keys.get(race_id, ()) if k[0] == kind)
        return [s for k in keys if (s := self.as_of(k[0], k[1], t)) is not None]

    def card_as_of(self, race_id: str, t: datetime) -> RaceCard:
        """The race card as it was knowable at t (withdrawn riders removed)."""
        race = self.as_of("race", race_id, t)
        if race is None:
            raise GateRejected(f"{race_id}: race card not known at {t.isoformat()}")
        cutoff = datetime.fromisoformat(race.payload["betting_cutoff_at"])
        if t >= cutoff:
            raise GateRejected(f"{race_id}: prediction time must precede the betting cutoff")
        rows = [s for s in self._race_rows(race_id, "entry", t)
                if s.payload.get("status", "entered") == "entered"]
        if len(rows) < 2:
            raise GateRejected(f"{race_id}: fewer than two starters known at {t.isoformat()}")
        lines: dict[int, list[dict]] = defaultdict(list)
        for s in rows:
            lines[s.payload["line_group"]].append(s.payload)
        entries = []
        for group, members in lines.items():
            # A withdrawal leaves a gap in the line; the riders behind move up.
            for pos, p in enumerate(sorted(members, key=lambda p: p["line_pos"]), start=1):
                entries.append(CardEntry(p["car"], p["name"], p["rider_class"], p["prefecture"],
                                         p["score"], p["style"], group, pos))
        used = [race, *rows]
        rp = race.payload
        return RaceCard(
            race_id=race_id, race_date=date.fromisoformat(rp["race_date"]), venue=rp["venue"],
            race_number=rp["race_number"], grade=rp["grade"], betting_cutoff_at=cutoff,
            source=",".join(sorted({s.source_id for s in used})),
            observed_at=max(s.observed_at for s in used),
            entered_at=max(s.ingested_at for s in used),
            entries=tuple(sorted(entries, key=lambda e: e.car_number)),
            back_wind_mps=rp.get("back_wind_mps"), wet=rp.get("wet"),
        )

    def rider_history(self, t: datetime) -> dict[str, dict[str, float]]:
        """Per rider name: starts / win rate / top-3 rate over races settled and known by t."""
        stats: dict[str, list[int]] = defaultdict(lambda: [0, 0, 0])
        for race_id in self._race_keys:
            race = self.as_of("race", race_id, t)
            if race is None or datetime.fromisoformat(race.payload["betting_cutoff_at"]) >= t:
                continue
            finish = {s.payload["car"]: s.payload["finish"]
                      for s in self._race_rows(race_id, "result", t)}
            if not finish:
                continue
            for s in self._race_rows(race_id, "entry", t):
                car = s.payload["car"]
                if s.payload.get("status", "entered") != "entered" or car not in finish:
                    continue
                row = stats[s.payload["name"]]
                row[0] += 1
                row[1] += finish[car] == 1
                row[2] += 1 <= finish[car] <= 3
        return {name: {"hist_starts": float(n), "hist_win_rate": w / n, "hist_top3_rate": t3 / n}
                for name, (n, w, t3) in stats.items()}

    def features(
        self, race_id: str, t: datetime, venues: dict[str, Velodrome] | None = None
    ) -> dict[int, dict[str, float]]:
        """Model features (model.race_features) plus as-of rider history, keyed by car."""
        card = self.card_as_of(race_id, t)
        history = self.rider_history(t)
        empty = {name: 0.0 for name in HISTORY_FEATURES}
        base = race_features(card, venues)
        return {e.car_number: base[e.car_number] | history.get(e.name, empty)
                for e in card.entries}
