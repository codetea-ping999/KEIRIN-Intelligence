# KEIRIN Intelligence — Product and Engineering Design v0.1

## Purpose
Develop an auditable, rights-aware keirin forecast research system that *may* support paid note content once data contracts, evaluation and sales approvals are met. No bets are placed automatically.

## MVP boundaries
One licensed race class / subset, initially 1st-place race-normalized scores and ordered 2-car exacta probability; no all-venue support, no real money wagering, no autopublishing.

## Data pipeline
Licensed provider -> provenance checks (source, observed_at, ingested_at) -> raw immutable snapshot -> PostgreSQL models and feature history -> versioned model -> pre-race prediction -> frozen artifact hash -> human-reviewed report -> result settlement -> disclosure dashboards.

Tables: data_sources, riders, velodromes, races, race_entries, entry_snapshots, line_snapshots, weather_snapshots, odds_snapshots, race_results, race_payouts, model_versions, prediction_runs, rider_predictions, ticket_predictions, prediction_evaluations and publications. Consult db/schema.sql; it is a blueprint, not a deployed migration.

## Model path
- M0 uniform and rating-softmax baseline (uncalibrated synthetic-only demonstration exists).
- M1 LightGBM based on rider ability, recent form, line role, venue and pre-cutoff weather.
- M2 independent calibration set; evaluate winner log loss, Brier, expected calibration error and top-1 accuracy.
- M3 Plackett-Luce ordering baseline vs correlation-aware exacta; do not multiply independent win rates.
- Ticket EV = probability * observable pre-cutoff decimal odds - 1; this is a forecast, NOT guaranteed realized ROI.

## Testing
Chronological train -> calibrate -> untouched holdout, then 8–12+ weeks of frozen shadow predictions. Record each published timestamp and revisions; compare venue, race grade, odds segment and line formation. Report maximum drawdown, missingness and abstentions. Do not use final odds as if known pre-race.

## note product assumptions
Free proof-of-work stats and analysis, followed only after rights/validation by paid detailed reports or member subscription. Test buyer demand, processing fees, data cost, work hours and refunds. Avoid profits claims or implying an accurate forecast means betting gains.

## Release acceptance
Gate A commercial rights and all source permissions; B as-of leak guards; C convincing and reproducible evaluation; D sufficiently long forward shadow; E contract with collaborator, consumer compliance, note rules, human approval. All must be reviewed and marked approved before commercial use.

## Development increments
1. Rights/provider outreach and contracts.
2. PostgreSQL migration and licensed ETL.
3. As-of feature store and evaluation baselines.
4. Calibrated ML and ordered market probabilities.
5. Pre-race frozen prediction ledger and note draft.
6. Forward validation, monetization experiment and go/no-go decision.

## Technical choices
Python 3.12+, PostgreSQL 15+, Parquet, FastAPI/Streamlit as needed; pytest, Ruff, GitHub Actions. Start minimal and introduce infrastructure when required.
