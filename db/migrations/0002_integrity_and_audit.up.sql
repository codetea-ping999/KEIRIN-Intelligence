-- 0002 cross-table timing rules, append-only publications and the rights decision log.
-- Implements business rules 1, 3, 5 and 6 of the original blueprint as database triggers.

-- Rule 3: a prediction must be made before the race's betting cutoff.
CREATE FUNCTION ki_check_prediction_timing() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE cutoff TIMESTAMPTZ;
BEGIN
    SELECT betting_cutoff_at INTO cutoff FROM races WHERE race_id = NEW.race_id;
    IF cutoff IS NULL THEN
        RAISE EXCEPTION 'race % has no betting_cutoff_at; cannot predict', NEW.race_id;
    END IF;
    IF NEW.prediction_asof_at >= cutoff THEN
        RAISE EXCEPTION 'prediction_asof_at % is not before betting cutoff %',
            NEW.prediction_asof_at, cutoff;
    END IF;
    IF NEW.line_snapshot_id IS NOT NULL AND NOT EXISTS (
        SELECT 1 FROM line_snapshots ls WHERE ls.line_snapshot_id = NEW.line_snapshot_id
          AND ls.race_id = NEW.race_id
          AND ls.observed_at <= NEW.prediction_asof_at
          AND ls.ingested_at <= NEW.prediction_asof_at) THEN
        RAISE EXCEPTION 'line snapshot is for another race or was not known at prediction time';
    END IF;
    RETURN NEW;
END $$;
CREATE TRIGGER trg_prediction_timing BEFORE INSERT OR UPDATE ON prediction_runs
    FOR EACH ROW EXECUTE FUNCTION ki_check_prediction_timing();

-- Rule 5: a ticket's odds must belong to the same race and bet type, observed before the run.
CREATE FUNCTION ki_check_ticket_odds() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF NEW.observed_odds_id IS NOT NULL AND NOT EXISTS (
        SELECT 1 FROM odds_snapshots o JOIN prediction_runs p ON p.race_id = o.race_id
        WHERE o.odds_id = NEW.observed_odds_id
          AND p.prediction_run_id = NEW.prediction_run_id
          AND o.bet_type = NEW.bet_type AND o.combination = NEW.combination
          AND o.observed_at <= p.prediction_asof_at
          AND o.ingested_at <= p.prediction_asof_at) THEN
        RAISE EXCEPTION 'odds do not match the ticket''s race/bet/combination or arrived late';
    END IF;
    RETURN NEW;
END $$;
CREATE TRIGGER trg_ticket_odds BEFORE INSERT OR UPDATE ON ticket_predictions
    FOR EACH ROW EXECUTE FUNCTION ki_check_ticket_odds();

-- Rule 1: commercial ingestion needs an approved, unexpired, unrevoked source with storage rights.
CREATE FUNCTION ki_check_batch_rights() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE s data_sources%ROWTYPE;
BEGIN
    IF NEW.validation_status <> 'accepted' THEN
        RETURN NEW;  -- quarantined / rejected batches are kept for audit only
    END IF;
    SELECT * INTO s FROM data_sources WHERE source_id = NEW.source_id;
    IF s.permission_status <> 'approved' OR NOT s.allowed_storage
       OR (s.permission_expires_at IS NOT NULL AND NEW.ingested_at >= s.permission_expires_at)
       OR (s.revoked_at IS NOT NULL AND NEW.ingested_at >= s.revoked_at)
       OR NEW.agreement_reference IS DISTINCT FROM s.agreement_reference THEN
        RAISE EXCEPTION 'source % has no valid storage permission for this batch', s.name;
    END IF;
    RETURN NEW;
END $$;
CREATE TRIGGER trg_batch_rights BEFORE INSERT OR UPDATE ON ingestion_batches
    FOR EACH ROW EXECUTE FUNCTION ki_check_batch_rights();

-- Rule 6: published payloads are immutable; corrections are new rows.
CREATE FUNCTION ki_publications_append_only() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'publications are append-only';
    END IF;
    IF OLD.published_at IS NOT NULL THEN
        RAISE EXCEPTION 'publication % is already published; add a correction instead',
            OLD.publication_id;
    END IF;
    IF NEW.draft_sha256 <> OLD.draft_sha256 THEN
        RAISE EXCEPTION 'draft hash cannot change; create a new publication row';
    END IF;
    RETURN NEW;
END $$;
CREATE TRIGGER trg_publications_append_only BEFORE UPDATE OR DELETE ON publications
    FOR EACH ROW EXECUTE FUNCTION ki_publications_append_only();

-- Rights decisions (mirror of the application's hash-chained audit log, Issue #3).
CREATE TABLE rights_decisions (
    decision_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    source_id BIGINT REFERENCES data_sources(source_id),
    source_name TEXT NOT NULL,
    purpose TEXT NOT NULL CHECK (purpose IN ('research','ingest','train','publish')),
    allowed BOOLEAN NOT NULL,
    reason TEXT NOT NULL,
    contract_id TEXT,
    decided_at TIMESTAMPTZ NOT NULL,
    previous_sha256 CHAR(64),
    sha256 CHAR(64) NOT NULL UNIQUE
);
CREATE INDEX idx_rights_decisions_source ON rights_decisions(source_name, decided_at DESC);

CREATE FUNCTION ki_append_only() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION '% is append-only', TG_TABLE_NAME;
END $$;
CREATE TRIGGER trg_rights_decisions_append_only BEFORE UPDATE OR DELETE ON rights_decisions
    FOR EACH ROW EXECUTE FUNCTION ki_append_only();
