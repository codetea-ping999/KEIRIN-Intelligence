"""Hand-entered real race cards (races.csv / entries.csv / results.csv).

Real data enters this project only as rows a person typed from a public race card.
Automated retrieval is out of scope: keirin.jp disallows robots, and other sites'
terms must be reviewed per docs/DATA_LICENSING.md before any automation.
"""

import csv
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

from keirin_intelligence.domain import require_aware

STYLES = {"逃", "両", "追"}


@dataclass(frozen=True)
class CardEntry:
    car_number: int
    name: str
    rider_class: str
    prefecture: str
    score: float
    style: str
    line_group: int
    line_pos: int

    def __post_init__(self) -> None:
        if not 1 <= self.car_number <= 9:
            raise ValueError(f"car_number must be 1-9: {self.car_number}")
        if self.style not in STYLES:
            raise ValueError(f"style must be one of {sorted(STYLES)}: {self.style!r}")
        if not 0 < self.score < 200:
            raise ValueError(f"score out of range for car {self.car_number}: {self.score}")
        if self.line_group < 1 or self.line_pos < 1:
            raise ValueError(f"line_group/line_pos must be positive for car {self.car_number}")


@dataclass(frozen=True)
class RaceCard:
    race_id: str
    race_date: date
    venue: str
    race_number: int
    grade: str
    betting_cutoff_at: datetime
    source: str
    observed_at: datetime
    entered_at: datetime
    entries: tuple[CardEntry, ...]

    def __post_init__(self) -> None:
        for name in ("betting_cutoff_at", "observed_at", "entered_at"):
            require_aware(getattr(self, name), name)
        cars = [e.car_number for e in self.entries]
        if len(cars) < 2 or len(set(cars)) != len(cars):
            raise ValueError(f"{self.race_id}: need >=2 entries with unique car numbers")
        lines: dict[int, list[int]] = defaultdict(list)
        for e in self.entries:
            lines[e.line_group].append(e.line_pos)
        for group, positions in lines.items():
            if sorted(positions) != list(range(1, len(positions) + 1)):
                raise ValueError(f"{self.race_id}: line {group} positions must be 1..n")

    @property
    def label(self) -> str:
        return f"{self.venue} {self.race_number}R"

    def lines(self) -> list[list[CardEntry]]:
        """Lines ordered by group number, each ordered front to back."""
        grouped: dict[int, list[CardEntry]] = defaultdict(list)
        for e in self.entries:
            grouped[e.line_group].append(e)
        return [sorted(grouped[g], key=lambda e: e.line_pos) for g in sorted(grouped)]

    def formation(self) -> str:
        """Japanese-style line notation, e.g. '1-4 / 7-2-5 / 3'."""
        return " / ".join("-".join(str(e.car_number) for e in line) for line in self.lines())


@dataclass(frozen=True)
class RaceResult:
    race_id: str
    order: tuple[int, ...]  # car numbers finishing 1st, 2nd, 3rd... (DNF/DSQ omitted)


def _parse_dt(value: str, field: str) -> datetime:
    parsed = datetime.fromisoformat(value.strip())
    require_aware(parsed, field)
    return parsed


def _read(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as f:
        return [{k.strip(): (v or "").strip() for k, v in row.items()} for row in csv.DictReader(f)]


def load_cards(data_dir: Path) -> dict[str, RaceCard]:
    entries_by_race: dict[str, list[CardEntry]] = defaultdict(list)
    for row in _read(data_dir / "entries.csv"):
        entries_by_race[row["race_id"]].append(
            CardEntry(
                car_number=int(row["car"]),
                name=row["name"],
                rider_class=row["rider_class"],
                prefecture=row["prefecture"],
                score=float(row["score"]),
                style=row["style"],
                line_group=int(row["line_group"]),
                line_pos=int(row["line_pos"]),
            )
        )
    cards: dict[str, RaceCard] = {}
    for row in _read(data_dir / "races.csv"):
        race_id = row["race_id"]
        if race_id in cards:
            raise ValueError(f"duplicate race_id {race_id}")
        cards[race_id] = RaceCard(
            race_id=race_id,
            race_date=date.fromisoformat(row["race_date"]),
            venue=row["venue"],
            race_number=int(row["race_number"]),
            grade=row["grade"],
            betting_cutoff_at=_parse_dt(row["betting_cutoff_at"], "betting_cutoff_at"),
            source=row["source"],
            observed_at=_parse_dt(row["observed_at"], "observed_at"),
            entered_at=_parse_dt(row["entered_at"], "entered_at"),
            entries=tuple(sorted(entries_by_race.pop(race_id, []), key=lambda e: e.car_number)),
        )
    if entries_by_race:
        raise ValueError(f"entries without races.csv row: {sorted(entries_by_race)}")
    return cards


def load_results(data_dir: Path) -> dict[str, RaceResult]:
    path = data_dir / "results.csv"
    if not path.exists():
        return {}
    finishes: dict[str, list[tuple[int, int]]] = defaultdict(list)
    for row in _read(path):
        if row["finish"] and int(row["finish"]) > 0:
            finishes[row["race_id"]].append((int(row["finish"]), int(row["car"])))
    return {
        race_id: RaceResult(race_id, tuple(car for _, car in sorted(rows)))
        for race_id, rows in finishes.items()
    }
