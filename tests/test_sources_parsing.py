"""Offline unit tests for source helpers and ATS payload parsers."""

from __future__ import annotations

from datetime import datetime, timezone
import unittest

from jobctl.config import ProfileConfig
from jobctl.sources.ashby import parse_ashby_payload
from jobctl.sources.common import infer_job_type, infer_work_mode
from jobctl.sources.greenhouse import parse_greenhouse_payload
from jobctl.sources.lever import parse_lever_payload
from jobctl.sources.linkedin import build_linkedin_queries, parse_linkedin_cards


def test_infer_job_type_does_not_confuse_international_with_intern() -> None:
    assert (
        infer_job_type(
            "Software Engineer",
            "Join our international distributed engineering team building internal ERP tools.",
        )
        == "full-time"
    )
    assert infer_job_type("Software Engineering Intern", "Summer internship") == "internship"
    assert infer_job_type("DevOps Engineer (Contract)", "6-month contract role") == "contract"


def test_infer_work_mode_handles_structured_and_text_signals() -> None:
    assert infer_work_mode("San Francisco, CA", "Backend Engineer", structured_workplace="Remote") == "remote"
    assert infer_work_mode("London (Hybrid)", "Backend Engineer") == "hybrid"
    assert infer_work_mode("Remote - Worldwide", "Platform Engineer") == "remote"


def test_parse_greenhouse_lever_ashby_and_linkedin_payloads() -> None:
    profile = ProfileConfig(level="mid")
    today_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    today_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)

    gh_payload = {
        "jobs": [
            {
                "title": "DevOps Engineer",
                "location": {"name": "Remote - Global"},
                "content": "&lt;p&gt;Manage PostgreSQL, Docker, and Kubernetes.&lt;/p&gt;",
                "absolute_url": "https://boards.greenhouse.io/gitlab/jobs/101",
                "first_published": today_iso,
            },
            {
                "title": "Senior Staff Engineer",
                "location": {"name": "Remote"},
                "content": "10+ years",
                "absolute_url": "https://boards.greenhouse.io/gitlab/jobs/102",
                "first_published": today_iso,
            },
        ]
    }
    gh_jobs = parse_greenhouse_payload(gh_payload, "gitlab", profile, max_posting_age_days=2)
    assert len(gh_jobs) == 1
    assert gh_jobs[0].company == "GitLab"
    assert gh_jobs[0].title == "DevOps Engineer"

    lever_payload = [
        {
            "text": "Backend Engineer",
            "createdAt": now_ms,
            "workplaceType": "remote",
            "categories": {"commitment": "Full-Time", "location": "Remote"},
            "descriptionPlain": "Node.js, TypeScript, and PostgreSQL backend services.",
            "hostedUrl": "https://jobs.lever.co/postman/abc",
        }
    ]
    lever_jobs = parse_lever_payload(lever_payload, "postman", profile, max_posting_age_days=2)
    assert len(lever_jobs) == 1
    assert lever_jobs[0].work_mode == "remote"

    ashby_payload = {
        "jobs": [
            {
                "title": "Database Engineer",
                "publishedAt": today_iso,
                "isRemote": True,
                "workplaceType": "Remote",
                "employmentType": "FullTime",
                "location": "Remote",
                "descriptionPlain": "Scale PostgreSQL and Redis infrastructure.",
                "jobUrl": "https://jobs.ashbyhq.com/supabase/1",
            }
        ]
    }
    ashby_jobs = parse_ashby_payload(ashby_payload, "supabase", profile, max_posting_age_days=2)
    assert len(ashby_jobs) == 1
    assert ashby_jobs[0].title == "Database Engineer"

    li_html = f"""
    <li>
      <h3 class="base-search-card__title">Software Engineer II</h3>
      <h4 class="base-search-card__subtitle"><a>CloudCorp</a></h4>
      <span class="job-search-card__location">Remote</span>
      <a class="base-card__full-link" href="https://www.linkedin.com/jobs/view/123456789?trk=guest"></a>
      <time datetime="{today_date}"></time>
    </li>
    """
    cards = parse_linkedin_cards(li_html, profile, max_posting_age_days=2)
    assert len(cards) == 1
    assert cards[0]["job_id"] == "123456789"
    queries = build_linkedin_queries(profile)
    assert any("PostgreSQL" in q for q in queries)


class TestSourcesParsing(unittest.TestCase):
    def test_all(self) -> None:
        test_infer_job_type_does_not_confuse_international_with_intern()
        test_infer_work_mode_handles_structured_and_text_signals()
        test_parse_greenhouse_lever_ashby_and_linkedin_payloads()
