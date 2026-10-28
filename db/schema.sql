-- KEIRIN Intelligence: PostgreSQL 15+ schema (minimal commercial audit foundation)
-- Commercialization is blocked until data licensing permits ingestion/modeling/derivative sales.
-- Monetary amounts in JPY; odds as decimal total-return multiples (e.g. 6.00).
BEGIN;

CREATE TABLE data_sources (
    source_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    source_url TEXT,
    agreement_reference TEXT,
    allowed_training BOOLEAN NOT NULL DEFAULT FALSE,
    allowed_derived_sales BOOLEAN NOT NULL DEFAULT FALSE,
    allowed_storage BOOLEAN NOT NULL DEFAULT FALSE,
    permission_status TEXT NOT NULL DEFAULT 'unverified'
       CHECK (permission_status IN ('unverified','approved','expired','revoked')),
    reviewed_at TIMESTAMPTZ,
    permission_expires_at TIMESTAMPTZ
);

CREATE TABLE ingestion_batches (
    batch_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    source_id BIGINT NOT NULL REFERENCES data_sources(source_id),
    ingested_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    raw_object_path TEXT NOT NULL,
    sha256 CHAR(64) NOT NULL,
    record_count INTEGER NOT NULL CHECK (record_count >= 0),
    validation_status TEXT NOT NULL CHECK (validation_status IN ('accepted','quarantined','rejected'))
);

