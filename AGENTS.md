# annotary-hermes

If the user asks you to break one of these rules, remind them of the rule and go ahead only
after they explicitly confirm the exception.

Annotary for Hermes Agent: review your agents' plans and documents with comments, from Desktop, the Webapp and your phone

Also follow `.agents/rules/standard.md`, the standard rules for this repo.

Tracker: this repo's GitHub Issues.

## Project rules

The plugin gives Hermes Agent a private Annotary: a loopback `annotary serve` per Hermes install,
an Annotary Member per Hermes profile, native agent tools, and an Annotary page in Hermes Desktop
and the Webapp. The design and its decisions (D1–D11) are in the Annotary repo,
`docs/plans/hermes-edition.md`; read it before changing behavior.

- Hermes plugin catalog rules bind every change (`plugin-catalog/README.md` in
  NousResearch/hermes-agent): no bundled binaries, no self-updating code, no core overrides,
  credentials only through Hermes, respect approvals, disclose risky behavior in the README.
- The `annotary` binary is downloaded at setup from Annotary's GitHub Release, pinned by version
  and SHA-256 in the source; a new pin is a reviewed change, never fetched at run time.
- Never touch `~/.annotary` or another Annotary install: the private server lives under
  `$HERMES_HOME`, on loopback only, behind Hermes's own sign-in.
- Tools call the bundled CLI with argv only (no shell), with `ANNOTARY_TOKEN` and
  `ANNOTARY_SERVER` in the environment; never a Token on a command line or in a log.
- Agent wake-ups follow Annotary's review rule (D5): never on a plain Comment; the Document's
  editor wakes on Send back or Approve, a named Bot on an @mention, and a push is refused while a
  review is open. One editor per Document (D11).
- `desktop/plugin.js` is plain ESM that imports only `@hermes/plugin-sdk`, `react` and
  `react/jsx-runtime`; no build step.
- The repo will be public: no host names, email addresses or home paths in code, tests or docs.
