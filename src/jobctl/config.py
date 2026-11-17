"""Typed configuration loader with TOML parsing, environment overrides, and level presets."""

from __future__ import annotations

from dataclasses import dataclass, field
import os
from pathlib import Path
import tomllib


SENIOR_TITLE_TOKENS: frozenset[str] = frozenset(
    {
        "senior",
        "sr",
        "staff",
        "principal",
        "lead",
        "manager",
        "director",
        "head",
        "vp",
        "chief",
        "architect",
    }
)


@dataclass(frozen=True, slots=True)
class LevelPreset:
    """Experience ceiling, LinkedIn experience codes, and excluded title tokens per level."""

    name: str
    label: str
    min_years: int
    max_years: int
    linkedin_f_e: str
    excluded_title_tokens: frozenset[str]


LEVEL_PRESETS: dict[str, LevelPreset] = {
    "intern": LevelPreset(
        name="intern",
        label="Intern (0 yrs)",
        min_years=0,
        max_years=0,
        linkedin_f_e="1",
        excluded_title_tokens=SENIOR_TITLE_TOKENS | {"junior", "mid", "ii", "iii"},
    ),
    "entry": LevelPreset(
        name="entry",
        label="Entry-Level (0-1 yr)",
        min_years=0,
        max_years=1,
        linkedin_f_e="1,2",
        excluded_title_tokens=SENIOR_TITLE_TOKENS | {"ii", "iii"},
    ),
    "junior": LevelPreset(
        name="junior",
        label="Junior (0-2 yrs)",
        min_years=0,
        max_years=2,
        linkedin_f_e="1,2",
        excluded_title_tokens=SENIOR_TITLE_TOKENS | {"iii"},
    ),
    "mid": LevelPreset(
        name="mid",
        label="Mid-Level (2-5 yrs)",
        min_years=2,
        max_years=5,
        linkedin_f_e="2,3,4",
        excluded_title_tokens=SENIOR_TITLE_TOKENS | {"intern", "internship"},
    ),
    "senior": LevelPreset(
        name="senior",
        label="Senior (5-10 yrs)",
        min_years=5,
        max_years=10,
        linkedin_f_e="4",
        excluded_title_tokens=frozenset({"principal", "director", "vp", "head", "chief", "intern", "internship"}),
    ),
}


DEFAULT_MID_SKILLS: list[str] = [
    "typescript",
    "javascript",
    "node.js",
    "nestjs",
    "express",
    "react",
    "next.js",
    "postgresql",
    "sql",
    "redis",
    "docker",
    "kubernetes",
    "ci/cd",
    "github actions",
    "aws",
    "linux",
    "terraform",
    "nginx",
    "microservices",
    "rest api",
    "erp",
]

DEFAULT_MID_TARGET_TITLES: list[str] = [
    "Software Engineer",
    "Software Engineer II",
    "Software Development Engineer",
    "Software Development Engineer II",
    "SDE II",
    "Backend Engineer",
    "Backend Developer",
    "Full Stack Engineer",
    "Full-Stack Engineer",
    "Full Stack Developer",
    "Full-Stack Developer",
    "Platform Engineer",
    "DevOps Engineer",
    "Site Reliability Engineer",
    "Cloud Engineer",
    "Infrastructure Engineer",
    "Database Engineer",
    "PostgreSQL Engineer",
    "Node.js Engineer",
    "TypeScript Engineer",
    "ERP Developer",
    "ERP Software Engineer",
    "Systems Engineer",
]

KNOWN_SOURCES: frozenset[str] = frozenset(
    {"linkedin", "wellfound", "ashby", "greenhouse", "lever", "adzuna"}
)


