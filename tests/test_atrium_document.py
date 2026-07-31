"""
tests/test_atrium_document.py

Tests the ATRIUM Document Schema & Accretion Policy ("paradata pair" model)
contract (six rules) for the translator integration.
"""

import json
from pathlib import Path

import pytest

from atrium_document import DocumentRecord
from atrium_paradata import ParadataLogger


@pytest.fixture
def mock_paradata(tmp_path):
    """Generates a mock paradata record and returns the run_id and ref."""
    para_dir = tmp_path / "paradata"
    para_dir.mkdir()
    logger = ParadataLogger("translator", {}, paradata_dir=str(para_dir))
    logger.log_component("lindat_cubbitt")
    paradata_ref = logger.finalize()
    return logger._run_id, paradata_ref


@pytest.fixture
def baseline_json(tmp_path):
    """Creates a mock baseline ATRIUM Document JSON from an upstream tool."""
    baseline = {
        "schema_version": "1.0",
        "doc_id": "CTX000000001",
        "source": {"filename": "CTX000000001.alto.xml"},
        "pages": [{"page": "1", "quality_score": 0.98}],
        "entities": [{"surface": "gotického kostela", "lemma": "gotický kostel", "page": "1", "line": 14}],
        "unknown_future_block": {"key": "value"},
    }
    baseline_path = tmp_path / "CTX000000001.document.json"
    baseline_path.write_text(json.dumps(baseline), encoding="utf-8")
    return baseline_path


def test_rule_1_and_2_baseline_in_record_out_and_own_block_only(tmp_path, baseline_json, mock_paradata):
    """Rule 1 & 2: Takes baseline, writes own block, deep-copies others unchanged."""
    run_id, paradata_ref = mock_paradata
    out_path = tmp_path / "out.json"

    with DocumentRecord.open(
        doc_id="CTX000000001",
        program="translator",
        baseline=baseline_json,
        run_id=run_id,
        paradata_ref=paradata_ref,
    ) as doc:
        doc.set_block("translations", {"en": "Full translation text here."})
        # MUST include the alignment keys ("page" and "line") so merge_block updates the existing row
        doc.merge_block(
            "entities", [{"page": "1", "line": 14, "surface": "gotického kostela", "translation_en": "gothic church"}]
        )
        doc.finalize(str(out_path))

    assert out_path.exists()
    result = json.loads(out_path.read_text(encoding="utf-8"))

    # Assert own block is written
    assert result["translations"]["en"] == "Full translation text here."

    # Assert merged block is correctly updated
    assert result["entities"][0]["translation_en"] == "gothic church"
    assert result["entities"][0]["lemma"] == "gotický kostel"  # Preserved from baseline

    # Assert other blocks remain untouched
    assert result["pages"][0]["quality_score"] == 0.98


def test_rule_3_no_baseline_own_part_only(tmp_path, mock_paradata):
    """Rule 3: Standalone runs work and produce own part plus identity fields."""
    run_id, paradata_ref = mock_paradata
    out_path = tmp_path / "out_standalone.json"

    with DocumentRecord.open(
        doc_id="CTX000000001",
        program="translator",
        baseline=None,
        run_id=run_id,
        paradata_ref=paradata_ref,
    ) as doc:
        doc.set_block("translations", {"en": "Standalone translation."})
        doc.finalize(str(out_path))

    result = json.loads(out_path.read_text(encoding="utf-8"))

    assert result["schema_version"] == "1.0"
    assert result["doc_id"] == "CTX000000001"
    assert result["translations"]["en"] == "Standalone translation."
    assert "pages" not in result


def test_rule_4_per_block_provenance(tmp_path, baseline_json, mock_paradata):
    """Rule 4: Every write stamps assembled.blocks[<block>] with the writer's info."""
    run_id, paradata_ref = mock_paradata
    out_path = tmp_path / "out_prov.json"

    with DocumentRecord.open(
        doc_id="CTX000000001",
        program="translator",
        baseline=baseline_json,
        run_id=run_id,
        paradata_ref=paradata_ref,
    ) as doc:
        doc.set_block("translations", {"en": "Text."})
        doc.finalize(str(out_path))

    result = json.loads(out_path.read_text(encoding="utf-8"))
    # Schema defines per-block provenance at assembled.blocks.<block_name>.run_id
    assert result["assembled"]["blocks"]["translations"]["run_id"] == run_id


