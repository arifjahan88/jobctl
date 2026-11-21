"""Job source adapters, HTTP session helper, and pluggable source registry."""

from jobctl.sources import adzuna, ashby, greenhouse, lever, linkedin, wellfound
from jobctl.sources.base import SOURCE_REGISTRY, JobSource, build_http_session, get_registered_sources, register_source

__all__ = [
    "JobSource",
    "SOURCE_REGISTRY",
    "adzuna",
    "ashby",
    "build_http_session",
    "get_registered_sources",
    "greenhouse",
    "lever",
    "linkedin",
    "register_source",
    "wellfound",
]
