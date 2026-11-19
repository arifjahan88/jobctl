"""Weighted job scoring (0–100), deduplication, and full filter+score pipeline."""

from __future__ import annotations

from datetime import datetime

from jobctl.config import FilterConfig, ProfileConfig, ScoringConfig
from jobctl.matching.filters import passes_hard_filters
from jobctl.matching.text import match_skills, title_match_ratio
from jobctl.models import Job, ScoreBreakdown, ScoredJob


def score_job(job: Job, profile: ProfileConfig, scoring: ScoringConfig) -> ScoredJob:
    """Compute a 0–100 match score for a single job listing."""
    combined_raw = f"{job.title}\n{job.description}"

    matched_skills = match_skills(profile.skills, combined_raw)
    target_count = scoring.skill_match_target or min(5, len(profile.skills)) or 1
    skill_ratio = min(len(matched_skills) / target_count, 1.0)

    target_titles = profile.target_titles or [profile.role_title]
    t_ratio = title_match_ratio(job.title, target_titles)

    jt_ratio = 1.0 if job.job_type.lower() in profile.job_types else 0.0

    w = scoring.weights
    final_score = round(
        100.0 * (w.skills * skill_ratio + w.title * t_ratio + w.job_type * jt_ratio)
    )

    if matched_skills:
        summary = (
            f"Matches {len(matched_skills)}/{len(profile.skills)} target skills: "
            f"{', '.join(matched_skills)}."
        )
    else:
        summary = "No direct skill keyword overlap found in description."

    breakdown = ScoreBreakdown(
        skills_pct=round(skill_ratio * 100),
        title_pct=round(t_ratio * 100),
        job_type_pct=round(jt_ratio * 100),
    )

    return ScoredJob(
        job=job,
        match_score=final_score,
        match_summary=summary,
        matched_skills=matched_skills,
        score_breakdown=breakdown,
    )


def deduplicate_jobs(jobs: list[Job]) -> list[Job]:
    """
    Remove duplicate listings across sources.
    Checks both the URL-based dedup_key and normalized (title, company) pair.
    """
    seen_keys: set[str] = set()
    seen_pairs: set[tuple[str, str]] = set()
    unique: list[Job] = []

    for job in jobs:
        key = job.dedup_key
        tc_pair = (job.title.strip().lower(), job.company.strip().lower())
        if key in seen_keys or tc_pair in seen_pairs:
            continue
        seen_keys.add(key)
        seen_pairs.add(tc_pair)
        unique.append(job)

    return unique


def filter_and_score_jobs(
    jobs: list[Job],
    profile: ProfileConfig,
    filters: FilterConfig,
    scoring: ScoringConfig,
    rejection_log: dict[str, int] | None = None,
    near_misses: list[ScoredJob] | None = None,
    now: datetime | None = None,
) -> list[ScoredJob]:
    """Run hard filters and weighted scoring over a list of deduplicated jobs."""
    results: list[ScoredJob] = []

    for job in jobs:
        passed, reason = passes_hard_filters(job, profile, filters, now=now)
        if not passed:
            if rejection_log is not None:
                category = reason.split("(")[0].split("'")[0].strip() or reason
                rejection_log[category] = rejection_log.get(category, 0) + 1
            continue

        scored = score_job(job, profile, scoring)
        skills_pct = scored.score_breakdown.skills_pct
        title_pct = scored.score_breakdown.title_pct

        if scoring.min_skills_pct and skills_pct < scoring.min_skills_pct:
            if rejection_log is not None:
                cat = f"skills match below threshold (<{scoring.min_skills_pct}%)"
                rejection_log[cat] = rejection_log.get(cat, 0) + 1
            if near_misses is not None:
                near_misses.append(scored)
            continue

        if scoring.min_title_pct and title_pct < scoring.min_title_pct:
            if rejection_log is not None:
                cat = f"title relevance below threshold (<{scoring.min_title_pct}%)"
                rejection_log[cat] = rejection_log.get(cat, 0) + 1
            if near_misses is not None:
                near_misses.append(scored)
            continue

        if scored.match_score >= scoring.min_score:
            results.append(scored)
        else:
            if rejection_log is not None:
                cat = f"below min_score (<{scoring.min_score})"
                rejection_log[cat] = rejection_log.get(cat, 0) + 1
            if near_misses is not None:
                near_misses.append(scored)

    results.sort(key=lambda item: (item.match_score, item.posted_date), reverse=True)
    return results