@dataclass(slots=True)
class ProfileConfig:
    role_title: str = "Software Engineer"
    level: str = "mid"
    work_modes: list[str] = field(default_factory=lambda: ["remote"])
    job_types: list[str] = field(default_factory=lambda: ["full-time", "contract"])
    location: str = "Worldwide"
    skills: list[str] = field(default_factory=lambda: list(DEFAULT_MID_SKILLS))
    target_titles: list[str] = field(default_factory=lambda: list(DEFAULT_MID_TARGET_TITLES))

    @property
    def preset(self) -> LevelPreset:
        return LEVEL_PRESETS[self.level]


@dataclass(slots=True)
class FilterConfig:
    # Strictly search only jobs from the previous 2 days by default
    max_posting_age_days: int = 2
    require_posted_date: bool = True
    max_years_override: int | None = None
    extra_excluded_phrases: list[str] = field(default_factory=list)

    def effective_max_years(self, profile: ProfileConfig) -> int:
        if self.max_years_override is not None:
            return self.max_years_override
        return profile.preset.max_years


@dataclass(slots=True)
class ScoreWeights:
    skills: float = 0.55
    title: float = 0.35
    job_type: float = 0.10


@dataclass(slots=True)
class ScoringConfig:
    min_score: int = 60
    min_skills_pct: int = 50
    min_title_pct: int = 50
    skill_match_target: int = 5
    weights: ScoreWeights = field(default_factory=ScoreWeights)


@dataclass(slots=True)
class SourceOptions:
    enabled: bool = True
    limit: int = 40
    companies: list[str] | None = None
    country_code: str = "us"
    app_id: str = ""
    app_key: str = ""


@dataclass(slots=True)
class OutputConfig:
    results_dir: str = "search_results"
    formats: list[str] = field(default_factory=lambda: ["docx", "csv", "json", "md"])
    only_new: bool = True
    history_db: str = "data/jobctl.db"


@dataclass(slots=True)
class AppConfig:
    profile: ProfileConfig = field(default_factory=ProfileConfig)
    filters: FilterConfig = field(default_factory=FilterConfig)
    scoring: ScoringConfig = field(default_factory=ScoringConfig)
    sources: dict[str, SourceOptions] = field(default_factory=dict)
    output: OutputConfig = field(default_factory=OutputConfig)

    def __post_init__(self) -> None:
        if not self.sources:
            self.sources = default_sources()
        self.validate()

    def validate(self) -> None:
        level_key = self.profile.level.strip().lower()
        if level_key not in LEVEL_PRESETS:
            valid = ", ".join(LEVEL_PRESETS)
            raise ValueError(f"Unknown profile.level '{self.profile.level}'. Valid options: {valid}")
        self.profile.level = level_key

        w = self.scoring.weights
        total_weight = round(w.skills + w.title + w.job_type, 4)
        if abs(total_weight - 1.0) > 0.01:
            raise ValueError(
                f"scoring.weights must sum to 1.0 (got {total_weight}: "
                f"skills={w.skills}, title={w.title}, job_type={w.job_type})"
            )

        unknown = set(self.sources) - KNOWN_SOURCES
        if unknown:
            raise ValueError(
                f"Unknown source(s) in configuration: {', '.join(sorted(unknown))}. "
                f"Known sources: {', '.join(sorted(KNOWN_SOURCES))}"
            )


def default_sources() -> dict[str, SourceOptions]:
    return {
        "linkedin": SourceOptions(enabled=True, limit=40),
        "wellfound": SourceOptions(enabled=True, limit=30),
        "ashby": SourceOptions(enabled=True, limit=40),
        "greenhouse": SourceOptions(enabled=True, limit=60),
        "lever": SourceOptions(enabled=True, limit=40),
        "adzuna": SourceOptions(
            enabled=False,
            limit=30,
            country_code=os.environ.get("ADZUNA_COUNTRY_CODE", "us"),
            app_id=os.environ.get("ADZUNA_APP_ID", ""),
            app_key=os.environ.get("ADZUNA_APP_KEY", ""),
        ),
    }


