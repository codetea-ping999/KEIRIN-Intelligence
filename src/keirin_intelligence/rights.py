"""Persistent rights registry, fail-closed boundary checks and a tamper-evident audit log.

Every boundary that touches data (ETL, training, publication) asks `RightsGate.check`
with the record's provenance and the purpose. The answer is logged to an append-only,
hash-chained JSONL file before the caller proceeds, so every refusal and every approval
can be audited later. Anything unknown, unverified, expired, revoked, synthetic (for a
commercial purpose) or observed after the decision time is refused.

This is an engineering guard, not legal advice. A permission only becomes `approved`
in `data/reference/rights_registry.csv` once a written agreement exists (Issue #2).
"""

import csv
import hashlib
import json
import os
from dataclasses import asdict, dataclass
from datetime import datetime
from enum import StrEnum
from pathlib import Path

from keirin_intelligence.domain import require_aware
from keirin_intelligence.governance import GateRejected

DEFAULT_REGISTRY = (
    Path(__file__).resolve().parents[2] / "data" / "reference" / "rights_registry.csv"
)
KILL_SWITCH_ENV = "KEIRIN_COMMERCIAL_KILL_SWITCH"
STATUSES = {"unverified", "approved", "expired", "revoked"}


class Purpose(StrEnum):
    """What the data is about to be used for. Only RESEARCH is non-commercial."""

    RESEARCH = "research"  # local analysis, never sold or published for money
    INGEST = "ingest"  # store in the commercial data store
    TRAIN = "train"  # fit a model that will be used commercially
    PUBLISH = "publish"  # paid note article or any derivative sale

    @property
    def commercial(self) -> bool:
        return self is not Purpose.RESEARCH


_REQUIRED_FLAGS = {
    Purpose.INGEST: ("allowed_storage",),
    Purpose.TRAIN: ("allowed_storage", "allowed_training"),
    Purpose.PUBLISH: ("allowed_storage", "allowed_training", "allowed_derived_sales"),
}


@dataclass(frozen=True)
class RightsRecord:
    """One row of the rights registry: what a source's written agreement allows."""

    source_id: str
    permission_status: str
    agreement_reference: str = ""
    allowed_storage: bool = False
    allowed_training: bool = False
    allowed_derived_sales: bool = False
    reviewed_at: datetime | None = None
    expires_at: datetime | None = None
    revoked_at: datetime | None = None

    def __post_init__(self) -> None:
        if self.permission_status not in STATUSES:
            raise ValueError(f"{self.source_id}: unknown permission_status {self.permission_status!r}")
        for name in ("reviewed_at", "expires_at", "revoked_at"):
            value = getattr(self, name)
            if value is not None:
                require_aware(value, name)


@dataclass(frozen=True)
class Provenance:
    """Where a record came from and when it became knowable."""

    source_id: str
    observed_at: datetime  # when the fact was published / observed at the source
    ingested_at: datetime  # when it entered our store
    contract_id: str = ""  # agreement reference the record was obtained under
    raw_sha256: str = ""  # hash of the raw object it was parsed from
    synthetic: bool = False

    def __post_init__(self) -> None:
        require_aware(self.observed_at, "observed_at")
        require_aware(self.ingested_at, "ingested_at")


@dataclass(frozen=True)
class Decision:
    allowed: bool
    reason: str
    source_id: str
    purpose: str
    decided_at: datetime
    contract_id: str = ""


def _parse_dt(value: str) -> datetime | None:
    return datetime.fromisoformat(value) if value.strip() else None


def load_registry(path: Path = DEFAULT_REGISTRY) -> dict[str, RightsRecord]:
    with path.open(encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))
    registry: dict[str, RightsRecord] = {}
    for row in rows:
        record = RightsRecord(
            source_id=row["source_id"],
            permission_status=row["permission_status"],
            agreement_reference=row["agreement_reference"],
            allowed_storage=row["allowed_storage"] == "1",
            allowed_training=row["allowed_training"] == "1",
            allowed_derived_sales=row["allowed_derived_sales"] == "1",
            reviewed_at=_parse_dt(row["reviewed_at"]),
            expires_at=_parse_dt(row["expires_at"]),
            revoked_at=_parse_dt(row["revoked_at"]),
        )
        if record.source_id in registry:
            raise ValueError(f"duplicate source_id {record.source_id}")
        registry[record.source_id] = record
    return registry


def kill_switch_engaged(flag_file: Path | None = None) -> bool:
    """Commercial processing stops when the env var is set or the flag file exists."""
    if os.environ.get(KILL_SWITCH_ENV, "").strip() not in ("", "0"):
        return True
    return flag_file is not None and flag_file.exists()


def _canonical(payload: dict) -> str:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


