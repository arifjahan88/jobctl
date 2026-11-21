"""CSV, JSON, and Markdown report exporters for jobctl."""

from __future__ import annotations

import csv
from datetime import datetime
import json
from pathlib import Path

from jobctl.models import ScoredJob

CSV_COLUMNS = [
    "rank",
    "match_score",
    "is_new",
    "title",
    "company",
    "location",
    "job_type",
    "work_mode",
    "posted_date",
    "source",
    "matched_skills",
    "skills_pct",
    "title_pct",
    "job_type_pct",
    "url",
]


def write_jobs_to_csv(jobs: list[ScoredJob], output_path: str | Path) -> Path:
    """Export scored jobs to a structured CSV file."""
    target = Path(output_path)
    target.parent.mkdir(parents=True, exist_ok=True)

    with target.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=CSV_COLUMNS)
        writer.writeheader()
        for rank, item in enumerate(jobs, start=1):
            writer.writerow(
                {
                    "rank": rank,
                    "match_score": item.match_score,
                    "is_new": item.is_new,
                    "title": item.title,
                    "company": item.company,
                    "location": item.location,
                    "job_type": item.job_type,
                    "work_mode": item.work_mode,
                    "posted_date": item.posted_date[:10] if item.posted_date else "",
                    "source": item.source,
                    "matched_skills": ", ".join(item.matched_skills),
                    "skills_pct": item.score_breakdown.skills_pct,
                    "title_pct": item.score_breakdown.title_pct,
                    "job_type_pct": item.score_breakdown.job_type_pct,
                    "url": item.url,
                }
            )
    return target.resolve()


def write_jobs_to_json(
    jobs: list[ScoredJob],
    output_path: str | Path,
    now: datetime | None = None,
) -> Path:
    """Export scored jobs to a formatted JSON report."""
    target = Path(output_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    current = now or datetime.now()

    payload = {
        "generated_by": "jobctl",
        "version": "2.0.0",
        "generated_at": current.isoformat(),
        "total_matches": len(jobs),
        "jobs": [item.to_dict() for item in jobs],
    }
    target.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    return target.resolve()


def write_jobs_to_markdown(
    jobs: list[ScoredJob],
    output_path: str | Path,
    now: datetime | None = None,
) -> Path:
    """Export scored jobs to a clean Markdown digest."""
    target = Path(output_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    current = now or datetime.now()

    lines: list[str] = [
        "# jobctl — Matched Engineering Jobs",
        "",
        f"- **Generated:** {current.strftime('%Y-%m-%d %H:%M')}",
        f"- **Matches Found:** {len(jobs)} (Posted within previous 2 days)",
        "",
    ]

    if not jobs:
        lines.append("_No jobs matched your criteria in this run._")
    else:
        lines.extend(
            [
                "| # | Score | Title | Company | Posted | Source | Matched Skills | Apply |",
                "|---:|---:|---|---|---|---|---|---|",
            ]
        )
        for idx, item in enumerate(jobs, start=1):
            posted = item.posted_date[:10] if item.posted_date else "N/A"
            skills = ", ".join(item.matched_skills[:6])
            link = f"[Apply]({item.url})" if item.url else "N/A"
            lines.append(
                f"| {idx} | **{item.match_score}** | {item.title} | {item.company} | "
                f"{posted} | {item.source} | {skills} | {link} |"
            )

    lines.append("")
    target.write_text("\n".join(lines), encoding="utf-8")
    return target.resolve()
