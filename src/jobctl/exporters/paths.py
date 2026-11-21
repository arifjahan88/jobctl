"""Output path builder for `search_results/<YYYY-MM-DD>/` dated folders."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path


@dataclass(frozen=True, slots=True)
class RunPaths:
    """Resolved folder and per-run output file paths inside search_results/<YYYY-MM-DD>/."""

    base_dir: Path
    date_dir: Path
    run_stamp: str

    def file_for(self, ext: str) -> Path:
        clean_ext = ext.lstrip(".")
        return self.date_dir / f"jobctl_{self.run_stamp}.{clean_ext}"

    @property
    def log_file(self) -> Path:
        return self.date_dir / f"run_{self.run_stamp}.log"


def prepare_run_paths(
    results_dir: str | Path = "search_results",
    now: datetime | None = None,
) -> RunPaths:
    """
    Create and return the dated folder `search_results/<YYYY-MM-DD>/` and unique
    per-run file paths so multiple runs on the same day never overwrite each other.
    """
    current = now or datetime.now()
    base = Path(results_dir)
    date_folder = base / current.strftime("%Y-%m-%d")
    date_folder.mkdir(parents=True, exist_ok=True)

    stamp = current.strftime("%H%M%S")
    return RunPaths(base_dir=base, date_dir=date_folder, run_stamp=stamp)
