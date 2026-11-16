"""Typed domain models for job listings, score breakdowns, and source health."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from hashlib import sha1
import re
from urllib.parse import urlsplit, urlunsplit


def normalize_url(url: str) -> str:
    """Normalize a job posting URL for deterministic deduplication."""
    if not url or not url.strip():
        return ""
    raw = url.strip()
    try:
        parts = urlsplit(raw)
        clean_path = parts.path.rstrip("/")
        return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), clean_path, "", ""))
    except Exception:
        return raw.lower().rstrip("/")


def _slug(text: str) -> str:
    cleaned = re.sub(r"[-_/]", " ", (text or "").lower())
    return re.sub(r"\s+", " ", cleaned).strip()


@dataclass(slots=True)
class Job:
    """Normalized job listing produced by any source adapter."""

    title: str
    company: str
    location: str
    job_type: str  # "full-time" | "contract" | "part-time" | "internship" | "unknown"
    work_mode: str  # "remote" | "hybrid" | "on-site" | "unknown"
    description: str
    url: str
    source: str
    posted_date: str = ""

    @property
    def dedup_key(self) -> str:
        """Stable SHA-1 key preferring normalized URL, falling back to title + company."""
        norm_url = normalize_url(self.url)
        if norm_url and norm_url not in ("https://wellfound.com/jobs",):
            basis = f"url:{norm_url}"
        else:
            basis = f"tc:{_slug(self.title)}|{_slug(self.company)}"
        return sha1(basis.encode("utf-8")).hexdigest()

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(slots=True)
class ScoreBreakdown:
    """Component percentages (0–100) for a scored job listing."""

    skills_pct: int
    title_pct: int
    job_type_pct: int

    def to_dict(self) -> dict[str, int]:
        return {
            "skills_pct": self.skills_pct,
            "title_pct": self.title_pct,
            "job_type_pct": self.job_type_pct,
        }


@dataclass(slots=True)
class ScoredJob:
    """A job listing enriched with match score, matched skills, and history metadata."""

    job: Job
    match_score: int
    match_summary: str
    matched_skills: list[str] = field(default_factory=list)
    score_breakdown: ScoreBreakdown = field(
        default_factory=lambda: ScoreBreakdown(skills_pct=0, title_pct=0, job_type_pct=0)
    )
    is_new: bool = True
    times_seen: int = 1

    @property
    def title(self) -> str:
        return self.job.title

    @property
    def company(self) -> str:
        return self.job.company

    @property
    def location(self) -> str:
        return self.job.location

    @property
    def job_type(self) -> str:
        return self.job.job_type

    @property
    def work_mode(self) -> str:
        return self.job.work_mode

    @property
    def description(self) -> str:
        return self.job.description

    @property
    def url(self) -> str:
        return self.job.url

    @property
    def source(self) -> str:
        return self.job.source

    @property
    def posted_date(self) -> str:
        return self.job.posted_date

    @property
    def dedup_key(self) -> str:
        return self.job.dedup_key

    def to_dict(self) -> dict:
        data = self.job.to_dict()
        data.update(
            {
                "match_score": self.match_score,
                "match_summary": self.match_summary,
                "matched_skills": list(self.matched_skills),
                "score_breakdown": self.score_breakdown.to_dict(),
                "is_new": self.is_new,
                "times_seen": self.times_seen,
            }
        )
        return data


@dataclass(slots=True)
class SourceStat:
    """Execution telemetry for a single job source."""

    name: str
    retrieved: int
    duration_ms: int
    error: str = ""
