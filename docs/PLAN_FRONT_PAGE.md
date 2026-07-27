# PLAN — New Front Page (three-product portal)

**Status:** built — portal, both forms, both endpoints, tests passing
**Date:** 2026-07-27
**Costed at:** 3d (front page) + 1.5d (L&D section) on the August build plan,
plus ~0.5–1d for the contact endpoint and ~1d for direct role submission, neither
of which the original estimate included.

> **Correction (2026-07-27).** An earlier draft of this plan implied the board's
> **Recruiter Posts** tier already gave recruiters a way to reach us. It does
> not. That tier is **LinkedIn posts we scrape**; recruiters had no channel to
> post to us at all. Direct submission is a new capability, added in §5.8.

---

## 1. What we're building and why

`/` today is a job-board landing page: hero → live stats → Exclusive callout →
Recruiter Posts callout → methodology stripe → footer. It sells one product.

FinEx offers three. The new `/` is a **portal**: three equal doors —
Careers, Executive Career Consultation, Professional L&D — with the two new
products expanded as sections further down the same page.

The job board is demoted from "the whole site" to "one of three doors". It is
still the traffic engine and still leads, but it no longer owns the front page.

### Naming note (decided, with a known tension)

The site keeps the name **FinEx Careers**, even though the portal now offers
mentoring and video learning alongside jobs. The tension — a site called
"Careers" whose front page offers two non-job products — is resolved in **copy,
not architecture**: "Careers" is framed broadly as *your career* (advice,
learning, opportunities), not narrowly as *job listings*. The hero copy has to
carry this. If it doesn't land, revisit the naming rather than the layout.

---

## 2. Page structure

```
/  — FinEx Careers
│
│  HERO           who FinEx is, one line, framing "careers" broadly
│
│  ┌──────────────┐┌──────────────┐┌──────────────┐
│  │   CAREERS    ││ CONSULTATION ││   LEARNING   │
│  │ 3,612 live   ││  Executive   ││   50,000+    │
│  │ 233 employers││              ││  subscribers │
│  └──────┬───────┘└──────┬───────┘└──────┬───────┘
│      → /jobs         ↓ scroll        ↓ scroll
│
│  ┌────────────────────────────────────────────┐
│  │ EXECUTIVE CAREER CONSULTATION              │
│  │ pitch · enquiry form · → /consulting       │
│  └────────────────────────────────────────────┘
│  ┌────────────────────────────────────────────┐
│  │ PROFESSIONAL L&D                           │
│  │ 6 video facades · → @finexclubhq           │
│  └────────────────────────────────────────────┘
│  FOOTER
```

**Door order is Careers → Consultation → Learning.** On desktop they sit side by
side; on mobile they stack, and stack order is priority order. Board leads
because it honours why people arrive and is the only door with live proof.

---

## 3. Decision log

Every decision below was made deliberately. Do not silently reverse one.

| # | Decision | Rationale |
|---|----------|-----------|
| 1 | `/` becomes a three-door portal | Site sells three products, page sold one |
| 2 | Zero new routes | Consultation + L&D are sections on `/`; board is `/jobs` |
| 3 | Door order: Careers · Consultation · Learning | Mobile stack order = priority; intent-led |
| 4 | Brand tokens unchanged | Colours/fonts live in shared `@theme`; changing them restyles the whole app |
| 5 | Name stays "FinEx Careers" | Owner decision; incoherence resolved in copy (§1) |
| 6 | Login-free now, Nav reserves a sign-in slot | Accounts are a separate 5d item; don't retrofit layout later |
| 7 | Callout *explanations* move to `/jobs`, not the callouts themselves | `/jobs` already has Exclusive + Recruiter Posts tabs — see §5.3 |
| 8 | Consultation aimed at **executives** | Owner decision. Note: finexclub.org describes a *student* service — see §7 |
| 9 | Enquiry form, not `mailto:` | mailto silently fails for webmail users |
| 10 | Form: name / email / career stage / message + honeypot | Short enough to complete, one field to triage on |
| 11 | Career stage: 3–8 / 8–15 / 15+ / C-suite | Follows the executive framing |
| 12 | Recipient hardcoded to `mohamedaminechahid@gmail.com` | "For now". Never taken from the request — header-injection defence |
| 13 | Consultation links to `finexclub.org/consulting` | Owner decision. Labelled honestly — see §5.2 |
| 14 | L&D: 6 hand-picked videos, dates hidden | The 6 *latest* are 4 parts of one series + a party, newest 4 months old |
| 15 | Click-to-load video facades | A real iframe costs ~1MB of YouTube JS and sets cookies before consent |
| 16 | "50,000+ subscribers" as the L&D credibility line | Recency can't be the signal when the channel is stale |
| 17 | Exact numbers, never rounded | Precision is the product's personality; `/api/stats` is already honest |
| 18 | Nav gains Consultation + Learning as cross-route anchors | Otherwise both products are invisible from `/jobs` |
| 19 | Recruiters can submit roles directly, at `/post-a-role` | No such channel existed; Recruiter Posts is scraped LinkedIn, not submissions |
| 20 | Submission + moderation only — no accounts, no billing | Ships in August; self-serve and paid inventory remain a separate 20–25d item |
| 21 | Submissions land in a JSONL queue, `status: "pending"` | Nothing reaches the board without a human approving it |

