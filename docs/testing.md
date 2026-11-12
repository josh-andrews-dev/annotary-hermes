# Testing

## Unit and live tests

`make test` runs pytest against a real `annotary serve` (the pinned release, downloaded once and
checked against its SHA-256) in a throwaway Hermes root, plus the desktop page's Node tests. No
model is called.

## Live review loop

`make live-loop` (or `python3 scripts/project/live_loop.py --profile coder`) checks a model, or a
change to the skill, tool descriptions or wake-up message, against a real Hermes install. It
opens an interactive session of the profile in a pseudo-terminal so the gateway can wake it, then:

1. asks the agent for a short plan and to share it with Annotary;
2. leaves two comments as the owner and chooses Send back;
3. waits for the woken agent to push Version 2 once, reply on each Thread citing it, and resolve
   both.

It prints a JSON report (timings, every reply) and exits 0 only when the agent did all of it. It
needs the plugin installed and wake-ups on for the profile (`hermes annotary wake on`). It uses
the profile's model; `--model` overrides it for one session.

The session runs in a temporary folder, so files the agent writes stay out of your checkout. At
the end, every Document the profile shared during the run is permanently removed: from the
server, its staged files and its entry in `state.json`. Do not use the profile for real work
while the loop runs, or that work goes too. Earlier Documents and other profiles' are left alone.
A failed owner step stops the run at once, and a Document that cannot be removed fails the run
and is named on stderr.

## Which model

Live checks run on Nous's free models, which do not count against usage limits: provider `nous`,
model `meituan/longcat-2.5:free`.

| Model | One tool call | Full review loop |
|---|---|---|
| `meituan/longcat-2.5:free` | correct | passed three times: one push, a reply on each Thread citing v2, both resolved, 50 to 160 s after Send back |
| `stepfun/step-3.7-flash:free` | correct, but about 4 minutes | not run: too slow |

The demo recording uses `deepseek/deepseek-v4.1-flash-1017` (provider `nous`). Switch every
profile with `hermes -p <profile> config set model.default <model>` and back the same way.

## A branch on a hosted Hermes

To check a branch on a Hermes you reach only through its Webapp (Hermes Cloud), push it, then have that instance's
agent run `hermes plugins install --force --ref <full 40-character commit SHA> <repo URL>`: the Webapp's Install from
Git takes no ref, and `--ref` takes a full SHA only. Then three things are still the old build, each until its own step:
- The published page (`$HERMES_ROOT/desktop-plugins/annotary/plugin.js`): a CLI install updates the plugin's
  `desktop/` but not this copy. The Webapp re-runs Hermes's half copy when it loads its plugins
  (`GET /api/desktop-plugins/root`); from a shell, `reconcile_desktop_halves_report` in `hermes_cli/desktop_plugin_halves.py`.
  Check it with `grep -c attachFrame` or a hash.
- The tools: until the gateway restarts (`hermes gateway restart --detach`, or the status menu at the bottom left ("Backend ready") → Restart gateway).
- The page's backend (`dashboard/plugin_api.py`): the dashboard imports it once and never again for a plugin already
  mounted, so a new route stays missing until the dashboard restarts. On Hermes Cloud the dashboard runs under s6:
  `s6-svc -r /run/service/dashboard` from the instance's terminal (`hermes dashboard` has no restart).

A wake-up on a hosted Hermes needs its own check from a Desktop chat: the dashboard hosts those chats (session keys
like `20261111_212221_fc90ed`, `host: desktop` in `state.json`) and the dashboard's watcher wakes them, which
`make live-loop`'s terminal session never exercises. `outcome: "woke"` in `hermes annotary status` only means Hermes
took the message; the turn ran only if the chat shows it, and a gateway log line `Plugin message injection was not
routed` marks a miss.

Hermes Desktop on a Mac connected to the instance showed the page from that Mac's own Hermes install
(`~/.hermes/desktop-plugins/annotary/`, refreshed on View → Reload), not the instance's copy, so check the page in the
Webapp, or update that Mac's plugin too. To see the page as a new browser does, remove
`hermes.desktop.pluginDecisions.v2` from the tab's localStorage.

To act as a person on a fresh Hermes Cloud install, mind that the plugin's setup there runs as the OS user `hermes`,
so the person starts as `@owner` (see `server.SERVICE_USERS`); the `hermes_cloud` test fixture sets up the same way.
A Safari result from the iOS Simulator is not a result about iPhones: the Simulator's Capabilities page failed where a
real iPhone, reaching it through a link's Open Plugins button, worked. Check phone claims on a device.
