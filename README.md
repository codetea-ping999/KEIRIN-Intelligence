# KEIRIN Intelligence

**Private research prototype for a data-rights-aware keirin forecasting and note publication workflow.**

> [!IMPORTANT]
> **NOT LIVE, NOT PRODUCTION-READY, NOT A PREDICTION SERVICE.** The demo uses **synthetic riders / synthetic ratings / simulated odds**. No real race data, scraping, automatic wagering, or automatic note publishing is included. Commercial ingestion, training and sale remain blocked until licensing/permissions and legal review are complete.

## Goals

1. Build reproducible pre-race probability forecasts (initially win probabilities, then exacta).
2. Preserve **as-of** input timestamps, model/version details and pre-race publication evidence.
3. Test forecast quality against transparent baselines using chronological walk-forward evaluation.
4. Prepare **human-approved** Japanese explanatory reports suitable for future note commercialization if permitted.

## Local quick start

Python **3.12+**. The baseline and synthetic demo use the Python standard library; no live API credentials needed.

```bash
python -m pip install -e .
keirin-demo
python -m pip install -e '.[dev]'
python -m pytest -q
```

Alternative without installing: `PYTHONPATH=src python -m keirin_intelligence.demo`.

## Current deliverables

- `docs/DESIGN.md` — business/MVP model design, KPI, roadmap (initial detailed design).
- `db/schema.sql` — PostgreSQL 15+ **blueprint**, not yet connected to demo.
- `src/keirin_intelligence/` — deterministic synthetic example, probability baseline and governance checks.
- `tests/` — tests for probability normalization, timestamp leak guards, publication/data-rights gating.
- `.github/workflows/ci.yml` — pytest and Ruff validation.
- `docs/BACKLOG.md` — issue-ready work packages and acceptance criteria.

## Engineering rules

- Every observation must have `observed_at` and `ingested_at`; both must be no later than `prediction_asof_at`, which must precede the betting cutoff.
- **Never** use finalized results, later odds or future data to train/test historical pre-race predictions.
- **No commercial processing** of unverified, expired, revoked or non-commercially licensed data; synthetic fixtures are rejected for commercial mode.
- Keep `BACKTEST`, pre-registered `SHADOW` and real-money `LIVE_ACTUAL` performance separate. Live wagering is **out of scope**.
- Do not represent the baseline as a calibrated model or model output as assured profit.
- All sale/publication requires a human approval process, terms review, and provenance verification.

## Roadmap

**Gate 0:** Rights/supplier terms -> **Gate 1:** Licensed ETL + as-of feature store -> **Gate 2:** walk-forward baseline/LightGBM -> **Gate 3:** odds/exacta evaluation -> **Gate 4:** forward shadow ledger and human-reviewed note reports -> **Gate 5:** commercial go/no-go.

See [docs/BACKLOG.md](docs/BACKLOG.md), [docs/DATA_LICENSING.md](docs/DATA_LICENSING.md) and [docs/BACKTEST_POLICY.md](docs/BACKTEST_POLICY.md).

## Security and copyright

No source data has been bundled. Do not commit provider exports, access tokens, personally identifying user data, purchased forecasts, or unlicensed material. Repository is private and **no open-source license is granted**. Copyright and commercial rights should be agreed in writing with collaborators before inviting them.

## Repository

Canonical private development repository: https://github.com/codetea-ping999/KEIRIN-Intelligence

Use feature branches, reviewed pull requests, and CI for subsequent changes. See `docs/BACKLOG.md` for issue plan. Before inviting collaborators, agree on source-code IP ownership and revenue sharing in writing.