---

## 4. Facts established (do not re-derive)

- **YouTube:** `youtube.com/@finexclubhq`, channel ID `UCJkITsrZncJrmEuNtbFGChg`.
  RSS at `youtube.com/feeds/videos.xml?channel_id=…` exposes **only the newest 15**.
  Latest upload **2026-03-21**. ~70 videos total; the Mastermind Roundtable
  series (named on `/education` as the flagship) is *not* in the RSS window.
- **`/api/stats` is already deduplicated.** `main.py:715` counts
  `is_active=1 AND is_primary=1` → **3,612**, not the 4,996 raw row count.
  The ~1,384 suppressed cross-posts are handled server-side. Safe to print as-is.
- **CORS is GET-only.** `main.py:468` sets `allow_methods=["GET"]`. A POST
  endpoint is invisible to the browser until this changes.
- **`main.py` has no POST endpoint at all** — `/api/contact` is the first.
- **`notifications._send_email(subject, body_html, body_text) -> bool`** exists
  and is reusable (Gmail SMTP, app password).
- **finexclub.org** is Wix. Real pages: `/about`, `/consulting`, `/education`,
  `/careers`, `/committees`, `/contact`, `/research`. `/plans-pricing` 404s —
  **there is no price to display.**
- **`/consulting` is B2B institutional advisory** (human capital, AI
  transformation, HNW wealth) — not individual career mentoring.
- **`/jobs` already has** tier tabs `All / Mainstream / Exclusive / Recruiter
  Posts` and a Recruiter Posts preview strip (`JobBoardPage.tsx:32-36`).

---

## 5. Implementation

### 5.1 Frontend — `/` rebuild

**`src/pages/LandingPage.tsx`** — rewritten. Current sections
(`HeroSection`, `ExclusiveCallout`, `RecruiterPostsCallout`, `MethodologyStripe`)
are replaced by:

| Component | Responsibility |
|-----------|----------------|
| `PortalHero` | Wordmark, one-line positioning, no CTA buttons — the doors *are* the CTA |
| `ProductDoors` | The three-door grid. Desktop `grid-cols-3`, mobile stacked |
| `ConsultationSection` | `id="consultation"` — pitch, `EnquiryForm`, outbound link |
| `LearningSection` | `id="learning"` — 6 video facades, subscriber line, channel link |
| `LandingFooter` | Kept, but the five dead `href="#"` links get real targets or go |

New files under `src/components/`:

- `ProductDoor.tsx` — one door: eyebrow, title, one-line description, live
  figure slot, arrow. Takes an `onActivate` so a door can navigate *or* scroll.
- `EnquiryForm.tsx` — the 4-field form, client validation, submit states
  (idle / sending / sent / error), honeypot input.
- `VideoFacade.tsx` — thumbnail + play overlay; injects the `<iframe>` only on
  click. `loading="lazy"` on the thumbnail.
- `featuredVideos.ts` — a plain typed constant. **Deliberately a hardcoded
  array** so swapping the six picks is a one-line edit with no API key, no
  quota, no build step.

```ts
export interface FeaturedVideo { id: string; title: string; blurb: string }
export const FEATURED_VIDEOS: FeaturedVideo[] = [ /* 6 entries */ ]
```

