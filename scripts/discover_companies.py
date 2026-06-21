#!/usr/bin/env python3
"""
scripts/discover_companies.py — platform discovery probe.

Given a master CSV of companies, find which platform (if any) actually serves
each company's Hong Kong jobs, and roughly how many. This automates the
slug/tenant guessing we used to do by hand, so we only add CONFIRMED-reachable
companies to companies.yaml.

Strategy (Principle 5: prefer reliable APIs over fragile JobsDB scraping):
    1. Workday   — POST {tenant}.wdN.myworkdayjobs.com JSON API, searchText="Hong Kong"
    2. Eightfold — GET  {tenant}.eightfold.ai JSON API, location="Hong Kong"
    3. JobsDB    — LAST resort; reuse the hardened JobsDBAdapter (page 1 only).
                   Only this path needs the headless browser, so it's tried last
                   and only when the APIs miss.

A fast DNS pre-check skips dead Workday/Eightfold subdomains without an HTTP
round-trip, so most wrong guesses cost almost nothing.

Usage:
    python scripts/discover_companies.py \
        --input  scripts/companies_master_list.csv \
        --output scripts/discovered_companies.csv \
        [--limit N] [--strong-only] [--no-jobsdb] [--include-known] [--workers 5]

Input CSV columns (header names matched case-insensitively, extras ignored):
    Company, Sector, Global_Website, Likely_HK_Presence
Output CSV columns:
    Company, Sector, Platform, Slug_or_Tenant, HK_Job_Count, Status
"""
from __future__ import annotations

import argparse
import csv
import logging
import random
import re
import socket
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import httpx
import yaml

# Make the package importable when run as a script.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
                    datefmt="%H:%M:%S")
# Silence the noisy headless-browser / http logs during probing.
for noisy in ("httpx", "httpcore", "scrapling", "hk_jobs.adapters.base", "hk_jobs.adapters.jobsdb"):
    logging.getLogger(noisy).setLevel(logging.CRITICAL)
logger = logging.getLogger("discover")

_HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                   "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"),
    "Accept": "application/json",
}

# Generic words dropped when deriving a Workday/Eightfold tenant from a name.
_GENERIC = {
    "the", "group", "holdings", "holding", "ltd", "limited", "inc", "incorporated",
    "plc", "sa", "ag", "nv", "co", "company", "corp", "corporation", "bank", "banking",
    "insurance", "assurance", "financial", "finance", "asset", "management", "investments",
    "investment", "international", "global", "and", "of", "hong", "kong", "hk", "china",
    "asia", "pacific", "securities", "capital", "life", "pension", "fund", "funds", "trust",
}

_WD_SUBS = ["wd3", "wd5", "wd1"]
_WD_SITES = ["External", "Careers", "careers", "Professional", "Experienced", "External_Career_Site"]


# ── name → candidate generators ────────────────────────────────────────────────

def _words(name: str) -> list[str]:
    name = name.replace("&", " and ")
    name = re.sub(r"\(.*?\)", " ", name)          # drop "(Hong Kong)" etc.
    name = re.sub(r"[^A-Za-z0-9 ]", " ", name)
    return [w for w in name.split() if w]


def _name_core(name: str) -> list[str]:
    ws = [w.lower() for w in _words(name)]
    core = [w for w in ws if w not in _GENERIC]
    return core or ws


def jobsdb_slugs(name: str) -> list[str]:
    """Candidate JobsDB slugs: 'Standard Chartered' → Standard-Chartered, standard-chartered…"""
    ws = _words(name)
    if not ws:
        return []
    title = "-".join(ws)
    lower = title.lower()
    cands = [title, lower, f"{lower}-hong-kong"]
    seen, out = set(), []
    for c in cands:
        if c not in seen:
            seen.add(c)
            out.append(c)
    return out


def workday_tenants(name: str) -> list[str]:
    """Candidate Workday tenants: 'AIA Hong Kong' → aia; 'Standard Chartered' → standardchartered, standard."""
    core = _name_core(name)
    cands = []
    if core:
        cands.append("".join(core))
        cands.append(core[0])
    ws = [w.lower() for w in _words(name)]
    if ws:
        cands.append(ws[0])
    seen, out = set(), []
    for c in cands:
        if c and c not in seen:
            seen.add(c)
            out.append(c)
    return out


