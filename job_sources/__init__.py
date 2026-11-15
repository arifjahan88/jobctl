"""
job_sources package
--------------------
Adapters for tech job portals and ATS platforms:
- LinkedIn (linkedin_api.py)
- Wellfound (wellfound_api.py)
- Greenhouse ATS (greenhouse_api.py)
- Lever ATS (lever_api.py)
- Ashby ATS (ashby_api.py)
- Adzuna (adzuna_api.py)

Every adapter returns job listings normalized to this shared schema:

{
    "title": str,
    "company": str,
    "location": str,
    "job_type": str,        # "internship" | "full-time" | "part-time" | "contract" | "unknown"
    "work_mode": str,       # "remote" | "on-site" | "hybrid" | "unknown"
    "description": str,     # plain text, HTML stripped
    "url": str,
    "source": str,          # e.g. "LinkedIn", "Wellfound", "Greenhouse (gitlab)", "Ashby (linear)"
    "posted_date": str,     # ISO date string or ""
}
"""
