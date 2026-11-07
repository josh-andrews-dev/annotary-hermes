# Repository standard

This file is rendered from the repo-standard template and is never edited in this repo; a change
to it arrives through a standard upgrade. The repo's own rules are in `AGENTS.md`.

## Commands

- The `Makefile` is the command surface; never type a raw build or test line from memory. Its
  targets: `make build`, `make test`, `make lint`; `make help` lists them all.
- The project's own recipes go in `project.mk`. Never edit `Makefile`, `scripts/standard/` or
  this file; they change only through a standard upgrade.
- `make lint` fails while `.agents/standard.yml` records a version behind the latest
  repo-standard tag: the upgrade comes first, in its own pull request, before other changes.
  The template repo is private, so where it cannot be read (a contributor's clone, the hosted
  CI runner) the lint only warns that the version was not checked.

## Merge gate

A pull request merges when:
- `make lint test` passes;
- the `ci` check has passed on the pull request;
- the pull request body has a `## Lessons` section with what the change taught that the repo
  should keep, or `None`; the required `lessons` check fails until it does, and editing the body
  runs it again;

A change touching only docs or agent instructions, made after your last local checks passed, may
rely on the `ci` check's lint instead of running `make lint` again.

A code change is reviewed before it merges by following the `review-gate` skill, which names the
reviewer (no other model reviews, and with no reviewer available the change waits), when it
touches a server (a product's web pages count; a documentation site does not), authentication,
secrets handling, money, a data migration, CI or a runner, a hook or guard, or more than about 200
changed lines; for any other code change the author decides and logs it in the PR body.

## Repository layout

- The root holds only `AGENTS.md`, `CLAUDE.md`, `GEMINI.md`, `DESIGN.md`, `README.md`,
  `CONTRIBUTING.md`, `SECURITY.md`, `LICENSE-MIT`, `LICENSE-APACHE`, `Makefile`, `project.mk`,
  the package manifest and dotfiles. Durable docs
  (why, decisions in `docs/decisions.md`, external contracts, ops playbooks) go in `docs/`.
  Working plans go in `docs/plans/` while active and move to `docs/archive/` in the PR that
  finishes the work; active docs do not link into `docs/archive/`, and you never read or follow
  `docs/archive/` unless asked about history.
- Keep each instruction, rule or skill file under 24,000 bytes. Long procedures go in a skill
  under `.agents/skills/`, history in `docs/`.
- Committed shell scripts never embed Python (`python3 -c`, heredocs); put it in a sibling `.py`
  file. Python the repo needs is pinned with `uv` (`.python-version`, `uv run`).
- The shipped version comes from the git tag at build time. Never write a version number into a
  file by hand; `0.0.0` placeholders are fine.
- This repo is public, so its CI runs on GitHub-hosted runners (`ubuntu-latest`,
  `macos-latest`). Never register a self-hosted runner to it or target one: a fork's pull
  request could run its code there.
- A job may use GitHub's cache (`actions/cache`, a setup action's `cache:` option); a hosted
  runner starts empty.

## American English

Product text is American English (en-US): anything a user sees or reads, including UI, CLI
output, messages, email, spoken prompts, public docs, store listings, and date and number
formats. Write other prose in American English too. Identifiers, stored field names and wire
names are exempt. `make lint` refuses new British spellings and `en-GB` locales on changed
lines; a deliberate exception goes in the repo's exceptions file with a reason.

- The exceptions file is `.agents/en-us-exceptions.json`, and it belongs to the repo.
- `python3 scripts/standard/en_us.py --all` scans the whole tree. Text already in the repo never
  fails `make lint`.
- `make lint` needs `uvx`, and fails rather than skips the check without it.

## Commits

- The commit-msg hook in `.githooks/` refuses a subject not in Conventional Commits form, and the `ci` check refuses such a pull request title, which becomes the
  squash-merge subject. Reword it; never bypass the hook.

## Secrets

- The pre-commit hook in `.githooks/` runs gitleaks on staged changes, and the pre-push hook on
  the commits each push sends. If one refuses, take the secret out of the change (rewrite the
  branch if it is already committed); never bypass the hooks.

## Monitoring

- Adding, renaming or removing anything that runs (service, LaunchAgent, systemd unit, runner,
  public hostname, scheduled job) updates the maintainer's monitoring in the same change.

## Tracker

"Bug", "ticket" and "issue" all mean an issue in this repo's GitHub Issues, whether a defect or
a feature; do not ask which. Outside reports arrive there too, through the forms in
`.github/ISSUE_TEMPLATE/`; questions go to Discussions, and security reports to private
vulnerability reporting (`SECURITY.md`), never a public issue. File and close issues with
`gh issue`; a pull request that fixes one says "Fixes #<number>" in its body.
