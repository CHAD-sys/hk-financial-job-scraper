from datetime import date

from hk_jobs.mt_audit import classify_page, parse_deadline
from scripts.audit_mt_programmes import html_report, programme_links, should_use_scrapling_fallback


def test_open_programme_needs_explicit_open_evidence_and_a_relevant_page():
    result = classify_page(
        "Graduate Management Trainee Programme — applications are now open. Apply by 31 October 2026.",
        http_status=200,
        today=date(2026, 9, 14),
    )

    assert result.status == "open"
    assert result.deadline == date(2026, 10, 31)
    assert "applications are now open" in result.evidence.lower()


def test_generic_apply_button_does_not_claim_the_programme_is_open():
    result = classify_page(
        "Explore our early careers programmes. Apply now to see all current opportunities.",
        http_status=200,
        today=date(2026, 9, 14),
    )

    assert result.status == "unknown"
    assert result.deadline is None


def test_stale_open_copy_does_not_claim_the_current_intake_is_open():
    result = classify_page(
        "Management Trainee Programme. Application is now open for our 2021 Internship Program.",
        http_status=200,
        today=date(2026, 9, 14),
    )

    assert result.status == "unknown"


def test_explicit_closed_language_wins_over_a_stale_deadline():
    result = classify_page(
        "Management Trainee Programme. Applications for this programme are closed. "
        "The previous deadline was 31 October 2025.",
        http_status=200,
        today=date(2026, 9, 14),
    )

    assert result.status == "closed"
    assert result.deadline is None


def test_missing_page_is_link_unavailable_not_a_claim_that_recruitment_closed():
    result = classify_page("Not Found", http_status=404, today=date(2026, 9, 14))

    assert result.status == "unavailable"


def test_deadline_parser_accepts_common_explicit_application_dates():
    assert parse_deadline("Applications close on 31 October 2026") == date(2026, 10, 31)
    assert parse_deadline("Apply by October 31, 2026") == date(2026, 10, 31)


def test_audit_reads_every_current_workbook_link_from_the_frontend_source_of_truth():
    links = programme_links()

    assert len(links) == 63
    assert sum(len(urls) for urls in links.values()) == 130


def test_html_report_is_self_contained_filterable_and_escapes_source_text():
    report = html_report([
        {
            "programme_id": "example-programme",
            "url": "https://example.com/job?a=1&b=2",
            "final_url": "https://example.com/job?a=1&b=2",
            "http_status": 200,
            "title": "Programme <title>",
            "checked_at": "2026-09-14T00:00:00+00:00",
            "status": "unknown",
            "deadline": None,
            "evidence": "No explicit status <found>",
        },
    ], "2026-09-14T00:00:00+00:00")

    assert 'data-status="unknown"' in report
    assert "filterRows" in report
    assert "Programme &lt;title&gt;" in report
    assert "No explicit status &lt;found&gt;" in report


def test_scrapling_fallback_is_reserved_for_unreadable_official_pages():
    assert should_use_scrapling_fallback("https://careers.hkjc.com/job/mt", 403, "") is True
    assert should_use_scrapling_fallback("https://hk.jobsdb.com/job/123", 403, "") is False
    assert should_use_scrapling_fallback("https://careers.hkjc.com/job/mt", 200, "Enough page text " * 40) is False
