"""Explainable, first-party Role recommendations for FinEx Seekers.

This deliberately is not an embedding model and it does not send Seeker data
anywhere. The board already has unusually good structured facts (sector,
seniority, skills, workplace type, company and role title); saved Roles and
settled discovery events turn those facts into a compact preference profile.

The module is pure ranking logic. It does not know about HTTP, sessions or
SQLite, which keeps the weights testable and makes a later model version a
contained replacement instead of a route rewrite.
"""

from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Iterable, Sequence

from job_read import JobSummary

MODEL_VERSION = "signals-v1"

_WORD_RE = re.compile(r"[a-z0-9+#.]{2,}")
_ENTITY_NOISE = re.compile(
    r"\b(limited|ltd|inc|plc|co|company|hong\s*kong|hk|s\.?a\.?r\.?|branch)\b"
)
_FILTER_WEIGHTS = {
    "sectors": ("sector", 4.5),
    "companies": ("company", 3.5),
    "seniority": ("seniority", 2.5),
    "remote_type": ("remote_type", 2.0),
    "skills": ("skill", 3.5),
}


@dataclass(frozen=True)
class _Signal:
    kind: str
    value: str
    label: str
    weight: float
    reason: str


@dataclass(frozen=True)
class RankedRole:
    job: JobSummary
    score: float
    reasons: tuple[str, ...]


@dataclass(frozen=True)
class RecommendationResult:
    items: tuple[RankedRole, ...]
    personalized: bool
    signal_count: int
    eligible_count: int


def _normalise(value: object) -> str:
    return " ".join(str(value or "").strip().lower().split())


def _employer_key(company: str) -> str:
    value = re.sub(r"[(),.]", " ", company.lower())
    return " ".join(_ENTITY_NOISE.sub(" ", value).split())


def _event_recency(created_at: object, now: datetime) -> float:
    try:
        moment = datetime.fromisoformat(str(created_at))
        if moment.tzinfo is None:
            moment = moment.replace(tzinfo=timezone.utc)
        age_days = max(0.0, (now - moment.astimezone(timezone.utc)).total_seconds() / 86_400)
    except (TypeError, ValueError):
        age_days = 90.0
    # Half-life of roughly one month, with an old event retaining a small voice.
    return max(0.15, math.exp(-age_days / 45.0))


def _add_saved_signals(signals: list[_Signal], role: JobSummary) -> None:
    direct = (
        ("sector", role.sector, 5.0, f"Matches {role.sector} Roles you saved"),
        ("company", role.company, 1.5, f"More from {role.company}"),
        ("seniority", role.seniority, 3.0, "Matches the level of a saved Role"),
        ("remote_type", role.remote_type, 2.0, "Matches your saved workplace preference"),
        ("job_category", role.job_category, 3.5, "Similar work to a saved Role"),
    )
    for kind, value, weight, reason in direct:
        if value:
            signals.append(_Signal(kind, _normalise(value), str(value), weight, reason))

    for skill in role.required_skills[:12]:
        value = _normalise(skill)
        if value:
            signals.append(
                _Signal(
                    "text",
                    value,
                    str(skill),
                    2.5,
                    f"Uses {skill}, found in a saved Role",
                )
            )

    for token in _WORD_RE.findall(_normalise(role.title)):
        signals.append(
            _Signal("text", token, token, 0.9, "Similar title to a saved Role")
        )


