---
name: annotary
description: Annotary reviews of your Markdown, reply on every Thread. Share a plan or document with the person for line-by-line review in Annotary, read their review Threads, push a new Version after they send it back, and reply on each Thread you acted on. Use when you wrote Markdown the person should read and decide on, or a message names an Annotary Document.
---

# Annotary: reviews of what you write

The person reviews your Markdown in Annotary: comments on exact lines, then **Send back** (fix it)
or **Approve**. Use the `annotary_*` tools; never the `annotary` CLI through the terminal.

## The loop

1. Wrote a plan, spec or report the person should decide on? `annotary_share` it (`path` to a
   `.md` file, or `markdown` + `name`). That makes you its **editor**.
2. Show it: on Desktop put the returned `card` line (`::annotary{doc="…"}`) on a paragraph of
   its own; elsewhere give the link. Pass on `tell_the_person` once if it is there.
3. **Wait.** A review is open while the person comments. Do not push, do not rewrite. You are
   woken when they Send back or Approve, or @mention you.
4. Sent back: `annotary_threads`, fix what they asked, `annotary_push_version` **once** with the
   full new content.
5. **After pushing, answer each Thread you acted on** with `annotary_reply`, briefly, like a
   colleague: what changed, in which Version (`Done in v3: split the intro`), or why not
   (`Kept: the spec fixes it`). A question gets an answer, no edit. Unclear? Ask in that Thread,
   don't guess. `resolve: true` only on what you fully addressed.
6. Approved: do not push. Answer every open Thread still waiting for you, then carry on.

## Reviewing a Document someone else edits

Asked to review another Bot's Document? You comment, you do not edit.

1. `annotary_read` it. Note the `version`.
2. `annotary_comment` once per point: `quote` the exact passage (long enough to match one place),
   say what is wrong in `body`, and pass `version`. Refused? Do what the reason says.
3. Asked to decide? `annotary_act` with `send-back` (it wakes the editor to fix it) or `approve`.
   Comment first, so the editor knows what to fix.

A plain comment wakes nobody. `@editor` in a comment wakes that Bot only to answer, and uses one
of the 3 wake-ups between Bots allowed per Document per hour; so does a Send back.

## Rules

- An @mention asks you something: answer in that Thread with `annotary_reply` (or ask back if
  it is unclear). Do not push.
- Only the editor pushes. Not the editor? `annotary_comment`, or @mention the editor (`@coder`). Hand a
  Document over with `annotary_handoff` only when the person asks.
- `annotary_push_version` refuses mid-review; use `review_over: true` only when the person said
  in this chat that the review is over.
- Quote Thread ids (`t3`) and text, not line numbers.
- `annotary_list` shows every Document and any wake-ups you missed.
