"""
Pipeline orchestrator.

Reads companies.yaml, instantiates the right adapter for each company,
calls fetch_jobs(), enriches each job, then upserts to the database.
A company that raises an exception is logged and skipped; the rest continue.
"""

# Phase 1 stub — orchestration logic added in a later phase.
