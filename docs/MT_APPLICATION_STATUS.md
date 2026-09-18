# MT application-status evidence

This file is the small, reviewable public-status ledger. It is intentionally
not populated from every reachable programme page. A record is added only when
the employer source makes a current, specific application claim.

## Published record

| Employer | Status | Deadline | Checked | Official source | Evidence |
| --- | --- | --- | --- | --- | --- |
| HKEX | Open | 25 October 2026 | 14 September 2026, 04:44 UTC | [HKEX Early Careers](https://www.hkexgroup.com/About-HKEX/Careers-at-HKEX/Early-Careers?sc_lang=en) | “Applications are now open until 25 October 2026.” |

## Audit posture

- `scripts/audit_mt_programmes.py` checks all supplied workbook links at a
  maximum of 2.5 requests/second and writes its latest output to
  `outputs/mt_link_audit.json` and `outputs/MT_LINK_AUDIT.md`.
- A later retry on 14 September was unable to connect to the HKEX Early Careers
  page. That does **not** change the previously captured status to Closed; it
  is recorded as a source-access failure requiring the next scheduled check.
- Do not infer a status from HTTP reachability, a generic “Apply” button, or a
  programme page describing a previous recruitment year.
