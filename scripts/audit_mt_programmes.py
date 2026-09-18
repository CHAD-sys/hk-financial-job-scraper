#!/usr/bin/env python3
"""Audit the workbook-supplied MT links and produce a reviewable evidence report.

Run from the project root:
    python scripts/audit_mt_programmes.py

The output is intentionally a report, not an automatic content overwrite.
Only a human-approved record with explicit employer evidence should be copied
into the public MT status layer.
"""

from __future__ import annotations

import argparse
import asyncio
from collections import Counter
from dataclasses import asdict
from datetime import UTC, datetime
import html
import json
from pathlib import Path
import re
import sys
from urllib.parse import urlparse

import httpx

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from hk_jobs.mt_audit import classify_page


LINKS_FILE = ROOT / "webapp/frontend/src/content/managementTraineeLinks.ts"
DEFAULT_OUTPUT = ROOT / "outputs/mt_link_audit.json"
DEFAULT_REPORT = ROOT / "outputs/MT_LINK_AUDIT.md"
DEFAULT_HTML = ROOT / "outputs/MT_LINK_AUDIT.html"
ENTRY = re.compile(r"^  (?:(?:'([^']+)')|([a-z0-9-]+)): \[(.*?)^  \],", re.MULTILINE | re.DOTALL)
URL = re.compile(r"'([^']+)'" )
TAG = re.compile(r"<[^>]+>")
TITLE = re.compile(r"<title[^>]*>(.*?)</title>", re.IGNORECASE | re.DOTALL)
AGGREGATOR_HOSTS = frozenset({"jobsdb.com", "indeed.com", "linkedin.com", "efinancialcareers.com"})
MINIMUM_READABLE_TEXT = 420


def programme_links() -> dict[str, list[str]]:
    """Read the existing TS source of truth without maintaining a duplicate URL list."""
    content = LINKS_FILE.read_text(encoding="utf-8")
    return {(quoted_key or bare_key): URL.findall(body) for quoted_key, bare_key, body in ENTRY.findall(content)}


def visible_text(markup: str) -> str:
    return html.unescape(TAG.sub(" ", markup))


def is_official_watch_url(url: str) -> bool:
    """Keep browser rendering away from aggregator pages and their ToS risk."""
    host = (urlparse(url).hostname or "").lower()
    return bool(host) and not any(host == domain or host.endswith(f".{domain}") for domain in AGGREGATOR_HOSTS)


def should_use_scrapling_fallback(url: str, http_status: int, page_text: str) -> bool:
    """Render only an official page that direct HTTP could not meaningfully read."""
    return is_official_watch_url(url) and (http_status in {403, 429} or len(page_text.strip()) < MINIMUM_READABLE_TEXT)


def fetch_rendered_page(url: str) -> tuple[int, str, str]:
    """One bounded, optional rendered retry for a genuinely unreadable official page."""
    from scrapling.fetchers import StealthyFetcher

    response = StealthyFetcher.fetch(url, headless=True, timeout=20_000)
    return int(response.status), str(response.html_content), url


async def fetch_one(
    client: httpx.AsyncClient,
    programme_id: str,
    url: str,
    *,
    rendered_fallback: bool = False,
    render_budget: asyncio.Queue[None] | None = None,
) -> dict[str, object]:
    checked_at = datetime.now(UTC).isoformat()
    try:
        response = await client.get(url, follow_redirects=True)
        markup = response.text
        response_status = response.status_code
        final_url = str(response.url)
        fetch_method = "httpx"
        page_text = visible_text(markup)
        if rendered_fallback and render_budget and should_use_scrapling_fallback(url, response_status, page_text):
            try:
                render_budget.get_nowait()
            except asyncio.QueueEmpty:
                pass
            else:
                try:
                    response_status, markup, final_url = await asyncio.to_thread(fetch_rendered_page, url)
                    page_text = visible_text(markup)
                    fetch_method = "scrapling"
                except Exception as error:  # Optional dependency/browser failures must not abort the audit.
                    fetch_method = f"httpx (render failed: {type(error).__name__})"
        title_match = TITLE.search(markup)
        classification = classify_page(page_text, http_status=response_status)
        return {
            "programme_id": programme_id,
            "url": url,
            "final_url": final_url,
            "http_status": response_status,
            "title": html.unescape(TAG.sub(" ", title_match.group(1))).strip() if title_match else None,
            "checked_at": checked_at,
            "fetch_method": fetch_method,
            **asdict(classification),
        }
    except httpx.HTTPError as error:
        return {
            "programme_id": programme_id,
            "url": url,
            "final_url": None,
            "http_status": None,
            "title": None,
            "checked_at": checked_at,
            "fetch_method": "httpx",
            "status": "unavailable",
            "deadline": None,
            "evidence": f"Request failed: {type(error).__name__}",
        }


