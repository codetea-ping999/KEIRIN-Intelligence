# Development status — 2026-10-28

- Private GitHub repository created, initialized and bootstrap scaffold under review.
- Synthetic research baseline, demo, governance guard and tests provided for initial development.
- PostgreSQL schema is an **unapplied blueprint**.
- Local tests on Python 3.13: 15 passed; GitHub Actions Python 3.12 must be checked separately.
- Data provider contract, rights for training/resale and legal review: **UNRESOLVED**.
- 2026-10-30 (v0.2): hand-entered real race card CSVs, M1 line-aware logit with MAP fitting, monthly walk-forward evaluation vs baselines, hash-chained pre-cutoff ledger, Japanese note draft renderer. Real-data accuracy is **not yet measured** (no results entered).
- Automated ingestion, LightGBM training and actual note publishing: **NOT IMPLEMENTED**.
- No valid performance or profitability claim exists.

## Immediate next actions

1. Approve/procure licensed commercial data.
2. Convert SQL blueprint to migrations and build as-of lineage.
3. Implement chronological evaluation and forward shadow ledger.
4. Review sale terms, revenue split, claims policy and human publication workflow.
