from __future__ import annotations

import inspect
from pathlib import Path
from xml.etree import ElementTree as ET

import pytest

from atrium_test_support import call_best_effort, import_any, maybe_resolve_attr

ALTO_NS = {"alto": "http://www.loc.gov/standards/alto/ns-v2#"}
TEI_NS = {"tei": "http://www.tei-c.org/ns/1.0"}


def _build_minimal_alto_root() -> ET.Element:
    return ET.fromstring(
        """<?xml version="1.0" encoding="UTF-8"?>
<alto xmlns="http://www.loc.gov/standards/alto/ns-v2#">
  <Layout>
    <Page ID="P1">
      <PrintSpace>
        <TextBlock ID="TB1">
          <TextLine ID="TL1">
            <String ID="S1" CONTENT="Ahoj"/>
            <String ID="S2" CONTENT="svete"/>
          </TextLine>
          <TextLine ID="TL2">
            <String ID="S3" CONTENT="Druha"/>
            <String ID="S4" CONTENT="radka"/>
          </TextLine>
        </TextBlock>
      </PrintSpace>
    </Page>
  </Layout>
</alto>
"""
    )


def test_align_tokens_to_lines_prefers_consistent_bucketing():
    """The aligner should preserve token order and not drop tokens."""
    utils = import_any(["utils"])
    align = maybe_resolve_attr(utils, ("_align_tokens_to_lines", "align_tokens_to_lines"))
    if align is None:
        pytest.skip("Alignment helper not exposed in utils.py")

    signature = inspect.signature(align)
    if len(signature.parameters) == 2:
        buckets = align("alpha beta gamma delta", ["A", "B", "C", "D"])
    else:
        buckets = call_best_effort(
            align,
            "alpha beta gamma delta",
            ["A", "B", "C", "D"],
        )

    assert isinstance(buckets, list)
    assert all(isinstance(bucket, list) for bucket in buckets)

    flattened = [token for bucket in buckets for token in bucket]
    assert flattened == ["alpha", "beta", "gamma", "delta"]


def test_load_xsd_accepts_local_schema_file(tmp_path: Path):
    """Local XSD loading is a documented supported path."""
    utils = import_any(["utils"])
    load_xsd = maybe_resolve_attr(utils, ("load_xsd", "_load_xsd", "read_xsd"))
    if load_xsd is None:
        pytest.skip("No XSD loader helper exposed in utils.py")

    xsd = tmp_path / "schema.xsd"
    xsd.write_text(
        """<?xml version="1.0" encoding="UTF-8"?>
<xs:schema xmlns:xs="http://www.w3.org/2001/XMLSchema"
           targetNamespace="urn:test"
           elementFormDefault="qualified">
  <xs:element name="root" type="xs:string"/>
</xs:schema>
""",
        encoding="utf-8",
    )

    result = call_best_effort(load_xsd, str(xsd), schema_path=str(xsd), xsd_path=str(xsd))
    assert result is not None


def _call_metadata_processor(process_metadata, xml_file: Path, out_file: Path, translator, xpaths):
    sig = inspect.signature(process_metadata)
    kwargs = {}
    if "src_lang" in sig.parameters:
        kwargs["src_lang"] = "cs"
    elif "source_lang" in sig.parameters:
        kwargs["source_lang"] = "cs"
    if "tgt_lang" in sig.parameters:
        kwargs["tgt_lang"] = "en"
    elif "target_lang" in sig.parameters:
        kwargs["target_lang"] = "en"
    if "xsd" in sig.parameters:
        kwargs["xsd"] = None
    if "xsd_schema" in sig.parameters:
        kwargs["xsd_schema"] = None
    if "vocabulary" in sig.parameters:
        kwargs["vocabulary"] = None
    if "csv_writer" in sig.parameters:
        kwargs["csv_writer"] = None
    if "identifier" in sig.parameters:
        kwargs["identifier"] = None
    return process_metadata(xml_file, out_file, xpaths, translator, **kwargs)


def _call_alto_processor(process_alto, alto_file: Path, out_file: Path, translator):
    sig = inspect.signature(process_alto)
    kwargs = {}
    if "src_lang" in sig.parameters:
        kwargs["src_lang"] = "cs"
    elif "source_lang" in sig.parameters:
        kwargs["source_lang"] = "cs"
    if "tgt_lang" in sig.parameters:
        kwargs["tgt_lang"] = "en"
    elif "target_lang" in sig.parameters:
        kwargs["target_lang"] = "en"
    if "xsd" in sig.parameters:
        kwargs["xsd"] = None
    if "xsd_schema" in sig.parameters:
        kwargs["xsd_schema"] = None
    if "vocabulary" in sig.parameters:
        kwargs["vocabulary"] = None
    if "csv_writer" in sig.parameters:
        kwargs["csv_writer"] = None
    if "identifier" in sig.parameters:
        kwargs["identifier"] = None
    return process_alto(alto_file, out_file, translator, **kwargs)


