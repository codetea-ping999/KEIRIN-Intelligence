from datetime import UTC, datetime, timedelta

from keirin_intelligence.baseline import rating_softmax
from keirin_intelligence.domain import Race, RiderEntry
from keirin_intelligence.reporting import render_synthetic_draft


def test_report_has_prominent_synthetic_and_blocked_labels():
    asof = datetime(2026, 10, 28, tzinfo=UTC)
    race = Race("FAKE", "架空", asof + timedelta(hours=1))
    entries = [RiderEntry(1, "架空A", 10), RiderEntry(2, "架空B", 9)]
    text = render_synthetic_draft(race, entries, rating_softmax(entries), asof)
    assert "合成データ" in text
    assert "公開不可" in text
    assert "BLOCKED" in text
    assert "未校正" in text
