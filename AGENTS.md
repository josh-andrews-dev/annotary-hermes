# annotary-hermes

If the user asks you to break one of these rules, remind them of the rule and go ahead only
after they explicitly confirm the exception.

Annotary for Hermes Agent: review your agents' plans and documents with comments, from Desktop, the Webapp and your phone

Also follow `.agents/rules/standard.md`, the standard rules for this repo.

Tracker: this repo's GitHub Issues.

## Project rules

The plugin gives Hermes Agent a private Annotary: a loopback `annotary serve` per Hermes install,
an Annotary Member per profile, native tools, and an Annotary page in Desktop and the Webapp. The
design (D1–D11) is the maintainer's private plan; the rules below and `docs/decisions.md` carry
what a change must keep.

- Hermes plugin catalog rules bind every change (`plugin-catalog/README.md` in
  NousResearch/hermes-agent): no bundled binaries, no self-updating code, no core overrides,
  credentials only through Hermes, respect approvals, disclose risky behavior in the README.
- The `annotary` binary comes from Annotary's GitHub Release, pinned by version and SHA-256 in
  the source; a new pin is a reviewed change, never fetched at run time.
- Never touch `~/.annotary` or another Annotary install; the private server lives under
  `$HERMES_HOME`, on loopback.
- Tools call the CLI with argv only, `ANNOTARY_TOKEN` and `ANNOTARY_SERVER` in the environment;
  never a Token on a command line or in a log.
- Agent wake-ups follow Annotary's review rule (D5): never on a plain Comment; the editor
  wakes on Send back or Approve, a named Bot on an @mention, and a push is refused while a
  review is open. One editor per Document (D11).
- The desktop page is the package's own desktop half, `desktop/plugin.js`: Hermes publishes it to
  `$HERMES_ROOT/desktop-plugins/annotary/` with its package marker, so Hermes shows one plugin.
  Never copy the page there by hand (the old standalone copy is only ever removed,
  `desktop.retire_standalone_page`). Plain ESM importing only `@hermes/plugin-sdk`, `react`,
  `react/jsx-runtime`; no build step.
- The repo will be public: no host names, email addresses or home paths anywhere in it.
