"""
tests/test_dockerfile_security_layer.py — the release gate must stay passable.

`ufal/atrium-project`'s `docker-tool.reusable.yml` blocks a release on *fixable*
CRITICAL vulnerabilities in the published image and, because the tag-promotion
step is `if: success()`, a failure means the image is published by digest with no
`:<version>` or `:latest` tag on it. That is exactly what happened to v1.0.0-beta
on 2026-09-13: `python:3.11-slim` carried perl-base 5.40.1-6 with three fixable
CRITICALs (CVE-2026-13221, CVE-2026-42496, CVE-2026-8376), and both matrix
targets failed the gate.

The Dockerfile now applies the distro's available security patches at build time.
These tests pin the two properties that make that work, because both are
invisible on inspection and silently degrade rather than break:

1. **Position relative to the cache-bust anchor.** The build runs with
   `cache-from: type=gha`. An apt layer placed above the `ENV` block that embeds
   `ATRIUM_RUNNER_REF` would be served from cache indefinitely and stop patching
   anything, while still *looking* correct in the file. CI passes that ARG as
   `github.ref_name`, unique per release tag, so sitting below it is what makes
   the layer re-run for every released image.
2. **Position relative to the non-root switch.** apt needs root; below
   `USER atrium` the layer fails the build outright.
"""

from __future__ import annotations

import re

from atrium_test_support import REPO_ROOT

DOCKERFILE = (REPO_ROOT / "Dockerfile").read_text()
LINES = DOCKERFILE.splitlines()


def _line_of(pattern: str) -> int:
    rx = re.compile(pattern)
    for i, line in enumerate(LINES):
        if rx.search(line):
            return i
    return -1


def test_security_patches_are_applied():
    """Without this layer the base image ships whatever Docker Hub last built."""
    assert _line_of(r"apt-get\s+upgrade") != -1, (
        "the Dockerfile applies no distro security patches, so the released image "
        "carries every fixable CVE in the python:3.11-slim base layer and the "
        "release gate blocks tag promotion"
    )


def test_apt_lists_are_cleaned_up():
    assert _line_of(r"rm -rf /var/lib/apt/lists") != -1, "apt lists left in the image layer"


def test_upgrade_runs_below_the_cache_bust_anchor():
    """Above the ref-bearing ENV block this layer would be cached forever."""
    env_ref = _line_of(r"ATRIUM_RUNNER_REF=\$\{ATRIUM_RUNNER_REF\}")
    upgrade = _line_of(r"apt-get\s+upgrade")
    assert env_ref != -1, "the ENV block that embeds ATRIUM_RUNNER_REF is gone; the anchor moved"
    assert upgrade > env_ref, (
        f"apt-get upgrade is at line {upgrade + 1}, above the ATRIUM_RUNNER_REF ENV at line "
        f"{env_ref + 1}. With cache-from: type=gha that layer is served from cache on every "
        "later build and silently stops patching."
    )


def test_upgrade_runs_as_root():
    """apt needs root; below USER atrium the build fails."""
    upgrade = _line_of(r"apt-get\s+upgrade")
    user_switch = _line_of(r"^USER atrium")
    assert user_switch != -1, "the non-root USER switch is gone — that is its own problem"
    assert upgrade < user_switch, (
        f"apt-get upgrade at line {upgrade + 1} runs after USER atrium at line {user_switch + 1}; apt requires root"
    )


def test_base_image_is_still_a_known_distro():
    """If the base moves off Debian, `apt-get upgrade` stops being the right fix."""
    assert re.search(r"^FROM\s+python:3\.11-slim", DOCKERFILE, re.MULTILINE), (
        "base image changed; re-check that apt-get upgrade is still the correct mechanism for applying security patches"
    )
