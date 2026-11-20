"""Fail-closed gate for any automated retrieval from a website.

`data/reference/source_terms.csv` records, per host, what the terms review found. Only a
host marked `permitted` (a written approval or terms that clearly allow it, plus
robots.txt) may be fetched by program; everything else is refused. Hand-entering facts
from a page a person is reading stays outside this module.
"""

import csv
from pathlib import Path
from urllib.parse import urlsplit
from urllib.robotparser import RobotFileParser

from keirin_intelligence.governance import GateRejected

STATUSES = {"permitted", "needs_permission", "blocked", "unreviewed"}
DEFAULT_REGISTRY = Path(__file__).resolve().parents[2] / "data" / "reference" / "source_terms.csv"
USER_AGENT = "KeirinIntelligenceResearch"


def load_registry(path: Path = DEFAULT_REGISTRY) -> dict[str, dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as f:
        rows = {row["host"]: row for row in csv.DictReader(f)}
    for host, row in rows.items():
        if row["status"] not in STATUSES:
            raise ValueError(f"{host}: unknown status {row['status']!r}")
    return rows


def require_automation_allowed(
    url: str, robots_txt: str, registry: dict[str, dict[str, str]] | None = None
) -> None:
    """Raise GateRejected unless both the terms review and robots.txt allow fetching `url`."""
    host = urlsplit(url).hostname or ""
    row = (registry if registry is not None else load_registry()).get(host)
    if row is None:
        raise GateRejected(f"{host}: no terms review recorded; add it to source_terms.csv first")
    if row["status"] != "permitted":
        raise GateRejected(f"{host}: automated access is {row['status']} ({row['evidence']})")
    parser = RobotFileParser()
    parser.parse(robots_txt.splitlines())
    if not parser.can_fetch(USER_AGENT, url):
        raise GateRejected(f"{url}: disallowed by robots.txt")
