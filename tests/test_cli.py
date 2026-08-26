"""
The command line: parsing it, and choosing which mode answers it.

`pipeline.main()` used to be sixteen `if` statements deep, and none of it was
reachable from a test without running the thing it dispatched to. The two facts
worth pinning down are the ones that were invisible: which settings exist (and
what they default to), and which mode wins when an invocation selects several.
"""

from __future__ import annotations

import dataclasses
from pathlib import Path

import pytest

from hk_jobs import cli
from hk_jobs.cli import MODES, PipelineArgs, build_parser, parse_args, select_mode

# ── Flags every documented invocation depends on ──────────────────────────────
#
# daily_run.sh runs eight of these on cron and the README documents twenty. A
# flag that stops parsing is a silently broken nightly run.

DOCUMENTED_INVOCATIONS = [
    [],
    ["--fetch-descriptions"],
    ["--enrich"],
    ["--enrich", "--re-enrich"],
    ["--audit-salaries"],
    ["--longtail-only"],
    ["--no-longtail"],
    ["--report", "trends"],
    ["--report", "velocity"],
    ["--weekly-report"],
    ["--export-trends", "data/trends.jsonl"],
    ["--backup"],
    ["--notify-summary"],
    ["--only", "hsbc-hk", "--dry-run", "-v"],
    ["--fetch-posts"],
    ["--promote-posts"],
    ["--check-ghost-jobs"],
    ["--harvest-recruiter-emails"],
    ["--posts-discovery"],
    ["--fetch-posts-backfill"],
    ["--deactivate-stale-posts"],
    ["--repair-companies"],
    ["--replay-salary-rules"],
    ["--posts-pilot-report"],
]


@pytest.mark.parametrize("argv", DOCUMENTED_INVOCATIONS, ids=lambda a: " ".join(a) or "(bare)")
def test_documented_invocations_still_parse(argv):
    assert isinstance(parse_args(argv), PipelineArgs)


# ── PipelineArgs ──────────────────────────────────────────────────────────────

def test_every_parser_dest_has_a_field():
    """
    A flag argparse accepts but `PipelineArgs` does not declare is a flag that
    parses and then does nothing — the worst failure mode available here,
    because it looks like it worked.
    """
    dests = set(vars(build_parser().parse_args([])))
    declared = {f.name for f in dataclasses.fields(PipelineArgs)}
    assert dests - declared == set(), f"dropped on the floor: {sorted(dests - declared)}"


def test_every_field_is_reachable_from_the_parser():
    dests = set(vars(build_parser().parse_args([])))
    declared = {f.name for f in dataclasses.fields(PipelineArgs)}
    assert declared - dests == set(), f"unsettable: {sorted(declared - dests)}"


def test_declared_defaults_match_what_the_parser_produces():
    """
    The load-bearing property. A test writes `PipelineArgs(db=...)` and gets
    production's settings — but only while these two agree. When they drift, a
    test passes against a configuration production never runs, which is exactly
    the class of bug this dataclass replaced.
    """
    from_parser = parse_args([])
    from_defaults = PipelineArgs(db=from_parser.db)
    assert from_parser == from_defaults


def test_pipeline_args_is_frozen():
    with pytest.raises(dataclasses.FrozenInstanceError):
        parse_args([]).dry_run = True  # type: ignore[misc]


def test_from_namespace_ignores_fields_it_does_not_declare():
    import argparse

    ns = argparse.Namespace(db="x.db", not_a_setting="ignored")
    assert PipelineArgs.from_namespace(ns).db == "x.db"


# ── --only / --company ────────────────────────────────────────────────────────

def test_only_flag_accepted():
    assert parse_args(["--only", "aia-hk", "--db", "data/jobs.db"]).company == ("aia-hk",)


def test_only_flag_accepts_multiple_slugs():
    args = parse_args(["--only", "aia-hk", "--only", "blackrock-hk", "--db", "data/jobs.db"])
    assert set(args.company) == {"aia-hk", "blackrock-hk"}


def test_company_flag_still_accepted():
    assert parse_args(["--company", "aia-hk", "--db", "data/jobs.db"]).company == ("aia-hk",)


def test_no_company_flag_is_an_empty_tuple():
    """
    argparse hands back `None` for an unused `action='append'`. Normalising to
    one shape here is why `run()` no longer asks which of three it received.
    """
    assert parse_args([]).company == ()


# ── --verbose ─────────────────────────────────────────────────────────────────

def test_verbose_flag_parsed():
    assert parse_args(["-v", "--db", "data/jobs.db"]).verbose is True
    assert parse_args(["--verbose", "--db", "data/jobs.db"]).verbose is True


def test_verbose_implies_debug_logging():
    assert parse_args(["-v"]).log_level == "DEBUG"
    assert parse_args(["--log-level", "ERROR", "-v"]).log_level == "DEBUG"


# ── Mode selection ────────────────────────────────────────────────────────────

def test_no_mode_flag_means_scrape():
    assert select_mode(parse_args([])) is None


