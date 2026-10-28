# Initial implementation backlog

See GitHub Issues for active tracking. Each item must have acceptance tests/evidence.

1. [P0][Rights] Obtain legal commercial provider agreement for ingestion, historic storage, ML training and paid derivative predictions.
2. [P0][Governance] Apply permission checks at every ingest/train/report boundary with immutable provenance.
3. [P0][Data] Convert SQL draft into PostgreSQL migrations and build dictionary.
4. [P0][Data] Idempotent ETL for authorized data source with quarantine on bad records.
5. [P0][ML] Timestamped as-of features and no-future leakage tests.
6. [P0][ML] Chronological backtesting, calibrated winner scores and comparisons.
7. [P1][ML] LightGBM with venue, weather and line ablation.
8. [P1][Model] Exacta probability and timestamped odds/ROI simulation.
9. [P1][Content] Human-reviewed note draft and immutable forecast scorecard.
10. [P1][Launch] Forward shadow test and evidence-backed paid launch GO/NO-GO.
