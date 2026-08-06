"""
tests/test_api.py
Automated TestClient coverage for the FastAPI service and DoS guards.
"""

import json
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

from service.api import MAX_UPLOAD_BYTES, app

client = TestClient(app)

MULTI_DOT_DOC_ID = "CTX000000001.v2"

_ALTO_XML = b"""<?xml version="1.0" encoding="UTF-8"?>
<alto xmlns="http://www.loc.gov/standards/alto/ns-v2#">
  <Layout>
    <Page ID="P1" PHYSICAL_IMG_NR="1" WIDTH="1000" HEIGHT="1000">
      <PrintSpace>
        <TextBlock ID="TB1">
          <TextLine ID="L1">
            <String ID="S1" CONTENT="Dobr\xc3\xbd"/>
            <String ID="S2" CONTENT="den"/>
          </TextLine>
        </TextBlock>
      </PrintSpace>
    </Page>
  </Layout>
</alto>
"""


def _json_part(body: bytes) -> dict:
    """Extract the document-record part of the multipart/mixed /translate response."""
    tail = body.split(b"Content-Type: application/json", 1)[1]
    return json.loads(tail[tail.index(b"{") : tail.rindex(b"}") + 1])


def test_info_endpoint():
    response = client.get("/info")
    assert response.status_code == 200
    assert "ALTO XML" in response.json()["supported_formats"]


def test_translate_rejects_non_xml():
    response = client.post(
        "/translate", files={"file": ("test.txt", b"dummy content", "text/plain")}, data={"is_alto": "true"}
    )
    # §4.4: unusable/invalid input is 422 (harmonized from 400).
    assert response.status_code == 422
    assert "Only XML files" in response.json()["detail"]


def test_translate_upload_size_limit():
    oversized_content = b"x" * (MAX_UPLOAD_BYTES + 1)
    response = client.post(
        "/translate", files={"file": ("large.alto.xml", oversized_content, "application/xml")}, data={"is_alto": "true"}
    )
    assert response.status_code == 413
    assert "File too large" in response.json()["detail"]


@patch("service.api.process_single_file")
@patch("service.api.ParadataLogger.log_component")
def test_translate_logs_components(mock_log_component, mock_process_single_file):
    """Component logging must fire on a successful API translation (M1)."""

    def _write_and_succeed(file_path=None, output_file=None, **kwargs):
        if output_file is not None:
            output_file.write_bytes(b"<alto/>")
        return True, 0

    mock_process_single_file.side_effect = _write_and_succeed

    fake_translator = MagicMock()
    fake_translator.name = "lindat"
    fake_translator.vocabulary = {}
    fake_translator.license_components.return_value = ["lindat_cubbitt"]

    fake_models = {"translator": fake_translator, "identifier": MagicMock()}

    with patch("service.api.models", fake_models):
        valid_xml_content = b"<alto></alto>"
        response = client.post(
            "/translate?source_lang=auto",
            files={"file": ("test.alto.xml", valid_xml_content, "application/xml")},
            data={"is_alto": "true"},
        )

    assert response.status_code == 200
    # fasttext is always logged when source_lang == "auto"
    mock_log_component.assert_any_call("fasttext")
    # At least one backend component must also have been logged
    assert mock_log_component.call_count >= 2, "backend license components should also be logged"


@patch("service.api.process_single_file")
def test_translate_happy_path(mock_process_single_file):
    """Full upload-to-response round-trip verifying HTTP headers and payload."""

    def fake_process(file_path=None, output_file=None, **kwargs):
        if output_file is not None:
            output_file.write_bytes(b"<alto><String CONTENT='translated'/></alto>")
        return True, 0

    mock_process_single_file.side_effect = fake_process

    fake_translator = MagicMock()
    fake_translator.name = "lindat"
    fake_translator.vocabulary = {}
    fake_translator.license_components.return_value = ["lindat_cubbitt"]

    fake_models = {"translator": fake_translator, "identifier": MagicMock()}

    with patch("service.api.models", fake_models):
        valid_xml_content = b"<alto><String CONTENT='original'/></alto>"
        response = client.post(
            "/translate?source_lang=cs&target_lang=en",
            files={"file": ("test.alto.xml", valid_xml_content, "application/xml")},
            data={"is_alto": "true"},
        )

    assert response.status_code == 200
    assert "application/xml" in response.headers["content-type"]
    assert 'attachment; filename="test_en.alto.xml"' in response.headers["content-disposition"]
    assert b"translated" in response.content


def test_translate_real_pipeline_keeps_the_multi_dot_doc_id():
    """
    D3 (atrium-project#10) at the service boundary, driven through the REAL
    process_single_file — every other test in this file mocks it, which is why two defects
    lived here unseen:

    * `f"{file.filename.split('.')[0]}.document.json"` truncated the doc_id at the FIRST dot,
      so an upload named `CTX000000001.v2.alto.xml` was answered with a record the client
      filed under `CTX000000001` while the record inside said `CTX000000001.v2`;
    * the args Namespace carried no `backend`, so `args.backend` raised AttributeError inside
      process_single_file's catch-all and the endpoint answered 500 to every real upload.

    Both are invisible to a test that mocks the very function under test — the same
    structural blindness the review pass recorded as J1 in the alto service.
    """
    baseline = json.dumps(
        {
            "schema_version": "1.0",
            "record_type": "atrium-document",
            "doc_id": MULTI_DOT_DOC_ID,
            "pages": [{"page": "1", "quality_score": 0.98}],
        }
    ).encode()

    fake_translator = MagicMock()
    fake_translator.name = "lindat"
    fake_translator.vocabulary = {}
    fake_translator.protected_count = 0
    fake_translator.translate.side_effect = lambda text, *a, **k: f"EN:{text}"
    fake_translator.license_components.return_value = ["lindat_cubbitt"]

    with patch("service.api.models", {"translator": fake_translator, "identifier": MagicMock()}):
        response = client.post(
            "/translate?source_lang=cs&target_lang=en",
            files={
                "file": (f"{MULTI_DOT_DOC_ID}.alto.xml", _ALTO_XML, "application/xml"),
                "document_json": (f"{MULTI_DOT_DOC_ID}.document.json", baseline, "application/json"),
            },
            data={"is_alto": "true"},
        )

    assert response.status_code == 200, response.content[:400]
    assert "multipart/mixed" in response.headers["content-type"]
    assert f'filename="{MULTI_DOT_DOC_ID}.document.json"'.encode() in response.content

    record = _json_part(response.content)
    assert record["doc_id"] == MULTI_DOT_DOC_ID
    assert record["pages"][0]["quality_score"] == 0.98  # baseline accreted, not orphaned
    assert record["translations"] == {"source_lang": "cs", "target_lang": "en", "backend": "lindat"}
