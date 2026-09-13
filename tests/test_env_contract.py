"""
tests/test_env_contract.py — .env.example is the published contract; keep it true.

atrium-project#60 asks for exactly this and says why: *"Each of the five repos has
an .env.example whose variable names are a superset of the service-layer
os.getenv/os.environ reads in that repo — check this with a script and keep it,
or the tables rot within a release."* A hand-maintained table of ~40 variables
does not survive contact with a codebase otherwise; `.env.example` was already a
superset of the `service/` reads but was missing 19 of the backend knobs, which
is how a repo advertising pluggable backends shipped a contract that documented
none of their configuration.

The second test is the one that actually broke in practice. `.env.example`'s
header used to tell the reader that "docker-compose reads `.env` from the repo
root automatically" — true for ${VAR} SUBSTITUTION, and false for INJECTION into
the container. Compose passes only what a service's `environment:` or `env_file:`
declares, and there was no `env_file:`, so LOG_LEVEL, ALLOWED_ORIGINS,
MAX_UPLOAD_MB, GRACEFUL_SHUTDOWN_S and HOST written into `.env` reached nothing.
"""

from __future__ import annotations

import ast
import re

import pytest
import yaml

from atrium_test_support import REPO_ROOT

ENV_EXAMPLE = REPO_ROOT / ".env.example"
COMPOSE = REPO_ROOT / "docker-compose.yml"

# Read from the process environment but supplied by the platform, not by an
# operator editing .env — documenting them as knobs would be misleading.
_NOT_OPERATOR_KNOBS = {
    "HOME",
    "PATH",
    "PYTHONPATH",
}

# Documented in .env.example but consumed outside this repo's Python, so the
# scanner below cannot see them. Each needs a reason, not just an entry.
_CONSUMED_ELSEWHERE = {
    "ATRIUM_VERSION": "docker-compose.yml only — picks the image tag",
    "HF_HOME": "read by huggingface_hub, set by the Dockerfile and compose",
}

_ENV_READ = re.compile(r'(?:os\.)?(?:environ\.get|getenv|environ\[)\(?\s*["\']([A-Z_][A-Z0-9_]*)["\']')
_ENV_HELPER = re.compile(r'_env_(?:float|int|str)\(\s*((?:["\'][A-Z_][A-Z0-9_]*["\']\s*,?\s*)+)')
_SKIP_DIRS = {"tests", "eval", "data_samples", "agent_dev_logs", ".git"}


def _indirect_env_reads(source: str) -> set[str]:
    """Resolve `os.environ.get(_SOME_CONST, ...)` to the literal it names.

    atrium_paradata.py reads ATRIUM_RUNNER_IMAGE / _REPO / _REF through
    module-level constants rather than inline strings, so a regex over the call
    sites misses all three and then reports them as documented-but-unread.
    """
    try:
        tree = ast.parse(source)
    except SyntaxError:  # pragma: no cover - every file here parses
        return set()

    constants = {
        target.id: node.value.value
        for node in tree.body
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Constant) and isinstance(node.value.value, str)
        for target in node.targets
        if isinstance(target, ast.Name)
    }

    names: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not node.args:
            continue
        func = node.func
        attr = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", "")
        if attr not in {"get", "getenv"}:
            continue
        first = node.args[0]
        if isinstance(first, ast.Name) and first.id in constants:
            value = constants[first.id]
            if re.fullmatch(r"[A-Z_][A-Z0-9_]*", value):
                names.add(value)
    return names


def _runtime_env_reads() -> dict[str, set[str]]:
    """Every environment variable the shipped code reads, and where."""
    found: dict[str, set[str]] = {}
    for py in sorted(REPO_ROOT.rglob("*.py")):
        if any(part in _SKIP_DIRS for part in py.relative_to(REPO_ROOT).parts):
            continue
        source = py.read_text()
        names = set(_ENV_READ.findall(source))
        for group in _ENV_HELPER.findall(source):
            names.update(re.findall(r'["\']([A-Z_][A-Z0-9_]*)["\']', group))
        names |= _indirect_env_reads(source)
        for name in names - _NOT_OPERATOR_KNOBS:
            found.setdefault(name, set()).add(str(py.relative_to(REPO_ROOT)))
    return found


def _documented() -> set[str]:
    """Names declared as `KEY=` in .env.example, commented-out entries included."""
    return set(re.findall(r"^#?\s*([A-Z_][A-Z0-9_]*)=", ENV_EXAMPLE.read_text(), re.MULTILINE))


def test_env_example_documents_every_variable_the_code_reads():
    reads = _runtime_env_reads()
    undocumented = sorted(set(reads) - _documented())
    detail = "\n".join(f"  {name}  (read in {', '.join(sorted(reads[name]))})" for name in undocumented)
    assert not undocumented, (
        "These variables are read by shipped code but are not in .env.example, so a "
        f"partner can only discover them by reading the source:\n{detail}"
    )


def test_env_example_documents_nothing_imaginary():
    """A contract that lists knobs the code does not read is its own kind of lie."""
    reads = set(_runtime_env_reads())
    phantom = sorted(_documented() - reads - set(_CONSUMED_ELSEWHERE))
    assert not phantom, (
        f".env.example documents variables nothing reads: {phantom}. Either the code "
        "stopped reading them, or they belong in _CONSUMED_ELSEWHERE with a reason."
    )


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
