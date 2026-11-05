---
name: "FinEx Learning"
description: "Integrated learning workspace on warm paper with focused navy contrast"
colors:
  bg: "#faf9f6"
  deep: "#f1efe9"
  surface: "#ffffff"
  raised: "#f2f1ec"
  line: "#dcdedc"
  subtle-line: "#e6e6e0"
  ink: "#17243a"
  muted: "#4c5c6e"
  faint: "#5d6a7b"
  gold: "#dfc28e"
  gold-hover: "#ecd2a4"
  gold-ink: "#1b2027"
  success: "#2c6a4e"
  success-bg: "#edf6ef"
  scroll-thumb: "#b1b8be"
  preview-ink: "#805d23"
  nav-active: "#17243a"
  nav-active-ink: "#faf9f6"
  nav-border: "#17243a"
  count-bg: "#e3e9ee"
  count-ink: "#624c28"
  member-bg: "#e5d8be"
  member-ink: "#403829"
  status: "#4c855c"
  cpd-icon-bg: "#f3ead9"
  badge-success-bg: "#edf6ef"
  badge-success-line: "#c5dccc"
  badge-gold-bg: "#f7efdf"
  badge-gold-line: "#decda8"
  progress-track: "#e1e5e8"
  secondary-ink: "#45566c"
  stat-ink: "#344258"
  continue-bg: "#f3f4f1"
  continue-icon-bg: "#e5efe6"
  continue-play-line: "#c8d5c9"
  field-line: "#cdd3d8"
  field-bg: "#ffffff"
  select-ink: "#46566d"
  sort-ink: "#46566d"
  card-hover-line: "#b3baaf"
  card-hover-bg: "#fdfcf9"
  category-blue: "#3e587d"
  category-sand: "#775e2a"
  category-sage: "#3f654d"
  avatar-blue-bg: "#e0e8f0"
  avatar-blue-ink: "#405b7d"
  avatar-sand-bg: "#eee6d8"
  avatar-sand-ink: "#71582d"
  avatar-sage-bg: "#e1eae1"
  avatar-sage-ink: "#41634b"
  secondary-line: "#cdd4da"
  secondary-text: "#3f5067"
  secondary-hover-bg: "#eef1f2"
  secondary-hover-line: "#8e9ca7"
  enrolled-bg: "#e8f3ec"
  enrolled-ink: "#2c6549"
  enrolled-line: "#b8d3c3"
  enrolled-hover-bg: "#dcece2"
  enrolled-hover-line: "#83a991"
  complete-bg: "#e0ede3"
  outline-line: "#b8c3cc"
  workshop-bg: "#ffffff"
  date-line: "#d9c99f"
  date-bg: "#f6efdf"
  dot: "#8090a4"
  workshop-action-line: "#d2bd95"
  workshop-action-bg: "#f6efdf"
  workshop-action-hover: "#efe2ca"
  announcement-ink: "#7c5d2b"
  dialog-line: "#bfc8d0"
  input-line: "#bfc9d1"
  input-bg: "#fafbf9"
  module-bg: "#e9edf1"
  module-done-bg: "#e2efe5"
  module-current-line: "#bea36c"
  module-current-bg: "#faf3e5"
  toast-bg: "#e7efe7"
  toast-ink: "#243d2c"
  toast-line: "#c2d3c4"
  toast-icon: "#38664f"
  toast-dismiss: "#3d5948"
  dialog-note-bg: "#f7f0e3"
  accent: "#805d23"
  focus: "#8b6528"
  highlight-bg: "#17243a"
  highlight-ink: "#f7f5ee"
  highlight-muted: "#c2cbd8"
  highlight-line: "#435168"
  highlight-track: "#64758e"
  highlight-accent: "#dfc28e"
  highlight-icon: "#303b4b"
  highlight-badge-bg: "#343a43"
  highlight-badge-line: "#776a50"
