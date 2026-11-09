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
    page = (ROOT / "desktop-page" / "plugin.js").read_text()
    called = set(re.findall(r"rest\(['`](/[a-z]+)", page))
    assert "/documents" in called and called <= {r.path for r in router().routes}
