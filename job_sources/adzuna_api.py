"""
job_sources/adzuna_api.py
---------------------------
Adapter for the Adzuna Job Search API (https://developer.adzuna.com/).
Free tier requires an app_id + app_key (register at the link above).
Adzuna covers on-site, hybrid, and remote roles across many countries,
so this adapter does its best to infer work_mode from text since Adzuna
doesn't expose a clean remote/on-site/hybrid field.
"""

import re

import requests

ADZUNA_ENDPOINT_TEMPLATE = "https://api.adzuna.com/v1/api/jobs/{country}/search/1"

_REMOTE_KEYWORDS = ["remote", "work from home", "wfh", "fully distributed"]
_HYBRID_KEYWORDS = ["hybrid"]

_JOB_TYPE_KEYWORDS = {
    "internship": ["intern", "internship"],
    "part-time": ["part-time", "part time"],
    "contract": ["contract", "contractor", "freelance"],
}


def _infer_work_mode(text: str) -> str:
    lowered = text.lower()
    if any(kw in lowered for kw in _HYBRID_KEYWORDS):
        return "hybrid"
    if any(kw in lowered for kw in _REMOTE_KEYWORDS):
        return "remote"
    return "on-site"  # Adzuna default assumption when no signal is present


def _infer_job_type(text: str) -> str:
    lowered = text.lower()
    for job_type, keywords in _JOB_TYPE_KEYWORDS.items():
        if any(kw in lowered for kw in keywords):
            return job_type
    return "full-time"


def fetch_jobs(
    config: dict, app_id: str, app_key: str, country_code: str, limit: int = 30
) -> list:
    """
    Fetch listings from Adzuna filtered by role title and (optionally)
    location. Returns [] if credentials are missing/invalid or the request
    fails, so a missing Adzuna account never breaks the overall pipeline.
    """
    if not app_id or not app_key:
        print(
            "[Adzuna] Skipping source — no ADZUNA_APP_ID / ADZUNA_APP_KEY configured."
        )
        return []

    endpoint = ADZUNA_ENDPOINT_TEMPLATE.format(country=country_code)
    params = {
        "app_id": app_id,
        "app_key": app_key,
        "results_per_page": limit,
        "what": config["role_title"],
        "content-type": "application/json",
    }

    location = config.get("location", "").strip().lower()
    if location and location not in ("worldwide", "remote", ""):
        params["where"] = config["location"]

    try:
        response = requests.get(endpoint, params=params, timeout=15)
        response.raise_for_status()
        payload = response.json()
    except requests.RequestException as exc:
        print(f"[Adzuna] Skipping source — request failed: {exc}")
        return []
    except ValueError as exc:
        print(f"[Adzuna] Skipping source — bad JSON response: {exc}")
        return []

    raw_jobs = payload.get("results", [])
    normalized = []

    for job in raw_jobs:
        title = job.get("title", "")
        description = job.get("description", "")
        combined_text = f"{title} {description}"

        company = job.get("company", {}).get("display_name", "Unknown Company")
        location_name = job.get("location", {}).get("display_name", "Unspecified")

        normalized.append(
            {
                "title": re.sub(r"\s+", " ", title).strip(),
                "company": company,
                "location": location_name,
                "job_type": _infer_job_type(combined_text),
                "work_mode": _infer_work_mode(combined_text),
                "description": re.sub(r"\s+", " ", description).strip(),
                "url": job.get("redirect_url", ""),
                "source": "Adzuna",
                "posted_date": job.get("created", ""),
            }
        )

    return normalized
