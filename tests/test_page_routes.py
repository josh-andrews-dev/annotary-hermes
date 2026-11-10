"""The plugin page's backend routes, as Hermes serves them on every profile."""

import importlib.util
import re

from conftest import ROOT
from fastapi import FastAPI


def router():
    spec = importlib.util.spec_from_file_location("annotary_plugin_api_routes", ROOT / "dashboard" / "plugin_api.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.router


def test_no_route_is_shadowed_by_a_fastapi_built_in_page():
    """A non-default profile's plugin host mounts the router on a bare FastAPI app, whose own
    pages win: a route at /docs answers with Swagger's HTML there."""
    app = FastAPI()
    built_in = {app.docs_url, app.redoc_url, app.openapi_url, app.swagger_ui_oauth2_redirect_url}
    assert not {r.path for r in router().routes} & built_in


def test_the_page_only_calls_routes_the_backend_has():
    page = (ROOT / "desktop" / "plugin.js").read_text()
    called = set(re.findall(r"rest\(['`](/[a-z]+)", page))
    assert "/documents" in called and called <= {r.path for r in router().routes}


def test_the_document_list_carries_the_head_versions_action(monkeypatch):
    """The list says "Approved by @josh", so it needs the Action's id and who took it, not only its label."""
    spec = importlib.util.spec_from_file_location("annotary_plugin_api_list", ROOT / "dashboard" / "plugin_api.py")
    api = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(api)
    rows = [{"id": "d1", "name": "a", "version": 2, "action": {"id": "approve", "label": "Approve", "by": "josh", "version": 2}},
            {"id": "d2", "name": "b", "version": 3, "action": {"id": "send-back", "label": "Send back", "by": "josh", "version": 2}}]
    monkeypatch.setattr(api, "_owner", lambda: "tok")
    monkeypatch.setattr(api.server, "api", lambda *_a, **_k: {"docs": rows})
    monkeypatch.setattr(api.state, "load", lambda: {})
    monkeypatch.setattr(api, "_editor_view", lambda *_a: {})
    docs = {d["id"]: d for d in api._docs()["docs"]}
    assert docs["d1"]["action"] == {"id": "approve", "label": "Approve", "by": "josh"}
    assert docs["d2"]["action"] is None  # an Action on an older Version is not the head's

