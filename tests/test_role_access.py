from datetime import timedelta

from role_access import RoleAccess


def test_grant_allows_only_the_exact_role_before_expiry():
    now = [1_000.0]
    access = RoleAccess("test-secret", ttl=timedelta(minutes=5), clock=lambda: now[0])
    grant = access.issue("workday", "RISK-1")

    assert access.allows(grant, "workday", "RISK-1") is True
    assert access.allows(grant, "workday", "OTHER") is False
    assert access.allows(grant, "jobsdb", "RISK-1") is False

    now[0] += 301
    assert access.allows(grant, "workday", "RISK-1") is False


def test_grant_rejects_missing_malformed_and_modified_tokens():
    access = RoleAccess("test-secret", clock=lambda: 1_000.0)
    grant = access.issue("workday", "RISK-1")
    body, signature = grant.split(".")

    assert access.allows(None, "workday", "RISK-1") is False
    assert access.allows("not-a-grant", "workday", "RISK-1") is False
    assert access.allows(f"{body}.{signature[:-1]}x", "workday", "RISK-1") is False
    assert access.allows("x" * 2_049, "workday", "RISK-1") is False


def test_process_local_secret_is_still_unpredictable_when_not_configured():
    first = RoleAccess(clock=lambda: 1_000.0)
    second = RoleAccess(clock=lambda: 1_000.0)
    grant = first.issue("workday", "RISK-1")

    assert first.allows(grant, "workday", "RISK-1") is True
    assert second.allows(grant, "workday", "RISK-1") is False
