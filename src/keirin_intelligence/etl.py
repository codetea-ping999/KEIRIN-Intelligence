"""Idempotent ingestion of licensed race data (Issue #5).

Flow per raw object: rights gate (fail-closed, audited) -> content hash -> skip if this
exact object was already ingested -> keep the raw bytes under their hash -> validate rows
-> bad rows to quarantine, new or changed rows become new record versions, identical rows
are counted as unchanged. Re-running the same input never duplicates records.

The store is SQLite (stdlib) so the pipeline runs anywhere; the PostgreSQL schema in
db/migrations mirrors the same batch / snapshot / quarantine idea for production.
No network adapter exists yet: none is allowed until a source is approved (Issue #2).
"""

import csv
import hashlib
import io
import json
import sqlite3
import time
from collections.abc import Callable, Iterable, Iterator
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Protocol

from keirin_intelligence.domain import require_aware
from keirin_intelligence.racecard import STYLES
from keirin_intelligence.rights import Provenance, Purpose, RightsGate

SYNTHETIC_SOURCE = "SYNTHETIC"


@dataclass(frozen=True)
class RawObject:
    source_id: str
    contract_id: str
    name: str  # races.csv / entries.csv / results.csv
    content: bytes
    observed_at: datetime  # when the provider published this version

    def __post_init__(self) -> None:
        require_aware(self.observed_at, "observed_at")

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.content).hexdigest()


class SourceAdapter(Protocol):
    source_id: str

    def fetch(self) -> Iterable[RawObject]: ...


class RateLimiter:
    """At most one call per `min_interval` seconds (per adapter)."""

    def __init__(self, min_interval: float, clock: Callable[[], float] = time.monotonic,
                 sleep: Callable[[float], None] = time.sleep) -> None:
        self.min_interval, self.clock, self.sleep = min_interval, clock, sleep
        self._last: float | None = None

    def wait(self) -> None:
        now = self.clock()
        if self._last is not None and now - self._last < self.min_interval:
            self.sleep(self.min_interval - (now - self._last))
            now = self.clock()
        self._last = now


@dataclass
class FileDropAdapter:
    """Files delivered by a provider (or typed by hand) into a folder: the compliant path."""

    source_id: str
    contract_id: str
    paths: list[Path]
    observed_at: datetime
    limiter: RateLimiter | None = None

    def fetch(self) -> Iterator[RawObject]:
        for path in self.paths:
            if self.limiter:
                self.limiter.wait()
            yield RawObject(self.source_id, self.contract_id, path.name, path.read_bytes(),
                            self.observed_at)


# ---- row validation: returns (natural key, normalized payload) or raises ValueError ----

def _aware(value: str, name: str) -> str:
    parsed = datetime.fromisoformat(value)
    require_aware(parsed, name)
    return parsed.isoformat()


def _race(row: dict[str, str]) -> tuple[str, dict]:
    if not row.get("race_id"):
        raise ValueError("race_id missing")
    payload = {
        "race_id": row["race_id"],
        "race_date": date.fromisoformat(row["race_date"]).isoformat(),
        "venue": row["venue"] or _missing("venue"),
        "race_number": _int_range(row["race_number"], 1, 99, "race_number"),
        "grade": row.get("grade", ""),
        "betting_cutoff_at": _aware(row["betting_cutoff_at"], "betting_cutoff_at"),
        "back_wind_mps": float(row["back_wind_mps"]) if row.get("back_wind_mps") else None,
        "wet": {"1": True, "0": False}.get(row.get("wet", "")),
    }
    return row["race_id"], payload


def _entry(row: dict[str, str]) -> tuple[str, dict]:
    car = _int_range(row["car"], 1, 9, "car")
    score = float(row["score"])
    if not 0 < score < 200:
        raise ValueError(f"score out of range: {score}")
    if row["style"] not in STYLES:
        raise ValueError(f"unknown style {row['style']!r}")
    payload = {
        "race_id": row["race_id"] or _missing("race_id"), "car": car,
        "name": row["name"] or _missing("name"), "rider_class": row["rider_class"],
        "prefecture": row["prefecture"], "score": score, "style": row["style"],
        "line_group": _int_range(row["line_group"], 1, 9, "line_group"),
        "line_pos": _int_range(row["line_pos"], 1, 9, "line_pos"),
        "status": row.get("status") or "entered",
    }
    if payload["status"] not in ("entered", "withdrawn"):
        raise ValueError(f"unknown status {payload['status']!r}")
    return f"{payload['race_id']}#{car}", payload