async def audit(
    links: dict[str, list[str]],
    *,
    rendered_fallback: bool = False,
    render_limit: int = 8,
) -> list[dict[str, object]]:
    work = [(programme_id, url) for programme_id, urls in links.items() for url in urls]
    headers = {"User-Agent": "FinEx Careers MT Link Auditor/1.0 (contact: careers@finexclub.org)"}
    timeout = httpx.Timeout(12.0, connect=8.0)
    render_budget: asyncio.Queue[None] | None = None
    if rendered_fallback:
        render_budget = asyncio.Queue(maxsize=render_limit)
        for _ in range(render_limit):
            render_budget.put_nowait(None)
    # Do not require the optional ``h2`` extra merely to run a local audit.
    # HTTP/1.1 is sufficient for these polite, low-volume checks.
    async with httpx.AsyncClient(headers=headers, timeout=timeout) as client:
        tasks = []
        # 2.5 starts/second stays below the project's 3 req/s source-polite limit.
        for index, (programme_id, url) in enumerate(work):
            if index:
                await asyncio.sleep(0.4)
            tasks.append(asyncio.create_task(
                fetch_one(
                    client, programme_id, url,
                    rendered_fallback=rendered_fallback,
                    render_budget=render_budget,
                )
            ))
        return await asyncio.gather(*tasks)


def markdown_report(results: list[dict[str, object]], checked_at: str) -> str:
    counts = Counter(str(row["status"]) for row in results)
    unavailable = [row for row in results if row["status"] == "unavailable"]
    manual = [row for row in results if row["status"] in {"unknown", "unavailable"}]
    lines = [
        "# MT programme link audit",
        "",
        f"Checked: {checked_at}",
        "",
        "## Evidence-backed status summary",
        "",
        "| Status | Links | Meaning |",
        "| --- | ---: | --- |",
        f"| Open | {counts['open']} | Explicit current open wording on a programme-relevant page |",
        f"| Closed | {counts['closed']} | Explicit closed wording; not inferred from a missing page |",
        f"| Unknown | {counts['unknown']} | Reachable but no safe current status evidence |",
        f"| Unavailable | {counts['unavailable']} | HTTP error, blocked page, or request failure |",
        "",
        "## Manual-review queue",
        "",
        "These pages need a human to confirm the current intake, a deadline, or a replacement URL. "
        "Do not publish them as open or closed from this audit alone.",
        "",
        "| Programme ID | Result | Check | HTTP | URL | Evidence |",
        "| --- | --- | --- | ---: | --- | --- |",
    ]
    for row in manual:
        url = str(row["url"]).replace("|", "%7C")
        evidence = str(row["evidence"]).replace("|", "\\|")[:160]
        lines.append(f"| {row['programme_id']} | {row['status']} | {row.get('fetch_method', 'httpx')} | {row['http_status'] or '—'} | {url} | {evidence} |")
    if unavailable:
        lines.extend(["", "## Broken or blocked links", ""])
        for row in unavailable:
            lines.append(f"- `{row['programme_id']}` — {row['url']} ({row['evidence']})")
    return "\n".join(lines) + "\n"


