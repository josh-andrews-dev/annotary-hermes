"""``hermes annotary …``: setup, status, members, enable, wake on|off, doctor, stop, logs."""

from __future__ import annotations

import json
import shutil
import subprocess
import sys

from . import accounts, desktop, enablement, install, paths, rules, server, state, webapp


def _hermes() -> list[str]:
    """How to run `hermes` again (another profile): the same interpreter and entry point."""
    exe = shutil.which("hermes")
    return [exe] if exe else [sys.executable, "-m", "hermes_cli.main"]


def _run_hermes(args: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run([*_hermes(), *args], capture_output=True, text=True, stdin=subprocess.DEVNULL,
                          timeout=180)


def _print(obj) -> None:
    print(json.dumps(obj, indent=2, default=str))


def setup(_args=None) -> int:
    """Install the binary, set up and start the server, reconcile."""
    r = server.ensure_running()
    retired = desktop.retire_standalone_page()
    report = accounts.reconcile()
    print(f"Annotary server: {r['outcome']} at {paths.server_url()} (data in {paths.data_dir()})")
    print("Desktop page: part of this plugin; Hermes puts it in place when Desktop or the Webapp loads plugins")
    if retired:
        print(f"  removed an earlier version's standalone copy at {paths.desktop_page_target()}")
    for pid, what in report.items():
        print(f"  {pid}: {what}")
    return 0


def status(_args=None) -> int:
    h = server.health()
    st = state.load()
    _print({"server": paths.server_url(), "running": bool(h and h.get("ok")), "health": h,
            "binary": install.installed(), "desktop_page": desktop.page_status(),
            "documents": len(st["docs"]), "members": len(st["members"]),
            "wake": wake_state(),
            "recent_wakes": [{**r, "result": rules.OUTCOME_TEXT.get(r.get("outcome"), r.get("outcome"))}
                             for r in st.get("wake_log", [])[-5:]]})
    return 0


def members(_args=None) -> int:
    server.ensure_running()
    accounts.reconcile()
    st = state.load()
    print(f"{'PROFILE':<16} {'HANDLE':<20} {'NAME':<24} STATE")
    you = accounts.person()
    print(f"{'(you)':<16} @{you['handle']:<19} {you['name']:<24} owner"
          + ("" if you["named"] else f", no name yet ({NAME_FIX})"))
    off = []
    for pid, m in sorted(st["members"].items()):
        flag = "disabled" if m.get("disabled") else "active"
        tok = "token ok" if accounts.token_for(pid) else "no token"
        plugin = "" if m.get("disabled") else ", " + {
            enablement.ON: "Annotary on", enablement.OFF: "Annotary OFF",
            enablement.COPY: "Annotary on (own copy)",
            enablement.DECLINED: "Annotary off (your choice)"}[enablement.plugin_state(pid)]
        if plugin.endswith(("OFF", "copy)")):
            off.append(pid)
        print(f"{pid:<16} @{m['handle']:<19} {m.get('name', ''):<24} {flag}, {tok}{plugin}")
    if off:
        print(f"\n{', '.join(off)}: run `{enablement.FIX}` so every profile has the Annotary tools and "
              "skill (a profile made after install has none, and a cloned one runs its own copy).")
    return 0


def _profile_ids() -> list[str]:
    return [p.id for p in accounts.list_profiles()]


def _turn_on(pid: str) -> bool:
    """Link the plugin into *pid* and enable it. A profile cloned from default has its own copy
    of the plugin; it is replaced by a link, so updates reach it."""
    new = enablement.plugin_state(pid) == enablement.OFF
    linked = enablement.link_plugin(pid)
    if linked != "linked":
        print(f"{pid}: {linked}")
    ok = False
    try:
        r = _run_hermes(["-p", pid, "plugins", "enable", paths.PLUGIN_ID])
        ok = r.returncode == 0
        print(f"{pid}: {'enabled' if ok else 'enable failed: ' + (r.stderr or r.stdout).strip()[-200:]}")
    finally:
        if new and linked == "linked" and not ok:
            enablement.unlink_plugin(pid)
    return ok


def _finish_enable() -> None:
    setup()
    print("Restart the gateway to load the tools in every profile: hermes gateway restart --detach")


def enable_all(_args=None) -> int:
    """D6: Annotary on in every profile, except one where the person turned it off."""
    failures = 0
    for pid in _profile_ids():
        if enablement.plugin_state(pid) == enablement.DECLINED:
            print(f"{pid}: left off, as you chose (to turn it on: {enablement.turn_on(pid)})")
        elif not _turn_on(pid):
            failures += 1
    _finish_enable()
    print("A profile you make later has no Annotary until you run `hermes annotary enable --all` again.")
    return 1 if failures else 0


def enable(args) -> int:
    """`enable --all`, or `enable PROFILE`: the one way to opt a declined profile back in."""
    profile, every = getattr(args, "profile", None), getattr(args, "all", False)
    if bool(profile) == bool(every):
        print("usage: hermes annotary enable --all | hermes annotary enable PROFILE", file=sys.stderr)
        return 1
    if every:
        return enable_all()
    known = _profile_ids()
    if profile not in known:
        print(f"error: no profile named {profile} (profiles: {', '.join(known)})", file=sys.stderr)
        return 1
    ok = _turn_on(profile)
    _finish_enable()
    return 0 if ok else 1


def wake_state() -> dict:
    out = {}
    for pid in _profile_ids():
        r = _run_hermes(["-p", pid, "config", "get", f"plugins.entries.{paths.PLUGIN_ID}.allow_gateway_injection"])
        out[pid] = r.stdout.strip().lower() == "true"
    return out


def wake(args) -> int:
    on = args.state == "on"
    for pid in _profile_ids():
        key = f"plugins.entries.{paths.PLUGIN_ID}.allow_gateway_injection"
        r = _run_hermes(["-p", pid, "config", "set", key, "true" if on else "false"])
        print(f"{pid}: {'on' if on else 'off'}" if r.returncode == 0 else f"{pid}: failed {r.stderr.strip()[-200:]}")
    print("Comments on shared Documents now wake the chat that shared them (Send back, Approve, @mentions)."
          if on else "Wake-ups are off: Send back, Approve and @mentions show as notifications instead.")
    return 0


def doctor(_args=None) -> int:
    problems = 0

    def check(ok: bool, what: str, fix: str = "") -> None:
        nonlocal problems
        problems += 0 if ok else 1
        print(f"{'ok ' if ok else 'FAIL'} {what}" + (f"\n     fix: {fix}" if fix and not ok else ""))

    b = install.installed()
    check(b["ok"], f"binary {b.get('version', 'dev')} at {b['path']}", "hermes annotary setup")
    try:
        server.ensure_running()
        check(True, f"server answers at {paths.server_url()}")
    except Exception as e:  # noqa: BLE001
        check(False, f"server: {e}", "hermes annotary logs")
    if desktop.retire_standalone_page():
        print("     removed an earlier version's standalone copy of the page")
    page = desktop.page_status()
    if page["ok"]:
        check(True, f"desktop page at {page['path']} (published by Hermes with this plugin)")
    elif not page["present"]:
        print("note desktop page not published yet: Hermes copies it when Desktop or the Webapp next loads plugins")
    elif page["paired"]:
        print("note desktop page is an older copy: reload Desktop or the Webapp and Hermes refreshes it")
    else:
        check(False, f"desktop page folder {page['path']} is not this plugin's (no package marker)",
              "move that folder away, then reload Desktop or the Webapp")
    try:
        report = accounts.reconcile()
        st = state.load()
        missing = [p for p in _profile_ids() if p not in st["members"] or not accounts.token_for(p)]
        check(not missing, f"a Member and Token for every profile ({len(st['members'])} mapped)"
              + (f"; missing: {missing}" if missing else ""), "hermes annotary members")
        for pid, what in report.items():
            print(f"     {pid}: {what}")
    except Exception as e:  # noqa: BLE001
        check(False, f"members: {e}")
    for pid in _profile_ids():
        plugin = enablement.plugin_state(pid)
        what = {enablement.ON: f"Annotary tools and skill on in profile {pid}",
                enablement.OFF: f"Annotary is off in profile {pid}: its agent has no Annotary tools or skill",
                enablement.COPY: f"profile {pid} runs its own copy of the plugin (cloned), which updates never reach",
                enablement.DECLINED: f"Annotary is off in profile {pid}, as you chose (to turn it on: "
                                     f"{enablement.turn_on(pid)})"}
        check(plugin in (enablement.ON, enablement.DECLINED), what[plugin], enablement.FIX)
    try:
        you = accounts.person()
        if you["named"]:
            check(True, f"you are @{you['handle']} ({you['name']})")
        else:
            print(f"note you show as @{you['handle']} until you give a name: {NAME_FIX}")
    except Exception as e:  # noqa: BLE001
        check(False, f"your Member: {e}")
    if state.load().get("page_seen_at"):
        check(True, "the Annotary page has loaded in Desktop or a browser")
    else:
        print("note the Annotary page has not loaded anywhere yet: in the Webapp, turn on Annotary in "
              "Capabilities → Plugins (once per browser); Desktop turns it on by itself")
    w = _run_hermes(["webapp", "--status"])
    print("Webapp:\n  " + "\n  ".join((w.stdout or w.stderr).strip().splitlines()[:8]))
    for line in _webapp_notes(w.stdout or w.stderr):
        print(line)
    print(f"Wake-ups: {wake_state()}  (hermes annotary wake on|off)")
    return 1 if problems else 0


def _webapp_notes(status_text: str) -> list[str]:
    """The public address when there is one, and the setup advice only for a Webapp not set up."""
    enabled, public = webapp.settings()
    if enabled or "Serving at" in status_text:
        return [f"  Annotary links open the Annotary page at {public}/?annotary=<id>."] if public else []
    return ["  Where Web Access cannot be switched on (a VPS, Docker, Hermes Cloud), set in config.yaml:",
            "    webapp:\n      enabled: true\n      public_url: https://<the HTTPS address you serve it at>",
            "  and a sign-in provider (see Hermes's docker.md, \"Behind a tunnel or reverse proxy\").",
            "  Annotary links then open the Annotary page at <public_url>/?annotary=<id>."]


NAME_FIX = 'hermes annotary name "Your Name"'


def name(args) -> int:
    """The person's name; while they have none, also their handle (see accounts.name_person)."""
    server.ensure_running()
    try:
        out = accounts.name_person(" ".join(args.name))
    except ValueError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    print(f"You are @{out['handle']}, shown as {out['name']}."
          + (f" @{out['was']} is retired." if out.get("changed_handle") else ""))
    return 0


def stop(_args=None) -> int:
    _print(server.stop())
    return 0


def logs(args) -> int:
    f = server.log_file()
    lines = f.read_text(errors="replace").splitlines()[-int(getattr(args, "lines", 50) or 50):] if f.exists() else []
    print("\n".join(lines) or f"(no log yet at {f})")
    return 0


def setup_argparse(parser) -> None:
    subs = parser.add_subparsers(dest="annotary_command")
    subs.add_parser("setup", help="Install the server, the desktop page and the Members")
    subs.add_parser("status", help="Server, page, Members and recent wake-ups")
    subs.add_parser("members", help="Which Member each profile is")
    en = subs.add_parser("enable", help="Turn the tools on in one profile, or in every profile you have not turned off")
    en.add_argument("profile", nargs="?", help="One profile, including one where you turned Annotary off")
    en.add_argument("--all", action="store_true", help="Every profile, except any where you turned Annotary off")
    wk = subs.add_parser("wake", help="Let comments wake the chat that shared a Document")
    wk.add_argument("state", choices=["on", "off"])
    nm = subs.add_parser("name", help="The name Annotary shows for you (and your handle, until you have one)")
    nm.add_argument("name", nargs="+")
    subs.add_parser("doctor", help="Check and repair the install; Webapp settings")
    subs.add_parser("stop", help="Stop the private Annotary server")
    lg = subs.add_parser("logs", help="The server's log")
    lg.add_argument("-n", "--lines", type=int, default=50)
    parser.set_defaults(func=main)


COMMANDS = {"setup": setup, "status": status, "members": members, "enable": enable, "wake": wake,
            "name": name, "doctor": doctor, "stop": stop, "logs": logs}


def main(args) -> int:
    cmd = getattr(args, "annotary_command", None)
    if cmd not in COMMANDS:
        print("usage: hermes annotary {setup|status|members|enable --all|enable PROFILE|wake on|off|name NAME|doctor|stop|logs}")
        return 1
    try:
        return COMMANDS[cmd](args) or 0
    except (server.ServerError, install.InstallError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
