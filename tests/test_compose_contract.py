"""tests/test_compose_contract.py — docker-compose actually delivers what .env promises.

Relocated out of tests/test_env_contract.py (atrium-project#60) when that file's name
was reserved for the canonical, vendored env-var-ledger guard shared across all five
tool repos (docs/templates/shared/test_env_contract.py). These three checks are
translator-specific — the `env_file:` delivery mechanism and the FastText cache mount
are not part of the canonical contract every repo shares — so they live here instead of
being lost when the vendored file overwrote their old home.

The first two are the check that actually broke in practice. `.env.example`'s header
used to tell the reader that "docker-compose reads `.env` from the repo root
automatically" — true for ${VAR} SUBSTITUTION, and false for INJECTION into the
container. Compose passes only what a service's `environment:` or `env_file:`
declares, and before this repo added `env_file:`, LOG_LEVEL, ALLOWED_ORIGINS,
MAX_UPLOAD_MB, GRACEFUL_SHUTDOWN_S and HOST written into `.env` reached nothing.

Run: pytest tests/test_compose_contract.py
"""

from __future__ import annotations

import pytest
import yaml

from atrium_test_support import REPO_ROOT

COMPOSE = REPO_ROOT / "docker-compose.yml"


def _compose_services() -> dict:
    return yaml.safe_load(COMPOSE.read_text())["services"]


@pytest.mark.parametrize("service", ["translator", "api"])
def test_compose_services_load_the_env_file(service):
    """Substitution is not injection — the distinction that silently dropped config."""
    spec = _compose_services()[service]
    entries = spec.get("env_file") or []
    paths = [e["path"] if isinstance(e, dict) else e for e in entries]
    assert ".env" in paths, (
        f"docker-compose.yml's `{service}` service has no `env_file: .env`, so every "
        "variable in .env that is not also named in its `environment:` block is "
        "silently discarded (atrium-project#60)."
    )


@pytest.mark.parametrize("service", ["translator", "api"])
def test_compose_env_file_is_optional(service):
    """.env is gitignored; a fresh clone must still `docker compose up`."""
    entries = _compose_services()[service].get("env_file") or []
    for entry in entries:
        if isinstance(entry, dict) and entry.get("path") == ".env":
            assert entry.get("required") is False, (
                "env_file must be `required: false` — .env is gitignored, so a fresh "
                "clone has none and compose would refuse to start."
            )


def test_api_service_caches_the_language_model():
    """Without this the API re-downloads FastText on every start, and fails with no egress."""
    mounts = _compose_services()["api"].get("volumes") or []
    assert any("hf-cache" in str(m) for m in mounts), (
        "the api service does not mount the hf-cache volume; LanguageIdentifier "
        "downloads the FastText model during lifespan startup on every `up`, and a "
        "host without egress then starts the service in its degraded 'everything is "
        "English' state."
    )
