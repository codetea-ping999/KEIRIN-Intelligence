from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from keirin_intelligence.etl import FileDropAdapter, RateLimiter, Store, ingest
from keirin_intelligence.governance import GateRejected
from keirin_intelligence.rights import AuditLog, Purpose, RightsGate, RightsRecord

TEMPLATES = Path(__file__).resolve().parents[1] / "data" / "templates"
NOW = datetime(2026, 11, 19, 12, tzinfo=UTC)
LICENSED = RightsRecord("licensed.example", "approved", "AGR-TEST", True, True, True)


@pytest.fixture
def env(tmp_path):
    gate = RightsGate({LICENSED.source_id: LICENSED}, AuditLog(tmp_path / "audit.jsonl"))
    return Store(tmp_path / "store"), gate, tmp_path


def adapter(paths, source="licensed.example", contract="AGR-TEST"):
    return FileDropAdapter(source, contract, paths, NOW - timedelta(hours=3))


def template_files():
    return [TEMPLATES / n for n in ("races.csv", "entries.csv", "results.csv")]


def test_rerunning_the_same_input_does_not_duplicate_records(env):
    store, gate, _ = env
    first = ingest(adapter(template_files()), store, gate, now=NOW)
    records = store.count("records")
    assert records > 0 and all(r.status == "ingested" for r in first)
    second = ingest(adapter(template_files()), store, gate, now=NOW + timedelta(hours=1))
    assert all(r.status == "duplicate_object" for r in second)
    assert store.count("records") == records and store.count("batches") == 3


def test_changed_row_becomes_a_new_version_and_same_rows_are_unchanged(env, tmp_path):
    store, gate, _ = env
    ingest(adapter([TEMPLATES / "entries.csv"]), store, gate, now=NOW)
    lines = (TEMPLATES / "entries.csv").read_text(encoding="utf-8").splitlines()
    changed = tmp_path / "drop" / "entries.csv"
    changed.parent.mkdir()
    lines[1] = lines[1].replace("105.20", "106.00")  # score correction for car 1
    changed.write_text("\n".join(lines) + "\n", encoding="utf-8")
    [report] = ingest(adapter([changed]), store, gate, now=NOW + timedelta(hours=1))
    assert (report.inserted, report.changed, report.unchanged) == (0, 1, len(lines) - 2)
    versions = [r["version"] for r in store.records("entry") if r["natural_key"] == "EXAMPLE-0001#1"]
    assert versions == [1, 2]


def test_bad_rows_go_to_quarantine(env, tmp_path):
    store, gate, _ = env
    bad = tmp_path / "results.csv"
    bad.write_text("race_id,car,finish\nR1,1,1\nR1,12,2\nR1,1,3\n,2,2\n", encoding="utf-8")
    [report] = ingest(adapter([bad]), store, gate, now=NOW)
    assert (report.inserted, report.quarantined) == (1, 3)
    assert store.count("quarantine") == 3
    assert any("duplicate key" in r for r in report.reasons)


@pytest.mark.parametrize(("source", "contract", "reason"), [
    ("unlicensed.example", "", "unknown source"),
    ("licensed.example", "AGR-OTHER", "current agreement"),
    ("SYNTHETIC", "", "synthetic"),
])
def test_input_without_rights_is_never_stored(env, source, contract, reason):
    store, gate, _ = env
    with pytest.raises(GateRejected, match=reason):
        ingest(adapter(template_files(), source, contract), store, gate, now=NOW)
    assert store.count("batches") == store.count("records") == 0
    assert not store.raw_dir.exists()
    assert gate.audit.read()[-1]["payload"]["allowed"] is False


def test_research_purpose_can_ingest_synthetic_data_but_marks_it(env):
    store, gate, _ = env
    ingest(adapter(template_files(), "SYNTHETIC", ""), store, gate, now=NOW,
           purpose=Purpose.RESEARCH)
    assert store.count("records") > 0
    assert all(r["synthetic"] == 1 for r in store.records())


def test_raw_object_is_kept_by_hash(env):
    store, gate, _ = env
    [report] = ingest(adapter([TEMPLATES / "races.csv"]), store, gate, now=NOW)
    raw = store.raw_dir / "licensed.example" / report.sha256
    assert raw.read_bytes() == (TEMPLATES / "races.csv").read_bytes()


def test_rate_limiter_spaces_calls():
    clock, slept = [0.0], []
    limiter = RateLimiter(2.0, clock=lambda: clock[0],
                          sleep=lambda s: (slept.append(s), clock.__setitem__(0, clock[0] + s)))
    limiter.wait()
    clock[0] += 0.5
    limiter.wait()
    assert slept == [1.5]
