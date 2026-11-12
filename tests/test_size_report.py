"""The size report: deterministic counts (bytes and requests, never times) of what the plugin
sends, held equal to the committed perf/size-report.json and under the ceilings in
perf/BUDGETS.md ("Size ceilings"). `make size-report` rewrites the file.

It counts the desktop page's own bytes, what the agents are told (the skill file, the tool
schemas, the wake-up messages), and the plugin backend's answers (`dashboard/plugin_api.py`,
rendered as FastAPI sends them) to show the list and to open one Document, against the real
pinned `annotary serve` with a fixed seeded set of Documents. How each number is counted:
docs/size-report.md.

Set up as on Hermes Cloud (the OS user `hermes`), so the person is `@owner` on every machine.
Two things in an answer depend on the run, not the code, and are normalized before counting:
the server's address and the text of relative times, as annotary's own size report does.
Document and Thread ids are random but always the same length.
"""

from __future__ import annotations

import asyncio
import importlib.util
import json
import os
import re
import sys
from pathlib import Path
from urllib.parse import quote

from conftest import ROOT

from annotary_hermes import paths, rules, server, tools, watcher

REPORT = ROOT / "perf" / "size-report.json"
BUDGETS = ROOT / "perf" / "BUDGETS.md"
#: What a normalized answer says in place of this run's server address.
SERVER = "http://127.0.0.1:7377"
#: The headers the frame's embed.js adds to every request (fixed here: a browser sends its own zone).
FRAME_HEADERS = {"X-Annotary-Embed": "1", "X-Annotary-Tz": "UTC", "X-Annotary-Hc": "24"}

# ---------------------------------------------------------------- the fixture

SMALL_DOCS = 7  # besides the reviewed one: the list shows eight rows
REVIEW_LINES = 2000
REVIEW_THREADS = 80
REVIEW_REPLIES = 32
REVIEW_RESOLVED = 8


def small_markdown(i: int) -> str:
    steps = "\n".join(f"{n}. Step {n} of plan {i}: write it, test it, ship it." for n in range(1, 13))
    return f"# Plan {i}\n\nWhy plan {i} matters, in one paragraph of plain prose.\n\n## Steps\n\n{steps}\n"


def review_markdown(version: int) -> str:
    """REVIEW_LINES lines of fixed prose in sections; Version 2 changes every tenth paragraph."""
    out = ["# Review fixture", ""]
    line = 2
    n = 0
    while line < REVIEW_LINES:
        if n % 20 == 0:
            out += [f"## Section {n // 20 + 1}", ""]
            line += 2
        edited = " (edited in v2)" if version == 2 and n % 10 == 3 else ""
        out += [f"Paragraph {n}{edited}: the reviewer reads this line and comments on what it says.", ""]
        line += 2
        n += 1
    return "\n".join(out[:REVIEW_LINES]) + "\n"


def _owner_cli(*args: str, stdin: str | None = None) -> dict:
    r = server.run_cli(server.owner_token(), [*args, "--json"], stdin=stdin)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout) if r.stdout.strip() else {}


