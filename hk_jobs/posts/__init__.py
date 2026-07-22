"""
LinkedIn recruiter-posts "Secret Market" pipeline (LP-2: ingestion backbone).

See docs/PLAN_LINKEDIN_POSTS.md for the full design and phase plan. This
package only covers the raw ingestion tier — vendor calls, watchlist
polling, discovery search, and cost/budget enforcement. Extraction and
promotion to the `jobs` table is LP-3, not here.
"""
