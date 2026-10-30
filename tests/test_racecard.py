import shutil
from pathlib import Path

import pytest

from keirin_intelligence.racecard import load_cards, load_results

TEMPLATES = Path(__file__).resolve().parents[1] / "data" / "templates"


def test_template_card_loads_with_formation():
    card = load_cards(TEMPLATES)["EXAMPLE-0001"]
    assert len(card.entries) == 7
    assert card.formation() == "4-1-6 / 2-5-7 / 3"
    assert load_results(TEMPLATES) == {}


def test_broken_line_positions_rejected(tmp_path):
    shutil.copytree(TEMPLATES, tmp_path, dirs_exist_ok=True)
    entries = tmp_path / "entries.csv"
    entries.write_text(entries.read_text(encoding="utf-8").replace(",1,3\n", ",1,4\n"),
                       encoding="utf-8")
    with pytest.raises(ValueError, match="positions"):
        load_cards(tmp_path)


def test_naive_cutoff_rejected(tmp_path):
    shutil.copytree(TEMPLATES, tmp_path, dirs_exist_ok=True)
    races = tmp_path / "races.csv"
    races.write_text(races.read_text(encoding="utf-8").replace("16:25:00+09:00", "16:25:00"),
                     encoding="utf-8")
    with pytest.raises(ValueError, match="timezone-aware"):
        load_cards(tmp_path)


def test_results_order_skips_non_finishers(tmp_path):
    (tmp_path / "results.csv").write_text(
        "race_id,car,finish\nR,3,2\nR,5,1\nR,1,\nR,2,3\n", encoding="utf-8")
    assert load_results(tmp_path)["R"].order == (5, 3, 2)
