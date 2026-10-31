"""Japanese note.com draft for one real race. Drafts only; publishing stays manual.

Wording rules (docs/NOTE_PUBLISHING.md): entertainment framing, no guarantee of hits
or profit, adults-only reminder, and a track record taken only from the frozen ledger.
"""

from datetime import timedelta, timezone

from keirin_intelligence.evaluation import TRIFECTA_TOP_N
from keirin_intelligence.model import RacePrediction
from keirin_intelligence.racecard import RaceCard, Velodrome

JST = timezone(timedelta(hours=9))
MARKS = ("◎", "○", "▲", "△", "×")

# Phrases that imply guaranteed outcomes; render_note refuses to output them.
BANNED_PHRASES = ("必ず当たる", "絶対", "確実に儲", "100%的中", "元本保証", "損しない", "必勝")

DISCLAIMER = """\
---
**ご注意**
- 本記事はデータ分析を楽しむためのエンタメコンテンツです。的中や利益を保証するものではありません。
- 掲載の確率はモデルによる推定値で、実際の結果とは大きく異なることがあります。
- 車券の購入は20歳以上の方に限られます。購入はご自身の判断と責任で、余裕のある範囲でお楽しみください。
- のめり込みが心配な方は、お住まいの地域の精神保健福祉センターなどの相談窓口をご利用ください。
- 出走表の情報は公表資料を手入力したものです。最新の出走情報・欠車は必ず公式発表でご確認ください。
"""


def _pct(p: float) -> str:
    return f"{p * 100:.1f}%"


def _bank_comment(card: RaceCard, venue: Velodrome | None) -> list[str]:
    """Venue / weather remarks. Wording stays hedged: the sources disagree on several effects."""
    out = []
    if venue is not None and venue.straight_m is not None:
        if venue.straight_m < 45:
            tilt = "先行・捲りが残りやすい短めの直線"
        elif venue.straight_m > 60:
            tilt = "番手・追い込みが届きやすい長めの直線"
        else:
            tilt = "標準的な直線"
        place = "屋内" if venue.indoor else "屋外"
        out.append(
            f"- バンク: {venue.name}（{place}・{venue.lap_m:g}m）はみなし直線 {venue.straight_m:.1f}m。"
            f"{tilt}とされます。"
        )
    if card.back_wind_mps is not None and abs(card.back_wind_mps) >= 5:
        if card.back_wind_mps > 0:
            out.append(
                f"- 風: バック向かい風 約{card.back_wind_mps:.0f}m/s。"
                "先行が消耗し、後方に展開が向きやすいといわれます。"
            )
        else:
            out.append(
                f"- 風: バック追い風 約{-card.back_wind_mps:.0f}m/s。先行が粘りやすい可能性があります。"
            )
    if card.wet:
        out.append("- 路面: 濡れています。無理な仕掛けが減るとも荒れるともいわれ、見方が分かれます。")
    return out


def _comment(
    card: RaceCard, pred: RacePrediction, venue: Velodrome | None = None
) -> list[str]:
    by_car = {e.car_number: e for e in card.entries}
    lines = card.lines()
    multi = [line for line in lines if len(line) >= 2] or lines
    strongest = max(multi, key=lambda line: sum(e.score for e in line) / len(line))
    honmei = by_car[pred.ranked()[0]]
    out = [
        *_bank_comment(card, venue),
        f"- 並び予想は **{card.formation()}**。連携ラインで平均得点が最も高いのは "
        f"{'-'.join(str(e.car_number) for e in strongest)} のラインです。",
    ]
    role = {1: "先頭", 2: "番手"}.get(honmei.line_pos, f"{honmei.line_pos}番手")
    size = sum(1 for e in card.entries if e.line_group == honmei.line_group)
    role = "単騎" if size == 1 else role
    out.append(
        f"- 本命は {honmei.car_number}番 {honmei.name}（{honmei.rider_class}・"
        f"得点{honmei.score:.2f}・{role}）。推定1着率 {_pct(pred.win[honmei.car_number])}、"
        f"3着内率 {_pct(pred.top3[honmei.car_number])}。"
    )
    upset = max((c for c in pred.ranked()[3:]), key=lambda c: pred.top3[c], default=None)
    if upset is not None:
        e = by_car[upset]
        out.append(f"- 穴なら {e.car_number}番 {e.name}。3着内率は {_pct(pred.top3[upset])} と推定。")
    return out


