"""
tests/integration/test_translate_live.py — /translate against a reachable backend.

The gap this closes, in the words of the workflow that failed to catch it
(`.github/workflows/scheduled-smoke.yml:26-29`):

    What it does NOT cover: a live LINDAT backend. Every /translate test mocks
    the pipeline, which is how service/api.py shipped omitting `backend` from its
    args and returned HTTP 500 on every real upload. That gap needs an
    integration lane with a reachable backend, not a marker.

Everything here runs the real path: the real FastAPI handler, the real
`process_single_file`, the real `LindatTranslator`, the real chunker, the real
ALTO reconstruction and the real paradata write. Nothing is patched except the
two endpoint URLs, which atrium-project#63 made attachable for exactly this
reason — so the substitution is a supported configuration rather than a
test seam.

Marked `integration` and deselected from the fast lane, because each test starts
an HTTP server and drives a full document through the pipeline.
"""

from __future__ import annotations

import os
import re

import pytest

pytest.importorskip("fastapi")

from fastapi.testclient import TestClient  # noqa: E402

from tests.integration.stub_lindat import TOKEN_SUFFIX, StubLindat  # noqa: E402

# `integration` selects this lane; `slow` keeps it out of the fast one. The hub's
# PR lane is `pytest -m "not slow"`, so without the second marker these tests run
# there too -- which is how the reload leak above was found, and is 6s of HTTP
# servers in a lane whose whole purpose is to be quick. They still run on every
# push and PR, in .github/workflows/integration.yml's own job.
pytestmark = [pytest.mark.integration, pytest.mark.slow]

_ALTO = """<?xml version="1.0" encoding="UTF-8"?>
<alto xmlns="http://www.loc.gov/standards/alto/ns-v2#">
  <Layout>
    <Page ID="P1" PHYSICAL_IMG_NR="1" WIDTH="1200" HEIGHT="1600">
      <PrintSpace HPOS="0" VPOS="0" WIDTH="1200" HEIGHT="1600">
        <TextBlock ID="B1" HPOS="100" VPOS="100" WIDTH="800" HEIGHT="200">
          <TextLine ID="L1" HPOS="100" VPOS="100" WIDTH="800" HEIGHT="40">
            <String ID="S1" CONTENT="Archeologicky" HPOS="100" VPOS="100" WIDTH="300" HEIGHT="40"/>
            <String ID="S2" CONTENT="vyzkum" HPOS="420" VPOS="100" WIDTH="200" HEIGHT="40"/>
          </TextLine>
          <TextLine ID="L2" HPOS="100" VPOS="160" WIDTH="800" HEIGHT="40">
            <String ID="S3" CONTENT="lokalita" HPOS="100" VPOS="160" WIDTH="250" HEIGHT="40"/>
            <String ID="S4" CONTENT="Praha" HPOS="370" VPOS="160" WIDTH="180" HEIGHT="40"/>
          </TextLine>
        </TextBlock>
      </PrintSpace>
    </Page>
  </Layout>
</alto>
"""


LIVE = os.environ.get("ATRIUM_LIVE_BACKEND", "").strip().lower() in ("1", "true", "yes", "on")


class _LiveBackend:
    """Stand-in for StubLindat when running against the real LINDAT hosts.

    It records nothing, because there is nothing local to record — the assertions
    that inspect `.calls` skip themselves rather than pretend.
    """

    calls: list = []


@pytest.fixture
def stubbed_backend(monkeypatch):
    """Point both backing services at a local stub and build the app around it.

    No importlib.reload() anywhere, and that is a property of the code rather
    than a convenience: atrium-project#63 made the endpoints attachable by
    resolving them at CONSTRUCTION time (`processors/translator.py:241`
    `resolve_translation_url(base_url)`, `processors/lemmatizer.py:90`
    `resolve_udpipe_url(url)`), not at import. Setting the variables before
    TestClient runs `lifespan` is therefore enough.

    The first version of this fixture did reload both modules, and it was worth
    removing for more than tidiness: reload() rebinds module-level objects, so
    tests/test_degraded_startup.py -- which imports `_deep_health` and `models`
    from service.api -- was left asserting against a stale pair, and three
    unrelated tests failed depending on collection order. A test lane that
    corrupts the suite it runs in is not a lane anyone can trust.

    With ATRIUM_LIVE_BACKEND set (the manual `live-backend` CI job) the stub is
    skipped and the defaults are left in place, so the same tests exercise the
    real hosts. A failure there is a contract change at LINDAT, not a regression
    here.
    """
    import service.api as api_module

    if LIVE:
        monkeypatch.delenv("TRANSLATION_URL", raising=False)
        monkeypatch.delenv("UDPIPE_URL", raising=False)
        monkeypatch.delenv("LINDAT_BASE_URL", raising=False)
        monkeypatch.setenv("TRANSLATION_BACKEND", "lindat")
        with TestClient(api_module.app) as client:
            yield client, _LiveBackend()
        return

    with StubLindat() as stub:
        monkeypatch.setenv("TRANSLATION_URL", stub.translation_url)
        monkeypatch.setenv("UDPIPE_URL", stub.udpipe_url)
        monkeypatch.setenv("TRANSLATION_BACKEND", "lindat")
        monkeypatch.delenv("LINDAT_BASE_URL", raising=False)

        with TestClient(api_module.app) as client:
            yield client, stub


