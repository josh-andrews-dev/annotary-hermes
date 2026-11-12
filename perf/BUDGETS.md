# Size budgets

This repo has no timed budgets: what the plugin costs is counted, never timed. Annotary's own
pages are timed in annotary's `perf/BUDGETS.md`.

## Size ceilings

Deterministic counts, never times: what the plugin sends for the same seeded set of Documents,
measured by `tests/test_size_report.py` in `perf/size-report.json` (`make size-check`; how each
number is counted: [`docs/size-report.md`](../docs/size-report.md)). The test fails when a number
is above its ceiling here, and so does the pull request's `size` check, which also fails on any
growth over the base branch without a `Size growth:` line in the body. Each ceiling was set on
2026-11-12 about 10% above the first measurement, rounded up to two significant figures; a count
under 10 stays at its value. The other numbers of the report have no ceiling and are guarded by
the growth check alone.

| id | metric | ceiling | unit | first measured |
|---|---|---:|---|---:|
| `page.plugin_js.bytes` | Desktop page: plugin.js | 29,000 | bytes | 25,940 |
| `list.requests` | Show the list: backend requests | 2 | count | 2 |
| `list.bytes` | Show the list: bytes | 1,800 | bytes | 1,617 |
| `open.requests` | Open a Document: backend requests | 7 | count | 7 |
| `open.bytes` | Open a Document: bytes | 1,200,000 | bytes | 1,032,209 |
| `poll.requests` | Each 10 s poll, a Document open: requests | 3 | count | 3 |
| `poll.bytes` | Each 10 s poll, a Document open: bytes | 170,000 | bytes | 152,769 |
| `agents.skill.bytes` | Agents: SKILL.md | 4,700 | bytes | 4,209 |
| `agents.tools.bytes` | Agents: tool schemas (JSON) | 5,800 | bytes | 5,242 |

## Raise rule

A ceiling may be raised only after at least three genuine attempts to stay under it, each a real
change (a smaller answer, fewer requests, shorter text the model reads) with the numbers recorded
before and after. If the number is still over after three attempts, that ceiling only may be
raised to one absolute value judged reasonable from the measurements, never a multiplier, and the
raise is recorded below: the old and new values, the three attempts with their numbers, and why
the rest of the gap is not cheaply closed. The pull request that raises it says so on its
`Size growth:` line. A lower ceiling needs no rule: lower one whenever a number falls well below
it.

### Raised ceilings

None yet.
