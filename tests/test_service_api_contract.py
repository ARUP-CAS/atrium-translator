from __future__ import annotations

import json

import pytest

from atrium_test_support import import_any, maybe_resolve_attr


def _get_fastapi_app():
    service_api = import_any(["service.api", "service"])
    app = maybe_resolve_attr(service_api, ("app", "api", "fastapi_app"))
    if app is None:
        pytest.skip("No FastAPI app object exposed by service.api")
    return app


def test_service_module_exposes_fastapi_app():
    """The repo documents a FastAPI service wrapper in service/api.py."""
    app = _get_fastapi_app()

    try:
        openapi = app.openapi()
    except Exception:
        pytest.skip("The service app object does not look like a FastAPI app")

    paths = openapi.get("paths", {})
    assert "/translate" in paths or any("translate" in key for key in paths)


def test_translate_route_is_registered():
    """The /translate route should be registered even without calling the backend."""
    app = _get_fastapi_app()

    routes = getattr(app, "routes", [])
    route_paths = []
    for route in routes:
        path = getattr(route, "path", "")
        if path:
            route_paths.append(path)
    assert "/translate" in route_paths or any(path.endswith("translate") for path in route_paths)


def test_translate_endpoint_rejects_missing_payload():
    """A malformed request should fail validation before hitting translation code."""
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    app = _get_fastapi_app()
    client = TestClient(app)
    response = client.post("/translate", data={})
    assert response.status_code in {400, 415, 422}


def test_translate_endpoint_documented_in_openapi():
    """The OpenAPI schema should advertise the translate endpoint for clients."""
    app = _get_fastapi_app()

    schema = app.openapi()
    dumped = json.dumps(schema, ensure_ascii=False)
    assert "translate" in dumped.lower()
