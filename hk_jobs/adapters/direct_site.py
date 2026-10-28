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


class DirectSiteAdapter(BaseAdapter):
    """Choose a portal extractor by the validated ``site`` config key."""

    source_name = "direct_site"

    def fetch_jobs(self) -> list[Job]:
        return self._safe_fetch(self._fetch)

    def _fetch(self) -> list[Job]:
        site = self.config["site"]
        with self._client(timeout=30.0) as client:
            return SITE_FETCHERS[site](client, self.company, self.company_slug)
