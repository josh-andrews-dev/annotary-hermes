"""One live review loop against a real Hermes install, to check a model (or a skill change) end to end.

A live interactive session of PROFILE (in a pseudo-terminal, so the gateway can wake it) is asked
to write a short plan and share it. The owner then leaves two comments and chooses Send back, and
the loop waits for the woken agent to push Version 2 once, reply on each Thread citing it, and
resolve both. Prints a JSON report (timings, Versions, every reply); exits 0 only when the agent
did all of it and the run cleaned up after itself. Needs the plugin installed and wake-ups on for
PROFILE. Every Document PROFILE shares during the run is permanently removed at the end, so do
not use PROFILE for real work while this runs.

`--scenario decide` asks instead for a plan with a decisions table. The owner answers both
Questions, draws a Markup (a red cross over the first Question's text, with no words) and chooses
Send back; the run waits for Version 2 to record both answers in its Decided cells, the drawing to
be opened with annotary_markup, and a reply on the drawing's Thread that describes it.

    python3 scripts/project/live_loop.py --profile coder [--model MODEL] [--timeout 900] [--scenario decide]
"""

from __future__ import annotations

import argparse
import json
import os
import pty
import re
import select
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import zlib
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

COMMENTS = ("Add a rollback step in case the new host fails.",
            "Which week does step 2 happen? Put a date on it.")


def cites_version(body: str, version: int) -> bool:
    """Whether a reply names the Version it points to: "v2", "Version 2", "version 2"."""
    return re.search(rf"\b(?:v|version\s*){version}\b", body or "", re.I) is not None


def loop_status(version: int, threads: list[dict], author: str) -> dict:
    """How far the woken agent got: one push to Version 2, a reply by *author* on every Thread
    citing it, every Thread resolved."""
    rows = []
    for t in threads:
        mine = [r for r in t.get("replies") or [] if r.get("author") == author]
        rows.append({"thread": t.get("id"), "replied": bool(mine),
                     "cites_version": any(cites_version(r.get("body", ""), 2) for r in mine),
                     "resolved": bool(t.get("resolved"))})
    done = (version == 2 and len(rows) == len(COMMENTS)
            and all(r["replied"] and r["cites_version"] and r["resolved"] for r in rows))
    return {"version": version, "threads": rows, "done": done}


#: What the owner answers in the decide scenario (whatever the agent recommends).
DECIDE_ANSWERS = {"D1": "B", "D2": "A"}
#: Words a reply that describes the drawing (a red cross) uses.
DESCRIBES = re.compile(r"\b(cross(?:ed|es)?|x|strike|struck|red|lines?|marks?(?:ed)?|drawing|drew|delete[ds]?|remove[ds]?)\b", re.I)


def decide_status(version: int, questions: list[dict], threads: list[dict], author: str, drawn: str,
                  opened: bool) -> dict:
    """How far the woken agent got in the decide scenario: Version 2 records every answer in its
    Decided cells, the drawing was opened with annotary_markup, and the agent replied on the
    drawing's Thread *drawn* describing it."""
    decided = {q.get("key"): q.get("decided") for q in questions if q.get("source") == "table"}
    replies = [r.get("body") or "" for t in threads if t.get("id") == drawn
               for r in t.get("replies") or [] if r.get("author") == author]
    rows = {"recorded": {k: bool(decided.get(k)) for k in DECIDE_ANSWERS}, "opened_drawing": opened,
            "described": any(DESCRIBES.search(b) for b in replies), "replies": replies}
    done = version == 2 and all(rows["recorded"].values()) and opened and rows["described"]
    return {"version": version, **rows, "done": done}


