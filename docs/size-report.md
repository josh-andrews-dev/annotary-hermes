# The size report

`perf/size-report.json` holds deterministic counts of what the plugin sends: bytes and requests,
never times, so they are the same on every run and every machine. `tests/test_size_report.py`
measures them on each `make test` and fails when the file differs from what it measured or when a
number is above its ceiling in [`perf/BUDGETS.md`](../perf/BUDGETS.md). `make size-report`
rewrites the file; read the diff before you commit it.

On a pull request, the `size` check compares the file at the base and the head. It fails when a
number grew, a ceiling was raised or removed, or a number is no longer reported, until the body
has a line `Size growth: <why>`; it always fails when a number is above its ceiling. A bot comment
shows each number on `main`, on the pull request, the change and the ceiling, and is updated in
place. Both workflows read the two files through the API and treat them only as data, and neither
runs the pull request's copy of `.github/scripts/size-report.cjs`: the check takes it from the
pull request's base and the comment from the default branch, so a pull request cannot loosen the
check in the change that grows a number (`ci` tests the head's copy). A change to the report's
shape therefore merges in the script first, then in the report.

## The fixture

The test runs the real pinned `annotary serve` that `make test` starts, set up as on Hermes Cloud
(the OS user `hermes`, so the person is `@owner` everywhere), with three profiles (`default`,
`coder`, `bencha`). `coder` shares seven small plans and one review Document of 2,000 lines; the
owner leaves 80 Threads on the review, chooses Send back, and `coder` pushes Version 2 and replies
to 32 Threads, resolving 8. Its embedded page is over annotary's `PART_MAX` (384 KiB), so it arrives
in parts.

Two things in an answer depend on the run, not the code, and are normalized before counting: the
server's address and the text of relative times (`<time class="cd-rel">`), as annotary's own size
report does. Document and Thread ids are random but always the same length, and every timestamp
has a fixed width.

## What each number counts

A backend answer is counted as FastAPI sends it: the route's value rendered by `JSONResponse`,
uncompressed. Each route is called as the page calls it (`desktop/plugin.js`).

- `page.plugin_js.bytes`: `desktop/plugin.js` on disk. Hermes loads it uncompiled on every page
  load.
- `list.*`: what the Annotary page loads to show the list, `/documents` and `/status`.
- `open.*`: opening the review Document in embed mode. The review bar's `/doc`, the frame's
  `/shell`, then the frame's own requests through `/proxy` as annotary's `embed.js` makes them: the
  page with `Accept: text/html` and fixed zone headers, part 0 and then each part with its etag, a
  `412` starting over (`open.page.restarts`), then each avatar URL in the page (`data-cd-av`)
  once, as bytes, and the first poll of the live feed from the page's `seq`
  (`/api/v1/events?doc=…&since=…&me=1&limit=200`), as `app.js` does.
- `poll.*`: what the page loads again every 10 s (`POLL_MS`) while a Document is open: the list's
  two routes and the review bar's `/doc`. `poll.events.bytes` is the frame's own live-feed poll,
  every 4 s (`EMBED_POLL_MS`) while the frame is visible, when nothing has changed.
- `agents.*`: what is sent to a model. `SKILL.md` on disk; the tool schemas as registered, one
  compact JSON list; the wake-up message for a Send back and for an @mention with no Threads or
  excerpt, so the numbers are the fixed text alone.

## What is not counted, and why

- A live-feed poll that carries events: its size is the events', not the plugin's. Image Assets
  (`data-cd-src`) are not in the fixture.
- Anything only a browser does: running the page's scripts, Hermes's own page and its SDK, and
  what Hermes adds around a backend answer (its sign-in, its gateway bridge).
- The chat card: it calls `/doc`, already counted as `open.doc.bytes`.
- Native Desktop's fallback view (no embed mode): the pinned annotary always has embed mode.