def _event_filters(event: dict) -> dict:
    raw = event.get("filters_json", "{}")
    try:
        parsed = json.loads(raw) if isinstance(raw, str) else raw
    except (TypeError, ValueError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _add_event_signals(
    signals: list[_Signal], event: dict, *, now: datetime
) -> None:
    recency = _event_recency(event.get("created_at"), now)
    query = _normalise(event.get("search_query"))
    if query:
        signals.append(
            _Signal(
                "text",
                query,
                query,
                5.0 * recency,
                f"Matches your “{query}” searches",
            )
        )
        if " " in query:
            for token in _WORD_RE.findall(query):
                signals.append(
                    _Signal(
                        "text",
                        token,
                        token,
                        1.2 * recency,
                        f"Related to your “{query}” searches",
                    )
                )

    filters = _event_filters(event)
    for field, (kind, base_weight) in _FILTER_WEIGHTS.items():
        values = filters.get(field) or []
        if not isinstance(values, list):
            continue
        for label in values[:20]:
            value = _normalise(label)
            if not value:
                continue
            signals.append(
                _Signal(
                    kind,
                    value,
                    str(label),
                    base_weight * recency,
                    f"Matches your {label} filters",
                )
            )

    if filters.get("is_internship") is True:
        signals.append(
            _Signal(
                "internship",
                "true",
                "internship",
                4.0 * recency,
                "Matches your internship searches",
            )
        )

    tier = _normalise(filters.get("tier"))
    if tier and tier != "all":
        signals.append(
            _Signal(
                "source_tier",
                tier,
                tier,
                3.5 * recency,
                f"Matches your {tier.title()} Role filters",
            )
        )

    numeric_filters = (
        ("salary_min", "salary_min", 3.5, "Fits your salary filters"),
        ("salary_max", "salary_max", 3.0, "Fits your salary filters"),
        ("exp_min", "exp_min", 2.5, "Fits your experience filters"),
        ("exp_max", "exp_max", 2.5, "Fits your experience filters"),
        (
            "max_applicants",
            "max_applicants",
            2.5,
            "Matches your lower-competition filters",
        ),
    )
    for field, kind, weight, reason in numeric_filters:
        value = filters.get(field)
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            signals.append(
                _Signal(kind, str(value), str(value), weight * recency, reason)
            )

    boolean_filters = (
        (
            "salary_disclosed_only",
            "salary_disclosed",
            2.0,
            "Shows the salary information you prefer",
        ),
        ("is_new", "new", 2.0, "Matches your new-Role filters"),
        ("urgently_hiring", "urgent", 2.5, "Matches your urgently-hiring filters"),
        ("hidden_only", "hidden", 2.5, "Matches your hidden-Role filters"),
        ("verified_only", "verified", 2.5, "Matches your verified-Role filters"),
    )
    for field, kind, weight, reason in boolean_filters:
        if filters.get(field) is True:
            signals.append(
                _Signal(kind, "true", field, weight * recency, reason)
            )

    # False is an intentional filter value here ("exclude internships"), not
    # the absence of preference, so it deserves its own signal as well.
    if filters.get("is_internship") is False:
        signals.append(
            _Signal(
                "internship",
                "false",
                "non-internship",
                2.0 * recency,
                "Matches your non-internship filters",
            )
        )


def _profile(
    saved_roles: Sequence[JobSummary],
    discovery_events: Sequence[dict],
    *,
    now: datetime,
) -> list[_Signal]:
    raw: list[_Signal] = []
    for role in saved_roles[:50]:
        _add_saved_signals(raw, role)
    for event in discovery_events[:100]:
        _add_event_signals(raw, event, now=now)

    # Repeated intent should strengthen a feature without letting one habit
    # swamp every other signal forever. Aggregate equal reason/value pairs and
    # cap each contribution at 15 points.
    aggregated: dict[tuple[str, str, str], _Signal] = {}
    for signal in raw:
        key = (signal.kind, signal.value, signal.reason)
        previous = aggregated.get(key)
        weight = min(15.0, signal.weight + (previous.weight if previous else 0.0))
        aggregated[key] = _Signal(
            signal.kind, signal.value, signal.label, weight, signal.reason
        )
    return list(aggregated.values())


def _posted_timestamp(value: str | None) -> float:
    if not value:
        return 0.0
    try:
        moment = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if moment.tzinfo is None:
            moment = moment.replace(tzinfo=timezone.utc)
        return moment.timestamp()
    except ValueError:
        return 0.0


def _freshness(role: JobSummary, now: datetime) -> float:
    stamp = _posted_timestamp(role.posted_at)
    if not stamp:
        return 0.0
    age = max(0.0, (now.timestamp() - stamp) / 86_400)
    if age <= 7:
        return 1.5
    if age <= 30:
        return 0.75
    return 0.0


def _salary_floor(role: JobSummary) -> int | None:
    return role.salary_hkd_min or role.salary_estimated_min


def _salary_ceiling(role: JobSummary) -> int | None:
    return role.salary_hkd_max or role.salary_estimated_max


def _signal_dicts(role: JobSummary) -> Iterable[dict]:
    for value in role.board_signals.values():
        if isinstance(value, dict):
            yield value


def _applicant_counts(role: JobSummary) -> list[int]:
    counts: list[int] = []
    for signals in _signal_dicts(role):
        value = signals.get("applicant_count")
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            counts.append(int(value))
    return counts


def _has_market_flag(role: JobSummary, name: str) -> bool:
    return any(signals.get(name) is True for signals in _signal_dicts(role))


def _matches(
    signal: _Signal,
    role: JobSummary,
    haystack: str,
    *,
    now: datetime,
) -> bool:
    if signal.kind == "text":
        return signal.value in haystack
    if signal.kind == "sector":
        return signal.value == _normalise(role.sector)
    if signal.kind == "company":
        return _employer_key(signal.value) == _employer_key(role.company)
    if signal.kind == "seniority":
        return signal.value == _normalise(role.seniority)
    if signal.kind == "remote_type":
        return signal.value == _normalise(role.remote_type)
    if signal.kind == "job_category":
        return signal.value == _normalise(role.job_category)
    if signal.kind == "skill":
        return signal.value in {_normalise(skill) for skill in role.required_skills}
    if signal.kind == "internship":
        return role.is_internship is (signal.value == "true")
    if signal.kind == "source_tier":
        return signal.value == _normalise(role.source_tier)
    if signal.kind == "salary_min":
        return _salary_floor(role) is not None and _salary_floor(role) >= float(signal.value)
    if signal.kind == "salary_max":
        return _salary_ceiling(role) is not None and _salary_ceiling(role) <= float(signal.value)
    if signal.kind == "salary_disclosed":
        return role.salary_hkd_min is not None or role.salary_hkd_max is not None
    if signal.kind == "exp_min":
        return (
            role.years_experience_required is not None
            and role.years_experience_required >= float(signal.value)
        )
    if signal.kind == "exp_max":
        return (
            role.years_experience_required is not None
            and role.years_experience_required <= float(signal.value)
        )
    if signal.kind == "new":
        return _has_market_flag(role, "new_job") or _freshness(role, now) > 0
    if signal.kind == "urgent":
        return _has_market_flag(role, "urgently_hiring")
    if signal.kind == "max_applicants":
        counts = _applicant_counts(role)
        return bool(counts) and max(counts) < float(signal.value)
    if signal.kind == "verified":
        return _has_market_flag(role, "not_a_ghost_job")
    if signal.kind == "hidden":
        return role.source_tier == "social" and not _has_market_flag(
            role, "not_a_ghost_job"
        )
    return False


def _score(role: JobSummary, signals: Sequence[_Signal], now: datetime) -> RankedRole:
    haystack = " ".join(
        filter(
            None,
            [
                _normalise(role.title),
                _normalise(role.title_en),
                _normalise(role.company),
                _normalise(role.sector),
                _normalise(role.job_category),
                *(_normalise(skill) for skill in role.required_skills),
            ],
        )
    )
    reasons: dict[str, float] = {}
    score = _freshness(role, now)
    for signal in signals:
        if _matches(signal, role, haystack, now=now):
            score += signal.weight
            reasons[signal.reason] = reasons.get(signal.reason, 0.0) + signal.weight

    ordered_reasons = tuple(
        reason for reason, _ in sorted(reasons.items(), key=lambda item: (-item[1], item[0]))[:2]
    )
    if not ordered_reasons:
        ordered_reasons = ("Recently listed",)
    return RankedRole(role, round(score, 3), ordered_reasons)


def _page_with_employer_diversity(
    ranked: Sequence[RankedRole], *, page: int, page_size: int
) -> tuple[RankedRole, ...]:
    """Build pages that prefer one Role per employer, without losing rank."""
    remaining = list(ranked)
    selected_page: list[RankedRole] = []
    for _ in range(page):
        selected_page = []
        seen: set[str] = set()
        for item in remaining:
            key = _employer_key(item.job.company)
            if key in seen:
                continue
            seen.add(key)
            selected_page.append(item)
            if len(selected_page) == page_size:
                break
        if len(selected_page) < page_size:
            chosen = {(item.job.source, item.job.source_id) for item in selected_page}
            selected_page.extend(
                item
                for item in remaining
                if (item.job.source, item.job.source_id) not in chosen
            )
            selected_page = selected_page[:page_size]
        selected_keys = {(item.job.source, item.job.source_id) for item in selected_page}
        remaining = [
            item
            for item in remaining
            if (item.job.source, item.job.source_id) not in selected_keys
        ]
    return tuple(selected_page)


def rank_roles(
    candidates: Iterable[JobSummary],
    *,
    saved_roles: Sequence[JobSummary],
    discovery_events: Sequence[dict],
    saved_refs: set[tuple[str, str]],
    page: int,
    page_size: int,
    now: datetime | None = None,
) -> RecommendationResult:
    """Rank open candidate Roles and return one diverse recommendation page."""
    moment = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    signals = _profile(saved_roles, discovery_events, now=moment)
    eligible = [
        role
        for role in candidates
        if not role.closed and (role.source, role.source_id) not in saved_refs
    ]
    ranked = [_score(role, signals, moment) for role in eligible]
    ranked.sort(
        key=lambda item: (
            -item.score,
            -_posted_timestamp(item.job.posted_at),
            item.job.company.casefold(),
            item.job.source,
            item.job.source_id,
        )
    )
    safe_page = max(1, int(page))
    safe_size = max(1, min(int(page_size), 24))
    return RecommendationResult(
        items=_page_with_employer_diversity(ranked, page=safe_page, page_size=safe_size),
        personalized=bool(signals),
        signal_count=len(signals),
        eligible_count=len(ranked),
    )
