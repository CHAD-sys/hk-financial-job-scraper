#!/usr/bin/env python3
"""Build the mined half of the resume vocabulary from what employers actually ask for.

    python3 scripts/mine_vocabulary.py [--db data/jobs.db] [--min-df 2]

Reads `job_enrichments.required_skills` — every skill list AI enrichment has
ever written — and emits `webapp/backend/vocabulary_mined.json`:

    {"document_count": 17479, "terms": {"stakeholder management": 3176, ...}}

TWO THINGS THIS BUYS, and they are different:

1. **Vocabulary.** ~12,000 real HK-finance terms nobody would think to type by
   hand — `independent price verification (ipv)`, `str preparation`,
   `equity swaps`, `cbbc`. The handwritten table in `finance_vocabulary.py`
   cannot cover the tail, and the tail is where a specialist lives.

2. **Rarity, which is the important one.** The document frequency is what lets
   `score_resume_fit` weight a match by how much it actually says.
   `stakeholder management` appears in 18.2% of postings and
   `statistical arbitrage` in 0.02%. Scoring them equally is how a Morgan
   Stanley quant's top match came to be a Compliance Manager, matched on
   "english", "training" (from "strength training", in his hobbies) and
   "mathematics" (from his degree).

The output is CHECKED IN. Railway has no jobs.db at build time, and a missing
file must never be fatal — `finance_vocabulary.mined()` degrades to an empty
table and the handwritten layer carries on alone. Re-run this whenever the
catalogue has grown enough to matter; nothing breaks if you forget.
"""

from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "webapp" / "backend"))

import finance_vocabulary as vocabulary  # noqa: E402

OUT_PATH = ROOT / "webapp" / "backend" / "vocabulary_mined.json"

#: A term must look like a skill, not like a sentence the model rambled into.
MAX_TERM_CHARS = 48
MAX_TERM_WORDS = 6
MIN_TERM_CHARS = 2
_TIDY_RE = re.compile(r"\s+")
_PLAUSIBLE_RE = re.compile(r"^[a-z0-9][a-z0-9 +#/&().,'-]*$")


def _tidy(raw: object) -> str | None:
    """Normalise one model-written skill string, or reject it."""
    value = _TIDY_RE.sub(" ", str(raw or "").strip().casefold())
    if not (MIN_TERM_CHARS <= len(value) <= MAX_TERM_CHARS):
        return None
    if len(value.split()) > MAX_TERM_WORDS:
        return None
    if not _PLAUSIBLE_RE.match(value):
        return None
    if value in vocabulary.STOP_SKILLS:
        return None
    return value


def mine(db_path: Path, min_df: int) -> dict:
    conn = sqlite3.connect(db_path)
    try:
        rows = conn.execute(
            "SELECT required_skills FROM job_enrichments "
            "WHERE required_skills IS NOT NULL AND required_skills != ''"
        ).fetchall()
    finally:
        conn.close()

    counts: Counter[str] = Counter()
    documents = 0
    for (payload,) in rows:
        try:
            skills = json.loads(payload)
        except (TypeError, ValueError):
            continue
        if not isinstance(skills, list) or not skills:
            continue
        documents += 1
        # set(): a term counts once per POSTING. Document frequency, not raw
        # frequency — one posting repeating "python" three times must not make
        # python look three times more common than it is.
        for term in {t for t in (_tidy(s) for s in skills) if t}:
            counts[term] += 1

    terms = {term: n for term, n in counts.items() if n >= min_df}
    return {
        "document_count": documents,
        "min_document_frequency": min_df,
        "terms": dict(sorted(terms.items(), key=lambda kv: (-kv[1], kv[0]))),
        "effective": _effective_frequencies(terms),
    }


def _effective_frequencies(terms: dict[str, int]) -> dict[str, int]:
    """How generic a term is, counting the terms that CONTAIN it.

    Raw document frequency confuses a rare string with a rare skill. The model
    almost always writes the long form, so bare `risk` was seen in 2 postings
    and bare `engineering` in 3 — which made both look like specialisms rarer
    than `statistical arbitrage`, and put an HR Technology & Analytics role at
    the top of a quant trader's matches.

    A word that turns up inside many other skills is a generic concept, not a
    specialism. So a term's effective frequency is its own, plus that of every
    mined term whose words are a superset of its own: `risk` collects
    `risk management`, `credit risk`, `market risk`, `operational risk` and
    lands where it belongs, while `statistical arbitrage` is inside almost
    nothing and stays rare.

    Built with an inverted index on the rarest word of each term, which keeps
    this near-linear instead of comparing all 10,000 terms with each other.
    """
    by_word: dict[str, list[tuple[frozenset[str], int]]] = {}
    for term, count in terms.items():
        words = frozenset(term.split())
        if not words:
            continue
        for word in words:
            by_word.setdefault(word, []).append((words, count))

    effective: dict[str, int] = {}
    for term, count in terms.items():
        words = frozenset(term.split())
        if not words:
            continue
        # Any superset of `words` must contain every one of them, so it is
        # enough to scan the postings list of whichever word is scarcest.
        pivot = min(words, key=lambda word: len(by_word.get(word, ())))
        total = 0
        for other_words, other_count in by_word.get(pivot, ()):
            if words <= other_words:
                total += other_count
        effective[term] = max(total, count)
    return effective


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", default=str(ROOT / "data" / "jobs.db"))
    parser.add_argument(
        "--min-df",
        type=int,
        default=2,
        help="drop terms seen in fewer postings than this (default 2: a term "
             "only one posting ever used is usually the model's phrasing, not "
             "the industry's)",
    )
    args = parser.parse_args()

    db_path = Path(args.db)
    if not db_path.exists():
        print(f"No such database: {db_path}", file=sys.stderr)
        return 1

    mined = mine(db_path, args.min_df)
    OUT_PATH.write_text(json.dumps(mined, indent=0, sort_keys=False), encoding="utf-8")

    terms = mined["terms"]
    print(f"{mined['document_count']:,} postings -> {len(terms):,} terms  ->  {OUT_PATH}")
    effective = mined["effective"]
    print("  most common :", ", ".join(list(terms)[:5]))
    inflated = sorted(
        ((effective[t] / max(n, 1), t, n, effective[t]) for t, n in terms.items()),
        reverse=True,
    )[:5]
    print("  generic words rescued from looking rare:")
    for _, term, raw, eff in inflated:
        print(f"      {term:32} seen {raw:5} alone, {eff:6} including compounds")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
