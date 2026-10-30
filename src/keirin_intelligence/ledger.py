"""Append-only shadow ledger: predictions frozen (hashed) before the betting cutoff.

The note's track record must come only from this ledger, so every published
hit rate includes the misses and nothing is selected after the fact.
"""

import hashlib
import json
from datetime import datetime
from pathlib import Path

from keirin_intelligence.domain import require_aware
from keirin_intelligence.evaluation import TRIFECTA_TOP_N
from keirin_intelligence.governance import GateRejected
from keirin_intelligence.model import RacePrediction
from keirin_intelligence.racecard import RaceCard, RaceResult


def _canonical(payload: dict) -> str:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def freeze(
    ledger_path: Path,
    card: RaceCard,
    pred: RacePrediction,
    model_weights: dict[str, float],
    frozen_at: datetime,
) -> dict:
    require_aware(frozen_at, "frozen_at")
    if frozen_at >= card.betting_cutoff_at:
        raise GateRejected("cannot freeze a prediction at or after the betting cutoff")
    if card.entered_at > frozen_at or card.observed_at > frozen_at:
        raise GateRejected("race card was entered after the freeze time")
    existing = read(ledger_path)
    if any(row["payload"]["race_id"] == card.race_id for row in existing):
        raise GateRejected(f"{card.race_id} already frozen; corrections must be new races")
    top_trifecta = sorted(pred.trifecta, key=pred.trifecta.get, reverse=True)[:TRIFECTA_TOP_N]
    payload = {
        "race_id": card.race_id,
        "frozen_at": frozen_at.isoformat(),
        "betting_cutoff_at": card.betting_cutoff_at.isoformat(),
        "weights": model_weights,
        "ranked": pred.ranked(),
        "win": {str(c): round(p, 6) for c, p in pred.win.items()},
        "exacta_top1": list(max(pred.exacta, key=pred.exacta.get)),
        "trifecta_top": [list(t) for t in top_trifecta],
        "previous_sha256": existing[-1]["sha256"] if existing else None,
    }
    row = {"payload": payload, "sha256": hashlib.sha256(_canonical(payload).encode()).hexdigest()}
    ledger_path.parent.mkdir(parents=True, exist_ok=True)
    with ledger_path.open("a", encoding="utf-8") as f:
        f.write(_canonical(row) + "\n")
    return row


def read(ledger_path: Path) -> list[dict]:
    if not ledger_path.exists():
        return []
    rows = [json.loads(line) for line in ledger_path.read_text(encoding="utf-8").splitlines()
            if line.strip()]
    previous = None
    for row in rows:
        if hashlib.sha256(_canonical(row["payload"]).encode()).hexdigest() != row["sha256"]:
            raise GateRejected(f"ledger tampering detected at {row['payload']['race_id']}")
        if row["payload"]["previous_sha256"] != previous:
            raise GateRejected(f"ledger chain broken at {row['payload']['race_id']}")
        previous = row["sha256"]
    return rows


def track_record(ledger_path: Path, results: dict[str, RaceResult]) -> dict[str, int]:
    """Counts over ALL settled frozen predictions (no cherry-picking)."""
    record = {"settled": 0, "pending": 0, "honmei_win": 0, "honmei_top3": 0,
              "exacta_hit": 0, "trifecta_hit": 0}
    for row in read(ledger_path):
        p = row["payload"]
        result = results.get(p["race_id"])
        if result is None or not result.order:
            record["pending"] += 1
            continue
        record["settled"] += 1
        record["honmei_win"] += p["ranked"][0] == result.order[0]
        record["honmei_top3"] += p["ranked"][0] in result.order[:3]
        record["exacta_hit"] += p["exacta_top1"] == list(result.order[:2])
        record["trifecta_hit"] += list(result.order[:3]) in p["trifecta_top"]
    return record
