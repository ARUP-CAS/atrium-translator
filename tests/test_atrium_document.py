"""
tests/test_atrium_document.py

Tests the ATRIUM Document Schema & Accretion Policy ("paradata pair" model)
contract (six rules) for the translator integration.
"""

import json

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
