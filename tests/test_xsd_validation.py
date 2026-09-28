"""tests/test_xsd_validation.py — `--xsd` against a real-world record schema (issue #46).

Two defects kept `--xsd https://api.aiscr.cz/schema/amcr/2.2/amcr.xsd` from ever
answering the #46 `maxOccurs` question:

* **The schema could not be loaded.** AMCR 2.2 imports the XML namespace's schema from
  `http://www.w3.org/2001/03/xml.xsd` (for `xml:lang`). lxml 6 bundles libxml2 2.14,
  which has no HTTP client, so the import failed and `main()` aborted with "XSD schema
  load failed" in every environment. Imports are now resolved in Python.
* **The envelope was validated, not the record.** Harvested AMCR records arrive inside
  an OAI-PMH envelope; the schema declares `amcr` as its root, so every file — even an
  untouched source — failed at the root. The record inside is validated now.

With both fixed, the published schema accepts the shipped records as source and as
`replace` output and rejects them as `append` output (`xml:lang` is not declared on the
free-text fields, and the repeated element is not allowed there) — which is why append
mode on AMCR records now warns. Everything here is hermetic: small local schemas, no
network.
"""

import csv
import io
import logging

import pytest
from lxml import etree

import utils
from utils import OUTPUT_MODE_APPEND, OUTPUT_MODE_REPLACE, load_xsd, process_metadata_xml, validate_xml_with_xsd

_RECORD_SCHEMA = """<?xml version="1.0"?>
<xs:schema xmlns:xs="http://www.w3.org/2001/XMLSchema" xmlns:r="urn:rec" targetNamespace="urn:rec"
           elementFormDefault="qualified">
  <xs:import namespace="http://www.w3.org/XML/1998/namespace" schemaLocation="http://www.w3.org/2001/03/xml.xsd"/>
  <xs:element name="rec">
    <xs:complexType>
      <xs:sequence>
        <xs:element name="title" type="xs:string"/>
        <xs:element name="term" minOccurs="0">
          <xs:complexType>
            <xs:simpleContent>
              <xs:extension base="xs:string">
                <xs:attribute ref="xml:lang" use="required"/>
              </xs:extension>
            </xs:simpleContent>
          </xs:complexType>
        </xs:element>
      </xs:sequence>
    </xs:complexType>
  </xs:element>
</xs:schema>
"""

_OAI = "http://www.openarchives.org/OAI/2.0/"


def _in_envelope(record: str) -> etree._ElementTree:
    return etree.ElementTree(
        etree.fromstring(
            f'<OAI-PMH xmlns="{_OAI}"><GetRecord><record><header/><metadata>{record}</metadata></record>'
            "</GetRecord></OAI-PMH>"
        )
    )


_VALID = '<rec xmlns="urn:rec"><title>Davle</title><term xml:lang="cs">kostel</term></rec>'
_APPENDED = (
    '<rec xmlns="urn:rec"><title xml:lang="cs">Davle</title><title xml:lang="en">Davle</title>'
    '<term xml:lang="cs">kostel</term></rec>'
)


@pytest.fixture
def no_network(monkeypatch):
    def _refuse(url):
        raise AssertionError(f"unexpected network fetch: {url}")

    monkeypatch.setattr(utils, "_fetch", _refuse)


@pytest.fixture
def schema(tmp_path, no_network):
    path = tmp_path / "rec.xsd"
    path.write_text(_RECORD_SCHEMA, encoding="utf-8")
    return load_xsd(str(path))


# ── loading ──────────────────────────────────────────────────────────────────


def test_a_schema_importing_the_xml_namespace_over_http_compiles_offline(schema):
    """The import that made AMCR 2.2 unloadable is served locally, without a fetch."""
    assert isinstance(schema, etree.XMLSchema)


