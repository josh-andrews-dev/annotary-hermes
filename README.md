# Annotary for Hermes Agent

Annotary for Hermes Agent: review your agents' plans and documents with comments, from Desktop,
the Webapp and your phone.

An agent shares a Markdown plan; you comment on exact lines in the **Annotary** page (Desktop's
sidebar, or the Webapp in any browser, phone included); you press **Send back** or **Approve**; the
agent wakes in the chat that shared it, fixes what you asked, pushes one new Version, and answers
each Thread. Unlike Desktop's in-browser "Annotate" mode, which drops one note into the composer,
a Document keeps its Versions, Threads and replies.

## Install

```bash
hermes plugins install josh-andrews-dev/annotary-hermes --enable
hermes annotary enable --all        # tools in every profile (see below)
hermes gateway restart --detach
hermes annotary wake on             # optional: let Send back, Approve and @mentions wake the chat
```

Needs Hermes 0.23.0 or newer, on macOS or Linux (WSL counts as Linux).

## What you get

- **One private Annotary server** for the whole Hermes install, on `127.0.0.1:7391` only.
- **An Annotary account (Member) per profile**, kept in step with your profiles: a new profile
  gets one within 5 minutes, a renamed one keeps its Member (through `previous_names`), a deleted
  one is disabled (its comments keep their author), and a profile made again under the same name
  gets the same Member back, enabled, with a new Token (the old one stays revoked). Each Bot's handle is its Bot Mode tag
  (`@coder`; the default profile is `@hermes` until you name it). You are the owner, named after
  your OS user. `hermes annotary members` shows the mapping.
- **Each Bot's face next to its comments**: the Bot Mode face from Desktop, animated when Desktop
  animates it and still under reduced motion. A change to a Bot's face reaches Annotary within
  5 minutes. Needs Annotary 0.5.0 or newer; an older server keeps its initials.
- **Native tools** (no approval prompts, and they work in profiles with no terminal):
  `annotary_share`, `annotary_threads`, `annotary_reply`, `annotary_push_version`,
  `annotary_handoff`, `annotary_act`, `annotary_list`, and a skill, `annotary`.
