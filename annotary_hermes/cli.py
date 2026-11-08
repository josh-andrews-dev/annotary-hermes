"""``hermes annotary …``: setup, status, members, enable --all, wake on|off, doctor, stop, logs."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

from . import accounts, desktop, install, paths, server, state


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
    """Install the binary, set up and start the server, put the page in place, reconcile."""
    r = server.ensure_running()
    page = desktop.install_page()
    report = accounts.reconcile()
    print(f"Annotary server: {r['outcome']} at {paths.server_url()} (data in {paths.data_dir()})")
    print(f"Desktop page: {'updated' if page['changed'] else 'current'} at {page['path']}")
    if page.get("removed_marker"):
        print(f"  removed a package marker someone wrote there: {page['removed_marker']}")
    for pid, what in report.items():
        print(f"  {pid}: {what}")
    return 0


def status(_args=None) -> int:
    h = server.health()
    st = state.load()
    _print({"server": paths.server_url(), "running": bool(h and h.get("ok")), "health": h,
            "binary": install.installed(), "desktop_page": desktop.page_status(),
            "documents": len(st["docs"]), "members": len(st["members"]),
            "wake": wake_state(), "recent_wakes": st.get("wake_log", [])[-5:]})
    return 0


def members(_args=None) -> int:
    server.ensure_running()
    accounts.reconcile()
    st = state.load()
    print(f"{'PROFILE':<16} {'HANDLE':<20} {'NAME':<24} STATE")
    owner = server.owner_handle()
    print(f"{'(you)':<16} @{owner:<19} {'':<24} owner")
    for pid, m in sorted(st["members"].items()):
        flag = "disabled" if m.get("disabled") else "active"
        tok = "token ok" if accounts.token_for(pid) else "no token"
        print(f"{pid:<16} @{m['handle']:<19} {m.get('name', ''):<24} {flag}, {tok}")
    return 0


def _profile_ids() -> list[str]:
    return [p.id for p in accounts.list_profiles()]


def enable_all(_args=None) -> int:
    """D6: make the plugin available and enabled in every profile, then set up."""
    root = paths.hermes_root()
    src = paths.package_dir()
    root_link = root / "plugins" / paths.PLUGIN_ID
    failures = 0
    for pid in _profile_ids():
        home = paths.profile_home(pid, root)
        here = home / "plugins" / paths.PLUGIN_ID
        if pid != "default" or not here.exists():
            if not here.exists() and not here.is_symlink():
                here.parent.mkdir(parents=True, exist_ok=True)
                target = root_link.resolve() if root_link.exists() else src
                here.symlink_to(target, target_is_directory=True)
                print(f"{pid}: linked {here} -> {target}")
        r = _run_hermes(["-p", pid, "plugins", "enable", paths.PLUGIN_ID])
        ok = r.returncode == 0
        failures += 0 if ok else 1
        print(f"{pid}: {'enabled' if ok else 'enable failed: ' + (r.stderr or r.stdout).strip()[-200:]}")
    setup()
    print("Restart the gateway to load the tools in every profile: hermes gateway restart --detach")
    return 1 if failures else 0


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
    page = desktop.page_status()
    if not page["ok"]:
        fixed = desktop.install_page()
        print(f"     repaired the desktop page (removed marker: {fixed.get('removed_marker')})")
        page = desktop.page_status()
    check(page["ok"], f"desktop page at {page['path']} (standalone, no package marker)")
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
        r = _run_hermes(["-p", pid, "plugins", "list"])
        enabled = any(paths.PLUGIN_ID in line and "enabled" in line for line in r.stdout.splitlines())
        check(enabled, f"tools enabled in profile {pid}", "hermes annotary enable --all")
    w = _run_hermes(["webapp", "--status"])
    print("Webapp:\n  " + "\n  ".join((w.stdout or w.stderr).strip().splitlines()[:8]))
    print("  Where Web Access cannot be switched on (a VPS, Docker, Hermes Cloud), set in config.yaml:\n"
          "    webapp:\n      enabled: true\n      public_url: https://<the HTTPS address you serve it at>\n"
          "  and a sign-in provider (see Hermes's docker.md, \"Behind a tunnel or reverse proxy\").\n"
          "  Annotary links then open the Annotary page at <public_url>/#/annotary?doc=<id>.")
    print(f"Wake-ups: {wake_state()}  (hermes annotary wake on|off)")
    return 1 if problems else 0


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
    en = subs.add_parser("enable", help="Turn the tools on in profiles")
    en.add_argument("--all", action="store_true", required=True, help="Every profile")
    wk = subs.add_parser("wake", help="Let comments wake the chat that shared a Document")
    wk.add_argument("state", choices=["on", "off"])
    subs.add_parser("doctor", help="Check and repair the install; Webapp settings")
    subs.add_parser("stop", help="Stop the private Annotary server")
    lg = subs.add_parser("logs", help="The server's log")
    lg.add_argument("-n", "--lines", type=int, default=50)
    parser.set_defaults(func=main)


COMMANDS = {"setup": setup, "status": status, "members": members, "enable": enable_all, "wake": wake,
            "doctor": doctor, "stop": stop, "logs": logs}


def main(args) -> int:
    cmd = getattr(args, "annotary_command", None)
    if cmd not in COMMANDS:
        print("usage: hermes annotary {setup|status|members|enable --all|wake on|off|doctor|stop|logs}")
        return 1
    try:
        return COMMANDS[cmd](args) or 0
    except (server.ServerError, install.InstallError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
