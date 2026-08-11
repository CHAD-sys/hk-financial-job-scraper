# Front page — current portal

**Status:** built
**Updated:** 2026-08-11

The `/` route presents FinEx Careers as a three-door portal:

1. **Careers** → `/jobs`
2. **Consultation** → `https://www.finexclub.org/mentor-program`
3. **Learning** → `/learning`

Consultation is an external destination owned by FinEx Club. FinEx Careers does
not collect consultation requests or operate an intake flow.

## Decisions

- The name remains **FinEx Careers**.
- Careers leads because public Roles are the main acquisition path.
- Consultation opens the Club's mentor programme in a new tab.
- Learning remains a first-party page with curated video material.
- Navigation exposes Home, Careers, Consultation, Learning, Market Research and About.
- Recruiter Role submission remains a separate moderated flow at `/post-a-role`.
- Nothing submitted by a Recruiter reaches the board until an administrator approves it.

## Main files

- `webapp/frontend/src/pages/LandingPage.tsx`
- `webapp/frontend/src/components/ProductDoor.tsx`
- `webapp/frontend/src/components/Nav.tsx`
- `webapp/frontend/src/pages/LearningPage.tsx`
- `webapp/frontend/src/pages/PostRolePage.tsx`
- `webapp/backend/main.py` (`POST /api/post-role`)

## Verification

- Frontend tests and production build must pass.
- Backend submission tests must cover the honeypot, rate limit, validation,
  header safety and durable moderation queue.
- Mobile navigation must keep all six public destinations visible.