typography:
  display:
    fontFamily: "DM Sans, sans-serif"
    fontSize: "58px"
    fontWeight: 400
    lineHeight: 1.06
    letterSpacing: "-0.04em"
  headline:
    fontFamily: "DM Sans, sans-serif"
    fontSize: "31px"
    fontWeight: 400
    lineHeight: 1.15
    letterSpacing: "-0.035em"
  title:
    fontFamily: "DM Sans, sans-serif"
    fontSize: "21px"
    fontWeight: 500
    lineHeight: 1.26
    letterSpacing: "-0.027em"
  body:
    fontFamily: "DM Sans, sans-serif"
    fontSize: "14px"
    fontWeight: 400
    lineHeight: 1.65
  label:
    fontFamily: "DM Sans, sans-serif"
    fontSize: "12px"
    fontWeight: 500
rounded:
  badge: "5px"
  action: "7px"
  control: "8px"
  field: "9px"
  strip: "12px"
  panel: "14px"
  dialog: "16px"
spacing:
  inline: "8px"
  compact: "12px"
  standard: "16px"
  section: "24px"
  roomy: "28px"
components:
  button-primary:
    backgroundColor: "{colors.gold}"
    textColor: "{colors.gold-ink}"
    typography: "{typography.label}"
    rounded: "{rounded.control}"
    padding: "11px 16px"
  button-primary-hover:
    backgroundColor: "{colors.gold-hover}"
  button-outline:
    textColor: "{colors.ink}"
    rounded: "{rounded.control}"
    padding: "11px 16px"
  course-cta:
    backgroundColor: "{colors.gold}"
    textColor: "{colors.gold-ink}"
    rounded: "{rounded.action}"
    width: "100%"
  course-card:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.ink}"
    rounded: "{rounded.panel}"
    padding: "24px 23px 22px"
  search:
    backgroundColor: "{colors.field-bg}"
    textColor: "{colors.faint}"
    rounded: "{rounded.field}"
    padding: "0 16px"
  badge-success:
    backgroundColor: "{colors.badge-success-bg}"
    textColor: "{colors.success}"
    rounded: "{rounded.badge}"
    padding: "5px 8px"
  navigation:
    textColor: "{colors.muted}"
    rounded: "{rounded.control}"
    padding: "9px 14px"
---

# Design System: FinEx Learning

## Overview

**Creative North Star: "The Professional Learning Workspace"**

An integrated professional learning workspace uses warm off-white foundations, white panels, navy text and champagne filled actions. The white website masthead retains navy and gold branding. Concentrated navy contrast marks the CPD summary and selected Learning navigation tab; the CPD panel uses ivory text and gold accents. Bronze reading accents and sage learning states remain clear on paper. Fine separators and modest rounding retain a consistent density.

This scoped system belongs to the Learning route composed by LearningPage, the existing website Nav, LearningCenter and LearningResources. Identity comes from the real Seeker session and verified membership comes from the existing API. Guests and new Seekers begin with zero CPD hours, no enrolments and no reservations. Programme prices, faculty, ratings and CPD records remain illustrative; local enrolment takes no payment and lesson content is absent.

**Key Characteristics:**
- One self-hosted sans voice.
- Tonal panels with fine separators.
- Fixed paper palette, focused navy contrast and sage learning states.
- Responsive catalogue and native modal interactions.

## Colors

The single palette uses semantic --v2-* properties under .learning-site. Warm paper and white are the default surfaces; the navy CPD panel is a local component treatment.

### Primary
- **Champagne — gold / gold-hover / gold-ink:** filled actions use #dfc28e with #1b2027 text; hover uses #ecd2a4.
- **Reading accent — accent:** #805d23 for text actions, headline emphasis and category labels. Keep this distinct from the filled button color.
- **Navy highlight — highlight-bg / highlight-ink:** #17243a with #f7f5ee text for the CPD panel. Highlight-muted is #c2cbd8, highlight-line #435168, highlight-track #64758e and highlight-accent #dfc28e.

### Secondary
- **Sage — success / success-bg:** #2c6a4e / #edf6ef. Enrolled controls and badges have dedicated background, border and text tokens.

### Neutral
- **Page — bg / deep:** #faf9f6 / #f1efe9.
- **Panels — surface / raised:** #ffffff / #f2f1ec.
- **Text — ink / muted / faint:** #17243a / #4c5c6e / #5d6a7b.
- **Rules — line / subtle-line:** #dcdedc / #e6e6e0.
- **Focus — focus:** #8b6528 on paper; the CPD component locally uses highlight-accent.

LearningPage uses one fixed color-scheme: light palette without appearance controls or appearance persistence. Low-specificity :where(.learning-site) resets preserve component colors. Scoped aliases keep the shared white masthead’s navy and gold branding within Learning without changing the global system.

