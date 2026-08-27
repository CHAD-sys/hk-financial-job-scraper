"""
Cross-language parity for the Research Scope gate (ADR 0018).

`job_read.MIN_RESEARCH_QUERY_LENGTH` and its TypeScript twin in
`webapp/frontend/src/api/client.ts` cannot share one constant — Python and
the browser are different processes, different languages. This test is the
seam that replaces sharing: it fails the moment either side's number changes
without the other, which is exactly the drift four independent copies of a
bare `2` used to risk silently.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

from .support import BACKEND

sys.path.insert(0, str(BACKEND))

from job_read import MIN_RESEARCH_QUERY_LENGTH  # noqa: E402

FRONTEND_CLIENT = (
    Path(__file__).resolve().parent.parent
    / "webapp" / "frontend" / "src" / "api" / "client.ts"
)


def test_frontend_min_research_query_length_matches_the_backend():
    source = FRONTEND_CLIENT.read_text(encoding="utf-8")
    match = re.search(r"MIN_RESEARCH_QUERY_LENGTH\s*=\s*(\d+)", source)
    assert match, (
        f"Could not find MIN_RESEARCH_QUERY_LENGTH in {FRONTEND_CLIENT}. "
        "Did it get renamed on one side only?"
    )
    frontend_value = int(match.group(1))
    assert frontend_value == MIN_RESEARCH_QUERY_LENGTH, (
        f"Frontend MIN_RESEARCH_QUERY_LENGTH={frontend_value} but backend "
        f"job_read.MIN_RESEARCH_QUERY_LENGTH={MIN_RESEARCH_QUERY_LENGTH} — "
        "ADR 0018's gate would reject/accept different queries on the client "
        "than the server actually enforces."
    )
