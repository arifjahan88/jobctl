"""Offline unit tests for the 8 new public job source adapters (2-day freshness enforced)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from email.utils import format_datetime
import unittest

from jobctl.config import ProfileConfig
from jobctl.sources.bdjobs import parse_bdjobs_payload
from jobctl.sources.hackernews import parse_hn_comments_payload
from jobctl.sources.recruitee import parse_recruitee_payload
from jobctl.sources.remoteok import parse_remoteok_payload
from jobctl.sources.remotive import parse_remotive_payload
from jobctl.sources.smartrecruiters import parse_smartrecruiters_payload
from jobctl.sources.weworkremotely import parse_wwr_rss
from jobctl.sources.workable import parse_workable_payload


def test_parse_all_eight_new_public_api_sources() -> None:
    profile = ProfileConfig(level="mid")
    now_utc = datetime.now(timezone.utc)
    today_iso = now_utc.strftime("%Y-%m-%dT%H:%M:%SZ")
    today_date = now_utc.strftime("%Y-%m-%d")
    today_rfc2822 = format_datetime(now_utc)
    stale_iso = (now_utc - timedelta(days=10)).strftime("%Y-%m-%dT%H:%M:%SZ")

    # 1. Remotive
    remotive_payload = {
        "jobs": [
            {
                "title": "Backend Engineer (Node.js & PostgreSQL)",
                "company_name": "RemotiveCorp",
                "candidate_required_location": "Worldwide",
                "job_type": "full_time",
                "publication_date": today_iso,
                "url": "https://remotive.com/remote-jobs/software-dev/backend-1",
                "description": "<p>TypeScript, Node.js, PostgreSQL, Docker.</p>",
            },
            {
                "title": "Backend Engineer (Stale)",
                "company_name": "OldCorp",
                "publication_date": stale_iso,
                "url": "https://remotive.com/remote-jobs/software-dev/old",
                "description": "Old listing",
            },
        ]
    }
    remotive_jobs = parse_remotive_payload(remotive_payload, profile, max_posting_age_days=2)
    assert len(remotive_jobs) == 1
    assert remotive_jobs[0].company == "RemotiveCorp"

    # 2. RemoteOK
    remoteok_payload = [
        {"legal": "RemoteOK API Terms"},
        {
            "position": "DevOps Engineer",
            "company": "CloudNativeInc",
            "location": "Remote",
            "date": today_iso,
            "tags": ["kubernetes", "docker", "terraform", "aws"],
            "description": "<p>Manage Kubernetes clusters and CI/CD.</p>",
            "url": "https://remoteok.com/remote-jobs/123",
        },
    ]
    remoteok_jobs = parse_remoteok_payload(remoteok_payload, profile, max_posting_age_days=2)
    assert len(remoteok_jobs) == 1
    assert remoteok_jobs[0].title == "DevOps Engineer"

    # 3. WeWorkRemotely RSS
    wwr_xml = f"""<?xml version="1.0" encoding="UTF-8"?>
    <rss version="2.0">
      <channel>
        <item>
          <title>PostgresCloud: Software Engineer II</title>
          <region>Anywhere in the World</region>
          <type>Full-Time</type>
          <pubDate>{today_rfc2822}</pubDate>
          <description>&lt;p&gt;Build PostgreSQL, Redis, and Docker services.&lt;/p&gt;</description>
          <link>https://weworkremotely.com/remote-jobs/postgrescloud-swe-ii</link>
        </item>
      </channel>
    </rss>
    """
    wwr_jobs = parse_wwr_rss(wwr_xml, profile, max_posting_age_days=2)
    assert len(wwr_jobs) == 1
    assert wwr_jobs[0].company == "PostgresCloud"
    assert wwr_jobs[0].title == "Software Engineer II"

    # 4. Hacker News "Who's Hiring" (Algolia JSON)
    hn_payload = {
        "hits": [
            {
                "objectID": "42000001",
                "created_at": today_iso,
                "comment_text": (
                    "AcmeInfra | Platform Engineer | Remote (Worldwide) | Full-time<p>"
                    "We use PostgreSQL, Kubernetes, Terraform, TypeScript, and AWS."
                ),
            }
        ]
    }
    hn_jobs = parse_hn_comments_payload(hn_payload, profile, max_posting_age_days=2)
    assert len(hn_jobs) == 1
    assert hn_jobs[0].company == "AcmeInfra"
    assert hn_jobs[0].title == "Platform Engineer"

    # 5. SmartRecruiters
    sr_payload = {
        "content": [
            {
                "id": "sr-101",
                "name": "Cloud Infrastructure Engineer",
                "releasedDate": today_iso,
                "location": {"city": "Berlin", "country": "de", "remote": True},
                "typeOfEmployment": {"label": "Full-time"},
                "department": {"label": "DevOps & PostgreSQL"},
                "company": {"name": "Aiven"},
            }
        ]
    }
    sr_jobs = parse_smartrecruiters_payload(sr_payload, "Aiven", profile, max_posting_age_days=2)
    assert len(sr_jobs) == 1
    assert sr_jobs[0].company == "Aiven"

    # 6. Recruitee
    rec_payload = {
        "offers": [
            {
                "title": "Full Stack Engineer",
                "published_at": today_iso,
                "remote": True,
                "location": "Remote",
                "description": "<p>TypeScript, React, Node.js, PostgreSQL.</p>",
                "careers_url": "https://baserow.recruitee.com/o/full-stack-engineer",
            }
        ]
    }
    rec_jobs = parse_recruitee_payload(rec_payload, "baserow", profile, max_posting_age_days=2)
    assert len(rec_jobs) == 1
    assert rec_jobs[0].work_mode == "remote"

    # 7. Workable
    workable_payload = {
        "name": "Percona",
        "jobs": [
            {
                "title": "PostgreSQL Database Engineer",
                "published_on": today_date,
                "telecommuting": True,
                "city": "Remote",
                "country": "Worldwide",
                "employment_type": "Full-time",
                "description": "<p>PostgreSQL, Linux, Docker, Kubernetes.</p>",
                "url": "https://apply.workable.com/percona/j/ABC123/",
            }
        ],
    }
    wk_jobs = parse_workable_payload(workable_payload, "percona", profile, max_posting_age_days=2)
    assert len(wk_jobs) == 1
    assert wk_jobs[0].company == "Percona"

    # 8. BDJobs
    bd_payload = {
        "data": [
            {
                "jobId": "1300999",
                "jobTitle": "Software Engineer (ERP & PostgreSQL)",
                "compName": "Dhaka Cloud ERP Ltd",
                "location": "Remote (Dhaka)",
                "publishDate": today_date,
                "jobContext": "Remote role building scalable ERP with Node.js, PostgreSQL, Docker.",
            }
        ]
    }
    bd_jobs = parse_bdjobs_payload(bd_payload, profile, max_posting_age_days=2)
    assert len(bd_jobs) == 1
    assert bd_jobs[0].company == "Dhaka Cloud ERP Ltd"


class TestNewSources(unittest.TestCase):
    def test_all(self) -> None:
        test_parse_all_eight_new_public_api_sources()