### Named Rules
**The Learning State Rule.** Pair sage progress and reservation colors with readable state text and progress values.

## Typography

**Display Font:** DM Sans, sans-serif.
**Body Font:** DM Sans, sans-serif.

The Learning center uses this sans voice; the shared website Nav retains its own incumbent typography. Sidecar component samples inherit --v2-* values from a .learning-site container.

Four local TTF files provide weights 400, 500, 600 and 700, with font-display: swap and font-synthesis: none. The files and OFL license live in public/learning-assets/fonts. No raster artwork is used; profile portraits are initials in colored circles and structural icons are SVGs.

### Hierarchy
- **Display:** 58px/400, 1.06 line height, -0.04em tracking. The responsive source uses 66px from 1600px, 50px through 1170px, 43px through 880px, 44px through 600px and 40px through 360px.
- **Headline:** section heads 31px/400, 1.15, -0.035em; 28px through 880px and 27px through 600px.
- **Title:** course titles 21px/500, 1.26, -0.027em; 20px through 1170px and 23px on mobile and wide desktops. Dialog titles within content use 29px, falling to 25px on mobile.
- **Body:** course descriptions 14px/400, 1.65; mobile 1.7. The scoped Learning body is 14px/1.5. Hero supporting copy is 16px/1.7, 18px on wide desktops and 14px on tablet/mobile, with a 55ch maximum.
- **Label:** most task metadata, navigation and controls are 12px, generally 400 or 500; course CTA weight is 600. Faculty biography copy uses 13px/1.7. This is an observed hierarchy rather than a fixed mathematical scale.
- **Data:** CPD total 30px/500 and course prices 25px/500 use tabular numerals. Mobile prices reach 28px.

## Layout

The centered container is calc(100% - 80px), max-width 1320px; it reaches 1380px from 1600px. Gutters reduce to 24px through 1170px, 18px through 600px and 14px through 360px. Spacing follows the component’s density, including 8/12/16/24/28px steps; the 17px catalogue gap is an actual exception, not a fabricated universal grid.

Catalogue columns are three by default, two through 880px and one through 600px. The default filter row is 1fr / 230px / 170px; tablet puts the search beside stacked filters, while mobile uses full-width search above two select columns. Course cards use flex columns so prices and actions align despite differing content.

The hero is a two-column 1.1fr / .9fr composition with 100px gap, then a single column through 600px. Learning navigation moves to its own row through 1200px; mobile uses compact button labels. The existing website Nav sits above the sticky Learning header, whose top offset is 65px and z-index is 30. Its inner height is 82px before responsive reflow. Content scroll clearance is 170px, rising to 210px through 1200px. Workshops and announcements collapse to one column through 880px.

## Elevation & Depth

Most depth comes from tonal surfaces and 1px separators. Course hover uses card-hover-line and card-hover-bg without lift: #b3baaf / #fdfcf9. Native dialogs use a dark translucent blurred backdrop; toasts have a smaller ambient shadow.

### Shadow Vocabulary
- **Dialog:** `0 30px 80px rgba(0, 0, 0, 0.4)`.
- **Toast:** `0 10px 30px rgba(0, 0, 0, 0.3)`.
- **Dialog backdrop:** `rgba(4, 8, 15, 0.8)` with `blur(5px)`.

### Named Rules
**The Tonal Surface Rule.** Separate the page, panels and raised regions with bg, surface and raised tones plus fine borders; reserve large shadows for overlays.

## Shapes

Course and CPD panels use 14px corners; faculty and learning rows use 13px, continuation strips 12px, dialogs 16px (13px on mobile). Buttons use 7–8px, search fields 9px, and badges 5px. Avatar initials are circular. Fine 1px borders provide structure; progress tracks have rounded ends and clipped fills.

## Components

