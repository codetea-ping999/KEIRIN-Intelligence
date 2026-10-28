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