Thumbnails: `https://i.ytimg.com/vi/{id}/hqdefault.jpg`. No YouTube JS until click.

### 5.2 The outbound consultation link

Label it **"FinEx Consulting — our institutional advisory practice →"**, not
"learn more about consultation". `/consulting` sells corporate advisory; an
executive expecting career guidance would otherwise hit a mismatch. Framing it
as *the firm's other practice* turns that into a credibility signal instead.

### 5.3 Frontend — `/jobs` additions

`/jobs` already has the tabs. What it lacks is the *explanation* the landing
callouts carried. So:

- Add the 4 `StatCard`s above the filter bar (moved wholesale from `/`).
- Add a **compact explainer** — one or two sentences — shown when the Exclusive
  or Recruiter Posts tab is active, explaining what that tier is and where the
  data comes from. Do **not** paste the full landing callouts in; they'd
  duplicate the tabs that already exist.

### 5.4 Frontend — Nav

`src/components/Nav.tsx`:

- Items become **Home · Careers · Consultation · Learning · About**.
- Consultation and Learning are anchors. On `/` they smooth-scroll. On any other
  route they must `navigate('/#consultation')` **and scroll on arrival** —
  react-router does not do hash scrolling for you. Add a small
  `useHashScroll()` hook in `src/hooks/`, called from `LandingPage`, that reads
  `location.hash` on mount and scrolls with `behavior: 'smooth'` *unless*
  `prefers-reduced-motion` is set.
- Reserve the right-hand slot for a future **Sign in** — lay it out now, render
  nothing. Do not ship a button that doesn't work.
- Watch desktop crowding: 5 items + Saved + reserved slot. Check ~768–900px.
- Mobile menu gains both entries.

### 5.5 Backend — `POST /api/contact`

The app's **first write endpoint**. `main.py`'s docstring says "Read-only access
to jobs.db"; update it.

```
POST /api/contact
{ name, email, career_stage, message, website }   # `website` = honeypot
→ 200 { ok: true }
→ 400 validation failure
→ 429 rate limited
```

Guardrails — all required, none optional:

| Guard | Implementation |
|-------|----------------|
| Honeypot | Field named `website`, hidden via CSS. Non-empty → return 200 and **send nothing**. Never tell a bot it failed |
| Rate limit | In-memory `{ip: [timestamps]}`, e.g. 3/hour. In-memory is fine for one instance; note it resets on deploy |
| Length caps | name ≤100, email ≤200, message ≤5000, career_stage from a fixed enum. Reject, don't truncate |
| Header injection | Recipient is a module constant. Subject is built by us. **Never** interpolate user input into a header — user email goes in the *body*, and in `Reply-To` only after validation |
| Email validation | Pydantic `EmailStr` (needs `email-validator`; add to `webapp/backend/requirements.txt`) |
| CORS | `allow_methods=["GET", "POST"]` — currently GET-only, so this is required or the browser blocks it |
| Failure | If SMTP fails, return 500 and **log the enquiry** so it isn't lost |

Body reuses `notifications._send_email()`. Import path from the backend needs
checking — `webapp/backend/` is not obviously on the same path as `hk_jobs/`.
If it isn't importable, copy the ~15-line SMTP helper rather than contorting
`sys.path`.

**Cost note:** this endpoint is real work with real abuse surface. The original
3d estimate did not include it; budget ~0.5–1d on top.

### 5.8 Direct role submission (new capability)

The board's **Recruiter Posts** tier is LinkedIn activity we scrape. It is not a
channel *into* us — until this, a recruiter with a live mandate had no way to put
it in front of this audience except by hoping we scraped it.

`/post-a-role` is that channel. Scope is deliberately **submission + moderation**:

- **In:** a public form (role details + submitter contact), `POST /api/post-role`,
  the same guardrails as `/api/contact`, an append-only JSONL queue with
  `status: "pending"`, and an email notification per submission.
- **Out:** employer accounts, self-serve editing, payment, and any automatic
  publication. Those are the Track 2 "Exclusive Job Listing — paid" item
  (20–25 days) and are not prerequisites for a recruiter posting today.

Entry points: a dark stripe at the foot of the portal, a quiet Nav button, and a
footer link. Deliberately **not** a fourth door — it addresses employers rather
than candidates, and a fourth door would blunt the three that matter.

