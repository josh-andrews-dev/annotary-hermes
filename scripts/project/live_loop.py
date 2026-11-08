"""One live review loop against a real Hermes install, to check a model (or a skill change) end to end.

A live interactive session of PROFILE (in a pseudo-terminal, so the gateway can wake it) is asked
to write a short plan and share it. The owner then leaves two comments and chooses Send back, and
the loop waits for the woken agent to push Version 2 once, reply on each Thread citing it, and
resolve both. Prints a JSON report (timings, Versions, every reply); exits 0 only when the agent
did all of it and the run cleaned up after itself. Needs the plugin installed and wake-ups on for
PROFILE. Every Document PROFILE shares during the run is permanently removed at the end, so do
not use PROFILE for real work while this runs.

    python3 scripts/project/live_loop.py --profile coder [--model MODEL] [--timeout 900]
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


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--profile", default="coder")
    ap.add_argument("--model", default="", help="override the profile's model for this session")
    ap.add_argument("--timeout", type=float, default=900)
    ap.add_argument("--label", default=time.strftime("%H%M%S"))
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
