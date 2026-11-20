# Model evaluation protocol (draft)

1. **As-of integrity:** Features must have both observed and ingested timestamps before the prediction instant. The prediction instant precedes betting cutoff.
2. **Split:** chronological train -> calibration -> untouched test. Group all starters in the same race together; tune on prior data only.
3. **Baselines:** uniform, rating-based, and pre-cutoff market-implied probabilities where licensed.
4. **Metrics:** multiclass winner log loss, Brier, calibration, then top-1 accuracy with race-level denominators.
5. **Bet simulation:** retain timestamped pre-race odds, settle from authorized results accounting for cancellations, refunds, dead heats and disqualification.
6. **No-pick:** register thresholds before evaluating holdout profit; include abstentions in reports.
7. **Shadow:** freeze predictions and article hashes before race; preserve entire cohort.
8. **Uncertainty:** plot rolling results, drawdown, confidence bounds, segment-level sample counts.
9. **Disclosure:** BACKTEST, SHADOW, LIVE_ACTUAL must be separate. This codebase never places bets.
10. **Go/no-go:** No profitable prediction claims from synthetic data or backtest-only evidence.

## 実行方法（Issue #7）

```bash
keirin --data data/real backtest --train-end 2026-09-01 --calib-end 2026-10-01 [--odds data/real/odds.csv]
```

- **分割**: `race_date < train-end` で M1 を学習、`[train-end, calib-end)` で温度（1パラメータ）だけを調整、`calib-end` 以降を未使用の検証期間として評価します。レース単位で分け、混ぜません。
- **ベースライン**: 一様、競走得点のみ、市場（締切前の単勝オッズ `odds.csv`: `race_id,car,win_odds,observed_at`。締切以後に観測した行は捨てます）。市場は、オッズがそろっているレースだけで、同じレースの M1 と並べて比べます。
- **指標**: 多クラス Log Loss、Brier、本命の1着率・3着内率、2車単・3連単の的中率、校正表（10区間）と ECE。
- **報告**: 各期間の開始日・終了日・レース数、再学習の境界、結果のないレースの数と割合、オッズの付いた割合。出力の `evidence` は常に `BACKTEST` です（シャドー運用・実運用の成績とは分けて扱います）。
