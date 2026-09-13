"""Repo-local declarations for tests/test_env_contract.py (atrium-project#60).

Never vendored, never in para-drift, never in docs/templates/ruff.toml's [format]
exclude — unlike test_env_contract.py itself, this file's SHAPE is per-repo by
design: what one repo deliberately withholds from its ledger is not the same set as
what another does. See the canonical test's module docstring for the full rationale.
"""

from __future__ import annotations

# Read by shipped code but deliberately absent from .env.example, each with a reason.
# Empty here: translator's .env.example is a complete ledger with no withheld names.
NOT_PUBLISHED: dict[str, str] = {}

# In .env.example but read by no Python in this repo — each with a reason.
CONSUMED_ELSEWHERE: dict[str, str] = {
    "ATRIUM_VERSION": "read only by docker-compose.yml to pick the image tag; no Python here reads it",
    "HF_HOME": "read by huggingface_hub itself, set by the Dockerfile and docker-compose.yml",
}

# service/README.md or .env.example cells whose value is prose rather than a literal
# the code-default resolver can compare against (e.g. "see below", a value read out of
# another config file). Empty here: every active entry in this repo's files is a
# literal that matches its call site.
PROSE_DEFAULTS: dict[str, str] = {}
