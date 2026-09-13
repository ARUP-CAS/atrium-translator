"""
tests/test_upload_limits.py — the upload limit must be enforced DURING the read.

`/translate` used to decide whether an upload was too large like this::

    content = await file.read()
    if len(content) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, ...)

which answers the question only once the whole upload is resident in memory. The
413 was therefore unreachable for exactly the inputs it existed to refuse: an
unauthenticated caller could OOM-kill the container before the check ran, while
README.md advertised "full DoS guards and file-size constraints".

`tests/test_api.py::test_translate_upload_size_limit` passed against that code
and still does, because a 413 comes back either way — the status code is not the
property that was broken. These tests assert the property that was: that the
reader STOPS, and that a declared oversize envelope is refused before the body is
touched at all.
"""

import asyncio

import pytest
from fastapi import HTTPException

from service.api import (
    _UPLOAD_CHUNK_BYTES,
    MAX_REQUEST_BYTES,
    MAX_UPLOAD_BYTES,
    _read_bounded,
    _reject_oversized_envelope,
)


class _EndlessUpload:
    """An upload that never ends, counting what a reader actually consumed."""

    def __init__(self, chunk_bytes: int = _UPLOAD_CHUNK_BYTES):
        self.served = 0
        self._chunk = b"x" * chunk_bytes

    async def read(self, size: int = -1) -> bytes:
        chunk = self._chunk if size < 0 else self._chunk[:size]
        self.served += len(chunk)
        return chunk


class _FiniteUpload:
    def __init__(self, payload: bytes):
        self._buf = payload
        self._pos = 0

    async def read(self, size: int = -1) -> bytes:
        if size < 0:
            size = len(self._buf) - self._pos
        chunk = self._buf[self._pos : self._pos + size]
        self._pos += len(chunk)
        return chunk


class _Req:
    def __init__(self, **headers):
        self.headers = headers


def test_read_bounded_stops_instead_of_consuming_everything():
    """The reader must refuse mid-stream, not after buffering the whole upload."""
    upload = _EndlessUpload()

    with pytest.raises(HTTPException) as excinfo:
        asyncio.run(_read_bounded(upload, MAX_UPLOAD_BYTES, "File"))

    assert excinfo.value.status_code == 413
    # It may overshoot by at most the chunk that crossed the limit — never more.
    assert upload.served <= MAX_UPLOAD_BYTES + _UPLOAD_CHUNK_BYTES


def test_read_bounded_returns_content_under_the_limit():
    payload = b"<alto/>" * 100
    assert asyncio.run(_read_bounded(_FiniteUpload(payload), MAX_UPLOAD_BYTES, "File")) == payload


def test_read_bounded_accepts_exactly_the_limit():
    payload = b"y" * 2048
    assert asyncio.run(_read_bounded(_FiniteUpload(payload), 2048, "File")) == payload


def test_read_bounded_refuses_one_byte_over():
    with pytest.raises(HTTPException) as excinfo:
        asyncio.run(_read_bounded(_FiniteUpload(b"y" * 2049), 2048, "File"))
    assert excinfo.value.status_code == 413


def test_oversized_declared_envelope_is_refused():
    with pytest.raises(HTTPException) as excinfo:
        _reject_oversized_envelope(_Req(**{"content-length": str(MAX_REQUEST_BYTES + 1)}))
    assert excinfo.value.status_code == 413


def test_plausible_envelope_is_allowed_through():
    """Two parts at the limit plus multipart overhead is legitimate, not an attack."""
    _reject_oversized_envelope(_Req(**{"content-length": str(2 * MAX_UPLOAD_BYTES)}))


def test_absent_or_unparseable_content_length_is_not_fatal():
    """A missing or junk length is a hint that is absent, not a request to refuse."""
    _reject_oversized_envelope(_Req())
    _reject_oversized_envelope(_Req(**{"content-length": "not-a-number"}))