def domain_from_website(url: str, name: str) -> str | None:
    if url:
        m = re.search(r"https?://(?:www\.)?([^/\s]+)", url.strip())
        if m:
            return m.group(1)
    core = _name_core(name)
    return f"{''.join(core)}.com" if core else None


# ── probes ─────────────────────────────────────────────────────────────────────

def _dns_ok(host: str) -> bool:
    try:
        socket.gethostbyname(host)
        return True
    except OSError:
        return False


def probe_workday(name: str, timeout: float = 12.0) -> dict | None:
    for tenant in workday_tenants(name)[:2]:
        for wd in _WD_SUBS:
            host = f"{tenant}.{wd}.myworkdayjobs.com"
            if not _dns_ok(host):
                continue
            for site in _WD_SITES:
                url = f"https://{host}/wday/cxs/{tenant}/{site}/jobs"
                body = {"appliedFacets": {}, "limit": 20, "offset": 0, "searchText": "Hong Kong"}
                try:
                    with httpx.Client(timeout=timeout, headers=_HEADERS, follow_redirects=True) as c:
                        r = c.post(url, json=body)
                    if r.status_code == 200:
                        total = (r.json() or {}).get("total", 0)
                        if total and total > 0:
                            return {"platform": "workday", "slug": f"{tenant}/{site}/{wd}", "count": total}
                except Exception:
                    pass
                time.sleep(random.uniform(0.3, 0.8))
    return None


def probe_eightfold(name: str, website: str, timeout: float = 12.0) -> dict | None:
    domain = domain_from_website(website, name)
    for tenant in workday_tenants(name)[:2]:   # same heuristic as Workday tenants
        host = f"{tenant}.eightfold.ai"
        if not _dns_ok(host):
            continue
        for dom in [d for d in (domain, f"{tenant}.com") if d]:
            url = f"https://{host}/api/apply/v2/jobs"
            params = {"domain": dom, "start": 0, "num": 10, "location": "Hong Kong"}
            try:
                with httpx.Client(timeout=timeout, headers=_HEADERS, follow_redirects=True) as c:
                    r = c.get(url, params=params)
                if r.status_code == 200:
                    cnt = (r.json() or {}).get("count", 0)
                    if cnt and cnt > 0:
                        return {"platform": "eightfold", "slug": f"{tenant}/{dom}", "count": cnt}
            except Exception:
                pass
            time.sleep(random.uniform(0.3, 0.8))
    return None


def probe_jobsdb(name: str, timeout: float = 90.0) -> dict | None:
    """Last resort — uses the headless browser, so keep candidates to ≤2 and page 1 only."""
    import concurrent.futures as cf

    from hk_jobs.adapters.jobsdb import JobsDBAdapter
    for slug in jobsdb_slugs(name)[:2]:
        adapter = JobsDBAdapter(company=name, company_slug="probe", jobsdb_slug=slug, max_pages=1)
        try:
            with cf.ThreadPoolExecutor(max_workers=1) as ex:
                jobs = ex.submit(adapter.fetch_jobs).result(timeout=timeout)
            if jobs:
                return {"platform": "jobsdb", "slug": slug, "count": len(jobs)}
        except Exception:
            pass
    return None


def discover_one(row: dict, use_jobsdb: bool) -> dict:
    name = row["Company"]
    sector = row.get("Sector", "")
    website = row.get("Global_Website", "")

    hit = probe_workday(name) or probe_eightfold(name, website)
    if not hit and use_jobsdb:
        hit = probe_jobsdb(name)

    if hit:
        logger.info("✓ %-40s %-9s %-30s %s jobs", name[:40], hit["platform"], hit["slug"][:30], hit["count"])
        return {"Company": name, "Sector": sector, "Platform": hit["platform"],
                "Slug_or_Tenant": hit["slug"], "HK_Job_Count": hit["count"], "Status": "reachable"}
    logger.info("· %-40s no reachable platform", name[:40])
    return {"Company": name, "Sector": sector, "Platform": "", "Slug_or_Tenant": "",
            "HK_Job_Count": 0, "Status": "unreachable"}


# ── CSV / known-company handling ────────────────────────────────────────────────

