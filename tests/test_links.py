"""The links a share hands the agent: a full web address that survives sign-in, never a bare route."""

import urllib.parse

import pytest

from annotary_hermes import tools, webapp


@pytest.fixture()
def root(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    return tmp_path


def _public(root, url):
    (root / "config.yaml").write_text(f"webapp:\n  enabled: true\n  public_url: {url}\n")


def test_the_web_link_carries_the_document_in_the_query_so_sign_in_keeps_it(root):
    """A server-side sign-in keeps only path and query (`next=`); the fragment is lost."""
    _public(root, "https://agent.example.test/")
    url = tools.links("nveriy5x")["webapp"]
    assert url == "https://agent.example.test/?annotary=nveriy5x#/annotary?doc=nveriy5x"
    kept = urllib.parse.urlsplit(url)
    assert urllib.parse.parse_qs(kept.query) == {webapp.LINK_PARAM: ["nveriy5x"]}


def test_no_public_address_means_no_web_link_and_no_bare_route(root):
    """A bare `#/annotary?doc=` was completed by agents with the dashboard's origin."""
    lk = tools.links("nveriy5x")
    assert lk == {"desktop": "hermes://open/annotary?doc=nveriy5x"}
    said = tools._present(tools.Caller("coder", surface="desktop"), "nveriy5x")["show_card"]
    assert "webapp.public_url is not set" in said and "never build a link yourself" in said


def test_desktop_and_the_webapp_get_the_card_and_the_link_on_request(root):
    _public(root, "https://agent.example.test")
    out = tools._present(tools.Caller("coder", surface="desktop"), "nveriy5x")
    assert out["card"] == '::annotary{doc="nveriy5x"}'
    assert "links.webapp" in out["show_card"] and "Capabilities → Plugins" in out["show_card"]
    assert out["links"]["webapp"].startswith("https://agent.example.test/?annotary=nveriy5x")


def test_a_chat_elsewhere_gets_the_web_link(root):
    _public(root, "https://agent.example.test")
    out = tools._present(tools.Caller("coder", surface="telegram"), "nveriy5x")
    assert "card" not in out and "links.webapp" in out["show_link"]


def test_a_public_address_with_a_path_prefix_keeps_it_once():
    assert webapp.doc_url("nveriy5x", "https://h.example.test/hermes/") == \
        "https://h.example.test/hermes/?annotary=nveriy5x#/annotary?doc=nveriy5x"