def seed() -> tuple[str, dict]:
    """The fixed set of Documents. Returns the reviewed Document's id and the fixture's counts."""
    coder = tools.Caller("coder")
    for i in range(1, SMALL_DOCS + 1):
        tools.share(coder, markdown=small_markdown(i), name=f"plan-{i}")
    doc = tools.share(coder, markdown=review_markdown(1), name="review")["id"]
    text = review_markdown(1).split("\n")
    paragraph_lines = [i + 1 for i, t in enumerate(text) if t.startswith("Paragraph ")]
    threads = []
    for k in range(REVIEW_THREADS):
        line = paragraph_lines[k * len(paragraph_lines) // REVIEW_THREADS]
        anchor = f"{line}:0-{line}:{len(text[line - 1])}"
        t = _owner_cli("thread", "new", doc, anchor, "-m", "-",
                       stdin=f"Comment {k}: say more about this, and why it is needed here.")
        threads.append(t.get("thread") or t.get("id"))
    _owner_cli("act", doc, "send-back")
    tools.push_version(coder, doc=doc, markdown=review_markdown(2), message="Answer the review")
    for k, t in enumerate(threads[:REVIEW_REPLIES]):
        tools.reply(coder, doc=doc, thread=t, text=f"Done in v2: paragraph {k} now says why.",
                    resolve=k < REVIEW_RESOLVED)
    lines = REVIEW_LINES + SMALL_DOCS * len(small_markdown(1).splitlines())
    return doc, {"documents": SMALL_DOCS + 1, "lines": lines, "versions": SMALL_DOCS + 2,
                 "threads": REVIEW_THREADS, "replies": REVIEW_REPLIES, "profiles": 3}


# ---------------------------------------------------------------- the backend, as Hermes serves it

def _plugin_api():
    spec = importlib.util.spec_from_file_location("annotary_plugin_api_size", ROOT / "dashboard" / "plugin_api.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def normalize(text: str) -> str:
    here = paths.server_url().rstrip("/")
    text = text.replace(here, SERVER).replace(quote(here, safe=""), quote(SERVER, safe=""))
    # `\"` inside a JSON string (a page carried in a /proxy answer) as well as `"` in a page.
    return re.sub(r'(<time class=\\?"cd-rel\\?"[^>]*>)[^<]*(</time>)', r"\1now\2", text)


class Backend:
    """Calls the page backend's routes and counts each answer as FastAPI renders it."""

    def __init__(self):
        from fastapi.encoders import jsonable_encoder
        from fastapi.responses import JSONResponse
        self.api = _plugin_api()
        self._render = lambda v: JSONResponse(jsonable_encoder(v)).body.decode("utf-8")
        self.log: list[tuple[str, int]] = []
        self.dump = os.environ.get("SIZE_REPORT_DUMP")

    def call(self, route: str, coro) -> dict:
        value = asyncio.run(coro)
        body = normalize(self._render(value))
        self.log.append((route, len(body.encode("utf-8"))))
        if self.dump:
            Path(self.dump).mkdir(parents=True, exist_ok=True)
            (Path(self.dump) / f"{len(self.log):02d}-{route.strip('/').replace('/', '_')}.json").write_text(body)
        return value

    def proxy(self, path: str, headers: dict | None = None, binary: bool = False) -> dict:
        msg = {"method": "GET", "path": path, "headers": {**FRAME_HEADERS, **(headers or {})}, "body": None}
        if binary:
            msg["binary"] = True
        return self.call("/proxy", self.api.proxy(msg))


def fetch_page(backend: Backend, path: str) -> tuple[list[dict], int]:
    """A page as the frame's embed.js loads it: part 0, then parts 1… with its etag; a 412 (the
    answer changed between parts) starts over, three times at most. Returns (parts, restarts)."""
    page = {"Accept": "text/html"}
    for attempt in range(4):
        first = backend.proxy(path, page)
        if first["status"] != 206:
            assert first["status"] == 200, first["status"]
            return [first], attempt
        h = first["headers"]
        assert h["x-annotary-status"] == "200", h
        parts = [first]
        for i in range(1, int(h["x-annotary-parts"])):
            r = backend.proxy(path, {**page, "X-Annotary-Part": str(i), "X-Annotary-Etag": h["x-annotary-etag"]})
            if r["status"] != 206:
                assert r["status"] == 412, r["status"]
                break
            parts.append(r)
        else:
            return parts, attempt
    raise AssertionError(f"{path} kept changing between parts")


def measure(backend: Backend, doc: str) -> list[dict]:
    api = backend.api
    metrics: list[dict] = []

    def add(mid: str, label: str, unit: str, value: int) -> None:
        metrics.append({"id": mid, "label": label, "unit": unit, "value": int(value)})

    def total(since: int) -> tuple[int, int]:
        part = backend.log[since:]
        return len(part), sum(n for _, n in part)

    # The page itself: plugin.js, loaded uncompiled on every page load.
    add("page.plugin_js.bytes", "Desktop page: plugin.js", "bytes", (ROOT / "desktop" / "plugin.js").stat().st_size)

    # The list: what AnnotaryPage loads (desktop/plugin.js, AnnotaryPage's load()).
    start = len(backend.log)
    backend.call("/documents", api.docs())
    backend.call("/status", api.status())
    n, b = total(start)
    add("list.requests", "Show the list: backend requests", "count", n)
    add("list.bytes", "Show the list: bytes", "bytes", b)
    add("list.documents.bytes", "Show the list: /documents", "bytes", backend.log[start][1])
    add("list.status.bytes", "Show the list: /status", "bytes", backend.log[start + 1][1])

    # Open one Document in embed mode: the review bar's /doc, the frame shell, then the frame's
    # requests: the page (in parts when over annotary's PART_MAX), each avatar it fetches, and the
    # first poll of its live feed.
    start = len(backend.log)
    backend.call("/doc", api.doc(doc))
    add("open.doc.bytes", "Open a Document: /doc", "bytes", backend.log[-1][1])
    backend.call("/shell", api.shell())
    add("open.shell.bytes", "Open a Document: /shell", "bytes", backend.log[-1][1])
    page_start = len(backend.log)
    pages, restarts = fetch_page(backend, f"/d/{doc}")
    pn, pb = total(page_start)
    add("open.page.parts", "Open a Document: page parts", "count", len(pages))
    add("open.page.restarts", "Open a Document: page restarts (412)", "count", restarts)
    add("open.page.requests", "Open a Document: page requests", "count", pn)
    add("open.page.bytes", "Open a Document: page through /proxy", "bytes", pb)
    html = "".join(p["body"] for p in pages)
    avatar_start = len(backend.log)
    # app.js's loadAvatars: each data-cd-av URL once, as bytes (data-cd-av-static only under reduced motion).
    for url in dict.fromkeys(re.findall(r'data-cd-av="([^"]+)"', html)):
        r = backend.proxy(url.replace("&amp;", "&"), binary=True)
        assert r["status"] == 200, (url, r["status"])
    an, ab = total(avatar_start)
    add("open.avatars", "Open a Document: avatars fetched", "count", an)
    add("open.avatars.bytes", "Open a Document: avatars through /proxy", "bytes", ab)
    # app.js's subscribe, on a Document page: transport.events polls the feed at once from the
    # page's seq, then every EMBED_POLL_MS (4 s) from the answer's seq.
    data = json.loads(re.search(r'<script type="application/json" id="cd-data">(.*?)</script>', html, re.S).group(1))
    feed = f"/api/v1/events?doc={doc}&since={{}}&me=1&limit=200"
    first_poll = backend.proxy(feed.format(data["seq"]), {"Accept": "application/json"})
    assert first_poll["status"] == 200, first_poll["status"]
    add("open.events.bytes", "Open a Document: first live-feed poll", "bytes", backend.log[-1][1])
    n, b = total(start)
    add("open.requests", "Open a Document: backend requests", "count", n)
    add("open.bytes", "Open a Document: bytes", "bytes", b)

    # Every POLL_MS (10 s) while that Document is open, the list and the review bar load again
    # (useLive); every 4 s, the frame polls its live feed, empty while nothing changes.
    start = len(backend.log)
    backend.call("/documents", api.docs())
    backend.call("/status", api.status())
    backend.call("/doc", api.doc(doc))
    n, b = total(start)
    add("poll.requests", "Each 10 s poll, a Document open: requests", "count", n)
    add("poll.bytes", "Each 10 s poll, a Document open: bytes", "bytes", b)
    seq = max(int(json.loads(first_poll["body"]).get("seq") or 0), int(data["seq"]))
    again = backend.proxy(feed.format(seq), {"Accept": "application/json"})
    assert again["status"] == 200 and not json.loads(again["body"]).get("events"), again
    add("poll.events.bytes", "Each 4 s live-feed poll, nothing new: bytes", "bytes", backend.log[-1][1])

    # What the agents are told: sent to a model on every session, or on every wake-up.
    add("agents.skill.bytes", "Agents: SKILL.md", "bytes", (ROOT / "skills" / "annotary" / "SKILL.md").stat().st_size)
    schemas = _plugin_schemas()
    add("agents.tools", "Agents: tools registered", "count", len(schemas))
    add("agents.tools.bytes", "Agents: tool schemas (JSON)", "bytes",
        len(json.dumps([{"name": k, **v} for k, v in schemas.items()], separators=(",", ":"),
                       ensure_ascii=False).encode("utf-8")))
    wake = dict(profile="coder", doc="k7q2m9xd", name="plan", by="owner")
    add("agents.wake.send_back.bytes", "Agents: Send back wake-up, without Threads", "bytes",
        len(watcher.message_for(rules.Wake(reason="review", action="send-back", **wake), me="coder",
                                digest="").encode("utf-8")))
    add("agents.wake.mention.bytes", "Agents: mention wake-up, without the excerpt", "bytes",
        len(watcher.message_for(rules.Wake(reason="mention", thread="t1", excerpt="", **wake), me="coder",
                                digest="").encode("utf-8")))
    return metrics


def _plugin_schemas() -> dict:
    spec = importlib.util.spec_from_file_location("annotary_plugin_size_schemas", ROOT / "__init__.py",
                                                  submodule_search_locations=[str(ROOT)])
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module.SCHEMAS


# ---------------------------------------------------------------- the report

def ceilings(md: str) -> dict[str, int]:
    """`| id | metric | ceiling | unit | ...` under "## Size ceilings" in perf/BUDGETS.md."""
    out: dict[str, int] = {}
    inside = False
    for line in md.splitlines():
        if line.startswith("## "):
            inside = line[3:].strip().startswith("Size ceilings")
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if not inside or not line.startswith("|") or len(cells) < 4 or not cells[0].startswith("`"):
            continue
        mid = cells[0].strip("`")
        value = cells[2].replace(",", "")
        assert value.isdigit(), f"perf/BUDGETS.md: the ceiling of {mid} is not a whole number: {cells[2]!r}"
        assert mid not in out, f"perf/BUDGETS.md: {mid} has two ceilings"
        out[mid] = int(value)
    return out


def render(fixture: dict, metrics: list[dict], ceil: dict[str, int]) -> str:
    report = {"schema": 1, "fixture": fixture,
              "metrics": [{**m, "ceiling": ceil.get(m["id"])} for m in metrics]}
    return json.dumps(report, indent=2) + "\n"


def test_the_size_report_matches_what_the_plugin_sends_and_stays_under_its_ceilings(hermes_cloud):
    doc, fixture = seed()
    metrics = measure(Backend(), doc)
    ceil = ceilings(BUDGETS.read_text())
    assert ceil, 'perf/BUDGETS.md has no "## Size ceilings" table'
    ids = {m["id"] for m in metrics}
    assert not set(ceil) - ids, f"perf/BUDGETS.md: size ceilings name no measured number: {sorted(set(ceil) - ids)}"
    want = render(fixture, metrics, ceil)
    if os.environ.get("SIZE_REPORT") == "overwrite":
        REPORT.parent.mkdir(exist_ok=True)
        REPORT.write_text(want)
    over = [f"{m['label']} ({m['id']}): {m['value']} > ceiling {ceil[m['id']]}"
            for m in metrics if m["id"] in ceil and m["value"] > ceil[m["id"]]]
    assert not over, "above the ceilings in perf/BUDGETS.md:\n" + "\n".join(over)
    have = REPORT.read_text() if REPORT.exists() else ""
    assert have == want, ("perf/size-report.json differs from what was measured: run `make size-report`, "
                          "review the diff and commit it (a number that grew needs a `Size growth:` line "
                          "in the pull request body)")


def test_ceilings_come_from_their_own_table():
    md = ("## Budgets\n\n| `x` | a | 1 | count |\n\n## Size ceilings\n\n| id | metric | ceiling | unit |\n"
          "|---|---|---:|---|\n| `list.bytes` | Show the list: bytes | 1,200 | bytes |\n\n## Other\n\n"
          "| `y` | b | 2 | count |\n")
    assert ceilings(md) == {"list.bytes": 1200}


def test_normalize_replaces_the_address_and_relative_times(monkeypatch):
    monkeypatch.setenv("ANNOTARY_HERMES_PORT", "41234")
    here = paths.server_url().rstrip("/")
    page = f'<a href="{here}/d/x">{quote(here, safe="")}</a><time class="cd-rel" datetime="z">3m</time>'
    assert normalize(page) == (f'<a href="{SERVER}/d/x">{quote(SERVER, safe="")}</a>'
                               '<time class="cd-rel" datetime="z">now</time>')
    assert normalize(json.dumps(page)) == json.dumps(normalize(page))
