"""Interaction guardrails for the moving landing-page highlights."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_hover_pauses_the_conveyor_but_returning_from_a_card_cannot():
    css = (ROOT / "webapp" / "frontend" / "src" / "index.css").read_text(encoding="utf-8")

    assert ".hl__viewport:focus-within .hl__track" not in css
    assert ".hl__viewport:active .hl__track" not in css
    assert ".hl__viewport:hover .hl__track" in css
    assert "animation-play-state: paused" in css


def test_both_highlight_rails_are_pointer_swipeable():
    component = (
        ROOT
        / "webapp"
        / "frontend"
        / "src"
        / "components"
        / "highlights"
        / "WeeklyHighlights.tsx"
    ).read_text(encoding="utf-8")
    css = (ROOT / "webapp" / "frontend" / "src" / "index.css").read_text(encoding="utf-8")

    assert "useSwipeableMarquee(viewportRef, trackRef)" in component
    assert "useSwipeableMarquee(coachViewportRef, coachTrackRef)" in component
    assert "touch-action: pan-y" in css


def test_weekly_band_is_the_first_landing_content_after_navigation():
    page = (ROOT / "webapp" / "frontend" / "src" / "pages" / "LandingPage.tsx").read_text(
        encoding="utf-8"
    )

    assert page.index("<WeeklyHighlights />") < page.index("<PortalHero />")


def test_weekly_header_is_a_single_clean_client_message():
    component = (
        ROOT
        / "webapp"
        / "frontend"
        / "src"
        / "components"
        / "highlights"
        / "WeeklyHighlights.tsx"
    ).read_text(encoding="utf-8")

    assert '<h2 id="hl-heading" className="hl__title">This week at FinEx.</h2>' in component
    assert "Welcome to<br />FinEx Careers." not in component
    assert "Just landed · {items.length} picks" in component
    assert "Fresh roles, sharp insight" not in component
    assert "Explore all roles" not in component


def test_weekly_drop_keeps_card_elevation_without_side_fades():
    css = (ROOT / "webapp" / "frontend" / "src" / "index.css").read_text(encoding="utf-8")
    v2 = css[css.index("/* V2 concept — Weekly Drop.") :]

    assert ".hl-card {" in v2
    assert "box-shadow: 4px 4px 0 var(--hl-ink)" in v2
    assert "box-shadow: 6px 7px 0 var(--hl-ink)" in v2
    assert ".hl-card__coach-photo" in v2
    assert "box-shadow: 3px 3px 0 var(--hl-ink)" in v2[v2.index(".hl-card__coach-photo") :]

    viewport = v2[v2.index(".hl__viewport {") : v2.index(".hl-card {")]
    assert "-webkit-mask-image: none" in viewport
    assert "mask-image: none" in viewport


def test_reduced_motion_still_disables_the_animation():
    css = (ROOT / "webapp" / "frontend" / "src" / "index.css").read_text(encoding="utf-8")

    reduced_motion = css[css.index("@media (prefers-reduced-motion: reduce)") :]
    assert ".hl__track" in reduced_motion
    assert "animation: none" in reduced_motion


def test_coach_portraits_crop_out_the_embedded_profile_text():
    component = (
        ROOT
        / "webapp"
        / "frontend"
        / "src"
        / "components"
        / "highlights"
        / "WeeklyHighlights.tsx"
    ).read_text(encoding="utf-8")
    css = (ROOT / "webapp" / "frontend" / "src" / "index.css").read_text(encoding="utf-8")

    assert 'className="hl-coach-card__photo-frame"' in component
    frame = css[css.index(".hl-coach-card__photo-frame {") :]
    photo = css[css.index(".hl-coach-card__photo {") :]
    assert "overflow: hidden" in frame.split("}", 1)[0]
    assert "transform: scale(" in photo.split("}", 1)[0]
    assert "transform-origin:" in photo.split("}", 1)[0]