def test_other_http_imports_are_fetched_through_urllib(tmp_path, monkeypatch):
    fetched = []
    other = b"""<xs:schema xmlns:xs="http://www.w3.org/2001/XMLSchema" targetNamespace="urn:other">
                  <xs:element name="note" type="xs:string"/></xs:schema>"""

    def _fetch(url):
        fetched.append(url)
        return other

    monkeypatch.setattr(utils, "_fetch", _fetch)
    path = tmp_path / "main.xsd"
    path.write_text(
        """<xs:schema xmlns:xs="http://www.w3.org/2001/XMLSchema" targetNamespace="urn:main">
             <xs:import namespace="urn:other" schemaLocation="https://example.org/other.xsd"/>
             <xs:element name="main" type="xs:string"/></xs:schema>""",
        encoding="utf-8",
    )
    load_xsd(str(path))
    assert fetched == ["https://example.org/other.xsd"]


# ── what gets validated ──────────────────────────────────────────────────────


def test_a_record_inside_an_oai_pmh_envelope_is_validated_not_the_envelope(schema):
    valid, log = validate_xml_with_xsd(_in_envelope(_VALID), schema)
    assert valid, log


def test_an_appended_record_fails_on_both_halves_of_the_pair(schema):
    valid, log = validate_xml_with_xsd(_in_envelope(_APPENDED), schema)
    assert not valid
    assert "lang" in log and "is not allowed" in log, "xml:lang on an element that does not declare it"
    assert "This element is not expected" in log, "the repeated element"


def test_a_bare_document_is_validated_as_before(schema):
    assert validate_xml_with_xsd(etree.ElementTree(etree.fromstring(_VALID)), schema)[0]
    assert not validate_xml_with_xsd(etree.ElementTree(etree.fromstring(_APPENDED)), schema)[0]


# ── append mode on AMCR records warns ────────────────────────────────────────

_AMCR = """<?xml version="1.0" encoding="utf-8"?>
<amcr:amcr xmlns:amcr="https://api.aiscr.cz/schema/amcr/2.2/"><amcr:nazev>Davle</amcr:nazev></amcr:amcr>
"""
_OTHER = """<?xml version="1.0" encoding="utf-8"?>
<doc><nazev>Davle</nazev></doc>
"""


class _Translator:
    name = "lindat"
    vocabulary: dict = {}
    protected_count = 0

    def reset_protected_count(self):
        pass

    def translate(self, text, src_lang, tgt_lang="en"):
        return "\n".join(f"EN {line}" for line in text.split("\n"))


def _run(tmp_path, document, xpath, mode):
    src = tmp_path / "rec.xml"
    src.write_text(document, encoding="utf-8")
    process_metadata_xml(
        src,
        tmp_path / "rec_en.xml",
        [xpath],
        _Translator(),
        "cs",
        "en",
        csv_writer=csv.writer(io.StringIO()),
        output_mode=mode,
    )


@pytest.fixture
def fresh_latch(monkeypatch):
    monkeypatch.setattr(utils, "_AMCR_APPEND_WARNED", False)


def test_append_on_an_amcr_record_warns_once(tmp_path, fresh_latch, caplog):
    with caplog.at_level(logging.WARNING, logger="utils"):
        _run(tmp_path, _AMCR, "//amcr:amcr/amcr:nazev", OUTPUT_MODE_APPEND)
        _run(tmp_path, _AMCR, "//amcr:amcr/amcr:nazev", OUTPUT_MODE_APPEND)
    warnings = [r for r in caplog.records if "does NOT validate against the AMCR 2.2 schema" in r.getMessage()]
    assert len(warnings) == 1


@pytest.mark.parametrize(
    ("document", "xpath", "mode"),
    [(_AMCR, "//amcr:amcr/amcr:nazev", OUTPUT_MODE_REPLACE), (_OTHER, "//nazev", OUTPUT_MODE_APPEND)],
    ids=["amcr-replace", "non-amcr-append"],
)
def test_no_warning_for_replace_or_for_other_documents(tmp_path, fresh_latch, caplog, document, xpath, mode):
    with caplog.at_level(logging.WARNING, logger="utils"):
        _run(tmp_path, document, xpath, mode)
    assert "AMCR 2.2 schema" not in caplog.text


# ──────────────────────────────────────────────────────────────────────────────
# The verdict is returned, summarised once per run and kept in the paradata
# ──────────────────────────────────────────────────────────────────────────────

