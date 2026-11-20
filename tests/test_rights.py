from datetime import UTC, datetime, timedelta

import pytest

from keirin_intelligence.governance import GateRejected
from keirin_intelligence.rights import (
    KILL_SWITCH_ENV,
    AuditLog,
    Provenance,
    Purpose,
    RightsGate,
    RightsRecord,
    load_registry,
    reevaluate,
)

NOW = datetime(2026, 11, 19, 12, tzinfo=UTC)
APPROVED = RightsRecord(
    "licensed.example", "approved", "AGR-001", True, True, True,
    reviewed_at=NOW - timedelta(days=30), expires_at=NOW + timedelta(days=365),
)


def prov(source="licensed.example", contract="AGR-001", **kw):
    base = {"observed_at": NOW - timedelta(hours=2), "ingested_at": NOW - timedelta(hours=1)}
    return Provenance(source, contract_id=contract, **(base | kw))


@pytest.fixture
def gate(tmp_path):
    return RightsGate({APPROVED.source_id: APPROVED}, AuditLog(tmp_path / "audit.jsonl"),
                      kill_switch_file=tmp_path / "KILL")


def test_approved_agreement_allows_all_commercial_purposes(gate):
    for purpose in (Purpose.INGEST, Purpose.TRAIN, Purpose.PUBLISH):
        gate.require(prov(), purpose, NOW)
    assert len(gate.audit.read()) == 3


@pytest.mark.parametrize(("record", "reason"), [
    (None, "unknown source"),
    (RightsRecord("licensed.example", "unverified"), "status is unverified"),
    (RightsRecord("licensed.example", "approved", "AGR-001", True, True, True,
                  expires_at=NOW - timedelta(seconds=1)), "expired"),
    (RightsRecord("licensed.example", "approved", "AGR-001", True, True, True,
                  revoked_at=NOW - timedelta(days=1)), "revoked"),
    (RightsRecord("licensed.example", "approved", "", True, True, True), "agreement reference"),
    (RightsRecord("licensed.example", "approved", "AGR-001", True, True, False), "derived_sales"),
])
def test_missing_or_lapsed_rights_fail_closed(tmp_path, record, reason):
    registry = {} if record is None else {record.source_id: record}
    gate = RightsGate(registry, AuditLog(tmp_path / "a.jsonl"))
    with pytest.raises(GateRejected, match=reason):
        gate.require(prov(), Purpose.PUBLISH, NOW)
    [row] = gate.audit.read()
    assert row["payload"]["allowed"] is False and reason in row["payload"]["reason"]


def test_lookahead_is_refused_even_for_research(gate):
    with pytest.raises(GateRejected, match="lookahead"):
        gate.require(prov(ingested_at=NOW + timedelta(minutes=1)), Purpose.RESEARCH, NOW)


def test_synthetic_and_wrong_contract_are_refused_commercially(gate):
    gate.require(prov(synthetic=True), Purpose.RESEARCH, NOW)
    with pytest.raises(GateRejected, match="synthetic"):
        gate.require(prov(synthetic=True), Purpose.TRAIN, NOW)
    with pytest.raises(GateRejected, match="current agreement"):
        gate.require(prov(contract="AGR-OLD"), Purpose.TRAIN, NOW)


def test_kill_switch_by_file_and_env(gate, monkeypatch):
    gate.kill_switch_file.write_text("stop")
    with pytest.raises(GateRejected, match="kill switch"):
        gate.require(prov(), Purpose.INGEST, NOW)
    gate.kill_switch_file.unlink()
    monkeypatch.setenv(KILL_SWITCH_ENV, "1")
    with pytest.raises(GateRejected, match="kill switch"):
        gate.require(prov(), Purpose.INGEST, NOW)


def test_audit_log_detects_edits(gate):
    gate.check(prov(), Purpose.INGEST, NOW)
    gate.check(prov(source="other"), Purpose.INGEST, NOW)
    lines = gate.audit.path.read_text().splitlines()
    gate.audit.path.write_text("\n".join([lines[0].replace('"allowed":true', '"allowed":false'),
                                          lines[1]]) + "\n")
    with pytest.raises(GateRejected, match="tampering"):
        gate.audit.read()


def test_reevaluate_lists_approvals_that_are_now_revoked(gate):
    gate.require(prov(), Purpose.PUBLISH, NOW)
    assert reevaluate(gate, NOW + timedelta(days=1)) == []
    gate.registry[APPROVED.source_id] = RightsRecord(
        "licensed.example", "revoked", "AGR-001", True, True, True,
        revoked_at=NOW + timedelta(hours=12))
    [stale] = reevaluate(gate, NOW + timedelta(days=1))
    assert stale["purpose"] == "publish" and "revoked" in stale["reason"]


def test_bundled_registry_approves_nothing_yet():
    registry = load_registry()
    assert "SYNTHETIC" in registry
    assert all(r.permission_status != "approved" for r in registry.values())