### Buttons
Gold buttons are quiet, filled actions: 8px radius, 11px 16px padding, 12px/500, minimum height 44px; hover uses gold-hover. Course CTAs use 7px radius and 600 weight, with a 47px minimum on mobile. Outline buttons use outline-line (#b8c3cc) and raised hover background. Enrolled course CTAs use sage tones. Icon dialog close controls are 44px square. Focus is 2px solid focus, offset 4px.

### Chips
Gold and green badges are 12px/500 with 5px radius, 5px 8px padding and thin colored borders. They convey course and learning status. Course category labels are existing course taxonomy; their uppercase tracking is not a general license to add decorative kickers.

### Cards / Containers
Course cards use surface and line, 14px corners and 24px 23px 22px padding. Wide desktops use 28px; compact desktops use 20px 18px; mobile uses 23px and 20px through 360px. Course descriptions remain 14px. Prices, instructor identity, facts, availability and actions use separators instead of nested floating boxes.

### Inputs / Fields
Search uses field-bg (#ffffff), a field-line border (#cdd3d8), 9px radius and 48px minimum outer height (47px mobile). Focus-within shifts its border to gold; native input/select focus-visible retains the shared outline. Selects remain native. Enrolment fields use input-bg (#fafbf9) and input-line (#bfc9d1), 8px corners and 46px minimum height; mobile fields use 16px text.

### Navigation
Transparent 44px-high buttons carry muted 12px/500 text and 8px corners. Hover uses surface/ink; the selected Learning button uses navy nav-active and nav-border (#17243a) with nav-active-ink (#faf9f6). Mobile label changes preserve access to catalogue, learning, faculty and support views.

### CPD / Learning Progress
The CPD summary locally remaps surface, text, separator, focus, icon, badge and progress colors to the highlight tokens. Its navy #17243a panel uses ivory #f7f5ee primary text, muted #c2cbd8 metadata and gold #dfc28e accents. This component treatment stays within the fixed paper page palette.

Rounded tracks are 6px for the CPD summary, 3px for desktop course cards and 4px for mobile cards. Progress fills animate transform from the left over .24s ease-out. Progress text remains visible alongside the visual fill. Signed-in preview module completion updates the Seeker’s local workspace state and illustrative CPD total. Fresh visitors begin at zero.

### Dialogs / Feedback
PreviewDialog calls native showModal(), preserving browser focus trapping and background isolation; Escape, close and backdrop clicks dismiss it. Standard width is 520px, wide width 680px, with viewport-constrained height and internal scrolling. Native dialog placement is centered explicitly with margin: auto and inset: 0. Its header stays sticky and a visible illustrative-data notice precedes content. The page also provides a skip link. Buttons and links transition color/border/background over .18s ease; reduced-motion disables animations and transitions. Toast feedback confirms actions. Final cascade overrides give search clear, toast dismiss and utility back links 44px targets; navigation counts are 12px with a 20px line box.

### Identity / Sample Data Boundary
Catalogue and faculty content come from catalogue.ts; static brochures live under /learning-assets/brochures. A visible notice directly after the trust statistics identifies catalogue prices, ratings, trainers and dates as sample content for the local preview. useAuth supplies the actual Seeker identity. Real /register and /signin links are shown to guests. Member pricing and workshop access require membership verified by fetchMyLearning; a failed verification does not grant membership. No fictitious active member is seeded.

useLearningWorkspace starts empty, validates saved module counts and known IDs, and stores signed-in preview activity under finex-learning-workspace-v3:<seekerId>. Guests cannot mutate or persist a workspace. Switching Seekers selects the corresponding workspace; the former seeded demo key is never read. Failed storage keeps the visit usable with a persistence notice. Programme brochures, pricing, faculty and CPD totals remain illustrative; no payment or CPD accreditation is issued.

## Do's and Don'ts

### Do:
- **Do** preserve the .learning-site scope and use its semantic --v2-* custom properties.
- **Do** keep course descriptions at 14px and action controls at the implemented 44px minimum.
- **Do** retain visible sample-data labels in the page and dialogs.
- **Do** preserve native dialog behavior, visible keyboard focus and reduced-motion overrides.

### Don't:
- **Don't** present sample prices, faculty or CPD totals as verified commercial or accreditation records.
- **Don't** treat the local preview workspace as payment, accreditation or server-persisted enrolment.
- **Don't** promote a component-specific exception into a new global type or spacing rule.

Not canonized: superseded seed-member behavior and appearance switching are not rules for the integrated route; actual Seeker identity and the fixed paper palette govern it. Synthetic tonal ramps are omitted because the build defines no such tokens. This documentation pass reads source; browser verification belongs to the build review.
