"""Job source adapters, HTTP session helper, and pluggable source registry."""

from jobctl.sources import (
    adzuna,
    ashby,
    bdjobs,
    greenhouse,
    hackernews,
    lever,
    linkedin,
    recruitee,
    remoteok,
    remotive,
    smartrecruiters,
    wellfound,
    weworkremotely,
    workable,
)
from jobctl.sources.base import (
    SOURCE_REGISTRY,
    JobSource,
    build_http_session,
    get_registered_sources,
    register_source,
)

__all__ = [
    "JobSource",
    "SOURCE_REGISTRY",
    "adzuna",
    "ashby",
    "bdjobs",
    "build_http_session",
    "get_registered_sources",
    "greenhouse",
    "hackernews",
    "lever",
    "linkedin",
    "recruitee",
    "register_source",
    "remoteok",
    "remotive",
    "smartrecruiters",
    "wellfound",
    "weworkremotely",
    "workable",
]
