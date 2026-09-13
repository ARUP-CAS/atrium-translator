"""
tests/test_python_version_parity.py — CI must run the Python that ships.

`.github/workflows/scheduled-smoke.yml` pinned `python-version: '3.12'` while
every image in the ecosystem is `python:3.11-slim` and every other lane —
including the PR lane inside the hub's `docker-tool.reusable.yml` — is 3.11. It
was the ecosystem's only 3.12 job and also its broadest (it runs the whole
suite), so a 3.12-only failure read as a product bug and a 3.12-only pass hid
one (atrium-project#64, 12-factor X).

`64.digest.md` closes on the observation that fixing the pin leaves the
convention enforced by nothing: *"After this fix, `python-version` is 3.11
everywhere by convention only. The next workflow added can differ silently. A
one-line check (grep the workflows, compare to the image base) would keep it."*
This is that check. It derives the expected version from the **Dockerfile**
rather than hard-coding it, so the day this repo moves to 3.12 the images move
first and the lanes are then required to follow — which is the direction
dev/prod parity has to run.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from atrium_test_support import REPO_ROOT

WORKFLOWS = sorted((REPO_ROOT / ".github" / "workflows").glob("*.yml"))


def _image_python_version() -> str:
    """The X.Y this repo's image is built on — the definition of 'production'."""
    dockerfile = (REPO_ROOT / "Dockerfile").read_text()
    match = re.search(r"^FROM\s+python:(\d+\.\d+)", dockerfile, re.MULTILINE)
    assert match, "no `FROM python:X.Y` in the Dockerfile; this check needs one"
    return match.group(1)


def test_dockerfile_declares_a_python_version():
    assert _image_python_version() == "3.11"


@pytest.mark.parametrize("workflow", WORKFLOWS, ids=lambda p: p.name)
def test_workflow_python_matches_the_image(workflow: Path):
    expected = _image_python_version()
    pinned = re.findall(r"^\s*python-version:\s*['\"]?([\d.]+)['\"]?", workflow.read_text(), re.MULTILINE)

    mismatched = [v for v in pinned if v != expected]
    assert not mismatched, (
        f"{workflow.name} pins python-version {mismatched} but the image is "
        f"python:{expected}-slim. A lane that differs from production reports "
        f"its own failures as product bugs (atrium-project#64)."
    )


def test_ruff_target_version_matches_the_image():
    """The third place the version is declared, and the only one tooling reads."""
    expected = _image_python_version().replace(".", "")
    ruff = (REPO_ROOT / "ruff.toml").read_text()
    match = re.search(r'^target-version\s*=\s*"py(\d+)"', ruff, re.MULTILINE)
    assert match, "ruff.toml has no target-version; the image version is then asserted by nothing"
    assert match.group(1) == expected, (
        f"ruff.toml targets py{match.group(1)}, image is python:{_image_python_version()}"
    )
