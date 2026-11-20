import pytest

from keirin_intelligence.governance import GateRejected
from keirin_intelligence.sources import load_registry, require_automation_allowed

OPEN = "User-agent: *\nDisallow:\n"
REGISTRY = {"ok.example": {"host": "ok.example", "status": "permitted", "evidence": "written approval"}}


def test_bundled_registry_permits_nothing_yet():
    registry = load_registry()
    assert {"keirin.jp", "keirin.netkeiba.com"} <= set(registry)
    assert all(row["status"] != "permitted" for row in registry.values())


@pytest.mark.parametrize("host", ["keirin.jp", "keirin.netkeiba.com", "gamboo.jp"])
def test_reviewed_sites_are_refused_even_with_open_robots(host):
    with pytest.raises(GateRejected, match="automated access"):
        require_automation_allowed(f"https://{host}/db/", OPEN)


def test_unknown_host_is_refused():
    with pytest.raises(GateRejected, match="no terms review"):
        require_automation_allowed("https://new.example/", OPEN, REGISTRY)


def test_permitted_host_still_respects_robots():
    require_automation_allowed("https://ok.example/data", OPEN, REGISTRY)
    with pytest.raises(GateRejected, match="robots"):
        require_automation_allowed("https://ok.example/data", "User-agent: *\nDisallow: /data\n", REGISTRY)