def test_rule_6_unknown_blocks_preserved(tmp_path, baseline_json, mock_paradata):
    """Rule 6: Unknown or newer blocks are preserved verbatim."""
    run_id, paradata_ref = mock_paradata
    out_path = tmp_path / "out_unknown.json"

    with DocumentRecord.open(
        doc_id="CTX000000001",
        program="translator",
        baseline=baseline_json,
        run_id=run_id,
        paradata_ref=paradata_ref,
    ) as doc:
        doc.set_block("translations", {"en": "Text."})
        doc.finalize(str(out_path))

    result = json.loads(out_path.read_text(encoding="utf-8"))
    assert result["unknown_future_block"]["key"] == "value"


# ── P0.5 regression: process_metadata_xml/process_alto_xml's actual `translations`
# shape, not just the generic DocumentRecord primitive above ──────────────────────


def test_process_metadata_xml_writes_schema_shaped_translations(
    amcr_xml_file, tmp_path, mock_translator, mock_paradata
):
    """
    The previous implementation wrote `{tgt_lang: "<entire translated corpus text>"}`,
    which contradicts the schema (`{source_lang, target_lang, backend}`) and duplicates
    text that already persists via `derived_from.translated_xml`. Also asserts entity
    translation is NOT attempted — entities[] doesn't exist yet when the translator
    runs (pc→alto→translate→nlp→llm), so that pass was unreachable dead code.
    """
    from utils import process_metadata_xml

    run_id, paradata_ref = mock_paradata
    out_xml = tmp_path / "out.xml"

    with DocumentRecord.open(
        doc_id="CTX01", program="translator", baseline=None, run_id=run_id, paradata_ref=paradata_ref
    ) as doc:
        process_metadata_xml(
            amcr_xml_file,
            out_xml,
            ["//amcr:amcr/amcr:dokument/amcr:popis"],
            mock_translator,
            "cs",
            "en",
            doc=doc,
            backend="lindat",
        )
        doc.finalize(str(tmp_path / "CTX01.document.json"))

    result = json.loads((tmp_path / "CTX01.document.json").read_text(encoding="utf-8"))
    assert result["translations"] == {"source_lang": "cs", "target_lang": "en", "backend": "lindat"}


def test_process_alto_xml_writes_schema_shaped_translations(alto_xml_file, tmp_path, mock_translator, mock_paradata):
    from utils import process_alto_xml

    run_id, paradata_ref = mock_paradata
    out_xml = tmp_path / "out.alto.xml"

    with DocumentRecord.open(
        doc_id="CTX02", program="translator", baseline=None, run_id=run_id, paradata_ref=paradata_ref
    ) as doc:
        process_alto_xml(alto_xml_file, out_xml, mock_translator, "cs", "en", doc=doc, backend="ctranslate2")
        doc.finalize(str(tmp_path / "CTX02.document.json"))

    result = json.loads((tmp_path / "CTX02.document.json").read_text(encoding="utf-8"))
    assert result["translations"] == {"source_lang": "cs", "target_lang": "en", "backend": "ctranslate2"}


def test_translations_output_validates_against_schema(amcr_xml_file, tmp_path, mock_translator, mock_paradata):
    jsonschema = pytest.importorskip("jsonschema")
    from utils import process_metadata_xml

    run_id, paradata_ref = mock_paradata
    out_xml = tmp_path / "out.xml"

    with DocumentRecord.open(
        doc_id="CTX03", program="translator", baseline=None, run_id=run_id, paradata_ref=paradata_ref
    ) as doc:
        process_metadata_xml(
            amcr_xml_file,
            out_xml,
            ["//amcr:amcr/amcr:dokument/amcr:popis"],
            mock_translator,
            "cs",
            "en",
            doc=doc,
        )
        doc.finalize(str(tmp_path / "CTX03.document.json"))

    result = json.loads((tmp_path / "CTX03.document.json").read_text(encoding="utf-8"))

    schema_path = Path(__file__).resolve().parent.parent / "atrium_document.schema.json"
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    jsonschema.Draft202012Validator(schema).validate(result)
