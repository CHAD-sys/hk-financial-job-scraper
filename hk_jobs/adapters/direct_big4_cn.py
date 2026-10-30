"""Deloitte China (Hong Kong) and KPMG China (Hong Kong) careers, read from their ATS JSON APIs.

Deloitte runs a Wintalent "wecruit" tenant: a form-POST list endpoint filtered
server-side to the Hong Kong ``workPlaceCode`` plus a per-vacancy detail
endpoint (the only place the full work-place list and the HTML body live).

KPMG runs a Moka HR site. Moka returns the job list as AES-128-CBC ciphertext
``{"data": <base64>, "necromancer": <key>}``: the key travels in the response
itself and the IV (``aesIv``) is printed in the public site HTML, so this is
transport obfuscation done by the page's own JavaScript, not an access control.
Decoding needs no credential and no extra package: a small pure-Python AES
decryptor below reproduces the browser's step. Hong Kong is selected with the
site's own location facet (``locationIds``), then re-checked per job.
"""

import base64
import functools
import html
import json
import logging
import re
import time
from datetime import UTC, datetime, timedelta, timezone

import httpx

from hk_jobs.adapters.workday import _strip_html
from hk_jobs.schema import Job

logger = logging.getLogger(__name__)

_SLEEP = 0.4  # seconds between requests (>= 0.3 required)
_PAGE_CAP = 30  # hard stop on listing pages
_HKT = timezone(timedelta(hours=8))
_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)

# ── Deloitte (Wintalent) ──────────────────────────────────────────────────────

DELOITTE_BASE = "https://ehjobs.deloitte.com.cn"
DELOITTE_SUITE = "SU649e304a6a9f0ef690533e9a"
DELOITTE_HK_CODE = "0/4/595/538135297"
_DL_API = f"{DELOITTE_BASE}/wecruit/positionInfo"
_DL_PARAMS = {"iSaJAx": "isAjax", "request_locale": "en_US"}
_DL_PAGE_SIZE = 50
_DL_HEADERS = {"User-Agent": _UA, "Referer": f"{DELOITTE_BASE}/{DELOITTE_SUITE}/pb/social.html"}


def _parse_dt(value: str | None, tz=_HKT) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.strip().replace(" ", "T"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=tz)


def _as_list(value) -> list:
    """Wintalent sometimes serialises ``workPlaceList`` as a JSON string."""
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError:
            return []
    return value if isinstance(value, list) else []


def deloitte_is_hong_kong(row: dict, detail: dict | None = None) -> bool:
    """True when the work-place list holds the HK code (list rows carry only a label)."""
    places = _as_list((detail or {}).get("workPlaceList") or row.get("workPlaceList"))
    if places:
        return any(p.get("code") == DELOITTE_HK_CODE for p in places if isinstance(p, dict))
    return (row.get("workPlaceStr") or "").strip().lower() == "hong kong"


def deloitte_url(post_id: str) -> str:
    return f"{DELOITTE_BASE}/{DELOITTE_SUITE}/pb/posDetail.html?postId={post_id}&postType=society"


def map_deloitte(row: dict, detail: dict, company: str, company_slug: str) -> Job:
    raw = detail.get("workContent") or ""
    if "&lt;" in raw and "<" not in raw:
        raw = html.unescape(raw)
    extra = detail.get("applyPositionContent") or ""
    if extra:
        raw = f"{raw}\n{extra}"
    places = [
        p.get("name") for p in _as_list(detail.get("workPlaceList")) if isinstance(p, dict) and p.get("name")
    ]
    return Job(
        source="direct_site",
        source_id=f"{company_slug}:{row['postId']}",
        company=company,
        company_slug=company_slug,
        url=deloitte_url(row["postId"]),
        title=(row.get("postName") or "").strip(),
        description_raw=raw,
        description_clean=_strip_html(raw),
        locations=places or [row.get("workPlaceStr") or "Hong Kong"],
        department=row.get("postTypeName") or None,
        posted_at=_parse_dt(row.get("publishFirstDate") or row.get("publishDate")),
        scraped_under_slug=company_slug,
    )


def _deloitte_list(client: httpx.Client) -> list[dict]:
    rows: dict[str, dict] = {}
    expected = None
    for page in range(1, _PAGE_CAP + 1):
        response = client.post(
            f"{_DL_API}/listPosition/{DELOITTE_SUITE}",
            params=_DL_PARAMS,
            data={
                "recruitType": 2,
                "workPlaceCode": DELOITTE_HK_CODE,
                "pageSize": _DL_PAGE_SIZE,
                "currentPage": page,
            },
            headers=_DL_HEADERS,
        )
        response.raise_for_status()
        form = (response.json().get("data") or {}).get("pageForm") or {}
        data = form.get("pageData") or []
        expected = form.get("dataCount", expected)
        fresh = [r for r in data if r.get("postId") and r["postId"] not in rows]
        if not fresh:
            break
        for r in fresh:
            rows[r["postId"]] = r
        if page >= (form.get("totalPage") or 1):
            break
        time.sleep(_SLEEP)
    if expected is not None and len(rows) != expected:
        raise ValueError(f"Deloitte listing is inconsistent: collected {len(rows)} of {expected}")
    return list(rows.values())


