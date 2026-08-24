"""The zero-dependency smoke check is itself exercised here.

`scripts/smoke_core.py` runs in a CI job where httpx and cryptography are
absent — an environment the normal test run never sees, so nothing else would
catch it rotting. It rotted once already: an earlier inline version of it used
VAT numbers that stopped validating the day check-digit verification landed,
and the workflow stayed broken because nobody reads a green-until-you-look YAML.

These tests run its logic in the ordinary environment. They cannot prove the
"no optional dependencies" part — only CI can — but they prove everything else
the script asserts, which is where the drift actually happens.
"""
import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "smoke_core.py"


def test_the_script_is_where_ci_expects_it():
    assert SCRIPT.is_file(), f"CI runs {SCRIPT.name}; it must exist"


def test_the_workflow_actually_invokes_it():
    """A smoke script nothing runs is a smoke script that rots."""
    workflow = (SCRIPT.parents[1] / ".github" / "workflows" / "ci.yml").read_text()
    assert "scripts/smoke_core.py" in workflow


def test_its_assertions_hold_in_an_ordinary_environment():
    """Everything the script checks except the absence of the extras."""
    spec = importlib.util.spec_from_file_location("smoke_core", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    assert module.main() == 0


def test_running_it_as_a_subprocess_reports_the_right_thing():
    """With the extras installed it must refuse rather than pass vacuously —
    a check that cannot fail is not a check."""
    if all(importlib.util.find_spec(name) is None for name in ("httpx", "cryptography")):
        pytest.skip("optional extras genuinely absent here; that is the CI path")

    result = subprocess.run(
        [sys.executable, str(SCRIPT)], capture_output=True, text=True, check=False)

    assert result.returncode != 0
    assert "must NOT be installed" in (result.stdout + result.stderr)