def cross_png(w: int = 360, h: int = 120) -> bytes:
    """A red cross on white, as a Markup crop: a PNG drawn here, no imaging library."""
    rows = []
    for y in range(h):
        row = bytearray(b"\x00")
        for x in range(w):
            on = abs(x * h - y * w) < 3 * w or abs(x * h - (h - 1 - y) * w) < 3 * w
            row += bytes((220, 20, 20) if on else (255, 255, 255))
        rows.append(bytes(row))

    def chunk(t: bytes, d: bytes) -> bytes:
        return len(d).to_bytes(4, "big") + t + d + (zlib.crc32(t + d) & 0xFFFFFFFF).to_bytes(4, "big")
    ihdr = w.to_bytes(4, "big") + h.to_bytes(4, "big") + bytes((8, 2, 0, 0, 0))
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr) + chunk(b"IDAT", zlib.compress(b"".join(rows)))
            + chunk(b"IEND", b""))


class StepFailed(Exception):
    """A CLI step of the run failed; the message is safe to print."""


def checked(r: subprocess.CompletedProcess, step: str) -> None:
    """Fail at once on a non-zero exit, with stderr only: stdout is never shown."""
    if r.returncode != 0:
        raise StepFailed(f"{step}: {r.stderr.strip() or f'exit {r.returncode}'}")


def new_documents(docs: dict, before: set[str], profile: str) -> list[str]:
    """Documents *profile* shared since *before* was taken."""
    return [d for d, v in docs.items() if d not in before and v.get("editor") == profile]


def send_back(owner: str, doc: str) -> None:
    """The owner's review: two comments on the Document, then Send back."""
    from annotary_hermes import server
    for body in COMMENTS:
        checked(server.run_cli(owner, ["thread", "new", doc, "--document", "-m", "-"], stdin=body), "new comment")
    checked(server.run_cli(owner, ["act", doc, "send-back"]), "Send back")


def owner_decides(owner: str, doc: str) -> str:
    """The owner's review in the decide scenario: answer both Questions, draw a cross over the first
    Question's place (no words: the agent must look), Send back. Returns the drawing's Thread."""
    from annotary_hermes import server
    r = server.run_cli(owner, ["show", doc, "--json"])
    checked(r, "show")
    questions = {q["key"]: q for q in json.loads(r.stdout).get("questions") or []}
    missing = sorted(set(DECIDE_ANSWERS) - set(questions))
    if missing:
        raise StepFailed(f"the Document has no decisions table rows {', '.join(missing)}")
    for key, option in DECIDE_ANSWERS.items():
        checked(server.run_cli(owner, ["answer", doc, key, option]), f"answer {key}")
    with tempfile.TemporaryDirectory() as tmp:
        checked(server.run_cli(owner, ["pull", doc, "--as-pushed", "--out", tmp]), "pull")
        lines = next(Path(tmp).glob("*.md")).read_text(encoding="utf-8").split("\n")
        q = questions["D1"]
        first, last = (q.get("place") or {}).get("a") or q["row"], (q.get("place") or {}).get("b") or q["row"]
        (Path(tmp) / "m.png").write_bytes(cross_png())
        (Path(tmp) / "m.json").write_text(json.dumps({"strokes": [
            {"color": "#dc1414", "width": 6, "points": [[0, 0, 0], [359, 119, 0.4]]},
            {"color": "#dc1414", "width": 6, "points": [[0, 119, 0.6], [359, 0, 1.0]]}]}))
        r = server.run_cli(owner, ["thread", "new", doc, f"{first}:0-{last}:{len(lines[last - 1])}", "--markup",
                                   str(Path(tmp) / "m.png"), "--strokes", str(Path(tmp) / "m.json"), "--json"])
        checked(r, "draw a Markup")
    checked(server.run_cli(owner, ["act", doc, "send-back"]), "Send back")
    return json.loads(r.stdout)["id"]


