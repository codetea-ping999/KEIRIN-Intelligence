"""Migration tests. The PostgreSQL ones run when KEIRIN_TEST_DATABASE_URL is set (CI does)."""

import os
from datetime import UTC, datetime, timedelta

import pytest

from keirin_intelligence.migrate import discover, downgrade, upgrade

DSN = os.environ.get("KEIRIN_TEST_DATABASE_URL")
CUTOFF = datetime(2026, 11, 3, 7, 25, tzinfo=UTC)


def test_migrations_are_numbered_and_paired():
    migrations = discover()
    assert [m.version for m in migrations] == list(range(1, len(migrations) + 1))
    assert all(m.down.strip() for m in migrations)


def test_gap_in_versions_is_rejected(tmp_path):
    for name in ("0001_a", "0003_c"):
        (tmp_path / f"{name}.up.sql").write_text("SELECT 1;")
        (tmp_path / f"{name}.down.sql").write_text("SELECT 1;")
    with pytest.raises(ValueError, match="without gaps"):
        discover(tmp_path)


pg = pytest.mark.skipif(not DSN, reason="KEIRIN_TEST_DATABASE_URL not set")


@pytest.fixture
def conn():
    psycopg = pytest.importorskip("psycopg")
    with psycopg.connect(DSN, autocommit=True) as c:
        downgrade(c, discover(), 0)
        upgrade(c, discover())
        yield c
        downgrade(c, discover(), 0)


def _tables(c):
    return {r[0] for r in c.execute(
        "SELECT tablename FROM pg_tables WHERE schemaname = current_schema()").fetchall()}


def _race(c):
    c.execute("INSERT INTO velodromes(name) VALUES ('架空バンク')")
    c.execute("""INSERT INTO races(velodrome_id, race_date, race_number, format_code,
                 scheduled_start_at, betting_cutoff_at)
                 SELECT velodrome_id, '2026-11-03', 11, 'ordinary_men_7', %s, %s FROM velodromes""",
              (CUTOFF + timedelta(minutes=5), CUTOFF))
    c.execute("INSERT INTO riders(official_rider_code) VALUES ('R1'), ('R2')")
    c.execute("""INSERT INTO race_entries(race_id, rider_id, car_number)
                 SELECT r.race_id, d.rider_id, d.rider_id FROM races r, riders d""")
    c.execute("INSERT INTO model_versions(model_name, version_tag, artifact_sha256) "
              "VALUES ('M1', 'v1', repeat('a', 64))")
    return c.execute("SELECT race_id FROM races").fetchone()[0]


@pg
def test_upgrade_builds_schema_and_downgrade_removes_it(conn):
    assert {"races", "race_entries", "publications", "rights_decisions"} <= _tables(conn)
    assert upgrade(conn, discover()) == []  # re-running is a no-op
    downgrade(conn, discover(), 1)
    assert "rights_decisions" not in _tables(conn) and "races" in _tables(conn)
    downgrade(conn, discover(), 0)
    assert _tables(conn) == {"schema_migrations"}
    assert upgrade(conn, discover()) == [1, 2]


@pg
def test_referential_integrity(conn):
    import psycopg

    race_id = _race(conn)
    with pytest.raises(psycopg.errors.ForeignKeyViolation):
        conn.execute("INSERT INTO race_entries(race_id, rider_id, car_number) VALUES (%s, 999, 3)",
                     (race_id,))
    conn.execute("INSERT INTO riders(official_rider_code) VALUES ('NOT-ENTERED')")
    with pytest.raises(psycopg.errors.ForeignKeyViolation):  # result for a rider not in the race
        conn.execute("""INSERT INTO race_results(race_id, rider_id, finish_position, result_status,
                        confirmed_at) SELECT %s, rider_id, 1, 'finished', NOW() FROM riders
                        WHERE official_rider_code = 'NOT-ENTERED'""", (race_id,))
    with pytest.raises(psycopg.errors.UniqueViolation):
        conn.execute("INSERT INTO race_entries(race_id, rider_id, car_number) "
                     "SELECT %s, rider_id, 1 FROM riders WHERE official_rider_code='NOT-ENTERED'",
                     (race_id,))


@pg
def test_prediction_after_cutoff_is_refused(conn):
    import psycopg

    race_id = _race(conn)
    sql = """INSERT INTO prediction_runs(race_id, model_version_id, prediction_asof_at,
             generated_at, input_sha256, execution_status)
             SELECT %s, model_version_id, %s, %s, repeat('b', 64), 'success' FROM model_versions"""
    conn.execute(sql, (race_id, CUTOFF - timedelta(hours=1), CUTOFF - timedelta(minutes=59)))
    with pytest.raises(psycopg.errors.RaiseException, match="not before betting cutoff"):
        conn.execute(sql, (race_id, CUTOFF, CUTOFF))


@pg
def test_unlicensed_batch_cannot_be_accepted(conn):
    import psycopg

    conn.execute("INSERT INTO data_sources(name) VALUES ('unverified.example')")
    sql = """INSERT INTO ingestion_batches(source_id, raw_object_path, sha256, record_count,
             validation_status) SELECT source_id, 'raw/x', repeat('c', 64), 1, %s FROM data_sources"""
    conn.execute(sql, ("quarantined",))
    with pytest.raises(psycopg.errors.RaiseException, match="no valid storage permission"):
        conn.execute(sql.replace("'c'", "'d'"), ("accepted",))
    with pytest.raises(psycopg.errors.CheckViolation):  # approved needs a written agreement
        conn.execute("UPDATE data_sources SET permission_status = 'approved'")


@pg
def test_publications_and_audit_are_append_only(conn):
    import psycopg

    race_id = _race(conn)
    conn.execute("""INSERT INTO prediction_runs(race_id, model_version_id, prediction_asof_at,
                    input_sha256, execution_status) SELECT %s, model_version_id, %s, repeat('b', 64),
                    'success' FROM model_versions""", (race_id, CUTOFF - timedelta(hours=1)))
    conn.execute("""INSERT INTO publications(prediction_run_id, draft_sha256, approved_by,
                    published_at) SELECT prediction_run_id, repeat('e', 64), 'editor', NOW()
                    FROM prediction_runs""")
    with pytest.raises(psycopg.errors.RaiseException, match="already published"):
        conn.execute("UPDATE publications SET note_url = 'https://example.invalid'")
    with pytest.raises(psycopg.errors.RaiseException, match="append-only"):
        conn.execute("DELETE FROM publications")
    conn.execute("""INSERT INTO rights_decisions(source_name, purpose, allowed, reason, decided_at,
                    sha256) VALUES ('x', 'ingest', false, 'unknown source', NOW(), repeat('f', 64))""")
    with pytest.raises(psycopg.errors.RaiseException, match="append-only"):
        conn.execute("UPDATE rights_decisions SET allowed = true")