def _result(row: dict[str, str]) -> tuple[str, dict]:
    car = _int_range(row["car"], 1, 9, "car")
    if "finish" not in row:
        raise ValueError("finish column missing")
    finish = int(row["finish"]) if row["finish"] else 0
    if finish < 0:
        raise ValueError("finish must be >= 0 (0 = did not finish)")
    payload = {"race_id": row["race_id"] or _missing("race_id"), "car": car, "finish": finish}
    return f"{payload['race_id']}#{car}", payload


def _int_range(value: str, lo: int, hi: int, name: str) -> int:
    number = int(value)
    if not lo <= number <= hi:
        raise ValueError(f"{name} must be {lo}-{hi}: {number}")
    return number


def _missing(name: str):
    raise ValueError(f"{name} missing")


PARSERS: dict[str, tuple[str, Callable[[dict[str, str]], tuple[str, dict]]]] = {
    "races.csv": ("race", _race),
    "entries.csv": ("entry", _entry),
    "results.csv": ("result", _result),
}

SCHEMA = """
CREATE TABLE IF NOT EXISTS batches (
    batch_id INTEGER PRIMARY KEY, source_id TEXT NOT NULL, contract_id TEXT NOT NULL,
    name TEXT NOT NULL, sha256 TEXT NOT NULL, raw_path TEXT NOT NULL,
    observed_at TEXT NOT NULL, ingested_at TEXT NOT NULL,
    inserted INTEGER NOT NULL, changed INTEGER NOT NULL, unchanged INTEGER NOT NULL,
    quarantined INTEGER NOT NULL, UNIQUE(source_id, sha256));
CREATE TABLE IF NOT EXISTS records (
    record_id INTEGER PRIMARY KEY, kind TEXT NOT NULL, natural_key TEXT NOT NULL,
    version INTEGER NOT NULL, content_sha256 TEXT NOT NULL, payload TEXT NOT NULL,
    source_id TEXT NOT NULL, contract_id TEXT NOT NULL, synthetic INTEGER NOT NULL,
    observed_at TEXT NOT NULL, ingested_at TEXT NOT NULL,
    batch_id INTEGER NOT NULL REFERENCES batches(batch_id),
    UNIQUE(kind, natural_key, version));
CREATE TABLE IF NOT EXISTS quarantine (
    batch_id INTEGER NOT NULL REFERENCES batches(batch_id), row_number INTEGER NOT NULL,
    reason TEXT NOT NULL, raw_row TEXT NOT NULL, PRIMARY KEY(batch_id, row_number));
"""


@dataclass
class BatchReport:
    name: str
    sha256: str
    status: str  # ingested / duplicate_object
    inserted: int = 0
    changed: int = 0
    unchanged: int = 0
    quarantined: int = 0
    reasons: list[str] = field(default_factory=list)


class Store:
    """SQLite record store. Writes happen only through `ingest`, which runs the rights gate."""

    def __init__(self, root: Path) -> None:
        root.mkdir(parents=True, exist_ok=True)
        self.root = root
        self.raw_dir = root / "raw"
        self.db = sqlite3.connect(root / "store.sqlite3")
        self.db.executescript(SCHEMA)

    def latest(self, kind: str, key: str) -> tuple[int, str, str, str] | None:
        """(version, content hash, source_id, contract_id) of the newest version."""
        return self.db.execute(
            "SELECT version, content_sha256, source_id, contract_id FROM records "
            "WHERE kind=? AND natural_key=? "
            "ORDER BY version DESC LIMIT 1", (kind, key)).fetchone()

    def records(self, kind: str | None = None) -> list[dict]:
        sql = ("SELECT kind, natural_key, version, payload, source_id, contract_id, synthetic, "
               "observed_at, ingested_at FROM records")
        rows = self.db.execute(sql + (" WHERE kind=?" if kind else "") + " ORDER BY record_id",
                               (kind,) if kind else ()).fetchall()
        cols = ("kind", "natural_key", "version", "payload", "source_id", "contract_id",
                "synthetic", "observed_at", "ingested_at")
        return [dict(zip(cols, r, strict=True)) | {"payload": json.loads(r[3])} for r in rows]

    def count(self, table: str) -> int:
        assert table in ("batches", "records", "quarantine")
        return self.db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]