def clean_up(owner: str, profile: str, before: set[str]) -> list[str]:
    """Remove what the run made: each new Document of *profile* from the server, its staged
    files and its state entry. A Document that fails keeps its files and entry, and is returned."""
    from annotary_hermes import paths, server, state
    failed, removed = [], []
    for doc in new_documents(state.load()["docs"], before, profile):
        try:
            for verb in ("delete", "purge"):
                checked(server.run_cli(owner, [verb, doc]), f"{verb} {doc}")
        except (StepFailed, OSError, subprocess.SubprocessError) as e:
            print(f"could not remove {doc}: {e}", file=sys.stderr, flush=True)
            failed.append(doc)
            continue
        shutil.rmtree(paths.shares_dir(profile) / doc, ignore_errors=True)
        shutil.rmtree(paths.markup_dir(profile) / doc, ignore_errors=True)
        removed.append(doc)

    def forget(st: dict) -> None:
        for doc in removed:
            st["docs"].pop(doc, None)
    state.update(forget)
    print(f"removed {len(removed)} Document(s): {' '.join(removed)}", file=sys.stderr, flush=True)
    return failed


class Session:
    """An interactive `hermes` session in a pseudo-terminal, run in *cwd*; its screen goes to *log*."""

    def __init__(self, argv: list[str], log: Path, cwd: str):
        self.pid, self.fd = pty.fork()
        if self.pid == 0:
            os.chdir(cwd)
            os.environ["TERM"] = "xterm-256color"
            os.execvp(argv[0], argv)
        self.log = open(log, "ab")
        self.alive = True
        self.pump = threading.Thread(target=self._pump, daemon=True)
        self.pump.start()

    def _pump(self) -> None:
        while self.alive:
            r, _, _ = select.select([self.fd], [], [], 1.0)
            if r:
                try:
                    data = os.read(self.fd, 65536)
                except OSError:
                    break
                if not data:
                    break
                self.log.write(data)
                self.log.flush()

    def type(self, text: str) -> None:
        os.write(self.fd, text.replace("\n", "\r").encode())

    def close(self) -> None:
        self.alive = False
        self.pump.join(timeout=3)  # it writes to the log
        self.log.close()
        # The CLI cannot finish exiting while its terminal is open and unread: close our end
        # first, and kill it outright if it is still there after a few seconds.
        for sig in (15, None, 9):
            try:
                if sig is None:
                    os.close(self.fd)
                else:
                    os.kill(self.pid, sig)
                for _ in range(50):
                    if os.waitpid(self.pid, os.WNOHANG)[0]:
                        return
                    time.sleep(0.1)
            except (OSError, ChildProcessError):
                return


def run_loop(args: argparse.Namespace, sess: Session, owner: str, before: set[str]) -> int:
    from annotary_hermes import accounts, server, state
    author = accounts.handle_of(args.profile) or args.profile
    t0 = time.time()
    events: list[tuple[float, str]] = []

    def stamp(what: str) -> None:
        events.append((round(time.time() - t0, 1), what))
        print(f"[{time.time() - t0:6.1f}s] {what}", file=sys.stderr, flush=True)

    time.sleep(15)  # the interactive CLI's start-up
    if args.scenario == "decide":
        sess.type(f"Write a short plan for moving the team wiki to a new host with two decisions: D1, where it "
                  f"runs (A: the existing box, B: a new VM), and D2, when (A: this week, B: next week). Give "
                  f"each decision a short section, and end with a decisions table with the columns Decision, "
                  f"Options, Recommended and Decided (leave Decided empty). Share it with me for review using "
                  f"Annotary. Name it 'Wiki decide {args.label}'.\n")
    else:
        sess.type(f"Write a short plan (a title and three numbered steps) for moving the team wiki to "
                  f"a new host, then share it with me for review using Annotary. Name it "
                  f"'Wiki move {args.label}'.\n")
    stamp("asked for a plan")
    doc = None
    while time.time() - t0 < args.timeout and not doc:
        new = new_documents(state.load()["docs"], before, args.profile)
        doc = new[0] if new else None
        time.sleep(2)
    if not doc:
        stamp("no Document shared")
        print(json.dumps({"done": False, "events": events}, indent=1))
        return 1
    stamp(f"shared {doc}")
    if args.scenario == "decide":
        return decide_loop(args, owner, doc, author, t0, events, stamp)
    try:
        send_back(owner, doc)
    except StepFailed as e:
        stamp("the owner's review failed")
        print(json.dumps({"done": False, "doc": doc, "error": str(e), "events": events}, indent=1))
        return 1
    stamp("two comments, then Send back")
    status: dict = {}
    while time.time() - t0 < args.timeout:
        head = server.api(owner, "GET", f"/api/v1/docs/{doc}")
        threads = server.api(owner, "GET", f"/api/v1/docs/{doc}/threads?status=all")["threads"]
        status = loop_status(int(head.get("version") or 0), threads, author)
        if status["done"]:
            break
        time.sleep(5)
    stamp("done" if status.get("done") else "timed out")
    threads = server.api(owner, "GET", f"/api/v1/docs/{doc}/threads?status=all")["threads"]
    print(json.dumps({
        "done": status.get("done", False), "doc": doc, "model": args.model or "(profile default)",
        "events": events, "status": status,
        "threads": [{"id": t.get("id"), "comment": t.get("body"), "resolved": bool(t.get("resolved")),
                     "replies": [f"@{r.get('author')}: {r.get('body')}" for r in t.get("replies") or []]}
                    for t in threads]}, indent=1))
    return 0 if status.get("done") else 1


