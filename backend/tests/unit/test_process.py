"""The five processes (design/01 §1.2): each is `python -m ews.<name>` and starts through ews.common.process."""
import importlib
import subprocess
import sys

import pytest

from ews.common import process


@pytest.mark.parametrize("name", process.PROCESSES)
def test_each_process_has_a_main_module(name):
    module = importlib.import_module(f"ews.{name}.__main__")
    assert module.run is process.run


def test_unknown_process_rejected():
    with pytest.raises(ValueError):
        process.run("scheduler")


def test_missing_env_stops_with_clear_message(tmp_path):
    """start.ps1 step 1: without .env a process stops with a message naming the file (exit 2)."""
    code = ("import ews.common.settings as s, pathlib; s.DEFAULT_ENV_FILE = pathlib.Path(r'%s') / '.env'; "
            "from ews.common.process import run; run('ingest')") % tmp_path
    result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=60)
    assert result.returncode == 2
    assert ".env not found" in result.stderr