# Tokens dropped when matching a master-list name against companies.yaml. The
# master uses global brand names ("AIA Group", "Zurich Insurance Group") while
# the config uses HK-localised names ("AIA Hong Kong", "Zurich Hong Kong"), so we
# strip geographic + corporate-form + sector words and compare the distinctive
# core. "bank"/"of" are intentionally kept to avoid over-merging distinct firms.
_STRIP_MATCH = {
    "hong", "kong", "hk", "asia", "pacific", "group", "holdings", "holding",
    "plc", "ltd", "limited", "inc", "incorporated", "sa", "ag", "nv", "the",
    "international", "global", "financial", "finance", "insurance", "assurance",
    "investments", "investment", "asset", "management", "co", "company",
    "corp", "corporation", "advisors", "advisers",
}


def _match_key(name: str) -> str:
    ws = [w for w in _words(name) if w.lower() not in _STRIP_MATCH]
    return "".join(w.lower() for w in (ws or _words(name)))


def load_known_names(config_path: str) -> set[str]:
    try:
        data = yaml.safe_load(Path(config_path).read_text())
        return {_match_key(c["name"]) for c in data.get("companies", []) if c.get("name")}
    except Exception as exc:
        logger.warning("Could not read %s for known-company skip: %s", config_path, exc)
        return set()


def read_master(path: str) -> list[dict]:
    rows = []
    with open(path, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        # Map headers case-insensitively to the names we use.
        fieldmap = {(k or "").strip().lower(): k for k in (reader.fieldnames or [])}

        def col(d, *names):
            for n in names:
                k = fieldmap.get(n)
                if k and d.get(k):
                    return d[k].strip()
            return ""
        for d in reader:
            company = col(d, "company", "name")
            if not company:
                continue
            rows.append({
                "Company": company,
                "Sector": col(d, "sector"),
                "Global_Website": col(d, "global_website", "website", "url"),
                "Likely_HK_Presence": col(d, "likely_hk_presence", "hk_presence", "presence").upper(),
            })
    return rows


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--input", required=True, help="Master list CSV")
    p.add_argument("--output", default="scripts/discovered_companies.csv")
    p.add_argument("--config", default="hk_jobs/companies.yaml", help="Existing config (to skip known companies)")
    p.add_argument("--limit", type=int, help="Probe only the first N (after filtering)")
    p.add_argument("--strong-only", action="store_true", help="Probe only Likely_HK_Presence == STRONG")
    p.add_argument("--no-jobsdb", action="store_true", help="Skip the slow JobsDB browser probe (API-only)")
    p.add_argument("--include-known", action="store_true", help="Do NOT skip companies already in companies.yaml")
    p.add_argument("--workers", type=int, default=5, help="Concurrent probes (default 5; keep ≤5 for JobsDB)")
    args = p.parse_args(argv)

    rows = read_master(args.input)
    known = set() if args.include_known else load_known_names(args.config)

    todo = []
    skipped_known = 0
    for r in rows:
        if args.strong_only and r["Likely_HK_Presence"] != "STRONG":
            continue
        if _match_key(r["Company"]) in known:
            skipped_known += 1
            continue
        todo.append(r)
    if args.limit:
        todo = todo[: args.limit]

    logger.info("Master rows: %d | already known (skipped): %d | to probe: %d | jobsdb=%s | workers=%d",
                len(rows), skipped_known, len(todo), not args.no_jobsdb, args.workers)

    results = []
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futs = {pool.submit(discover_one, r, not args.no_jobsdb): r for r in todo}
        for fut in as_completed(futs):
            results.append(fut.result())

    # Stable ordering: reachable first (by count desc), then unreachable.
    results.sort(key=lambda x: (x["Status"] != "reachable", -int(x["HK_Job_Count"]), x["Company"]))

    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["Company", "Sector", "Platform", "Slug_or_Tenant",
                                          "HK_Job_Count", "Status"])
        w.writeheader()
        w.writerows(results)

    reach = [r for r in results if r["Status"] == "reachable"]
    by_plat = {}
    for r in reach:
        by_plat[r["Platform"]] = by_plat.get(r["Platform"], 0) + 1
    logger.info("DONE → %s", out)
    logger.info("Reachable: %d / %d  |  by platform: %s  |  est. jobs: %d",
                len(reach), len(todo), by_plat or "{}", sum(int(r["HK_Job_Count"]) for r in reach))


if __name__ == "__main__":
    main()