def load_config(path: str | Path | None = None) -> AppConfig:
    """
    Load jobctl configuration from a TOML file.
    Resolution order when path is None:
      1. ./jobctl.toml (if present)
      2. ./jobctl.example.toml (if present)
      3. Built-in mid-level defaults
    """
    resolved_path: Path | None = None
    if path is not None:
        resolved_path = Path(path)
        if not resolved_path.exists():
            raise FileNotFoundError(f"Configuration file not found: {resolved_path}")
    else:
        for candidate in (Path("jobctl.toml"), Path("jobctl.example.toml")):
            if candidate.exists():
                resolved_path = candidate
                break

    if resolved_path is None:
        return AppConfig()

    with resolved_path.open("rb") as fh:
        raw = tomllib.load(fh)

    prof_raw = raw.get("profile", {})
    profile = ProfileConfig(
        role_title=prof_raw.get("role_title", "Software Engineer"),
        level=str(prof_raw.get("level", "mid")).lower(),
        work_modes=[m.lower() for m in prof_raw.get("work_modes", ["remote"])],
        job_types=[t.lower() for t in prof_raw.get("job_types", ["full-time", "contract"])],
        location=prof_raw.get("location", "Worldwide"),
        skills=list(prof_raw.get("skills", DEFAULT_MID_SKILLS)),
        target_titles=list(prof_raw.get("target_titles", DEFAULT_MID_TARGET_TITLES)),
    )

    filt_raw = raw.get("filters", {})
    filters = FilterConfig(
        max_posting_age_days=int(filt_raw.get("max_posting_age_days", 2)),
        require_posted_date=bool(filt_raw.get("require_posted_date", True)),
        max_years_override=filt_raw.get("max_years_override"),
        extra_excluded_phrases=[p.lower() for p in filt_raw.get("extra_excluded_phrases", [])],
    )

    score_raw = raw.get("scoring", {})
    weights_raw = score_raw.get("weights", {})
    weights = ScoreWeights(
        skills=float(weights_raw.get("skills", 0.55)),
        title=float(weights_raw.get("title", 0.35)),
        job_type=float(weights_raw.get("job_type", 0.10)),
    )
    scoring = ScoringConfig(
        min_score=int(score_raw.get("min_score", 60)),
        min_skills_pct=int(score_raw.get("min_skills_pct", 50)),
        min_title_pct=int(score_raw.get("min_title_pct", 50)),
        skill_match_target=int(score_raw.get("skill_match_target", 5)),
        weights=weights,
    )

    sources = default_sources()
    sources_raw = raw.get("sources", {})
    for name, src_cfg in sources_raw.items():
        key = name.strip().lower()
        if key not in KNOWN_SOURCES:
            sources[key] = SourceOptions()  # triggers validation error
            continue
        base_opt = sources[key]
        sources[key] = SourceOptions(
            enabled=bool(src_cfg.get("enabled", base_opt.enabled)),
            limit=int(src_cfg.get("limit", base_opt.limit)),
            companies=src_cfg.get("companies", base_opt.companies),
            country_code=str(
                src_cfg.get("country_code", os.environ.get("ADZUNA_COUNTRY_CODE", base_opt.country_code))
            ),
            app_id=str(os.environ.get("ADZUNA_APP_ID") or src_cfg.get("app_id", base_opt.app_id)),
            app_key=str(os.environ.get("ADZUNA_APP_KEY") or src_cfg.get("app_key", base_opt.app_key)),
        )

    out_raw = raw.get("output", {})
    output = OutputConfig(
        results_dir=str(out_raw.get("results_dir", "search_results")),
        formats=[f.lower() for f in out_raw.get("formats", ["docx", "csv", "json", "md"])],
        only_new=bool(out_raw.get("only_new", True)),
        history_db=str(out_raw.get("history_db", "data/jobctl.db")),
    )

    return AppConfig(
        profile=profile,
        filters=filters,
        scoring=scoring,
        sources=sources,
        output=output,
    )
