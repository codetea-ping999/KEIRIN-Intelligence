"""Plain-SQL migrations for PostgreSQL: `keirin-db upgrade | downgrade | status`.

Each migration is a pair `NNNN_name.up.sql` / `NNNN_name.down.sql` in db/migrations.
Applied versions and the checksum of their up-script are kept in `schema_migrations`;
a changed script that was already applied is refused instead of silently drifting.
Every migration runs in its own transaction. Requires the optional `db` extra (psycopg).
"""

import argparse
import hashlib
import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path

DEFAULT_DIR = Path(__file__).resolve().parents[2] / "db" / "migrations"
_NAME = re.compile(r"^(\d{4})_([a-z0-9_]+)\.up\.sql$")


@dataclass(frozen=True)
class Migration:
    version: int
    name: str
    up: str
    down: str

    @property
    def checksum(self) -> str:
        return hashlib.sha256(self.up.encode()).hexdigest()


def discover(directory: Path = DEFAULT_DIR) -> list[Migration]:
    migrations = []
    for path in sorted(directory.glob("*.up.sql")):
        match = _NAME.match(path.name)
        if not match:
            raise ValueError(f"bad migration file name: {path.name}")
        down = path.with_name(path.name.replace(".up.sql", ".down.sql"))
        if not down.exists():
            raise ValueError(f"{path.name} has no matching .down.sql")
        migrations.append(Migration(int(match[1]), match[2], path.read_text(encoding="utf-8"),
                                    down.read_text(encoding="utf-8")))
    versions = [m.version for m in migrations]
    if versions != list(range(1, len(versions) + 1)):
        raise ValueError(f"migration versions must be 1..n without gaps: {versions}")
    return migrations


def _ensure_table(conn) -> None:
    with conn.transaction():
        conn.execute("""CREATE TABLE IF NOT EXISTS schema_migrations (
            version INTEGER PRIMARY KEY, name TEXT NOT NULL, checksum CHAR(64) NOT NULL,
            applied_at TIMESTAMPTZ NOT NULL DEFAULT NOW())""")


def applied(conn) -> dict[int, str]:
    _ensure_table(conn)
    return dict(conn.execute("SELECT version, checksum FROM schema_migrations").fetchall())


def upgrade(conn, migrations: list[Migration], target: int | None = None) -> list[int]:
    done = applied(conn)
    for m in migrations:
        if m.version in done and done[m.version] != m.checksum:
            raise RuntimeError(f"migration {m.version:04d}_{m.name} changed after it was applied")
    ran = []
    for m in migrations:
        if m.version in done or (target is not None and m.version > target):
            continue
        with conn.transaction():
            conn.execute(m.up)
            conn.execute("INSERT INTO schema_migrations(version, name, checksum) VALUES (%s,%s,%s)",
                         (m.version, m.name, m.checksum))
        ran.append(m.version)
    return ran


def downgrade(conn, migrations: list[Migration], target: int) -> list[int]:
    done = applied(conn)
    ran = []
    for m in sorted(migrations, key=lambda m: m.version, reverse=True):
        if m.version <= target or m.version not in done:
            continue
        with conn.transaction():
            conn.execute(m.down)
            conn.execute("DELETE FROM schema_migrations WHERE version = %s", (m.version,))
        ran.append(m.version)
    return ran


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="keirin-db")
    parser.add_argument("--dsn", default=os.environ.get("KEIRIN_DATABASE_URL"),
                        help="PostgreSQL DSN (default: $KEIRIN_DATABASE_URL)")
    parser.add_argument("--dir", type=Path, default=DEFAULT_DIR)
    sub = parser.add_subparsers(dest="command", required=True)
    up = sub.add_parser("upgrade")
    up.add_argument("--to", type=int)
    down = sub.add_parser("downgrade")
    down.add_argument("--to", type=int, required=True, help="0 removes everything")
    sub.add_parser("status")
    args = parser.parse_args(argv)
    if not args.dsn:
        parser.error("--dsn or KEIRIN_DATABASE_URL is required")

    import psycopg  # optional dependency: pip install -e '.[db]'

    migrations = discover(args.dir)
    with psycopg.connect(args.dsn, autocommit=True) as conn:
        if args.command == "upgrade":
            print("applied:", upgrade(conn, migrations, args.to) or "nothing")
        elif args.command == "downgrade":
            print("rolled back:", downgrade(conn, migrations, args.to) or "nothing")
        else:
            done = applied(conn)
            for m in migrations:
                print(f"{m.version:04d}_{m.name}: {'applied' if m.version in done else 'pending'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
