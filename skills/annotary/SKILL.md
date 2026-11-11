---
name: annotary
description: Annotary reviews of your Markdown, reply on every Thread. Share a plan or document with the person for line-by-line review in Annotary, read their review Threads, push a new Version after they send it back, and reply on each Thread you acted on. Use when you wrote Markdown the person should read and decide on, or a message names an Annotary Document.
---

# Annotary: reviews of what you write

The person reviews your Markdown in Annotary: comments on exact lines, then **Send back** (fix it)
or **Approve**. Use the `annotary_*` tools; never the `annotary` CLI through the terminal
(`hermes annotary doctor` is another thing; see the end).

## The loop

1. Wrote a plan, spec or report the person should decide on? `annotary_share` it (`path` to a
   `.md` file, or `markdown` + `name`). That makes you its **editor**.
2. Show it: in Hermes (Desktop or the Webapp) put the returned `card` line
   (`::annotary{doc="…"}`) on a paragraph of its own; elsewhere, or when asked for a link, give
   `links.webapp` exactly. Never build a link yourself.
   The result has `setup_first` until Annotary is set up for the person: start your reply with
   those steps (the page, their name, wake-ups). When they give a name, `annotary_set_name`.
3. **Wait.** A review is open while the person comments. Do not push, do not rewrite. You are
   woken when they Send back or Approve, or @mention you.
4. Sent back: `annotary_threads`, fix what they asked, `annotary_push_version` **once** with the
   full new content.
5. **After pushing, answer each Thread you acted on** with `annotary_reply`, briefly, like a
   colleague: what changed, in which Version (`Done in v3: split the intro`), or why not
   (`Kept: the spec fixes it`). A question gets an answer, no edit. Unclear? Ask in that Thread,
   don't guess. `resolve: true` only on what you fully addressed, in a Thread that asked you for a fix.
6. Approved: do not push. Answer every open Thread still waiting for you, then carry on.

## Reviewing a Document someone else edits

Asked to review another Bot's Document? You comment, you do not edit.

1. `annotary_read` it. Note the `version`.
2. `annotary_comment` once per point: `quote` the exact passage (long enough to match one place),
   say what is wrong in `body`, and pass `version`. Refused? Do what the reason says.
3. Asked to decide? `annotary_act` with `send-back` (it wakes the editor to fix it) or `approve`.
   Comment first, so the editor knows what to fix.

A plain comment wakes nobody. `@editor` in a new comment wakes that Bot only to answer, and uses
one of the 3 wake-ups between Bots allowed per Document per hour; so does a Send back. A Bot's
reply wakes no Bot, so @mention another Bot only in a new comment that asks it to act.

## Rules

- An @mention asks you something: answer in that Thread with `annotary_reply` (or ask back if
  it is unclear). Do not push, and don't resolve it: the Thread is the asker's.
- Only the editor pushes. Not the editor? `annotary_comment`, or @mention the editor (`@coder`). Hand a
  Document over with `annotary_handoff` only when the person asks.
- `annotary_push_version` refuses mid-review; use `review_over: true` only when the person said
  in this chat that the review is over.
- Quote Thread ids (`t3`) and text, not line numbers.
- Asked only to read or sum up the comments? Report them; don't reply or resolve. A Thread that
  @mentions another Bot is that Bot's to answer.
- `annotary_list` shows every Document, the person's handle (to @mention them), and any wake-ups
  you missed. The person wants another name? `annotary_set_name`.

## When something is off

- The card shows as plain text, or a link opens Hermes's home page: the Annotary page is off in
  that browser (Hermes starts it off in each new one). Tell the person to turn on Annotary in
  Capabilities → Plugins; a link opened there offers an Open Plugins button.
- Anything else (a Document that won't open, a tool error, no wake-up): run
  `hermes annotary doctor` in a terminal, or ask the person to. It checks and repairs the install
  and says what to do; pass that on.