def render_note(
    card: RaceCard,
    pred: RacePrediction,
    *,
    track_record: dict[str, int] | None = None,
    model_label: str = "M1 line-aware logit",
    venue: Velodrome | None = None,
) -> str:
    by_car = {e.car_number: e for e in card.entries}
    ranked = pred.ranked()
    marks = {c: MARKS[i] for i, c in enumerate(ranked[: len(MARKS)])}
    table = [
        "| 印 | 車番 | 選手 | 級班 | 府県 | 得点 | 脚質 | 1着率 | 3着内率 |",
        "|:-:|:-:|---|:-:|:-:|--:|:-:|--:|--:|",
    ]
    for c in sorted(by_car):
        e = by_car[c]
        table.append(
            f"| {marks.get(c, '')} | {c} | {e.name} | {e.rider_class} | {e.prefecture} | "
            f"{e.score:.2f} | {e.style} | {_pct(pred.win[c])} | {_pct(pred.top3[c])} |"
        )
    top_tri = sorted(pred.trifecta, key=pred.trifecta.get, reverse=True)[:TRIFECTA_TOP_N]
    tri_rows = [f"  - {a}-{b}-{c}（推定 {_pct(pred.trifecta[(a, b, c)])}）" for a, b, c in top_tri]
    best_ex = max(pred.exacta, key=pred.exacta.get)
    cutoff = card.betting_cutoff_at.astimezone(JST).strftime("%Y-%m-%d %H:%M")

    record_section = ["## これまでの記録（事前公開分のみ・外れも含む）", ""]
    if track_record and track_record["settled"]:
        n = track_record["settled"]
        record_section += [
            f"- 対象 {n} レース（結果待ち {track_record['pending']}）",
            f"- 本命1着 {track_record['honmei_win']}/{n}（{_pct(track_record['honmei_win'] / n)}）"
            f"、本命3着内 {track_record['honmei_top3']}/{n}",
            f"- 2車単1点 的中 {track_record['exacta_hit']}/{n}"
            f"、3連単{TRIFECTA_TOP_N}点 的中 {track_record['trifecta_hit']}/{n}",
            "- 過去の記録は将来の結果を保証しません。",
        ]
    else:
        record_section.append("- まだ集計対象のレースがありません。記録は事前に固定した予想だけで集計します。")

    text = "\n".join([
        f"# {card.race_date.month}/{card.race_date.day} {card.label}（{card.grade}）データ分析ノート",
        "",
        "> 実在選手の公表データをもとにした**エンタメ目的の分析**です。的中・利益の保証はありません。",
        "",
        f"- 締切: {cutoff}（JST）　モデル: {model_label}",
        f"- データ: {card.source}（{card.observed_at.astimezone(JST):%m/%d %H:%M} 時点の公表情報を手入力）",
        "",
        "## 出走表と推定確率",
        "",
        *table,
        "",
        "## 展開メモ",
        "",
        *_comment(card, pred, venue),
        "",
        "## 参考の組み合わせ",
        "",
        f"- 2車単: {best_ex[0]}-{best_ex[1]}（推定 {_pct(pred.exacta[best_ex])}）",
        f"- 3連単 推定上位{TRIFECTA_TOP_N}点:",
        *tri_rows,
        "",
        *record_section,
        "",
        DISCLAIMER,
    ])
    found = [p for p in BANNED_PHRASES if p in text]
    if found:
        raise ValueError(f"note contains prohibited guarantee wording: {found}")
    return text
