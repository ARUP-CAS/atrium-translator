"""
tests/integration/stub_lindat.py — a local stand-in for the LINDAT services.

Every `/translate` test in this repo mocks `process_single_file`, which is how
`service/api.py` shipped omitting `backend` from its arguments and returned HTTP
500 on every real upload while the suite stayed green at an 81% ratchet. The
workflow that was supposed to catch it says so itself
(`.github/workflows/scheduled-smoke.yml`): *"What it does NOT cover: a live
LINDAT backend. ... That gap needs an integration lane with a reachable backend,
not a marker."*

This is that reachable backend, in-process and offline.

**Why a stub rather than the real LINDAT service.** The defect class is "the real
call path is never executed end to end", and a stub exercises exactly that path:
the same `LindatTranslator`, the same chunking, the same Tag-and-Protect
placeholder round-trip, the same XML reconstruction, the same paradata write. It
adds no network flakiness, no rate limits, and no load on a shared public
research service that this project does not own. `TRANSLATION_URL` and
`UDPIPE_URL` became attachable in atrium-project#63 precisely so an endpoint can
be substituted without touching code, so pointing them here is a supported
configuration rather than a test-only hack.

What a stub cannot prove is that LINDAT's own contract still holds — if CUBBITT
changes its response shape, this lane stays green. That is what the opt-in
`live-backend` job in `.github/workflows/integration.yml` is for, run by hand
before a release against the real hosts.

The translation applied is deliberately visible (`[cs>en] …`, words reversed) so
a test can assert the output really came through this path and is not the source
text copied by a fallback.
"""

from __future__ import annotations

import json
import re
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

# Language pairs the stub advertises from GET /models.
SUPPORTED_MODELS = ["cs-en", "de-en", "fr-en", "pl-en", "ru-en", "uk-en"]

# Suffix appended to every token, so a test can prove the text in the returned
# ALTO came through this path and is not the source copied by some fallback.
#
# A per-token suffix rather than a per-line prefix, and the difference is not
# cosmetic: the ALTO reconstruction redistributes translated tokens back onto the
# original String geometry, so a marker that adds one token per line shifts every
# String after it and empties the last one. The first version of this stub did
# exactly that and produced a document with a blank CONTENT attribute -- a stub
# artefact that looked like a reconstruction bug. TOKEN COUNT AND LINE COUNT ARE
# BOTH LOAD-BEARING here; a stub that changes either is testing its own
# distortion rather than the pipeline.
TOKEN_SUFFIX = "~mt"


def translate_text(text: str, src: str, tgt: str) -> str:
    """Suffix every token, preserving line count, token count AND token order.

    All three are load-bearing, and the third was learned the hard way. An earlier
    version of this stub reversed each line's word order to make the
    transformation obvious. Token counts matched, yet documents came back with
    text piled into the first line and later String elements blank -- which looks
    exactly like a reconstruction bug and is not one. The ALTO realignment maps
    translated tokens onto the original String geometry using similarity AND
    position, so reversing word order is adversarial input no real translation
    engine produces: cs->en reorders locally, it does not mirror a line.

    A stub must be unrealistic only in ways that do not matter. This one changes
    the text visibly (every token is marked) while leaving the structure a real
    backend would leave, so what the lane exercises is the pipeline rather than
    the pipeline's response to a distortion the stub invented.
    """
    out = []
    for line in text.split("\n"):
        if not line.strip():
            out.append(line)
            continue
        out.append(" ".join(f"{word}{TOKEN_SUFFIX}" for word in line.split()))
    return "\n".join(out)


def _conllu_for(chunk: str) -> str:
    """A minimal CoNLL-U parse: every token is its own lemma, tagged NOUN."""
    lines = []
    for sentence_index, sentence in enumerate(chunk.split("\n"), 1):
        tokens = [t for t in re.split(r"\s+", sentence) if t]
        if not tokens:
            continue
        lines.append(f"# sent_id = {sentence_index}")
        lines.append(f"# text = {sentence}")
        for i, token in enumerate(tokens, 1):
            bare = token.strip(".,;:!?()[]\"'")
            lemma = (bare or token).lower()
            lines.append(f"{i}\t{token}\t{lemma}\tNOUN\t_\tNumber=Sing\t0\troot\t_\t_")
        lines.append("")
    return "\n".join(lines)


class _Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):  # noqa: A002 - silence the default stderr spam
        pass

    def _send(self, status: int, body: str, content_type: str = "text/plain; charset=utf-8") -> None:
        payload = body.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    # ── GET /models — the model catalogue LindatTranslator fetches at init ──
    def do_GET(self):  # noqa: N802 - BaseHTTPRequestHandler's interface
        path = urlparse(self.path).path
        self.server.calls.append(("GET", path))

        if path.rstrip("/").endswith("/models"):
            body = {"_embedded": {"item": [{"model": name} for name in SUPPORTED_MODELS]}}
            self._send(200, json.dumps(body), "application/json")
            return
        self._send(404, "not found")

    def do_POST(self):  # noqa: N802
        parsed = urlparse(self.path)
        length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(length).decode("utf-8")
        form = {k: v[0] for k, v in parse_qs(raw, keep_blank_values=True).items()}
        self.server.calls.append(("POST", parsed.path))

        # ── UDPipe: POST / with model/tokenizer/tagger/parser/data ──
        if "data" in form and "model" in form:
            self._send(200, json.dumps({"result": _conllu_for(form["data"])}), "application/json")
            return

        # ── Translation: POST /models/<pair>?src=..&tgt=.. with input_text ──
        match = re.search(r"/models/([a-z]{2})-([a-z]{2})$", parsed.path)
        if match and "input_text" in form:
            query = parse_qs(parsed.query)
            src = query.get("src", [match.group(1)])[0]
            tgt = query.get("tgt", [match.group(2)])[0]
            self._send(200, translate_text(form["input_text"], src, tgt))
            return

        self._send(400, f"stub received an unrecognised request: {parsed.path} {sorted(form)}")


class StubLindat:
    """Context manager running the stub on an ephemeral port.

    Usage::

        with StubLindat() as stub:
            os.environ["TRANSLATION_URL"] = stub.translation_url
            os.environ["UDPIPE_URL"] = stub.udpipe_url
    """

    def __init__(self) -> None:
        self._server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
        self._server.calls = []
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)

    @property
    def base_url(self) -> str:
        host, port = self._server.server_address[:2]
        return f"http://{host}:{port}"

    @property
    def translation_url(self) -> str:
        """What TRANSLATION_URL should be set to (LINDAT's v2 base)."""
        return self.base_url

    @property
    def udpipe_url(self) -> str:
        """What UDPIPE_URL should be set to (a single POST endpoint)."""
        return f"{self.base_url}/udpipe"

    @property
    def calls(self) -> list[tuple[str, str]]:
        """(method, path) of everything the stub was actually asked for."""
        return list(self._server.calls)

    def __enter__(self) -> StubLindat:
        self._thread.start()
        return self

    def __exit__(self, *exc) -> None:
        self._server.shutdown()
        self._server.server_close()
        self._thread.join(timeout=5)