def decide_loop(args: argparse.Namespace, owner: str, doc: str, author: str, t0: float, events: list,
                stamp) -> int:
    from annotary_hermes import paths, server
    try:
        drawn = owner_decides(owner, doc)
    except StepFailed as e:
        stamp("the owner's review failed")
        print(json.dumps({"done": False, "doc": doc, "error": str(e), "events": events}, indent=1))
        return 1
    stamp(f"answered {' '.join(f'{k}={v}' for k, v in DECIDE_ANSWERS.items())}, drew {drawn}, then Send back")
    status: dict = {}
    while time.time() - t0 < args.timeout:
        version = int(server.api(owner, "GET", f"/api/v1/docs/{doc}").get("version") or 0)
        questions = server.api(owner, "GET", f"/api/v1/docs/{doc}/questions?version={version}").get("questions") or []
        threads = server.api(owner, "GET", f"/api/v1/docs/{doc}/threads?status=all")["threads"]
        opened = (paths.markup_dir(args.profile) / doc / f"{drawn}.png").is_file()
        status = decide_status(version, questions, threads, author, drawn, opened)
        if status["done"]:
            break
        time.sleep(5)
    stamp("done" if status.get("done") else "timed out")
    print(json.dumps({"done": status.get("done", False), "doc": doc, "scenario": "decide",
                      "model": args.model or "(profile default)", "events": events, "status": status}, indent=1))
    return 0 if status.get("done") else 1


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--profile", default="coder")
    ap.add_argument("--model", default="", help="override the profile's model for this session")
    ap.add_argument("--timeout", type=float, default=900)
    ap.add_argument("--label", default=time.strftime("%H%M%S"))
    ap.add_argument("--scenario", choices=("review", "decide"), default="review",
                    help="review: comments, Send back, push, replies; decide: a decisions table and a Markup")
    args = ap.parse_args()

    from annotary_hermes import server, state
    owner = server.owner_token()
    before = set(state.load()["docs"])
    argv = ["hermes", "-p", args.profile, *(["-m", args.model] if args.model else [])]
    log = Path(tempfile.gettempdir()) / f"annotary-live-loop-{args.label}.log"
    # The agent may write files where it runs: never in the caller's checkout.
    workdir = tempfile.TemporaryDirectory(prefix="annotary-live-loop-")
    sess = Session(argv, log, workdir.name)
    code = 1
    try:
        code = run_loop(args, sess, owner, before)
    finally:
        sess.close()
        left = clean_up(owner, args.profile, before)
        workdir.cleanup()
    return 1 if left else code


if __name__ == "__main__":
    sys.exit(main())