CREATE TABLE velodromes (
    velodrome_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    official_code TEXT UNIQUE,
    name TEXT NOT NULL,
    lap_length_m INTEGER CHECK (lap_length_m > 0),
    home_straight_m NUMERIC(6,1),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE riders (
    rider_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    official_rider_code TEXT NOT NULL UNIQUE,
    display_name TEXT,
    region_code TEXT
);

CREATE TABLE races (
    race_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    velodrome_id BIGINT NOT NULL REFERENCES velodromes(velodrome_id),
    race_date DATE NOT NULL,
    race_number SMALLINT NOT NULL CHECK (race_number BETWEEN 1 AND 99),
    format_code TEXT NOT NULL, -- ordinary_men_7 / ordinary_men_9 / girls_7 / advance_7, etc.
    grade_code TEXT,
    scheduled_start_at TIMESTAMPTZ,
    betting_cutoff_at TIMESTAMPTZ,
    status TEXT NOT NULL DEFAULT 'scheduled'
        CHECK (status IN ('scheduled','running','finalized','cancelled','void')),
    UNIQUE(velodrome_id, race_date, race_number)
);

CREATE TABLE race_entries (
    entry_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    race_id BIGINT NOT NULL REFERENCES races(race_id),
    rider_id BIGINT NOT NULL REFERENCES riders(rider_id),
    car_number SMALLINT NOT NULL CHECK (car_number BETWEEN 1 AND 9),
    UNIQUE(race_id, rider_id),
    UNIQUE(race_id, car_number)
);

CREATE TABLE entry_snapshots (
    entry_snapshot_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    entry_id BIGINT NOT NULL REFERENCES race_entries(entry_id),
    batch_id BIGINT NOT NULL REFERENCES ingestion_batches(batch_id),
    observed_at TIMESTAMPTZ NOT NULL,
    ingested_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    start_status TEXT NOT NULL DEFAULT 'entered'
        CHECK (start_status IN ('entered','withdrawn','unknown')),
    rating NUMERIC(7,3),
    rider_class TEXT,
    riding_style TEXT,
    back_count INTEGER CHECK (back_count >= 0),
    UNIQUE(entry_id, batch_id, observed_at)
);

CREATE TABLE line_snapshots (
    line_snapshot_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    race_id BIGINT NOT NULL REFERENCES races(race_id),
    batch_id BIGINT REFERENCES ingestion_batches(batch_id),
    observed_at TIMESTAMPTZ NOT NULL,
    ingested_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    verification_state TEXT NOT NULL
        CHECK (verification_state IN ('unknown','predicted','confirmed')),
    UNIQUE(race_id, observed_at, batch_id)
);

CREATE TABLE line_members (
    line_snapshot_id BIGINT NOT NULL REFERENCES line_snapshots(line_snapshot_id),
    car_number SMALLINT NOT NULL CHECK (car_number BETWEEN 1 AND 9),
    line_group SMALLINT, -- NULL when unverified; solo rider uses dedicated group
    line_position SMALLINT CHECK (line_position BETWEEN 1 AND 9),
    PRIMARY KEY(line_snapshot_id, car_number),
    CHECK (line_group IS NULL OR line_group > 0)
);

CREATE TABLE weather_snapshots (
    weather_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    race_id BIGINT NOT NULL REFERENCES races(race_id),
    source_id BIGINT NOT NULL REFERENCES data_sources(source_id),
    observed_at TIMESTAMPTZ NOT NULL,
    ingested_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    wind_speed_mps NUMERIC(5,2) CHECK (wind_speed_mps >= 0),
    wind_direction_deg NUMERIC(5,1) CHECK (wind_direction_deg >= 0 AND wind_direction_deg < 360),
    air_temp_c NUMERIC(5,2),
    precipitation_mm NUMERIC(7,2) CHECK (precipitation_mm >= 0),
    UNIQUE(race_id, source_id, observed_at)
);

CREATE TABLE odds_snapshots (
    odds_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    race_id BIGINT NOT NULL REFERENCES races(race_id),
    source_id BIGINT NOT NULL REFERENCES data_sources(source_id),
    bet_type TEXT NOT NULL CHECK (bet_type IN ('exacta','trifecta')),
    combination TEXT NOT NULL, -- canonical e.g. 1-5 / 1-5-3
    decimal_odds NUMERIC(12,3) CHECK (decimal_odds > 0),
    observed_at TIMESTAMPTZ NOT NULL,
    ingested_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(race_id, source_id, bet_type, combination, observed_at)
);

CREATE TABLE race_results (
    race_id BIGINT NOT NULL REFERENCES races(race_id),
    rider_id BIGINT NOT NULL REFERENCES riders(rider_id),
    finish_position SMALLINT CHECK (finish_position > 0),
    result_status TEXT NOT NULL CHECK (result_status IN ('finished','disqualified','withdrawn','did_not_finish','other')),
    confirmed_at TIMESTAMPTZ NOT NULL,
    PRIMARY KEY(race_id, rider_id)
);

CREATE TABLE race_payouts (
    payout_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    race_id BIGINT NOT NULL REFERENCES races(race_id),
    bet_type TEXT NOT NULL CHECK (bet_type IN ('exacta','trifecta')),
    combination TEXT NOT NULL,
    payout_per_100_yen INTEGER CHECK (payout_per_100_yen >= 0),
    settlement_kind TEXT NOT NULL DEFAULT 'normal'
        CHECK (settlement_kind IN ('normal','refund','void')),
    confirmed_at TIMESTAMPTZ NOT NULL,
    UNIQUE(race_id, bet_type, combination, settlement_kind)
);

CREATE TABLE model_versions (
    model_version_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    model_name TEXT NOT NULL,
    version_tag TEXT NOT NULL,
    train_start_date DATE,
    train_end_date DATE,
    artifact_sha256 CHAR(64) NOT NULL,
    config_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(model_name, version_tag)
);

CREATE TABLE prediction_runs (
    prediction_run_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    race_id BIGINT NOT NULL REFERENCES races(race_id),
    model_version_id BIGINT NOT NULL REFERENCES model_versions(model_version_id),
    line_snapshot_id BIGINT REFERENCES line_snapshots(line_snapshot_id),
    prediction_asof_at TIMESTAMPTZ NOT NULL,
    generated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    input_sha256 CHAR(64) NOT NULL,
    execution_status TEXT NOT NULL CHECK (execution_status IN ('success','no_pick','blocked')),
    block_reason TEXT,
    CHECK (generated_at >= prediction_asof_at)
);

CREATE TABLE rider_predictions (
    prediction_run_id BIGINT NOT NULL REFERENCES prediction_runs(prediction_run_id),
    entry_id BIGINT NOT NULL REFERENCES race_entries(entry_id),
    win_probability NUMERIC(10,8) NOT NULL CHECK (win_probability >= 0 AND win_probability <= 1),
    top2_probability NUMERIC(10,8) CHECK (top2_probability >= 0 AND top2_probability <= 1),
    top3_probability NUMERIC(10,8) CHECK (top3_probability >= 0 AND top3_probability <= 1),
    PRIMARY KEY(prediction_run_id, entry_id)
);

CREATE TABLE ticket_predictions (
    ticket_prediction_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    prediction_run_id BIGINT NOT NULL REFERENCES prediction_runs(prediction_run_id),
    bet_type TEXT NOT NULL CHECK (bet_type IN ('exacta','trifecta')),
    combination TEXT NOT NULL,
    estimated_probability NUMERIC(12,10) CHECK (estimated_probability >= 0 AND estimated_probability <= 1),
    observed_odds_id BIGINT REFERENCES odds_snapshots(odds_id),
    expected_roi NUMERIC(14,5),
    decision TEXT NOT NULL CHECK (decision IN ('candidate','publish','no_pick')),
    virtual_stake_yen INTEGER NOT NULL DEFAULT 0 CHECK (virtual_stake_yen >= 0),
    UNIQUE(prediction_run_id, bet_type, combination)
);

CREATE TABLE publications (
    publication_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    prediction_run_id BIGINT NOT NULL REFERENCES prediction_runs(prediction_run_id),
    note_url TEXT,
    draft_sha256 CHAR(64) NOT NULL,
    published_sha256 CHAR(64),
    approved_by TEXT,
    published_at TIMESTAMPTZ,
    correction_of BIGINT REFERENCES publications(publication_id),
    CHECK (published_at IS NULL OR approved_by IS NOT NULL)
);

CREATE TABLE prediction_evaluations (
    ticket_prediction_id BIGINT PRIMARY KEY REFERENCES ticket_predictions(ticket_prediction_id),
    publication_id BIGINT REFERENCES publications(publication_id),
    evaluation_type TEXT NOT NULL CHECK (evaluation_type IN ('backtest','shadow','live_actual')),
    settled_at TIMESTAMPTZ NOT NULL,
    result_kind TEXT NOT NULL CHECK (result_kind IN ('win','loss','refund','void','not_evaluable')),
    virtual_stake_yen INTEGER NOT NULL CHECK (virtual_stake_yen >= 0),
    payout_yen INTEGER NOT NULL CHECK (payout_yen >= 0),
    net_yen INTEGER GENERATED ALWAYS AS (payout_yen - virtual_stake_yen) STORED
);

CREATE INDEX idx_entries_race ON race_entries(race_id);
CREATE INDEX idx_entry_snapshot_asof ON entry_snapshots(entry_id, observed_at DESC, ingested_at DESC);
CREATE INDEX idx_line_snapshot_asof ON line_snapshots(race_id, observed_at DESC, ingested_at DESC);
CREATE INDEX idx_odds_asof ON odds_snapshots(race_id, bet_type, observed_at DESC, ingested_at DESC);
CREATE INDEX idx_prediction_race_time ON prediction_runs(race_id, generated_at DESC);
CREATE INDEX idx_publication_time ON publications(published_at);

COMMIT;

-- Business rules to implement in application transaction / trigger:
-- 1) Commercial ingestion requires active approved license with training/storage/sales flags.
-- 2) Exactly one racer per car, predictions must match the target race and active entries.
-- 3) All feature observations and ingestions <= prediction_asof_at, and prediction_asof_at < betting_cutoff_at.
-- 4) Sum of race win_probability must be 1 within epsilon after the full run is persisted.
-- 5) Odds and ticket predictions must reference SAME race, proper bet_type and matching combination.
-- 6) No edits to published prediction payload; corrections are additive publications.
-- 7) payout/refund/void/finished conditions must be reconciled using provider's rulebook.
-- 8) DDL is a blueprint, not a completed application: add row-level rights, audit triggers, backups,
--    permission checks, as-of views, idempotent ETL, access controls and compliance tests.