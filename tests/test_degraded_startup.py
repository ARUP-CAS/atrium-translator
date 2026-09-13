"""
tests/test_degraded_startup.py — a degraded model load must be declared, not hidden.

`LanguageIdentifier.__init__` downloads the FastText language-ID model from
HuggingFace at container start. It used to swallow any failure::

    except Exception as e:
        print(f"[ERROR] Failed to load FastText language model: ...")
        self.model = None

after which `detect()` returned ``("en", 0.0)`` for every document forever, while
`_deep_health()` looked only at the translator and reported the service perfectly
healthy. Nothing downstream could distinguish that from a genuine English
detection, so a cluster with restricted egress — where `hf_hub_download` is
exactly what fails — got a green service that silently mislabelled the source
language of everything it was handed.

The resolution is *declared degradation*, not a crash: a deployment that always
passes `--source_lang` never consults the identifier, so crash-looping it would
be wrong. `GET /health?deep=true` is where it surfaces.
"""

from unittest.mock import patch

import pytest

from service.api import _deep_health, models


@pytest.fixture
def restore_models():
    saved = dict(models)
    yield
    models.clear()
    models.update(saved)


class _Identifier:
    def __init__(self, load_error=None):
        self.load_error = load_error


def test_deep_health_reports_a_failed_identifier_load(restore_models):
    models["translator"] = object()
    models["identifier"] = _Identifier(load_error="ConnectionError: no route to huggingface.co")

    detail = _deep_health()
    assert detail is not None
    assert "language identification" in detail
    assert "no route to huggingface.co" in detail


def test_deep_health_is_clean_when_both_models_loaded(restore_models):
    models["translator"] = object()
    models["identifier"] = _Identifier()
    assert _deep_health() is None


def test_deep_health_still_reports_a_missing_translator(restore_models):
    models["translator"] = None
    models["identifier"] = _Identifier()
    assert _deep_health() == "translation backend not warmed up"


def test_identifier_records_why_it_failed():
    from processors.identifier import LanguageIdentifier

    with patch(
        "processors.identifier.hf_hub_download",
        side_effect=ConnectionError("no route to huggingface.co"),
    ):
        identifier = LanguageIdentifier()

    assert identifier.model is None
    assert "ConnectionError" in identifier.load_error
    assert "no route to huggingface.co" in identifier.load_error


def test_unavailable_identifier_warns_once_not_once_per_document(caplog):
    """This path runs per chunk; a per-call log line buries the startup cause."""
    from processors.identifier import LanguageIdentifier

    with patch("processors.identifier.hf_hub_download", side_effect=OSError("offline")):
        identifier = LanguageIdentifier()

    caplog.clear()
    with caplog.at_level("WARNING", logger="processors.identifier"):
        for _ in range(50):
            assert identifier.detect("nějaký český text") == ("en", 0.0)

    warnings = [r for r in caplog.records if "not loaded" in r.getMessage()]
    assert len(warnings) == 1, f"expected 1 warning for 50 detections, got {len(warnings)}"
