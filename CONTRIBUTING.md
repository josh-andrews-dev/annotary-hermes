# Contributing to annotary-hermes

Thanks for helping. Bugs and feature requests go to
[Issues](https://github.com/josh-andrews-dev/annotary-hermes/issues) (the forms ask for what is
needed), questions to [Discussions](https://github.com/josh-andrews-dev/annotary-hermes/discussions),
and security problems to private vulnerability reporting ([SECURITY.md](SECURITY.md)), never a
public issue.

## Set up

You need Python 3.11+ with `uv`, Hermes Agent 0.23.0 or newer, and Node (LTS) for the desktop
plugin's checks. `make test` runs the tests.

`make help` lists the commands. Turn on the repo's git hooks once in each clone:

    git config core.hooksPath .githooks

The pre-commit and pre-push hooks scan for secrets with
[gitleaks](https://github.com/gitleaks/gitleaks), which must be installed.

## Pull requests

- Branch from `main`, one change per pull request.
- `make lint test` passes before you open it; CI runs `make ci` on it as well.
- Commit messages and the pull request title follow
  [Conventional Commits](https://www.conventionalcommits.org/) (`fix: …`, `feat(cli): …`); the
  `commit-msg` hook and CI check them. A pull request is squash-merged with its title as the
  subject.
- A bug fix comes with a test that fails without the fix.
- A `feat`, `fix` or `perf` pull request has a `## Surfaces` section: one line each for Web, Hermes
  page, App, CLI and Agents, saying `changed`, `not affected: <why>` or `follows: <why>`. As an
  outside contributor you cannot change annotary's pages or the iPhone and iPad app, so write
  `follows: outside contributor` for those; the maintainer carries the change there.
  [`docs/surfaces.md`](docs/surfaces.md) has the list to walk.
- **Sizes.** `make test` counts what the plugin sends for a fixed set of Documents and compares
  it with `perf/size-report.json`. If your change moves a number, run `make size-report` and commit
  the file; if a number grew, add a line `Size growth: <why>` to the pull request body. A bot
  comment on the pull request shows every number against `main`
  ([`docs/size-report.md`](docs/size-report.md)).

## License

Unless you explicitly state otherwise, any contribution intentionally submitted for inclusion in
this project by you, as defined in the Apache-2.0 license, shall be dual licensed under the
[MIT license](LICENSE-MIT) and the [Apache License, Version 2.0](LICENSE-APACHE), without any
additional terms or conditions.