def ingest(
    adapter: SourceAdapter,
    store: Store,
    gate: RightsGate,
    *,
    now: datetime,
    purpose: Purpose = Purpose.INGEST,
) -> list[BatchReport]:
    """Ingest every raw object from the adapter. Raises GateRejected before storing anything
    from an object whose rights do not cover `purpose`."""
    require_aware(now, "now")
    reports = []
    for raw in adapter.fetch():
        if raw.name not in PARSERS:
            raise ValueError(f"no parser for {raw.name}; expected one of {sorted(PARSERS)}")
        prov = Provenance(raw.source_id, raw.observed_at, now, contract_id=raw.contract_id,
                          raw_sha256=raw.sha256, synthetic=raw.source_id == SYNTHETIC_SOURCE)
        gate.require(prov, purpose, now)
        reports.append(_ingest_one(store, raw, prov, now))
    return reports


def _ingest_one(store: Store, raw: RawObject, prov: Provenance, now: datetime) -> BatchReport:
    report = BatchReport(raw.name, raw.sha256, "ingested")
    if store.db.execute("SELECT 1 FROM batches WHERE source_id=? AND sha256=?",
                        (raw.source_id, raw.sha256)).fetchone():
        report.status = "duplicate_object"
        return report
    raw_path = store.raw_dir / raw.source_id / raw.sha256
    raw_path.parent.mkdir(parents=True, exist_ok=True)
    if not raw_path.exists():
        raw_path.write_bytes(raw.content)
    kind, parse = PARSERS[raw.name]
    text = raw.content.decode("utf-8-sig")
    rows = [{k.strip(): (v or "").strip() for k, v in r.items() if k}
            for r in csv.DictReader(io.StringIO(text))]
    with store.db:
        batch_id = store.db.execute(
            "INSERT INTO batches(source_id, contract_id, name, sha256, raw_path, observed_at, "
            "ingested_at, inserted, changed, unchanged, quarantined) VALUES (?,?,?,?,?,?,?,0,0,0,0)",
            (raw.source_id, raw.contract_id, raw.name, raw.sha256, str(raw_path),
             raw.observed_at.isoformat(), now.isoformat())).lastrowid
        seen_keys: set[str] = set()
        for number, row in enumerate(rows, start=2):  # row 1 is the header
            try:
                key, payload = parse(row)
                if key in seen_keys:
                    raise ValueError(f"duplicate key {key} within the same file")
            except (ValueError, KeyError) as err:
                report.quarantined += 1
                report.reasons.append(f"row {number}: {err}")
                store.db.execute("INSERT INTO quarantine VALUES (?,?,?,?)",
                                 (batch_id, number, str(err), json.dumps(row, ensure_ascii=False)))
                continue
            seen_keys.add(key)
            body = json.dumps(payload, ensure_ascii=False, sort_keys=True)
            content_sha = hashlib.sha256(body.encode()).hexdigest()
            latest = store.latest(kind, key)
            # Same content from a different source or agreement is a new version: the
            # provenance (e.g. licensed vs. synthetic) is part of what we must keep.
            if latest is not None and latest[1:] == (content_sha, prov.source_id,
                                                     prov.contract_id):
                report.unchanged += 1
                continue
            version = 1 if latest is None else latest[0] + 1
            if latest is None:
                report.inserted += 1
            else:
                report.changed += 1
            store.db.execute(
                "INSERT INTO records(kind, natural_key, version, content_sha256, payload, "
                "source_id, contract_id, synthetic, observed_at, ingested_at, batch_id) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (kind, key, version, content_sha, body, prov.source_id, prov.contract_id,
                 int(prov.synthetic), prov.observed_at.isoformat(), now.isoformat(), batch_id))
        store.db.execute(
            "UPDATE batches SET inserted=?, changed=?, unchanged=?, quarantined=? WHERE batch_id=?",
            (report.inserted, report.changed, report.unchanged, report.quarantined, batch_id))
    return report