def _deloitte_detail(client: httpx.Client, post_id: str) -> dict:
    response = client.post(
        f"{_DL_API}/listPositionDetail/{DELOITTE_SUITE}",
        params=_DL_PARAMS,
        data={"postId": post_id, "recruitType": 2},
        headers=_DL_HEADERS,
    )
    response.raise_for_status()
    return (response.json().get("data") or {}) if response.content else {}


def fetch_deloitte(client: httpx.Client, company: str, company_slug: str, limit: int | None = None) -> list[Job]:
    jobs = []
    for row in _deloitte_list(client)[:limit]:
        time.sleep(_SLEEP)
        detail = _deloitte_detail(client, row["postId"])
        if not deloitte_is_hong_kong(row, detail):
            continue
        jobs.append(map_deloitte(row, detail, company, company_slug))
    return jobs


# ── KPMG (Moka HR) ────────────────────────────────────────────────────────────

MOKA_BASE = "https://app.mokahr.com"
KPMG_ORG, KPMG_SITE = "kpmg", 74216
_MK_PAGE = f"{MOKA_BASE}/social-recruitment/{KPMG_ORG}/{KPMG_SITE}"
_MK_API = f"{MOKA_BASE}/api/outer/ats-apply/website/jobs/v2"
_MK_LIMIT = 15  # Moka rejects a larger page (code 102)
_AES_IV = re.compile(r"aesIv(?:&quot;|\")\s*:\s*(?:&quot;|\")(\w+)")


def _build_sbox() -> list[int]:
    sbox, p, q = [0] * 256, 1, 1
    while True:
        p = p ^ ((p << 1) & 0xFF) ^ (0x1B if p & 0x80 else 0)
        q ^= q << 1
        q ^= q << 2
        q ^= q << 4
        q &= 0xFF
        if q & 0x80:
            q ^= 0x09
        x = q ^ ((q << 1) | (q >> 7)) & 0xFF ^ ((q << 2) | (q >> 6)) & 0xFF
        x ^= ((q << 3) | (q >> 5)) & 0xFF ^ ((q << 4) | (q >> 4)) & 0xFF
        sbox[p] = (x ^ 0x63) & 0xFF
        if p == 1:
            break
    sbox[0] = 0x63
    return sbox


_SBOX = _build_sbox()
_INV_SBOX = [0] * 256
for _i, _v in enumerate(_SBOX):
    _INV_SBOX[_v] = _i


def _xtime(a: int) -> int:
    return ((a << 1) ^ 0x11B) & 0xFF if a & 0x80 else a << 1


def _mul(a: int, b: int) -> int:
    out = 0
    while b:
        if b & 1:
            out ^= a
        a, b = _xtime(a), b >> 1
    return out


_MUL = {n: [_mul(i, n) for i in range(256)] for n in (9, 11, 13, 14)}


def _expand_key(key: bytes) -> list[list[int]]:
    words = [list(key[i : i + 4]) for i in range(0, 16, 4)]
    rcon = 1
    for i in range(4, 44):
        word = list(words[i - 1])
        if i % 4 == 0:
            word = [_SBOX[b] for b in word[1:] + word[:1]]
            word[0] ^= rcon
            rcon = _xtime(rcon)
        words.append([a ^ b for a, b in zip(words[i - 4], word)])
    return [sum(words[r * 4 : r * 4 + 4], []) for r in range(11)]


def _decrypt_block(block: bytes, round_keys: list[list[int]]) -> bytes:
    s = [b ^ k for b, k in zip(block, round_keys[10])]
    for rnd in range(9, -1, -1):
        # inverse ShiftRows then inverse SubBytes (state is column-major)
        s = [_INV_SBOX[s[(i - 4 * (i % 4)) % 16]] for i in range(16)]
        s = [b ^ k for b, k in zip(s, round_keys[rnd])]
        if rnd:
            m9, m11, m13, m14 = _MUL[9], _MUL[11], _MUL[13], _MUL[14]
            out = []
            for c in range(0, 16, 4):
                a0, a1, a2, a3 = s[c : c + 4]
                out += [
                    m14[a0] ^ m11[a1] ^ m13[a2] ^ m9[a3],
                    m9[a0] ^ m14[a1] ^ m11[a2] ^ m13[a3],
                    m13[a0] ^ m9[a1] ^ m14[a2] ^ m11[a3],
                    m11[a0] ^ m13[a1] ^ m9[a2] ^ m14[a3],
                ]
            s = out
    return bytes(s)