class AuditLog:
    """Append-only JSONL; each row carries the previous row's hash, so edits are detected."""

    def __init__(self, path: Path) -> None:
        self.path = path

    def append(self, decision: Decision) -> dict:
        rows = self.read()
        payload = asdict(decision) | {
            "decided_at": decision.decided_at.isoformat(),
            "previous_sha256": rows[-1]["sha256"] if rows else None,
        }
        row = {"payload": payload, "sha256": hashlib.sha256(_canonical(payload).encode()).hexdigest()}
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as f:
            f.write(_canonical(row) + "\n")
        return row

    def read(self) -> list[dict]:
        if not self.path.exists():
            return []
        rows = [json.loads(line) for line in self.path.read_text(encoding="utf-8").splitlines()
                if line.strip()]
        previous = None
        for i, row in enumerate(rows):
            if hashlib.sha256(_canonical(row["payload"]).encode()).hexdigest() != row["sha256"]:
                raise GateRejected(f"audit log tampering detected at row {i}")
            if row["payload"]["previous_sha256"] != previous:
                raise GateRejected(f"audit log chain broken at row {i}")
            previous = row["sha256"]
        return rows


class RightsGate:
    def __init__(
        self,
        registry: dict[str, RightsRecord],
        audit: AuditLog,
        *,
        kill_switch_file: Path | None = None,
    ) -> None:
        self.registry = registry
        self.audit = audit
        self.kill_switch_file = kill_switch_file

    def evaluate(self, prov: Provenance, purpose: Purpose, at: datetime) -> Decision:
        """Pure decision (no logging). The first failing rule is the recorded reason."""
        require_aware(at, "at")

        def no(reason: str) -> Decision:
            return Decision(False, reason, prov.source_id, purpose.value, at, prov.contract_id)

        if prov.observed_at > at or prov.ingested_at > at:
            return no("lookahead: record observed or ingested after the decision time")
        if prov.ingested_at < prov.observed_at:
            return no("inconsistent provenance: ingested before it was observed")
        if not purpose.commercial:
            return Decision(True, "research use", prov.source_id, purpose.value, at, prov.contract_id)
        if kill_switch_engaged(self.kill_switch_file):
            return no("commercial kill switch engaged")
        if prov.synthetic:
            return no("synthetic data cannot be used commercially")
        record = self.registry.get(prov.source_id)
        if record is None:
            return no("unknown source: not in rights registry")
        if record.revoked_at is not None and at >= record.revoked_at:
            return no("permission revoked")
        if record.permission_status != "approved":
            return no(f"permission status is {record.permission_status}")
        if record.expires_at is not None and at >= record.expires_at:
            return no("permission expired")
        if not record.agreement_reference:
            return no("written agreement reference missing")
        if prov.contract_id != record.agreement_reference:
            return no("record was not obtained under the current agreement")
        missing = [flag for flag in _REQUIRED_FLAGS[purpose] if not getattr(record, flag)]
        if missing:
            return no(f"agreement does not allow: {', '.join(missing)}")
        return Decision(True, "approved agreement covers this use", prov.source_id,
                        purpose.value, at, prov.contract_id)

    def check(self, prov: Provenance, purpose: Purpose, at: datetime) -> Decision:
        """Decide, log the decision, and return it."""
        decision = self.evaluate(prov, purpose, at)
        self.audit.append(decision)
        return decision

    def require(self, prov: Provenance, purpose: Purpose, at: datetime) -> None:
        """Decide and log; raise GateRejected on refusal (fail-closed)."""
        decision = self.check(prov, purpose, at)
        if not decision.allowed:
            raise GateRejected(f"{prov.source_id} / {purpose.value}: {decision.reason}")


def reevaluate(gate: RightsGate, at: datetime) -> list[dict]:
    """Earlier commercial approvals that would now be refused (expiry, revocation, kill switch).

    Run after any registry change and on a schedule; every row returned means the
    derived data / models / articles from that source must be stopped (docs/RIGHTS_GATE.md).
    """
    require_aware(at, "at")
    stale, seen = [], set()
    for row in gate.audit.read():
        p = row["payload"]
        key = (p["source_id"], p["purpose"], p["contract_id"])
        if not p["allowed"] or p["purpose"] == Purpose.RESEARCH.value or key in seen:
            continue
        seen.add(key)
        probe = Provenance(p["source_id"], datetime.fromisoformat(p["decided_at"]),
                           datetime.fromisoformat(p["decided_at"]), contract_id=p["contract_id"])
        now = gate.evaluate(probe, Purpose(p["purpose"]), at)
        if not now.allowed:
            stale.append({"source_id": p["source_id"], "purpose": p["purpose"],
                          "contract_id": p["contract_id"], "reason": now.reason})
    return stale
