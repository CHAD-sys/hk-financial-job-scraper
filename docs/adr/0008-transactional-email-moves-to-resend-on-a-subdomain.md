# Transactional email to Seekers goes through Resend, from a subdomain

**Status:** accepted (2026-07-30)

Verification and password-reset mail is sent via **Resend**, from **`mail.finexclub.org`**
— a subdomain, not the root domain.

**Why a new capability is needed at all.** `webapp/backend/mailer.py` sends exactly one
message to a hardcoded `RECIPIENT` constant, and its docstring says why: *"the recipient
must never be derived from a request, or the endpoint becomes an open relay."* The
existing mailer is a one-way funnel *to the operator*. Accounts invert it — mail goes
**to a Seeker, at an address they typed** — which is the precise thing the current design
forbids. That new capability is also a new abuse vector, handled by per-email rate
limiting (see the plan's abuse section).

**Why not Gmail SMTP,** which already works: it caps around 500 recipients/day, and since
February 2024 Gmail and Yahoo require SPF, DKIM and DMARC from bulk senders — which
cannot be configured for `gmail.com`. Password-reset links landing in spam is a permanent
support burden.

**Why Resend:** its 3,000/month free tier is permanent, where AWS SES's is 12 months and
Postmark's 100/month is a token. SES is cheaper at volume and more work to set up; that
trade only pays off at a scale years away.

**Why a subdomain:** `finexclub.org` sends real business mail through Wix. Isolating
transactional sending on `mail.finexclub.org` means a reputation problem from platform
mail never poisons the address used with clients.

**Consequences:**

- **SPF, DKIM and DMARC records must be added to `finexclub.org` DNS.** This has external
  lead time (verification and propagation) and should start before the code does. There
  is no way to route around it — unauthenticated mail to Gmail and Outlook lands in spam,
  and this is the one feature where mail not arriving makes the account unusable.
- Resend becomes a **data processor holding Seeker email addresses in the US**, which is
  a cross-border transfer that the privacy notice must disclose.
