"""Run deterministic extractors against verified employer careers portals."""

from __future__ import annotations

from collections.abc import Callable

import httpx

from hk_jobs.adapters.base import BaseAdapter
from hk_jobs.adapters.direct_hkairport import fetch_hkairport
from hk_jobs.adapters.direct_hkma import fetch_hkma
from hk_jobs.adapters.direct_hkmc import fetch_hkmc
from hk_jobs.adapters.direct_hkmca import fetch_hkmca
from hk_jobs.adapters.direct_janestreet import fetch_janestreet
from hk_jobs.adapters.direct_mtr import fetch_mtr
from hk_jobs.adapters.direct_optiver import fetch_optiver
from hk_jobs.adapters.direct_towngas import fetch_towngas
from hk_jobs.adapters.direct_twosigma import fetch_twosigma
from hk_jobs.adapters import (
    direct_ats_misc_a,
    direct_ats_misc_b,
    direct_ats_misc_c,
    direct_big4_cn,
    direct_cn_banks_a,
    direct_cn_banks_b,
    direct_global_banks,
    direct_oracle_hcm,
    direct_phenom_pageup,
    direct_sf_rmk,
    direct_small_hk,
)
from hk_jobs.schema import Job

DirectFetcher = Callable[[httpx.Client, str, str], list[Job]]

SITE_FETCHERS: dict[str, DirectFetcher] = {
    "mtr": fetch_mtr,
    "hkma": fetch_hkma,
    "towngas": fetch_towngas,
    "hkairport": fetch_hkairport,
    "hkmc": fetch_hkmc,
    "hkmca": fetch_hkmca,
    "janestreet": fetch_janestreet,
    "optiver": fetch_optiver,
    "twosigma": fetch_twosigma,
}

# Employers' own careers feeds added 2026-10-30; each module owns its slugs.
# A duplicate key would silently replace an earlier fetcher, so refuse it.
for _module in (
    direct_oracle_hcm,
    direct_sf_rmk,
    direct_phenom_pageup,
    direct_big4_cn,
    direct_cn_banks_a,
    direct_cn_banks_b,
    direct_ats_misc_a,
    direct_ats_misc_b,
    direct_ats_misc_c,
    direct_global_banks,
    direct_small_hk,
):
    _clash = SITE_FETCHERS.keys() & _module.SITE_FETCHERS.keys()
    if _clash:
        raise RuntimeError(f"{_module.__name__} redefines direct sites: {sorted(_clash)}")
    SITE_FETCHERS.update(_module.SITE_FETCHERS)


class DirectSiteAdapter(BaseAdapter):
    """Choose a portal extractor by the validated ``site`` config key."""

    source_name = "direct_site"

    def fetch_jobs(self) -> list[Job]:
        return self._safe_fetch(self._fetch)

    def _fetch(self) -> list[Job]:
        site = self.config["site"]
        with self._client(timeout=30.0) as client:
            return SITE_FETCHERS[site](client, self.company, self.company_slug)