def aes128_cbc_decrypt(ciphertext: bytes, key: bytes, iv: bytes) -> bytes:
    """AES-128-CBC with PKCS7 unpadding (what Moka's page script does)."""
    if len(key) != 16 or len(iv) != 16 or not ciphertext or len(ciphertext) % 16:
        raise ValueError("bad AES-128-CBC key, iv or ciphertext length")
    round_keys = _expand_key(key)
    out, prev = bytearray(), iv
    for i in range(0, len(ciphertext), 16):
        block = ciphertext[i : i + 16]
        out += bytes(a ^ b for a, b in zip(_decrypt_block(block, round_keys), prev))
        prev = block
    pad = out[-1]
    if not 1 <= pad <= 16 or out[-pad:] != bytes([pad]) * pad:
        raise ValueError("bad PKCS7 padding: wrong key/iv or changed cipher")
    return bytes(out[:-pad])


def moka_unwrap(payload: dict, iv: str):
    """Return the ``data`` of a Moka response, decrypting it when it is wrapped."""
    if "necromancer" in payload:
        plain = aes128_cbc_decrypt(
            base64.b64decode(payload["data"]), payload["necromancer"].encode(), iv.encode()
        )
        payload = json.loads(plain.decode("utf-8"))
    if str(payload.get("code", "0")) not in ("0", "200") and payload.get("success") is False:
        raise ValueError(f"Moka error: {payload.get('msg')}")
    return payload.get("data")


def kpmg_is_hong_kong(job: dict) -> bool:
    return any(
        loc.get("cityId") == 810000
        or (loc.get("cityName") or "").strip().lower() == "hong kong"
        or (loc.get("provinceName") or "").strip().lower() == "hong kong"
        for loc in job.get("locations") or []
        if isinstance(loc, dict)
    )


def map_kpmg(job: dict, company: str, company_slug: str) -> Job:
    raw = job.get("jobDescription") or ""
    if "&lt;" in raw and "<" not in raw:
        raw = html.unescape(raw)
    names = []
    for loc in job.get("locations") or []:
        name = loc.get("cityName") or loc.get("provinceName")
        if name and name not in names:
            names.append(name)
    return Job(
        source="direct_site",
        source_id=f"{company_slug}:{job['id']}",
        company=company,
        company_slug=company_slug,
        url=f"{_MK_PAGE}#/job/{job['id']}",
        title=(job.get("title") or "").strip(),
        description_raw=raw,
        description_clean=_strip_html(raw),
        locations=names or ["Hong Kong"],
        posted_at=_parse_dt(job.get("openedAt") or job.get("publishedAt")),
        scraped_under_slug=company_slug,
        board_signals={"requisition": job.get("mjCode")},
    )


def fetch_kpmg(client: httpx.Client, company: str, company_slug: str) -> list[Job]:
    page = client.get(_MK_PAGE, headers={"User-Agent": _UA}, follow_redirects=True)
    page.raise_for_status()
    match = _AES_IV.search(page.text)
    if not match:
        raise ValueError("Moka site page no longer exposes aesIv")
    iv = match.group(1)
    headers = {"User-Agent": _UA, "Referer": _MK_PAGE}
    base = {"orgId": KPMG_ORG, "siteId": KPMG_SITE, "locale": "en-US"}

    def post(url: str, body: dict):
        time.sleep(_SLEEP)
        response = client.post(url, json=body, headers=headers)
        response.raise_for_status()
        return moka_unwrap(response.json(), iv)

    facets = post(f"{_MK_API}/filterFieldsAggregations", base) or {}
    locations = (facets.get("systemFieldsAggregations") or {}).get("locationAggregation") or {}
    ids = [
        row["id"]
        for entry in locations.get("locationList") or []
        if (entry.get("label") or "").strip().lower() == "hong kong"
        for row in entry.get("locationRows") or []
    ]
    if not ids:
        return []  # no Hong Kong location row on the site: nothing to list

    found: dict[str, dict] = {}
    for n in range(_PAGE_CAP):
        data = post(_MK_API, {**base, "limit": _MK_LIMIT, "offset": n * _MK_LIMIT, "locationIds": ids}) or {}
        rows = data.get("jobs") or []
        fresh = [r for r in rows if r.get("id") and r["id"] not in found]
        if rows and not fresh:
            break  # page repeated: stop rather than loop
        for r in fresh:
            found[r["id"]] = r
        if len(rows) < _MK_LIMIT:
            break
    return [map_kpmg(j, company, company_slug) for j in found.values() if kpmg_is_hong_kong(j)]


SITE_FETCHERS = {
    "deloitte": fetch_deloitte,
    "kpmg": fetch_kpmg,
}