def html_report(results: list[dict[str, object]], checked_at: str) -> str:
    """Render a standalone audit desk that is useful without the codebase."""
    counts = Counter(str(row["status"]) for row in results)
    status_order = ("open", "closed", "unknown", "unavailable")
    manual_count = counts["unknown"] + counts["unavailable"]

    def esc(value: object | None) -> str:
        return html.escape(str(value if value not in (None, "") else "Not captured"))

    def label(status: str) -> str:
        return {"open": "Open", "closed": "Closed", "unknown": "Needs review", "unavailable": "Unavailable"}[status]

    cards = "".join(
        f'<button class="summary-card summary-card--{status}" type="button" '
        f'onclick="filterRows(\'{status}\')" aria-label="Show {label(status).lower()} links">'
        f'<span>{label(status)}</span><strong>{counts[status]}</strong></button>'
        for status in status_order
    )
    rows = "\n".join(
        "<tr data-status=\"{status}\" data-search=\"{search}\">"
        "<td class=\"programme\">{programme}<span class=\"source-title\">{title}</span></td>"
        "<td><span class=\"status status--{status}\">{label}</span></td>"
        "<td>{http_status}</td><td>{deadline}</td><td>{checked_at}</td>"
        "<td><a href=\"{url}\" target=\"_blank\" rel=\"noopener noreferrer\">Open source <span aria-hidden=\"true\">↗</span></a></td>"
        "<td class=\"evidence\">{evidence}</td></tr>".format(
            status=esc(row["status"]),
            search=esc(" ".join(str(row.get(key) or "") for key in ("programme_id", "status", "title", "evidence", "url"))).lower(),
            programme=esc(row["programme_id"]),
            title=esc(row.get("title")),
            label=esc(label(str(row["status"]))),
            http_status=esc(row["http_status"]),
            deadline=esc(row["deadline"]),
            checked_at=esc(str(row["checked_at"]).replace("T", " ").replace("+00:00", " UTC")),
            url=esc(row["url"]),
            evidence=esc(row["evidence"]),
        )
        for row in results
    )
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>FinEx Careers — MT link audit</title>
  <style>
    :root {{ --navy:#0b1628; --navy-2:#16223a; --ink:#172033; --muted:#58647a; --paper:#fffdf9; --surface:#fff; --line:#dce3ec; --gold:#9a6f00; --gold-soft:#fbf0d3; --blue:#1e3a8a; --green:#126b46; --green-soft:#e3f3eb; --red:#a73535; --red-soft:#fbeaea; --slate:#516071; --slate-soft:#edf1f5; }}
    * {{ box-sizing:border-box; }} body {{ margin:0; background:var(--paper); color:var(--ink); font:15px/1.5 Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; }}
    .masthead {{ border-top:3px solid var(--gold); border-bottom:1px solid var(--line); background:var(--paper); color:var(--ink); }} .wrap {{ width:min(1160px, calc(100% - 40px)); margin:auto; }}
    .masthead .wrap {{ display:flex; align-items:baseline; justify-content:space-between; gap:24px; padding:24px 0; }} .eyebrow {{ margin:0; color:var(--gold); font-size:11px; font-weight:750; letter-spacing:.12em; text-transform:uppercase; }} h1 {{ margin:7px 0 0; font-family:Georgia, "Times New Roman", serif; font-size:clamp(1.75rem, 4vw, 2.65rem); letter-spacing:-.04em; line-height:1.02; }} .lede {{ max-width:32rem; margin:0; color:var(--muted); font-size:13px; }}
    main {{ padding:40px 0 72px; }} .brief {{ display:grid; grid-template-columns:minmax(0, 1.4fr) minmax(16rem, .6fr); gap:48px; border-bottom:1px solid var(--line); padding-bottom:34px; }} .brief h2 {{ max-width:20ch; margin:0; font-family:Georgia, "Times New Roman", serif; font-size:clamp(2rem, 4vw, 3.3rem); letter-spacing:-.045em; line-height:1.06; }} .brief p {{ max-width:60ch; margin:16px 0 0; color:var(--muted); font-size:16px; }} .action-note {{ align-self:end; border-top:2px solid var(--navy); padding-top:14px; }} .action-note strong {{ display:block; font-size:11px; letter-spacing:.1em; text-transform:uppercase; }} .action-note p {{ margin:7px 0 0; color:var(--ink); font-size:14px; }}
    .summary {{ display:grid; grid-template-columns:repeat(4, minmax(0, 1fr)); margin-top:26px; border-top:1px solid var(--line); border-bottom:1px solid var(--line); }} .summary-card {{ min-height:82px; border:0; border-right:1px solid var(--line); background:transparent; padding:14px 16px; color:var(--ink); text-align:left; cursor:pointer; }} .summary-card:last-child {{ border-right:0; }} .summary-card:hover, .summary-card:focus-visible {{ background:var(--surface); outline:2px solid var(--blue); outline-offset:-2px; }} .summary-card span {{ display:block; color:var(--muted); font-size:10px; font-weight:750; letter-spacing:.1em; text-transform:uppercase; }} .summary-card strong {{ display:block; margin-top:5px; font-family:Georgia, "Times New Roman", serif; font-size:28px; font-variant-numeric:tabular-nums; line-height:1; }} .summary-card--open strong {{ color:var(--green); }} .summary-card--closed strong, .summary-card--unavailable strong {{ color:var(--red); }} .summary-card--unknown strong {{ color:var(--gold); }}
    .context {{ display:flex; flex-wrap:wrap; justify-content:space-between; gap:12px; margin:46px 0 16px; border-bottom:1px solid var(--line); padding-bottom:16px; }} .context h2 {{ margin:0; font-family:Georgia, "Times New Roman", serif; font-size:1.9rem; letter-spacing:-.03em; }} .context p {{ margin:4px 0 0; color:var(--muted); }} .checked {{ color:var(--muted); font-size:13px; text-align:right; }}
    .controls {{ display:flex; flex-wrap:wrap; align-items:center; gap:10px; margin:16px 0; }} .filter {{ min-height:40px; border:1px solid var(--line); background:var(--surface); padding:0 13px; color:var(--ink); cursor:pointer; font:inherit; }} .filter[aria-pressed="true"] {{ border-color:var(--blue); background:#eef3ff; color:var(--blue); font-weight:700; }} #search {{ min-height:40px; min-width:min(100%, 320px); flex:1; border:1px solid var(--line); background:var(--surface); padding:0 13px; color:var(--ink); font:inherit; }} #search:focus {{ outline:2px solid var(--blue); outline-offset:2px; }} .result-count {{ margin-left:auto; color:var(--muted); font-size:13px; }}
    .table-shell {{ overflow:auto; border:1px solid var(--line); background:var(--surface); box-shadow:0 6px 18px rgb(11 22 40 / .06); }} table {{ width:100%; border-collapse:collapse; min-width:1050px; }} th {{ position:sticky; top:0; z-index:1; background:var(--navy-2); padding:11px 13px; color:#e2e8f0; font-size:10px; font-weight:750; letter-spacing:.1em; text-align:left; text-transform:uppercase; white-space:nowrap; }} td {{ border-top:1px solid var(--line); padding:13px; vertical-align:top; }} tr:hover td {{ background:#faf8f3; }} .programme {{ max-width:180px; font-weight:700; overflow-wrap:anywhere; }} .source-title {{ display:block; margin-top:4px; color:var(--muted); font-size:11px; font-weight:500; line-height:1.3; }} .evidence {{ min-width:270px; max-width:420px; color:var(--muted); }} a {{ color:var(--blue); font-weight:700; text-decoration:none; white-space:nowrap; }} a:hover {{ text-decoration:underline; }} .status {{ display:inline-flex; padding:3px 7px; font-size:11px; font-weight:750; letter-spacing:.04em; white-space:nowrap; }} .status--open {{ background:var(--green-soft); color:var(--green); }} .status--closed, .status--unavailable {{ background:var(--red-soft); color:var(--red); }} .status--unknown {{ background:var(--gold-soft); color:#705000; }} .empty {{ display:none; padding:30px; color:var(--muted); text-align:center; }}
    @media (max-width:720px) {{ .wrap {{ width:min(100% - 28px, 1240px); }} .masthead .wrap {{ display:block; padding:24px 0; }} .lede {{ margin-top:12px; }} .brief {{ grid-template-columns:1fr; gap:28px; }} .summary {{ grid-template-columns:repeat(2, minmax(0,1fr)); }} .summary-card:nth-child(2) {{ border-right:0; }} .summary-card:nth-child(-n+2) {{ border-bottom:1px solid var(--line); }} .checked {{ text-align:left; }} .result-count {{ width:100%; margin-left:0; }} }} @media print {{ .masthead {{ background:#fff; color:#000; }} .masthead .lede {{ color:#333; }} .summary-card {{ box-shadow:none; }} .controls {{ display:none; }} .table-shell {{ box-shadow:none; overflow:visible; }} table {{ min-width:0; font-size:10px; }} th {{ position:static; background:#eee; color:#111; }} }}
  </style>
</head>
<body>
  <header class="masthead"><div class="wrap"><div><p class="eyebrow">FinEx Careers · source review</p><h1>MT application evidence brief</h1></div><p class="lede">A decision document for turning a loose programme list into reliable application intelligence.</p></div></header>
  <main class="wrap"><section class="brief" aria-labelledby="brief-heading"><div><p class="eyebrow">The present picture</p><h2 id="brief-heading">Most programme links still need a human verdict.</h2><p>This review separates a live page from a trustworthy application fact. We only publish an opening, closing, or deadline when the employer says so explicitly and for the current recruitment cycle.</p></div><aside class="action-note"><strong>Recommended next move</strong><p><b>{manual_count} links</b> need follow-up. Prioritise the unavailable sources first: replace the URL or confirm access, then resolve the generic career pages into a current programme posting.</p></aside></section><section class="summary" aria-label="Audit disposition; select a disposition to filter the evidence ledger">{cards}</section>
    <section aria-labelledby="findings-heading"><div class="context"><div><h2 id="findings-heading">Review every finding</h2><p>Use the status controls or search by employer, evidence, or URL.</p></div><div class="checked">Audit finished<br><strong>{esc(checked_at)}</strong></div></div>
      <div class="controls" aria-label="Audit filters"><button class="filter" type="button" onclick="filterRows('all')" aria-pressed="true">All</button><button class="filter" type="button" onclick="filterRows('open')">Open</button><button class="filter" type="button" onclick="filterRows('closed')">Closed</button><button class="filter" type="button" onclick="filterRows('unknown')">Needs review</button><button class="filter" type="button" onclick="filterRows('unavailable')">Unavailable</button><input id="search" type="search" placeholder="Search employer, evidence, or URL" aria-label="Search audit results"><span id="result-count" class="result-count"></span></div>
      <div class="table-shell"><table><thead><tr><th>Programme</th><th>Finding</th><th>HTTP</th><th>Deadline</th><th>Checked</th><th>Source</th><th>Evidence / reason</th></tr></thead><tbody>{rows}</tbody></table><p id="empty" class="empty">No audit results match those filters.</p></div>
    </section>
  </main>
  <script>
    let activeStatus = 'all'; const rows = [...document.querySelectorAll('tbody tr')]; const search = document.querySelector('#search');
    function filterRows(status) {{ activeStatus = status; document.querySelectorAll('.filter').forEach(button => button.setAttribute('aria-pressed', String(button.textContent.trim().toLowerCase().replace('needs review','unknown') === status || (status === 'all' && button.textContent.trim() === 'All')))); applyFilters(); }}
    function applyFilters() {{ const term = search.value.trim().toLowerCase(); let visible = 0; rows.forEach(row => {{ const show = (activeStatus === 'all' || row.dataset.status === activeStatus) && row.dataset.search.includes(term); row.hidden = !show; if (show) visible += 1; }}); document.querySelector('#result-count').textContent = `${{visible}} of ${{rows.length}} links shown`; document.querySelector('#empty').style.display = visible ? 'none' : 'block'; }}
    search.addEventListener('input', applyFilters); applyFilters();
  </script>
</body></html>"""


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--html", type=Path, default=DEFAULT_HTML)
    parser.add_argument(
        "--render-official-fallback", action="store_true",
        help="Use Scrapling for up to --render-limit unreadable official pages; default is direct HTTP only.",
    )
    parser.add_argument("--render-limit", type=int, default=8, help="Maximum optional rendered retries (default: 8).")
    args = parser.parse_args()

    results = asyncio.run(audit(
        programme_links(),
        rendered_fallback=args.render_official_fallback,
        render_limit=max(0, args.render_limit),
    ))
    checked_at = datetime.now(UTC).isoformat()
    payload = {
        "checked_at": checked_at,
        "summary": Counter(str(row["status"]) for row in results),
        "results": results,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.html.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2, default=str) + "\n", encoding="utf-8")
    args.report.write_text(markdown_report(results, checked_at), encoding="utf-8")
    args.html.write_text(html_report(results, checked_at), encoding="utf-8")
    print(f"Wrote {args.output.relative_to(ROOT)}, {args.report.relative_to(ROOT)}, and {args.html.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
