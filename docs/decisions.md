# Decisions

Dated choices for annotary-hermes, as "chose X; rejected Y because Z". The design itself (D1–D11)
is in the Annotary repo, `docs/plans/hermes-edition.md`.

## 2026-11-07: the first version (the basic loop)

- **The desktop page is a standalone desktop plugin.** Chose to ship it as `desktop-page/plugin.js`
  and copy it, with no `.hermes-package.json` marker, to `$HERMES_ROOT/desktop-plugins/annotary/`
  from the plugin's setup step; rejected a package `desktop/` half because Hermes 0.23 loads a
  package half switched off in each new browser and Safari's Capabilities page cannot switch it
  on, and because Hermes's half-copier (Electron's and the Webapp's) adopts a marker-less copy
  whose `plugin.js` is byte-equal to a package half by writing a marker into it.
- **One watcher thread per profile, in the gateway only.** Chose per-profile watchers that act
  only on their own profile's wake-ups; rejected one shared watcher because
  `ctx.inject_message` reaches only the calling plugin's own profile. One of them (an flock)
  broadcasts live updates and runs the 5-minute reconcile. `register()` starts nothing outside
  `hermes gateway run`, since it runs in every `hermes` command.
- **Shared state on disk, under one flock.** Chose `$HERMES_ROOT/annotary/state.json`; rejected
  module globals because each profile imports its own copy of the plugin module and the backend
  runs in other processes.
- **The watcher reads events with the owner Token.** Chose the owner's view and the plugin's own
  classification (mentions as handles, author handle); rejected each agent's `mention` kind
  because Send back and Approve must reach the editor whether or not it is mentioned.
- **Tools call the CLI; the watcher, reconcile and backend call the HTTP API.** The CLI keeps
  Assets and Sidecars exactly as in Annotary; the API is cheaper for reads and long-polls. Either
  way the Token travels in the environment or a header, never on a command line.
- **The bridge refuses answers over 1 MB** (750 KB of binary, which grows by a third as base64)
  with 413, because the spike measured that a message over about 1 MB stalls the gateway. The
  frame then shows the Asset's "Open" button. Annotary's embed image limit was 2 MiB; at our
  request it is now 700 KiB, under the cap.
- **A returning profile gets its own Member back.** Annotary never reuses a handle, so a profile
  made again under a deleted one's name is matched to its disabled Member by profile id. Chose
  `annotary member enable` plus a newly minted Token (enabling keeps the old Tokens revoked);
  rejected minting `@name-2` because the Bot would lose its handle and its history.

## 2026-11-07: review round 1

- **A new pin replaces a running server's binary.** Chose to check the binary on ensure-running's
  fast path and, under the ensure lock, install the pinned binary and restart a server running
  anything else; rejected installing only when the server is down because a running server would
  then keep an old binary forever. The dev override skips the version check.
- **Each markdown share gets its own folder** (`shares/<doc id>/`); rejected one shared folder
  because the Sidecar `annotary push` leaves there bound a later share with the same name to the
  earlier Document. Sharing a file whose Sidecar already binds a Document is a new Version of it,
  under the editor and review rules.
- **A review restarts at the latest push, Send back or Approve**, and is open while a person's
  comment follows it; rejected "any Action ends the review" because a comment after Approve was
  then ignored.
- **Re-enabling a Member is detected, not assumed**: from `annotary member --help` (superseded by the v0.4.1 pin below).

## 2026-11-07: Annotary v0.4.1

- **Pinned Annotary v0.4.1** (embed mode, ordered Members, `serve --setup-only --json`,
  `member enable`); v0.4.0 has no release. Chose to read only the setup command's JSON; rejected
  keeping the `ANNOTARY_TOKEN=` fallback because only v0.3.4 printed that form. Chose to make the
  embed tests required (they fail, not skip, when the pinned server has no shell) because the
  pin guarantees embed mode.
- **`member enable` is called, not detected.** Every pinned binary has it; a failure is reported
  in the reconcile and tried again on the next pass, so one profile cannot stop the others.