Approval is manual for now: read `data/submitted_roles.jsonl`, and insert
approved rows into `jobs` with a `direct` source. Automating that is the natural
next step and is not built.

### 5.6 Frontend — API client

`src/api/client.ts`: add `submitEnquiry(payload): Promise<{ok: boolean}>` beside
the existing fetchers, plus an `EnquiryPayload` interface. Follow the existing
style — the file already exports typed fetchers.

### 5.7 Metadata

`index.html`: `<title>` and `<meta name="description">` currently describe a job
index only. Both should describe the three products. Note this changes how an
already-indexed site appears in search results.

---

## 6. Build order

| Phase | Work | Output |
|-------|------|--------|
| 1 | `ProductDoors` + `PortalHero`, wired to live `/api/stats` | Portal skeleton renders |
| 2 | `ConsultationSection` + `EnquiryForm` (UI only, no submit) | Form visible, validates |
| 3 | `POST /api/contact` + guardrails + CORS + `submitEnquiry` | Form actually sends |
| 4 | `LearningSection` + `VideoFacade` + `featuredVideos.ts` | Videos play on click |
| 5 | Nav + `useHashScroll`, reserved sign-in slot | Cross-route anchors work |
| 6 | `/jobs`: StatCards + tier explainers | Migrated content lands |
| 7 | Metadata, footer dead links, responsive + a11y pass | Ship-ready |

Phases 1–2 are safe to build and review before the backend exists.

---

## 7. Known risks

1. **The consultation copy is written from inference.** Nothing on
   finexclub.org describes an *executive* career consultation — `/about`
   describes a service for "undergraduates and postgraduates". The owner
   confirmed the executive framing, so we build to it, but **the copy needs a
   factual pass before it goes live.** This is the one thing on the page that
   cannot be verified from source.
2. **The YouTube channel is four months stale** and the 15 RSS-visible videos
   skew to committee-recruitment clips. Hiding dates mitigates the appearance;
   it does not fix the channel. Ideal fix: feature six Mastermind Roundtable
   episodes, which requires pulling the full catalogue.
3. **A public POST backed by a personal Gmail app password.** Guardrails above
   are the mitigation. If abuse appears, move to a dedicated address or a
   transactional provider before it affects the personal account.
4. **In-memory rate limiting resets on every deploy** and is per-instance. Fine
   for current scale; wrong the moment the backend runs more than one replica.
5. **Nav crowding** at 5 items + Saved + reserved slot on mid-size screens.
6. **`/` stops being a jobs landing page.** Whatever search visibility `/`
   carried for job queries now has to be carried by `/jobs`.

---

## 8. Testing

- **Backend:** `tests/test_contact.py` — honeypot returns 200 and sends nothing;
  over-limit returns 429; oversized fields rejected; header-injection attempt in
  `name`/`email` never reaches a header; SMTP failure returns 500 and logs.
  Mock `_send_email`, never send real mail from a test.
- **Frontend:** `npm run lint` (oxlint) and `npm run build` (tsc) must pass.
  The `react-doctor` and `design-audit` skills under
  `webapp/frontend/.claude/skills/` apply to this work.
- **Manual:** three doors on mobile at 375px; anchors from `/jobs`;
  keyboard-only nav through doors and form; video facade with JS-heavy blockers;
  `prefers-reduced-motion` honoured on smooth scroll.

---

## 9. Open items

- [ ] **Factual pass on the consultation copy** (§7.1) — highest priority, it is
      the only copy on the page written from inference rather than source
- [ ] Which 6 videos to feature — currently picked for range from the 15
      RSS-visible; Mastermind Roundtable episodes would be better
- [ ] Hero one-liner — drafted, needs owner approval
- [ ] Whether enquiries should move off the personal Gmail address
- [ ] `SMTP_USER` / `SMTP_PASS` / `CORS_ORIGINS` set in the deploy environment —
      without SMTP the queue still captures everything, but no email is sent
- [ ] Approval path for submitted roles (currently: read the JSONL by hand)
- [ ] Migrate StatCards + tier explainers onto `/jobs` (§5.3) — not yet done
- [ ] `index.html` title/meta still describe a job index only (§5.7)
- [ ] Success metric: enquiries, `/jobs` sessions, or time on site?
