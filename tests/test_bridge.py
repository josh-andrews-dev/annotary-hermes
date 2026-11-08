"""The embed bridge (protocol v1) against a real server on the pinned Annotary, which has embed
mode."""

import base64

from annotary_hermes import bridge, server, tools

PLAN = "# Plan\n\nStep one: build the thing.\n\n![shot](shot.png)\n"
# 1x1 PNG
PNG = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR4nGNgYGD4DwABBAEAwS2OUAAAAABJRU5ErkJggg==")


def needs_embed():
    assert bridge.shell() is not None, "the pinned Annotary must serve the embed shell"


def test_refuses_bad_paths_and_methods(hermes):
    for msg in ({"method": "GET", "path": "//evil.example/x"}, {"method": "GET", "path": "http://x/"},
                {"method": "GET", "path": "d/x"}, {"method": "TRACE", "path": "/"},
                {"method": "GET", "path": "/\r\nX: y"}):
        assert bridge.request(msg)["status"] == 400


def test_unreachable_is_status_zero(hermes, monkeypatch):
    monkeypatch.setenv("ANNOTARY_HERMES_PORT", "1")
    assert bridge.request({"method": "GET", "path": "/"})["status"] == 0


def test_shell_and_embed_render(hermes):
    needs_embed()
    assert "annotary-ready" in bridge.shell()
    doc = tools.share(tools.Caller("coder"), markdown="# Plan\n\nhello\n", name="plan")["id"]
    r = bridge.request({"method": "GET", "path": f"/d/{doc}", "headers": {"Accept": "text/html", "X-Evil": "1"}})
    assert r["status"] == 200 and "text/html" in r["headers"]["content-type"]
    assert "cd-embed" in r["body"] and "set-cookie" not in r["headers"]


def test_redirects_are_not_followed(hermes):
    needs_embed()
    r = bridge.request({"method": "GET", "path": "/members"})
    assert 300 <= r["status"] < 400 and r["headers"].get("location")


def fetch_in_parts(path):
    """Fetch a page the way Annotary's embed.js does: part 0, then parts 1… with its etag; a 412
    (the answer changed between parts) starts over, three times at most."""
    for attempt in range(3):
        first = bridge.request({"method": "GET", "path": path})
        if first["status"] != 206:
            return attempt, [first]
        h = first["headers"]
        parts = [first]
        for i in range(1, int(h["x-annotary-parts"])):
            r = bridge.request({"method": "GET", "path": path,
                                "headers": {"X-Annotary-Part": str(i), "X-Annotary-Etag": h["x-annotary-etag"]}})
            if r["status"] == 412:
                break
            parts.append(r)
        else:
            return attempt, parts
    raise AssertionError("the page kept changing between parts")


def test_big_pages_come_back_in_parts_with_their_headers(hermes):
    needs_embed()
    big = "# Big\n\n" + "\n\n".join(f"Paragraph {i}: " + "lorem ipsum dolor sit amet " * 12 for i in range(1500))
    doc = tools.share(tools.Caller("coder"), markdown=big, name="big")["id"]
    _, parts = fetch_in_parts(f"/d/{doc}")
    h = parts[0]["headers"]
    assert parts[0]["status"] == 206 and h["x-annotary-part"] == "0" and h["x-annotary-status"] == "200"
    assert len(parts) == int(h["x-annotary-parts"]) > 1
    assert all(r["status"] == 206 for r in parts)
    assert all(len(r["body"].encode()) <= bridge.MAX_BYTES for r in parts)
    page = "".join(r["body"] for r in parts)
    assert page.rstrip().endswith("</html>") and "Paragraph 1499" in page
    # once seen, the page renders the same bytes every time: no more restarts
    again, _ = fetch_in_parts(f"/d/{doc}")
    assert again == 0


def test_binary_assets_come_back_base64(hermes, tmp_path):
    needs_embed()
    (tmp_path / "plan.md").write_text(PLAN)
    (tmp_path / "shot.png").write_bytes(PNG)
    doc = tools.share(tools.Caller("coder", cwd=str(tmp_path)), path="plan.md")["id"]
    page = bridge.request({"method": "GET", "path": f"/d/{doc}"})["body"]
    import re
    src = re.search(r'data-cd-src="(/a/[^"]+)"', page).group(1)
    r = bridge.request({"method": "GET", "path": src, "binary": True})
    assert r["status"] == 200 and r["encoding"] == "base64"
    assert base64.b64decode(r["body"]) == PNG


def test_owner_setup_reads_the_json_form():
    assert server.parse_setup_token('{"created":true,"handle":"o","token":"tok-1","store":"/s"}\n') == "tok-1"
    assert server.parse_setup_token("Owner token…\n\n  ANNOTARY_TOKEN=tok-2\n") is None  # only the JSON form
    assert server.parse_setup_token('{"handle":"o","store":"/s"}\n') is None
