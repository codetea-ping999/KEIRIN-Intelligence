"""Synthetic-only draft report. Public note submission is intentionally absent."""

from datetime import datetime

from keirin_intelligence.domain import Race, RiderEntry


def render_synthetic_draft(
    race: Race,
    entries: list[RiderEntry],
    scores: dict[int, float],
    prediction_asof_at: datetime,
) -> str:
    """Visible DEMO label; no invented real players, odds or validated accuracy claims."""
    entry_by_car = {e.car_number: e for e in entries}
    rows = ["| 車番 | 選手（架空） | 未校正スコア |", "|---|---|---:|"]
    for number, value in sorted(scores.items(), key=lambda p: p[1], reverse=True):
        rows.append(f"| {number} | {entry_by_car[number].label} | {value:.1%} |")
    return "\n".join(
        [
            "# 【合成データ・公開不可のデモ】競輪分析レポート",
            "",
            "> ⚠ 完全な架空データ。実際の選手・レース・オッズ・推奨買い目ではありません。",
            "> この数値は勝率の校正も実績検証もされていません。販売・投稿禁止。",
            "",
            f"- 仮想レース: {race.label} ({race.race_id})",
            f"- 予測入力の基準時刻: {prediction_asof_at.isoformat()}",
            "- モデル: M0 rating-softmax (uncalibrated)",
            "",
            *rows,
            "",
            "## 公開判定",
            "**BLOCKED** — データ許諾、モデル妥当性、事前固定検証、手動承認が必要です。",
            "",
        ]
    )
