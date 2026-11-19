"""Base protocol, source registry, and resilient HTTP session with retries."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Callable

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from jobctl.config import ProfileConfig, SourceOptions
from jobctl.models import Job

DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)


def build_http_session() -> requests.Session:
    """Create a requests.Session configured with automatic retries on 429 and 5xx responses."""
    session = requests.Session()
    retry = Retry(
        total=3,
        read=2,
        connect=2,
        backoff_factor=0.5,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=frozenset({"GET"}),
        raise_on_status=False,
    )
    adapter = HTTPAdapter(max_retries=retry, pool_connections=20, pool_maxsize=20)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    session.headers.update(
        {
            "User-Agent": DEFAULT_USER_AGENT,
            "Accept-Language": "en-US,en;q=0.9",
        }
    )
    return session


class JobSource(ABC):
    """Abstract base class for every job portal / ATS source adapter."""

    name: str = ""
    description: str = ""

    @abstractmethod
    def fetch(
        self,
        profile: ProfileConfig,
        options: SourceOptions,
        max_posting_age_days: int = 2,
        session: requests.Session | None = None,
    ) -> list[Job]:
        """Fetch and normalize job listings for the given profile and options."""


SOURCE_REGISTRY: dict[str, JobSource] = {}


def register_source(name: str) -> Callable[[type[JobSource]], type[JobSource]]:
    """Class decorator that registers a JobSource implementation under `name`."""

    def _decorator(cls: type[JobSource]) -> type[JobSource]:
        instance = cls()
        instance.name = name
        SOURCE_REGISTRY[name] = instance
        return cls

    return _decorator


def get_registered_sources() -> dict[str, JobSource]:
    return dict(SOURCE_REGISTRY)
