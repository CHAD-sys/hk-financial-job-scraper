"""
Create (or reset) the Admin Mode accounts.

Admin Mode is not a separate account type — it is the ordinary Seeker sign-in
(webapp/backend/seekers_store.py, auth.py) plus one privilege bit
(`seekers.is_admin`, phase 2 migration). This script is the one-time/rare-reset
tool for the small, named set of humans who get that bit, matching
docs/PLAN_ACCOUNTS.md's existing "no admin UI, do it by hand" operating model
for anything account-related that is not self-serve.

It talks to seekers.db directly through webapp/backend's own modules (not a
copy of the schema) so there is exactly one definition of how a password is
hashed and how a Seeker row is shaped. webapp/backend is not normally on
sys.path outside the running server (see mailer.py/search_index.py: "the repo
root is not on sys.path") — this script adds it, script-side, rather than
teaching the backend package about scripts/.

Usage
    python scripts/create_admin.py               # local data/seekers.db
    SEEKERS_DB_PATH=/path/to/seekers.db python scripts/create_admin.py   # e.g. Railway

Each run rotates every admin's password to a fresh random value and prints it
ONCE, in plaintext, to stdout. Nothing else on disk ever holds the plaintext —
same rule as a password-reset link (auth.py's module docstring). Store the
printed values in a password manager immediately; running this script again
is how you get a new set if they are lost.
"""

from __future__ import annotations

import secrets
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent / "webapp" / "backend"
sys.path.insert(0, str(BACKEND))

import auth  # noqa: E402
import seekers_store  # noqa: E402

# The five people asked for, in the order given. "Ultimate Admin" is the
# fifth slot the owner described as a master account rather than a named
# person's — it gets its own login like the other four, nothing more.
#
# `username` (seekers_store.migrate_to_phase_3) is the whole point of this
# list existing separately from ADMINS-as-emails: signing in as "kenson"
# rather than "kenson@finexclub.org" is the entire ask this script exists to
# fulfil for these five, and for nobody else — there is no self-serve way to
# set this column.
ADMINS = [
    ("Amine Chahid", "amine@finexclub.org", "amine"),
    ("Morris", "morris@finexclub.org", "morris"),
    ("Benjamin", "benjamin@finexclub.org", "benjamin"),
    ("Kenson", "kenson@finexclub.org", "kenson"),
    ("Ultimate Admin", "admin@finexclub.org", "admin"),
]

# Only Ultimate Admin gets is_super_admin (seekers_store.migrate_to_phase_4) —
# the one account that can reach webapp/backend/job_edit.py's direct
# read/write onto a job row. The other four see the same dashboard, never that.
_SUPER_ADMIN_EMAIL = "admin@finexclub.org"


def _generate_password() -> str:
    """20 url-safe characters of `secrets` randomness — well past any brute-force budget."""
    return secrets.token_urlsafe(15)


def main() -> None:
    store = seekers_store.get_store()
    rows: list[tuple[str, str, str, str]] = []  # (display_name, email, username, password)

    for display_name, email, username in ADMINS:
        password = _generate_password()
        password_hash = auth.hash_password(password)
        existing = store.get_seeker_by_email(email)

        if existing is None:
            seeker_id = store.create_seeker(
                email,
                password_hash=password_hash,
                display_name=display_name,
                email_verified=True,  # internal account: nothing to prove by mailing a link
            )
            store.set_admin(seeker_id, True)
            action = "created"
        else:
            seeker_id = existing["id"]
            store.set_password_hash(seeker_id, password_hash)
            store.set_email_verified(seeker_id, True)
            store.set_admin(seeker_id, True)
            store.delete_sessions_for_seeker(seeker_id)  # old password, old sessions — both dead
            action = "reset"

        if email == _SUPER_ADMIN_EMAIL:
            store.set_super_admin(seeker_id, True)

        try:
            store.set_username(seeker_id, username)
        except Exception as exc:  # noqa: BLE001 — sqlite3.IntegrityError: username taken elsewhere
            print(f"  WARNING: could not set username {username!r} for {email}: {exc}",
                  file=sys.stderr)

        rows.append((display_name, email, username, password))
        print(f"  {action:8} {email}", file=sys.stderr)

    print()
    print("=" * 72)
    print("ADMIN MODE CREDENTIALS — shown once, never stored in plaintext anywhere.")
    print(f"Database: {store.db_path}")
    print("=" * 72)
    for display_name, email, username, password in rows:
        print(f"\n{display_name}")
        print(f"  sign in as: {username}   (or the full email: {email})")
        print(f"  password:   {password}")
        if email == _SUPER_ADMIN_EMAIL:
            print("  ** Ultimate Admin: can also directly edit any job's fields **")
    print()
    print("Sign in at /signin with any of the above (username or email both work) —")
    print("Admin Mode redirects to /admin automatically because the account's")
    print("is_admin bit is set.")
    print("Re-run this script any time to rotate all five passwords.")


if __name__ == "__main__":
    main()
