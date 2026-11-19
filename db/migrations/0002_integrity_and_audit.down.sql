-- 0002 rollback.
DROP TABLE IF EXISTS rights_decisions;
DROP FUNCTION IF EXISTS ki_append_only() CASCADE;
DROP FUNCTION IF EXISTS ki_publications_append_only() CASCADE;
DROP FUNCTION IF EXISTS ki_check_batch_rights() CASCADE;
DROP FUNCTION IF EXISTS ki_check_ticket_odds() CASCADE;
DROP FUNCTION IF EXISTS ki_check_prediction_timing() CASCADE;
