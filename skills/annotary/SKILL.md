---
name: annotary
description: Share a Markdown plan or document with the person for line-by-line review in Annotary, read their review Threads, reply, and push a new Version after they send it back. Use when you wrote Markdown the person should read and decide on, or a message names an Annotary Document.
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
4. Sent back: `annotary_threads`, fix everything they asked, `annotary_push_version` **once**
   with the full new content, then `annotary_reply` on each Thread naming the new Version
   (`fixed in v3`) with `resolve: true`.
5. Approved: do not push. Answer open Threads, then carry on with the work.

## Rules

- An @mention asks you a question: answer in that Thread with `annotary_reply`. Do not push.
- Only the editor pushes. Not the editor? Comment, or @mention the editor (`@coder`). Hand a
  Document over with `annotary_handoff` only when the person asks.
- `annotary_push_version` refuses mid-review; use `review_over: true` only when the person said
  in this chat that the review is over.
- Quote Thread ids (`t3`) and text, not line numbers.
- `annotary_list` shows every Document and any wake-ups you missed.
