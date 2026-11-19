from datetime import UTC, datetime, timedelta

import pytest

from keirin_intelligence.etl import FileDropAdapter, Store, ingest
from keirin_intelligence.features import AsOfStore, Snapshot
from keirin_intelligence.governance import GateRejected
from keirin_intelligence.rights import AuditLog, Purpose, RightsGate

PAST_CUTOFF = datetime(2026, 11, 1, 7, 0, tzinfo=UTC)
CUTOFF = datetime(2026, 11, 3, 7, 0, tzinfo=UTC)
T = CUTOFF - timedelta(hours=2)  # prediction time


def snap(kind, key, payload, observed, ingested=None, version=1):
    return Snapshot(kind, key, version, payload, observed, ingested or observed, "test")


def race(race_id, cutoff, d):
    return {"race_id": race_id, "race_date": d, "venue": "架空バンク", "race_number": 11,
            "grade": "F1", "betting_cutoff_at": cutoff.isoformat(), "back_wind_mps": None,
            "wet": None}


def entry(race_id, car, name, group, pos, score=100.0, status="entered", style="追"):
    return {"race_id": race_id, "car": car, "name": name, "rider_class": "S1",
            "prefecture": "東京", "score": score, "style": style, "line_group": group,
            "line_pos": pos, "status": status}


def base_snapshots():
    known = T - timedelta(days=1)
    past = PAST_CUTOFF - timedelta(days=1)
    rows = [
        snap("race", "PAST", race("PAST", PAST_CUTOFF, "2026-11-01"), past),
        snap("entry", "PAST#1", entry("PAST", 1, "架空A", 1, 1, style="逃"), past),
        snap("entry", "PAST#2", entry("PAST", 2, "架空B", 1, 2), past),
        snap("result", "PAST#1", {"race_id": "PAST", "car": 1, "finish": 1},
             PAST_CUTOFF + timedelta(hours=1)),
        snap("result", "PAST#2", {"race_id": "PAST", "car": 2, "finish": 2},
             PAST_CUTOFF + timedelta(hours=1)),
        snap("race", "R", race("R", CUTOFF, "2026-11-03"), known),
    ]
    for car, name, group, pos in ((1, "架空A", 1, 1), (2, "架空B", 1, 2), (3, "架空C", 1, 3),
                                  (4, "架空D", 2, 1)):
        rows.append(snap("entry", f"R#{car}", entry("R", car, name, group, pos), known))
    return rows


def test_future_data_never_reaches_features():
    clean = AsOfStore(base_snapshots()).features("R", T)
    late = T + timedelta(minutes=1)
    poisoned = base_snapshots() + [
        # result of the target race, and a score change published after T
        snap("result", "R#4", {"race_id": "R", "car": 4, "finish": 1}, CUTOFF + timedelta(hours=1)),
        snap("entry", "R#1", entry("R", 1, "架空A", 1, 1, score=130.0), late, version=2),
        # observed before T but only ingested after T (late arrival)
        snap("entry", "R#2", entry("R", 2, "架空B", 1, 2, score=80.0),
             T - timedelta(hours=1), late, version=2),
        # a past race whose result only arrived after T must not count as history
        snap("race", "PAST2", race("PAST2", PAST_CUTOFF, "2026-11-01"), PAST_CUTOFF - timedelta(1)),
        snap("entry", "PAST2#1", entry("PAST2", 1, "架空D", 1, 1), PAST_CUTOFF - timedelta(1)),
        snap("result", "PAST2#1", {"race_id": "PAST2", "car": 1, "finish": 1}, late),
    ]
    assert AsOfStore(poisoned).features("R", T) == clean


def test_history_counts_only_settled_known_races():
    feats = AsOfStore(base_snapshots()).features("R", T)
    assert feats[1]["hist_starts"] == 1 and feats[1]["hist_win_rate"] == 1.0
    assert feats[2]["hist_top3_rate"] == 1.0 and feats[2]["hist_win_rate"] == 0.0
    assert feats[4]["hist_starts"] == 0.0


def test_withdrawal_and_line_change_are_versioned():
    store = AsOfStore(base_snapshots() + [
        snap("entry", "R#2", entry("R", 2, "架空B", 1, 2, status="withdrawn"),
             T - timedelta(hours=1), version=2),
        snap("entry", "R#4", entry("R", 4, "架空D", 1, 4), T + timedelta(hours=1), version=2),
    ])
    card = store.card_as_of("R", T)
    assert [e.car_number for e in card.entries] == [1, 3, 4]
    assert card.formation() == "1-3 / 4"  # car 3 moved up; car 4's later line change unseen
    earlier = store.card_as_of("R", T - timedelta(hours=3))
    assert [e.car_number for e in earlier.entries] == [1, 2, 3, 4]


def test_prediction_at_or_after_cutoff_or_before_card_is_refused():
    store = AsOfStore(base_snapshots())
    with pytest.raises(GateRejected, match="precede"):
        store.card_as_of("R", CUTOFF)
    with pytest.raises(GateRejected, match="not known"):
        store.card_as_of("R", T - timedelta(days=2))


def test_reads_from_the_etl_store(tmp_path):
    from pathlib import Path

    templates = Path(__file__).resolve().parents[1] / "data" / "templates"
    store = Store(tmp_path / "s")
    gate = RightsGate({}, AuditLog(tmp_path / "a.jsonl"))
    observed = datetime(2026, 11, 2, 9, tzinfo=UTC)
    ingest(FileDropAdapter("SYNTHETIC", "", [templates / "races.csv", templates / "entries.csv"],
                           observed), store, gate, now=observed + timedelta(hours=1),
           purpose=Purpose.RESEARCH)
    asof = AsOfStore.from_etl(store)
    feats = asof.features("EXAMPLE-0001", observed + timedelta(hours=2))
    assert len(feats) == 7 and all("hist_starts" in f for f in feats.values())
    with pytest.raises(GateRejected):  # ingested an hour after this instant
        asof.card_as_of("EXAMPLE-0001", observed + timedelta(minutes=30))
