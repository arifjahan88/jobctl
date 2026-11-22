"""Unit tests for the `jobctl` CLI commands (init, sources, history)."""

from __future__ import annotations

import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from jobctl.cli import main


def test_cli_init_creates_config_file(tmp_path: Path) -> None:
    out_cfg = tmp_path / "jobctl.toml"
    rc = main(["init", "--output", str(out_cfg)])
    assert rc == 0
    assert out_cfg.exists()
    content = out_cfg.read_text(encoding="utf-8")
    assert "max_posting_age_days = 2" in content
    assert 'results_dir = "search_results"' in content


class TestCLI(unittest.TestCase):
    def test_cli_init_and_subcommands(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            tp = Path(td)
            test_cli_init_creates_config_file(tp)

            cfg = tp / "custom.toml"
            db = tp / "test.db"
            cfg.write_text(
                f'[profile]\nrole_title = "Software Engineer"\nlevel = "mid"\n'
                f"[filters]\nmax_posting_age_days = 2\n"
                f'[output]\nresults_dir = "{tp.as_posix()}/search_results"\n'
                f'history_db = "{db.as_posix()}"\n',
                encoding="utf-8",
            )

            buf = io.StringIO()
            with patch("sys.stdout", buf):
                assert main(["sources", "--config", str(cfg)]) == 0
                assert main(["history", "--config", str(cfg)]) == 0
            output = buf.getvalue()
            assert "greenhouse" in output
            assert "No history database found" in output