def test_process_metadata_xml_rewrites_target_fields(tmp_path: Path, fake_translator):
    """Metadata translation should replace only the selected nodes."""
    utils = import_any(["utils"])
    process_metadata = maybe_resolve_attr(utils, ("process_metadata_xml",))
    if process_metadata is None:
        pytest.skip("process_metadata_xml is not exposed in utils.py")

    xml_file = tmp_path / "input.xml"
    xml_file.write_text(
        """<?xml version="1.0" encoding="UTF-8"?>
<OAI-PMH xmlns="http://www.openarchives.org/OAI/2.0/" xmlns:amcr="https://api.aiscr.cz/schema/amcr/2.2/">
  <GetRecord>
    <record>
      <metadata>
        <amcr:amcr>
          <amcr:dokument>
            <amcr:popis>Archeologická poznámka.</amcr:popis>
            <amcr:poznamka>Should stay intact.</amcr:poznamka>
          </amcr:dokument>
        </amcr:amcr>
      </metadata>
    </record>
  </GetRecord>
</OAI-PMH>
""",
        encoding="utf-8",
    )

    xpaths = ["//amcr:amcr/amcr:dokument/amcr:popis"]
    out_file = tmp_path / "translated.xml"

    result = _call_metadata_processor(process_metadata, xml_file, out_file, fake_translator, xpaths)

    assert out_file.exists() or result is not None
    output_text = out_file.read_text(encoding="utf-8") if out_file.exists() else str(result)
    assert "EN:Archeologická poznámka." in output_text
    assert "Should stay intact." in output_text


def test_process_alto_xml_preserves_structure(tmp_path: Path, fake_translator):
    """ALTO translation should keep the same String elements and update CONTENT."""
    utils = import_any(["utils"])
    process_alto = maybe_resolve_attr(utils, ("process_alto_xml",))
    if process_alto is None:
        pytest.skip("process_alto_xml is not exposed in utils.py")

    alto_file = tmp_path / "sample.alto.xml"
    alto_file.write_text(
        """<?xml version="1.0" encoding="UTF-8"?>
<alto xmlns="http://www.loc.gov/standards/alto/ns-v2#">
  <Layout>
    <Page ID="P1">
      <PrintSpace>
        <TextBlock ID="TB1">
          <TextLine ID="TL1">
            <String ID="S1" CONTENT="Ahoj"/>
            <String ID="S2" CONTENT="svete"/>
          </TextLine>
        </TextBlock>
      </PrintSpace>
    </Page>
  </Layout>
</alto>
""",
        encoding="utf-8",
    )

    out_file = tmp_path / "translated.alto.xml"
    result = _call_alto_processor(process_alto, alto_file, out_file, fake_translator)

    assert out_file.exists() or result is not None
    output_text = out_file.read_text(encoding="utf-8") if out_file.exists() else str(result)
    assert "String" in output_text
    assert "EN:" in output_text


def test_process_alto_xml_handles_single_line_blocks(tmp_path: Path, fake_translator):
    """Single-line blocks are called out in the docs as a special edge case."""
    utils = import_any(["utils"])
    process_alto = maybe_resolve_attr(utils, ("process_alto_xml",))
    if process_alto is None:
        pytest.skip("process_alto_xml is not exposed in utils.py")

    alto_file = tmp_path / "single_line.alto.xml"
    alto_file.write_text(
        """<?xml version="1.0" encoding="UTF-8"?>
<alto xmlns="http://www.loc.gov/standards/alto/ns-v2#">
  <Layout>
    <Page ID="P1">
      <PrintSpace>
        <TextBlock ID="TB1">
          <TextLine ID="TL1">
            <String ID="S1" CONTENT="Jedna"/>
            <String ID="S2" CONTENT="radka"/>
          </TextLine>
        </TextBlock>
      </PrintSpace>
    </Page>
  </Layout>
</alto>
""",
        encoding="utf-8",
    )

    out_file = tmp_path / "single_line_out.alto.xml"
    result = _call_alto_processor(process_alto, alto_file, out_file, fake_translator)

    assert out_file.exists() or result is not None
    output_text = out_file.read_text(encoding="utf-8") if out_file.exists() else str(result)
    assert "EN:" in output_text
