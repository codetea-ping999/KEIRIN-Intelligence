import importlib.util
from pathlib import Path

from keirin_intelligence.model import LineAwareModel
from keirin_intelligence.racecard import default_velodromes, load_cards

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("sarashina_check", ROOT / "scripts" / "sarashina_check.py")
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

CARD = load_cards(ROOT / "data" / "templates")["EXAMPLE-0001"]
PRED = LineAwareModel(venues=default_velodromes()).predict(CARD)
PROMPT = mod.build_prompt(CARD, PRED, None)


def test_prompt_contains_only_card_facts():
    assert "4-1-6 / 2-5-7 / 3" in PROMPT and "架空 一郎" in PROMPT and "バンク情報なし" in PROMPT


def test_guard_accepts_grounded_reply():
    assert mod.check_reply(PROMPT, "4-1-6のラインが中心と推定されます。") == []


def test_guard_flags_guarantee_and_invented_numbers():
    problems = mod.check_reply(PROMPT, "必ず当たる。回収率は 187% です。")
    assert any("保証" in p for p in problems) and any("数値" in p for p in problems)