- **The Annotary page**: the Document list, then the Document itself: Annotary's own page in a
  sandboxed frame (Annotary's embed mode), fed through this plugin's backend, so it
  works on native Desktop, Desktop over SSH and the Webapp on a phone. Above it, the Document's
  editor and **Send back** / **Approve**. If the server cannot serve the frame (a development
  build without embed mode), the page shows the rendered Document, open Threads with reply and
  resolve, and a comment box instead. Chats on Desktop show
  an inline card for each shared Document.

## The review rule

The plugin, not the model, decides when an agent wakes:

- A plain comment wakes nobody: you can comment as long as you like.
- **Send back** or **Approve** wakes the Document's editor (the Bot that shared it) in the chat
  that shared it, with every open Thread.
- An **@mention** wakes only the Bot it names, to answer, never to edit.
- `annotary_push_version` refuses while a review is open, and refuses any Bot but the editor.
  `annotary_handoff` moves the editor.
- An agent's @mention of another agent wakes it at most 3 times per Document per hour.

Waking needs Hermes's `allow_gateway_injection` permission for this plugin, per profile. It is
off until you turn it on (`hermes annotary wake on`, or Settings → Plugins); the first share tells
you how. While it is off, Send back, Approve and @mentions show as notifications, and the agent
sees them on its next Annotary tool call.

## What it writes, and where

Disclosed per the Hermes plugin catalog rules. Nothing leaves the machine except the one download.

| What | Where | Why |
|---|---|---|
| The `annotary` binary | `$HERMES_ROOT/annotary/bin/` | Downloaded once, at first use, from [Annotary's GitHub Release](https://github.com/josh-andrews-dev/annotary/releases), pinned by version and SHA-256 in [`annotary_hermes/install.py`](annotary_hermes/install.py) and checked before it is used. Never updated by itself: a new pin is a new plugin version. Each release tarball also carries a GitHub build attestation, so you can check where it was built: `gh attestation verify annotary-<target>.tar.gz --repo josh-andrews-dev/annotary`. |
| The server's data | `$HERMES_ROOT/annotary/data/` | Documents, Threads and Members. Never `~/.annotary`: a standalone Annotary keeps running beside it. |
| A background server | `annotary serve` on `127.0.0.1:7391` | Started when first needed and left running detached, so it outlives gateway restarts. Its update check is off. `hermes annotary stop` stops it. |
| Owner password and Token | `$HERMES_ROOT/annotary/secrets.json`, mode 600 | A long random password nobody types (it stops a browser on this machine signing in to the bare server by loopback trust); you reach Annotary only through Hermes's own sign-in. |
| One Token per profile | `<profile home>/plugin-data/annotary/token`, mode 600 | What that profile's tools act as. Never on a command line or in a log. |
| Shared state | `$HERMES_ROOT/annotary/state.json` | Which Member each profile is, each Document's editor and sharing session. No secrets. |
| Each Bot's face | The private server (from `profile.yaml` and `assets/avatar.*`) | Read from the profile and uploaded to the loopback server with that Bot's own Token, only when it changes. A photo is sent as it is. |
| The page | `$HERMES_ROOT/desktop-plugins/annotary/plugin.js` | See below. |
| Plugin links | `<profile home>/plugins/annotary` → the installed plugin | Only from `hermes annotary enable --all`, which then runs `hermes -p <profile> plugins enable annotary` for each profile. |

**Why the page is a standalone desktop plugin.** Hermes loads a package's own `desktop/` half
switched off in each new browser, and in Safari on Hermes 0.23 the Capabilities page that switches
it on fails, so on a phone you could never turn the page on. A desktop plugin folder without
Hermes's package marker loads switched on everywhere. So this package keeps its page in
`desktop-page/`, which Hermes does not load as a package half, and its setup step (first use,
`hermes annotary enable --all` and `hermes annotary doctor`) copies it to
`$HERMES_ROOT/desktop-plugins/annotary/` with no marker. Hermes never pairs, adopts or prunes that
folder; `hermes plugins remove annotary` leaves it, so delete it by hand after removing the plugin.

## Commands

| Command | What it does |
|---|---|
| `hermes annotary setup` | Install the binary, start the server, put the page in place, sync Members |
| `hermes annotary status` | Server, page, Members and recent wake-ups, as JSON |
| `hermes annotary members` | Which Member each profile is |
| `hermes annotary enable --all` | Tools on in every profile (a profile made later needs it again) |
| `hermes annotary wake on\|off` | Let Send back, Approve and @mentions wake the chat |
| `hermes annotary doctor` | Check and repair; prints the `webapp:` settings for a VPS or Docker |
| `hermes annotary stop` / `logs` | Stop the server / its log |

On a VPS, in Docker or on Hermes Cloud, where Desktop's Web Access switch cannot be used, turn the
Webapp on in `config.yaml` (`webapp.enabled`, `webapp.public_url`, a sign-in provider);
`hermes annotary doctor` prints the exact block.

## Development

`make help` lists the commands; `make lint test` before a pull request. The tests run a real
`annotary serve` (the pinned release, downloaded once into `~/.cache/annotary-hermes-tests`).
`ANNOTARY_HERMES_DEV_BINARY=/path/to/annotary` runs an unreleased Annotary build instead (every
Hermes process needs it: the gateway does not inherit your shell, so put it in Hermes's `.env`
while you test, and restart the gateway after taking it out, since a running gateway keeps it and
starts the server on that build again), `ANNOTARY_HERMES_PORT` moves the server, and `ANNOTARY_HERMES_DOWNLOAD_CACHE`
keeps checked release tarballs between runs; all three are for development only. Without the
first, a server found running any binary but the pinned one, read from the server process itself
so a dev build that reports the pinned version counts too, is stopped and restarted on the pinned
one on the next call (also after a plugin upgrade that moves the pin). To switch at once after
taking the override out, run `hermes annotary stop`. `make validate` runs Hermes's plugin
validator where Hermes is installed.

A development build newer than the pinned binary migrates the server's store, and the pinned binary then refuses to open it. Copy `$HERMES_ROOT/annotary` before pointing a real install at one, and put the copy back afterward.

## Contributing

Bug reports and feature requests go to [Issues](https://github.com/josh-andrews-dev/annotary-hermes/issues),
questions to [Discussions](https://github.com/josh-andrews-dev/annotary-hermes/discussions). See
[CONTRIBUTING.md](CONTRIBUTING.md), and [SECURITY.md](SECURITY.md) for security reports.

## License

The Bot face code carries MIT-licensed ports of Hermes Desktop's faces and of blobatar: see
[docs/THIRD_PARTY.md](docs/THIRD_PARTY.md).

Licensed under either of [Apache License, Version 2.0](LICENSE-APACHE) or [MIT license](LICENSE-MIT)
at your option.

Unless you explicitly state otherwise, any contribution intentionally submitted for inclusion in
this project by you, as defined in the Apache-2.0 license, shall be dual licensed as above,
without any additional terms or conditions.
