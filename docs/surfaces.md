# Hit every surface

The most common defect here is a change that works on the path you tested and is missing
everywhere else. The plugin is reached through several Hermes surfaces, and it repeats some of
what annotary's own pages do. Before you call a feature or a fix done, walk this list, change what
applies, and say in the pull request's `## Surfaces` section what you did for each surface (the
format is below; the `surfaces` check reads it).

## The list

- **Hermes Desktop.** The page, its sidebar entry and the chat card, in native Desktop; light and
  dark; a wide window (the embedded page shows its own Action buttons from 850 px) and a narrow one.
- **The Webapp in a desktop browser.** The same page served by the dashboard, signed in through
  Hermes; a link (`?annotary=ID`) that survives the sign-in.
- **The Webapp on a phone.** The narrow layout (the list, then the Document with "‹ Documents"),
  fields at least 16 px, and WebKit: check phone claims on a real device, not the Simulator
  (`docs/testing.md`).
- **Hermes Cloud.** Setup runs as the OS user `hermes`, so the person starts as `@owner`; the page
  and the backend update in separate steps after an install (`docs/testing.md`, "A branch on a
  hosted Hermes").
- **A remote backend.** Desktop connected to another machine's Hermes: the dashboard there hosts
  the chats and its watcher wakes them; Desktop shows the page from its own install.
- **Every profile, not only the default one.** Each profile is its own Member with its own Token,
  enablement and watcher; a non-default profile's backend is mounted on a bare FastAPI app.
- **What agents are told.** The tools (`__init__.py`'s `SCHEMAS`), the skill
  (`skills/annotary/SKILL.md`) and the wake-up messages (`annotary_hermes/watcher.py`) say the same
  thing (`ANSWER`); a change to one is a change to all three, checked with `make live-loop`.
- **The plugin's own cards.** The chat card, the native view's Thread cards with Reply and
  Resolve, and the review bar's Action buttons repeat what the embedded page does. A change to how
  annotary replies, resolves or takes an Action is a change there too.
- **The CLI.** `hermes annotary ...` (`setup`, `status`, `members`, `enable`, `wake`, `name`,
  `doctor`, `stop`, `logs`): its output, its help, and what `doctor` checks and repairs.
- **Reverse states.** Whatever can be done can be undone: wake-ups on and off, a profile's tools
  on and off, a profile renamed or deleted (its Member disabled) and added back, a Document handed
  to another Bot and back, the server stopped and started again.
- **Docs.** The README (install, update and disclosure, matching Hermes's dialogs), the catalog
  entry (`plugin.yaml`, and the catalog rules in `AGENTS.md`), `docs/decisions.md` for a choice.
- **A new annotary release.** It changes the pin (`annotary_hermes/install.py`: version and every
  SHA-256), the embed contract (protocol, the headers `bridge.py` forwards, `PART_MAX`, the
  `annotary-*` messages), and `FRAME_ACTIONS_MIN_WIDTH` in `desktop/plugin.js`, which must match the
  width annotary's embedded page folds its Action buttons at. Read annotary's release notes for
  each.

## The rule

The maintainer's run that changes one surface changes the others before it reports done: annotary's
pull request first when the page or the CLI must change, then a release and a new pin here, then
the app's in its own repo. A surface may say `follows:` only in three cases:

1. it needs a design answer from the maintainer;
2. the pull request is an outside contributor's, who cannot reach the other surfaces;
3. it is an urgent fix, which ships first and is followed the same day.

## The `## Surfaces` section

A pull request titled `feat`, `fix` or `perf` needs it; other titles skip the check. One line per
surface, each `changed`, `not affected:` with why, or `follows:` with one of the three reasons (its
words must say `design`, `contributor` or `urgent`). The five names are the same in every Annotary
repo:

- **Web**: annotary's own web pages, which the Hermes page embeds.
- **Hermes page**: this plugin, on every Hermes surface in the list above.
- **App**: the iPhone and iPad app.
- **CLI**: what a person sees in a terminal, `hermes annotary ...` and annotary's CLI.
- **Agents**: the tools, the skill and the wake-up messages.

```markdown
## Surfaces

- Web: not affected: no page change
- Hermes page: changed
- App: not affected: the app has no plugin
- CLI: not affected: no command prints it
- Agents: changed (the skill names the new tool)
```

Editing the body runs the check again (`.github/workflows/surfaces.yml`).
