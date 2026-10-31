import json
import shutil
from datetime import timedelta
from pathlib import Path

import pytest

from keirin_intelligence import ledger
from keirin_intelligence.cli import main
from keirin_intelligence.governance import GateRejected
from keirin_intelligence.model import LineAwareModel
from keirin_intelligence.note import render_note
from keirin_intelligence.racecard import RaceResult, load_cards

TEMPLATES = Path(__file__).resolve().parents[1] / "data" / "templates"
CARD = load_cards(TEMPLATES)["EXAMPLE-0001"]
PRED = LineAwareModel().predict(CARD)
BEFORE = CARD.betting_cutoff_at - timedelta(minutes=30)


def test_freeze_rejects_after_cutoff(tmp_path):
    with pytest.raises(GateRejected, match="cutoff"):
        ledger.freeze(tmp_path / "l.jsonl", CARD, PRED, {}, CARD.betting_cutoff_at)


def test_freeze_once_and_detect_tampering(tmp_path):
    path = tmp_path / "l.jsonl"
    ledger.freeze(path, CARD, PRED, {}, BEFORE)
    with pytest.raises(GateRejected, match="already frozen"):
        ledger.freeze(path, CARD, PRED, {}, BEFORE)
    row = json.loads(path.read_text(encoding="utf-8"))
    row["payload"]["ranked"] = list(reversed(row["payload"]["ranked"]))
    path.write_text(json.dumps(row, ensure_ascii=False) + "\n", encoding="utf-8")
    with pytest.raises(GateRejected, match="tampering"):
        ledger.read(path)


def test_track_record_counts_misses_and_pending(tmp_path):
    path = tmp_path / "l.jsonl"
    ledger.freeze(path, CARD, PRED, {}, BEFORE)
    assert ledger.track_record(path, {})["pending"] == 1
    loser_first = PRED.ranked()[-1]
    record = ledger.track_record(path, {CARD.race_id: RaceResult(CARD.race_id, (loser_first, 1, 4))})
    assert record["settled"] == 1 and record["honmei_win"] == 0


def test_note_has_required_disclaimers():
    text = render_note(CARD, PRED)
    for phrase in ("エンタメ", "保証するものではありません", "20歳以上", "相談窓口", "外れも含む"):
        assert phrase in text


def test_note_refuses_guarantee_wording():
    with pytest.raises(ValueError, match="prohibited"):
        render_note(CARD, PRED, model_label="必勝モデル")


def test_cli_note_and_freeze(tmp_path, capsys):
    shutil.copytree(TEMPLATES, tmp_path, dirs_exist_ok=True)
    out = tmp_path / "drafts" / "note.md"
    assert main(["--data", str(tmp_path), "note", "EXAMPLE-0001", "--out", str(out)]) == 0
    assert "データ分析ノート" in out.read_text(encoding="utf-8")
