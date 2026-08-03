# Send as amine@finexclub.org over the existing mail host, not a new Resend subdomain

**Status:** accepted (2026-07-30) — supersedes the sending-domain half of ADR 0008

Transactional mail to Seekers is sent **from `amine@finexclub.org`, via the existing
authenticated SMTP server at `mail.finexclub.org`**. No new sending subdomain is
created and no DNS records change.

**What ADR 0008 got wrong.** It proposed verifying `mail.finexclub.org` with Resend as
an isolated sending subdomain. DNS says that hostname is not free:

```
finexclub.org  MX   →  mail.finexclub.org
finexclub.org  TXT  →  v=spf1 a mx include:websitewelcome.com ~all
```

`mail.finexclub.org` **is the live business mail server**. Adding Resend's records —
including its bounce MX — to that hostname would have been changing the configuration
of production email, not standing up an isolated channel.

**The second trap:** only one SPF record is valid per domain. The root already carries
HostGator's (`websitewelcome.com` is HostGator/EIG). Publishing a second SPF TXT for
Resend does not stack — it makes SPF return permerror and would degrade delivery of the
*business* mail as well as ours. Any Resend path requires carefully merging
`include:_spf.resend.com` into the existing line, never adding alongside it.

**Why the existing host is sufficient.** `amine@finexclub.org` is hosted on HostGator
with its own authenticated SMTP endpoint, and the current SPF record's `a mx` mechanism
already authorises that server. Sending as the pro address therefore needs **no DNS
change at all**, uses the SMTP code path `webapp/backend/mailer.py` already has, and
puts a recognisable business address in front of Seekers rather than a personal Gmail.

**Consequences:**

- Requires only the mailbox password for `amine@finexclub.org` — no domain verification,
  no propagation wait, and phase 3 stops being DNS-blocked.
- Shared-hosting SMTP has lower throughput and weaker deliverability than a dedicated
  transactional provider. Adequate for verification and password reset at foundation-release
  volume; **revisit before alerts ship**, since alerts are the first bulk send.
- `RESEND_API_KEY` stays configured as a fallback. The key is verified working — a live
  send from `onboarding@resend.dev` succeeded — but the supplied key is **send-only** and
  cannot add or verify domains, so switching to Resend later needs a full-access key and
  the SPF merge above.
- `SMTP_USER` is currently `mohamedaminechahid@gmail.com`. Moving transactional mail off
  the personal Gmail was already an open item; this closes it.