## 2026-11-08: agents answer the comments they act on

- **The skill, the tool descriptions, the push result and every wake-up say the same rule** as
  Annotary's own skill (its S39-01): push once, then answer each Thread you acted on, briefly,
  like a colleague (what changed and in which Version, or why not); a question gets an answer and
  no edit; an unclear comment gets a question back; resolve only what is fully addressed.
  Rejected changing the skill alone, because a woken agent acts on the wake-up message and the
  tool result in front of it more than on a skill it may not reload.
- **The wake-up's Thread list marks each Thread with no reply from the woken Bot** "(waiting for
  your answer)", so it knows which ones still need one.

## 2026-11-08: review round 2 follow-ups

- **The running binary is read from the server process.** Chose to compare the server's own
  command line (`ps`) with the pinned binary's path when the version matches; rejected recording
  the binary in `server.pid` because a server started before that record existed, or by another
  copy of the plugin, has none, and the record can go stale while the process cannot.

## 2026-11-08: live checks on a free model

- **Live checks run on `meituan/longcat-2.5:free`** (provider `nous`), which does not count
  against usage limits. Chose it after it passed the full review loop three times (share, Send back
  with two comments, one push, a reply on each Thread citing v2, both resolved); rejected
  `stepfun/step-3.7-flash:free` because one tool call took about 4 minutes. The demo recording
  stays on `deepseek/deepseek-v4.1-flash-1017`. See `docs/testing.md`.
- **The live loop drives a real interactive session in a pseudo-terminal**; rejected `hermes chat
  -q` because Hermes refuses to wake a session whose command has exited.

## 2026-11-08: every profile knows Annotary

- **The plugin reads each profile's plugin state from its files**, not `hermes -p X plugins list`:
  the gateway's reconcile runs every 5 minutes, and the old line match counted any plugin whose
  name contains "annotary".
- **The plugin never enables itself in a profile.** Chose to report it (members, doctor,
  reconcile) and to point at `hermes annotary enable --all`; rejected enabling from the reconcile
  because a third-party plugin starts off per profile and turning it on is the person's choice.
- **`enable --all` replaces a cloned copy of the plugin with a link**; rejected leaving it because
  a clone of default (Desktop's Bot Mode) would run that day's plugin code forever.
- **A profile where the person turned the plugin off is its own state (`DECLINED`)**, read from
  `plugins.disabled` or a plugin folder that isn't enabled. Chose to leave it off in `enable --all`
  and to raise no complaint; rejected treating it like a profile never set up, because that turned
  it back on unasked. `hermes annotary enable PROFILE` is the way back in. So a link is taken back
  when `hermes plugins enable` fails, or the half-done profile would read as declined.
- **A Document is never handed to a Bot whose profile has Annotary off**: it could not edit, and
  no watcher runs there to wake it.
- **The skill is registered with its description**, because Hermes lists a plugin skill in the
  system prompt with the description passed to `register_skill` and reads none from the file.

## 2026-11-08: Bots review each other

- **`annotary_comment` takes a quote, not a position.** The tool finds the passage in the head
  Version and posts its `L:C-L:C` range with `--version`. A quote that is missing or matches more
  than once is refused with what to do; rejected picking the first match, because a comment on the
  wrong line reads as a real one.
- **`annotary_read` was added with it.** A reviewer has to see a Document it did not write, and a
  profile may have no terminal. Rejected adding the text to `annotary_threads`, which every woken
  agent calls and would pay for each time.
- **A Bot's Send back or Approve wakes the editor** (never the editor's own). Rejected keeping it
  to people, because a Bot's Send back then did nothing at all. It counts against the cap of 3
  wake-ups between Bots per Document per hour.
- **A Bot's Action does not end a person's review.** Its Send back still wakes the editor, but
  while a person has commented and not decided, the editor's push stays refused. Rejected letting a
  Bot end it, because that would let an agent overrule someone who is still reading.