@pytest.mark.parametrize("argv,expected", [
    (["--weekly-report"], "weekly-report"),
    (["--notify-summary"], "notify-summary"),
    (["--backup"], "backup"),
    (["--report", "trends"], "analytics"),
    (["--export-trends", "out.jsonl"], "analytics"),
    (["--enrich"], "enrich"),
    (["--enrich-boutique"], "enrich"),
    (["--audit-salaries"], "audit-salaries"),
    (["--fetch-descriptions"], "fetch-descriptions"),
    (["--fetch-posts"], "fetch-posts"),
    (["--fetch-posts-backfill"], "fetch-posts-backfill"),
    (["--posts-discovery"], "posts-discovery"),
    (["--promote-posts"], "promote-posts"),
    (["--posts-pilot-report"], "posts-pilot-report"),
    (["--harvest-recruiter-emails"], "harvest-recruiter-emails"),
    (["--deactivate-stale-posts"], "deactivate-stale-posts"),
    (["--check-ghost-jobs"], "check-ghost-jobs"),
    (["--repair-companies"], "repair-companies"),
    (["--replay-salary-rules"], "replay-salary-rules"),
])
def test_each_flag_selects_its_mode(argv, expected):
    mode = select_mode(parse_args(argv))
    assert mode is not None and mode.name == expected


def test_two_flags_can_share_one_mode():
    """
    `--report` and `--export-trends` are one analytics pass; `--enrich-boutique`
    implies `--enrich`. This is why a mode is a predicate, not a flag name.
    """
    both = parse_args(["--report", "trends", "--export-trends", "o.jsonl"])
    assert select_mode(both).name == "analytics"
    assert select_mode(parse_args(["--enrich", "--enrich-boutique"])).name == "enrich"


def test_deactivate_stale_posts_selects_on_zero():
    """
    Its `is not None` test, not truthiness: `--deactivate-stale-posts 0` means
    "deactivate everything older than zero days", not "do nothing".
    """
    mode = select_mode(parse_args(["--deactivate-stale-posts", "0"]))
    assert mode is not None and mode.name == "deactivate-stale-posts"


def test_first_mode_in_the_list_wins(caplog):
    """
    Precedence is preserved from the old `if`-chain exactly — `--enrich
    --backup` has always run the backup and dropped the enrichment. The only
    change is that it now says so instead of doing it silently.
    """
    import logging

    with caplog.at_level(logging.WARNING):
        mode = select_mode(parse_args(["--enrich", "--backup"]))

    assert mode is not None and mode.name == "backup"
    assert any("2 modes requested" in m for m in caplog.messages)


def test_a_single_mode_warns_about_nothing(caplog):
    import logging

    with caplog.at_level(logging.WARNING):
        select_mode(parse_args(["--backup"]))
    assert not [m for m in caplog.messages if "modes requested" in m]


def test_mode_names_are_unique():
    names = [m.name for m in MODES]
    assert len(names) == len(set(names))


# ── main() ────────────────────────────────────────────────────────────────────

def test_main_migrates_then_dispatches(tmp_path: Path, monkeypatch):
    """
    Every mode gets a fully-migrated database. A mode used to name the phases it
    believed it needed — which is how the startup path came to be missing
    phases 27 and 28 while five modes each hand-picked phase 26.
    """
    from hk_jobs.migrations import LATEST_PHASE, applied_phases

    db = str(tmp_path / "jobs.db")
    ran: list[str] = []
    monkeypatch.setattr(cli, "_backup", lambda a: ran.append(a.db))
    monkeypatch.setattr(
        cli, "MODES",
        tuple(dataclasses.replace(m, run=lambda a: ran.append(a.db))
              if m.name == "backup" else m
              for m in MODES),
    )

    cli.main(["--backup", "--db", db])

    assert ran == [db]
    assert LATEST_PHASE in applied_phases(db)


def test_main_does_not_touch_the_database_on_a_dry_run(tmp_path: Path, monkeypatch):
    """
    --dry-run promises not to write, which includes not creating the file.

    This is a tightening: a few post modes used to migrate even under
    --dry-run, so they created tables the flag said they would not.
    """
    db = str(tmp_path / "jobs.db")
    monkeypatch.setattr("hk_jobs.pipeline.run", lambda args: [])

    cli.main(["--dry-run", "--db", db])

    assert not Path(db).exists()


def test_main_scrapes_when_no_mode_is_selected(tmp_path: Path, monkeypatch):
    seen: list[PipelineArgs] = []
    monkeypatch.setattr("hk_jobs.pipeline.run", lambda args: seen.append(args) or [])

    db = str(tmp_path / "jobs.db")
    cli.main(["--db", db, "--no-enrich"])

    assert len(seen) == 1
    assert seen[0].db == db and seen[0].no_enrich is True


def test_repair_internship_salaries_is_a_mode_and_needs_repair_apply_to_write():
    """The --repair-* convention: the pass reports by default and writes only when
    --repair-apply is given, so a dry run can never touch published salaries."""
    args = parse_args(["--repair-internship-salaries"])
    assert args.repair_internship_salaries is True
    assert args.repair_apply is False
    mode = select_mode(args)
    assert mode is not None and mode.name == "repair-internship-salaries"


def test_repair_internship_salaries_is_not_selected_by_default():
    assert select_mode(parse_args([])) is None
