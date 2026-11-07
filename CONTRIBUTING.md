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

## License

Unless you explicitly state otherwise, any contribution intentionally submitted for inclusion in
this project by you, as defined in the Apache-2.0 license, shall be dual licensed under the
[MIT license](LICENSE-MIT) and the [Apache License, Version 2.0](LICENSE-APACHE), without any
additional terms or conditions.
