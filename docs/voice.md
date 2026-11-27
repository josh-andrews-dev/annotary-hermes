# Voice

How Annotary for Hermes Agent's text reads: the Annotary page in Desktop and the Webapp, the
`hermes annotary` CLI output, the agent tools' messages and the public docs. The copy pass
(`product-copy`) sends this file with every string it writes.

## Audience

People who run Hermes Agent on their own machine or in Hermes Cloud and want to review what their agents write before the agents act on it. They already know Hermes (profiles, the gateway, Desktop, and the Webapp) and are comfortable in a terminal, though they review on a phone as often as at a desk. They want to see what is waiting, say what to change, and get back to their day.

## Tone

- Plain, calm, and brief, like a careful colleague.
- State what happened, then what to do next. Keep one idea per sentence and use short labels on buttons.
- Make failures specific: say what failed, why, and the next step when known (for example, `Could not reply`, followed by the reason).
- Skip cheerful filler, exclamation marks, apologies, and blame.
- Keep CLI and agent tool output terse and scannable: one fact per line, with any command to run written out in full.

## Terms

Capitalize Annotary's nouns and use them consistently across every surface:

- **Document**: A Markdown plan or document reviewed in Annotary. Share a Document to open it for review.
- **Version**: A revision of a Document. An agent pushes a new Version after making changes.
- **Thread**: A discussion attached to selected lines or to the whole Document.
- **Comment**: A remark on a Document or line that starts a Thread.
- **Reply**: A follow-up message in an existing Thread.
- **Action**: A review decision on a Document. The two review Actions are **Send back** and **Approve**; always use those exact words.
- **Bot**: An agent's identity in Annotary.
- **Member**: A person or Bot with access to Annotary.
- **Token**: A credential that connects a profile or Bot to Annotary.
- **@mention**: Naming a Bot in a Comment to ask it something and wake it.
- **Places**: **Hermes Desktop** (shortened to **Desktop** after first mention), **the Webapp**, **the Annotary page**, **a profile**, and **the gateway**.

## Formats

- **Spelling and punctuation**: American English (`en-US`).
- **Capitalization**: Sentence case for headings, titles, and buttons, keeping Annotary's nouns capitalized (`No Documents yet`, `Reply and resolve`, `Could not take the Action`).
- **Commands**: Inline code, complete and ready to copy (`hermes annotary enable --all`).
- **Ellipses**: Use the single ellipsis character (`…`), not three periods, for unfinished states and input placeholders (`Loading…`, `Reply…`).
- **Dates, times, and numbers**: Dates as `Nov 26, 2026`, times in the reader's locale, and counts as numerals (`3 Threads`).

## What to avoid

- **Code jargon in UI text**: Avoid implementation terms such as `loopback`, `serve`, `PID`, or `env` in user-facing copy.
- **Filler, hedging, and apologies**: Avoid "oops," "simply," "just," "please," and "sorry." They add noise, talk down to the reader, or soften an error instead of explaining it.
- **Synonym drift**: Do not call a Comment a "note" or a Document a "file." Use the glossary terms consistently.
- **"Click"**: Readers review on a phone as often as at a desk. Say **press** or **choose** instead.
- **Vague or passive errors**: Avoid messages that hide what broke. State the failed action and the cause.
- **Promising a wake-up from a plain Comment**: Never imply an agent will act on an ordinary Comment, since only **Send back**, **Approve**, and an **@mention** wake a Bot.
