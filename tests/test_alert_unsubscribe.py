from alert_unsubscribe import AlertUnsubscribeToken


def test_token_resolves_back_to_the_seeker_it_was_issued_for():
    tokens = AlertUnsubscribeToken("test-secret")
    token = tokens.issue("seeker-123")

    assert tokens.resolve(token) == "seeker-123"


def test_token_never_expires():
    """Unlike email_tokens or RoleAccess grants, there is no clock involved at all —
    an unsubscribe link minted today must still resolve years from now."""
    tokens = AlertUnsubscribeToken("test-secret")
    token = tokens.issue("seeker-123")

    assert tokens.resolve(token) == "seeker-123"
    assert tokens.resolve(token) == "seeker-123"  # resolving twice: still valid, nothing spent


def test_rejects_missing_malformed_and_modified_tokens():
    tokens = AlertUnsubscribeToken("test-secret")
    token = tokens.issue("seeker-123")
    seeker_id, signature = token.split(".")

    assert tokens.resolve(None) is None
    assert tokens.resolve("not-a-token") is None
    assert tokens.resolve(f"{seeker_id}.{signature[:-1]}x") is None
    assert tokens.resolve("x" * 513) is None


def test_a_token_for_one_seeker_does_not_resolve_as_another():
    tokens = AlertUnsubscribeToken("test-secret")
    token = tokens.issue("seeker-123")
    _, signature = token.split(".")

    forged = f"seeker-456.{signature}"
    assert tokens.resolve(forged) is None


def test_process_local_secret_is_still_unpredictable_when_not_configured():
    first = AlertUnsubscribeToken()
    second = AlertUnsubscribeToken()
    token = first.issue("seeker-123")

    assert first.resolve(token) == "seeker-123"
    assert second.resolve(token) is None