_AMCR_SCHEMA = """<?xml version="1.0"?>
<xs:schema xmlns:xs="http://www.w3.org/2001/XMLSchema" xmlns:amcr="https://api.aiscr.cz/schema/amcr/2.2/"
           targetNamespace="https://api.aiscr.cz/schema/amcr/2.2/" elementFormDefault="qualified">
  <xs:element name="amcr">
    <xs:complexType><xs:sequence>
      <xs:element name="nazev" type="xs:string"/>
      {extra}
    </xs:sequence></xs:complexType>
  </xs:element>
</xs:schema>
"""


def _amcr_schema(tmp_path, *, valid):
    path = tmp_path / ("ok.xsd" if valid else "strict.xsd")
    extra = "" if valid else '<xs:element name="popis" type="xs:string"/>'  # the record has no popis
    path.write_text(_AMCR_SCHEMA.replace("{extra}", extra), encoding="utf-8")
    return path


@pytest.mark.parametrize(("valid", "expected"), [(True, True), (False, False)])
def test_process_metadata_xml_returns_the_verdict(tmp_path, valid, expected):
    src = tmp_path / "rec.xml"
    src.write_text(_AMCR, encoding="utf-8")
    verdict = process_metadata_xml(
        src,
        tmp_path / "rec_en.xml",
        ["//amcr:amcr/amcr:nazev"],
        _Translator(),
        "cs",
        "en",
        xsd_schema=load_xsd(str(_amcr_schema(tmp_path, valid=valid))),
        csv_writer=csv.writer(io.StringIO()),
    )
    assert verdict is expected
    assert (tmp_path / "rec_en.xml").exists()  # written either way


def test_without_a_schema_there_is_no_verdict(tmp_path):
    src = tmp_path / "rec.xml"
    src.write_text(_AMCR, encoding="utf-8")
    assert process_metadata_xml(src, tmp_path / "o.xml", ["//amcr:amcr/amcr:nazev"], _Translator(), "cs", "en") is None


def _main_run(tmp_path, monkeypatch, *extra, valid):
    import json

    import main as main_module

    monkeypatch.chdir(tmp_path)
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "C-N1000019.xml").write_text(_AMCR, encoding="utf-8")
    (tmp_path / "fields.txt").write_text("//amcr:amcr/amcr:nazev\n", encoding="utf-8")
    schema = _amcr_schema(tmp_path, valid=valid)
    monkeypatch.setattr(main_module, "get_backend", lambda *a, **k: _Translator())
    argv = ["main.py", "docs", "--xpaths", "fields.txt", "--source_lang", "cs", "--xsd", str(schema), "-o", "out"]
    monkeypatch.setattr("sys.argv", [*argv, *extra])
    code = main_module.main()
    record = json.loads(next((tmp_path / "out" / "paradata").glob("*_translator.json")).read_text(encoding="utf-8"))
    return code, record["config"].get("xsd_validation")


def test_a_valid_run_is_summarised_and_recorded(tmp_path, monkeypatch, capsys):
    code, verdict = _main_run(tmp_path, monkeypatch, valid=True)
    assert code == 0
    assert verdict == {"valid": 1, "invalid": [], "strict": False}
    assert "XSD: 1/1 record(s) valid." in capsys.readouterr().out


def test_an_invalid_record_is_a_warning_by_default(tmp_path, monkeypatch, capsys):
    monkeypatch.delenv("XSD_STRICT", raising=False)
    code, verdict = _main_run(tmp_path, monkeypatch, valid=False)
    assert code == 0
    assert verdict == {"valid": 0, "invalid": ["C-N1000019"], "strict": False}
    assert "XSD: 0/1 record(s) valid; invalid: C-N1000019." in capsys.readouterr().out


@pytest.mark.parametrize("how", ["flag", "env"])
def test_xsd_strict_makes_an_invalid_record_a_failed_document(tmp_path, monkeypatch, how):
    from main import EXIT_FAILED

    extra = ("--xsd-strict",) if how == "flag" else ()
    if how == "env":
        monkeypatch.setenv("XSD_STRICT", "1")
    code, verdict = _main_run(tmp_path, monkeypatch, *extra, valid=False)
    assert code == EXIT_FAILED
    assert verdict["strict"] is True
    assert (tmp_path / "out" / "C-N1000019_en.xml").exists()  # the XML is still written
