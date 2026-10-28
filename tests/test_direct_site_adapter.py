"""The shared first-party source routes each configured portal to its parser."""

from pathlib import Path

import pytest

from hk_jobs.adapters.direct_site import SITE_FETCHERS, DirectSiteAdapter
from hk_jobs.config import load_companies

_COMPANY_DIR = Path(__file__).resolve().parents[1] / "hk_jobs"


@pytest.mark.parametrize("site", sorted(SITE_FETCHERS))
def test_direct_site_routes_to_the_configured_portal(monkeypatch, site):
    calls = []

    def fake_fetch(client, company, company_slug):
        calls.append((company, company_slug))
        return []

    monkeypatch.setitem(SITE_FETCHERS, site, fake_fetch)
    adapter = DirectSiteAdapter("Example", "example", site=site)
    assert adapter.fetch_jobs() == []
    assert calls == [("Example", "example")]


@pytest.mark.parametrize("site_yaml", ["unknown", "[hkma]"])
def test_unknown_direct_site_fails_at_config_load(tmp_path: Path, site_yaml: str):
    config = tmp_path / "companies.yaml"
    config.write_text(
        "companies:\n"
        "  - name: Example\n"
        "    slug: example\n"
        "    adapter: direct_site\n"
        "    config:\n"
        f"      site: {site_yaml}\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="unknown direct site"):
        load_companies(config)


def test_targeted_portals_are_configured_once_with_reviewed_enablement():
    entries = load_companies(_COMPANY_DIR / "companies.yaml", include_disabled=True)
    entries += load_companies(_COMPANY_DIR / "companies_longtail.yaml", include_disabled=True)
    direct = [entry for entry in entries if entry.adapter == "direct_site"]
    assert {entry.config["site"]: entry.enabled for entry in direct} == {
        "mtr": True,
        "hkma": True,
        "towngas": False,
        "hkairport": True,
        "hkmc": True,
        "hkmca": False,
        "janestreet": True,
        "optiver": True,
        "twosigma": True,
    }
    assert len(direct) == 9
    assert not any(entry.slug == "hkmc-annuity-limited" and entry.adapter == "longtail" for entry in entries)