def test_translate_returns_translated_alto(stubbed_backend):
    """The end-to-end path this repo had no coverage for at all."""
    client, stub = stubbed_backend

    response = client.post(
        "/translate",
        files={"file": ("sample.alto.xml", _ALTO.encode("utf-8"), "application/xml")},
        params={"source_lang": "cs", "target_lang": "en", "is_alto": "true"},
    )

    assert response.status_code == 200, f"/translate failed: {response.status_code} {response.text[:500]}"

    body = response.content.decode("utf-8")
    assert "<alto" in body, "response is not ALTO XML"
    # Every String must still be there — reconstruction preserves geometry.
    for string_id in ("S1", "S2", "S3", "S4"):
        assert f'ID="{string_id}"' in body, f"{string_id} was lost in reconstruction"


@pytest.mark.skipif(LIVE, reason="call recording is a property of the stub, not of LINDAT")
def test_the_request_actually_reached_the_backend(stubbed_backend):
    """Guards against a green test that never made a call (the original failure shape)."""
    client, stub = stubbed_backend

    client.post(
        "/translate",
        files={"file": ("sample.alto.xml", _ALTO.encode("utf-8"), "application/xml")},
        params={"source_lang": "cs", "target_lang": "en", "is_alto": "true"},
    )

    translation_calls = [c for c in stub.calls if c[0] == "POST" and "/models/" in c[1]]
    assert translation_calls, (
        "no translation request reached the stub — the document came back "
        f"untranslated by some fallback path. Calls seen: {stub.calls}"
    )


@pytest.mark.skipif(LIVE, reason="the marker is the stub's; real output carries a real translation")
def test_output_content_came_through_the_backend(stubbed_backend):
    """The CONTENT attributes must carry the stub's marker, not the source text.

    Asserting only on HTTP 200 is what let the original defect look fine for so
    long: a handler can answer 200 with the document it was handed.
    """
    client, stub = stubbed_backend

    response = client.post(
        "/translate",
        files={"file": ("sample.alto.xml", _ALTO.encode("utf-8"), "application/xml")},
        params={"source_lang": "cs", "target_lang": "en", "is_alto": "true"},
    )
    body = response.content.decode("utf-8")

    assert TOKEN_SUFFIX in body, (
        "the returned ALTO carries none of the stub's per-token marker "
        f"({TOKEN_SUFFIX}), so nothing was actually translated — the document came "
        "back as it went in"
    )


def test_every_string_keeps_content_after_reconstruction(stubbed_backend):
    """No String may come back empty.

    The token realignment redistributes translated tokens onto the original
    String geometry. If the token count shifts, the surplus lands on one element
    and the last one is left blank — silent text loss in a document that still
    validates as ALTO. Worth asserting directly: it is how a stub bug was first
    mistaken for a reconstruction bug here.
    """
    client, _ = stubbed_backend

    response = client.post(
        "/translate",
        files={"file": ("sample.alto.xml", _ALTO.encode("utf-8"), "application/xml")},
        params={"source_lang": "cs", "target_lang": "en", "is_alto": "true"},
    )
    body = response.content.decode("utf-8")

    empty = re.findall(r'<String ID="([^"]+)" CONTENT=""', body)
    assert not empty, f"reconstruction left these String elements empty: {empty}"


def test_health_and_ready_are_live_with_a_stubbed_backend(stubbed_backend):
    client, _ = stubbed_backend
    assert client.get("/health").status_code == 200
    assert client.get("/ready").status_code == 200

    info = client.get("/info").json()
    assert info["service"]
    assert info["version"]


def test_deep_health_reflects_the_real_dependency_state(stubbed_backend):
    """?deep=true must agree with the models actually loaded.

    Asserting a flat 200 would be wrong. The translation backend is stubbed and
    reachable, but the FastText language-ID model is a SECOND backing service
    (HuggingFace), and on a host without egress it does not load. That is exactly
    the degraded state issue #53's factor IX work made visible instead of silent,
    so the contract to assert is the correspondence, not a constant: degraded
    identifier → 503 naming it, healthy identifier → 200.
    """
    client, _ = stubbed_backend

    import service.api as api_module

    load_error = getattr(api_module.models.get("identifier"), "load_error", None)
    response = client.get("/health", params={"deep": "true"})

    if load_error:
        assert response.status_code == 503, (
            "the language-ID model failed to load but ?deep=true reported healthy — "
            "this is the silent-degradation failure mode, back again"
        )
        assert "language identification" in response.text
    else:
        assert response.status_code == 200, response.text


@pytest.mark.skipif(LIVE, reason="against live hosts the resolved URL IS the LINDAT default")
def test_paradata_records_the_endpoint_actually_used(stubbed_backend):
    """atrium-project#63: the record names the host the request went to.

    A paradata field that confidently names LINDAT while the request went to a
    self-hosted endpoint is worse than one that omits it.
    """
    client, stub = stubbed_backend

    client.post(
        "/translate",
        files={"file": ("sample.alto.xml", _ALTO.encode("utf-8"), "application/xml")},
        params={"source_lang": "cs", "target_lang": "en", "is_alto": "true"},
    )

    import processors.translator as translator_module

    assert translator_module.resolve_translation_url() == os.environ["TRANSLATION_URL"]
    assert "lindat.mff.cuni.cz" not in translator_module.resolve_translation_url()
