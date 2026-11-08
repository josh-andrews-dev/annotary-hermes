# Testing

## Unit and live tests

`make test` runs pytest against a real `annotary serve` (the pinned release, downloaded once and
checked against its SHA-256) in a throwaway Hermes root, plus the desktop page's Node tests. No
model is called.

## Live review loop

`make live-loop` (or `python3 scripts/project/live_loop.py --profile coder`) checks a model, or a
change to the skill, tool descriptions or wake-up message, against a real Hermes install. It
opens an interactive session of the profile in a pseudo-terminal so the gateway can wake it, then:

1. asks the agent for a short plan and to share it with Annotary;
2. leaves two comments as the owner and chooses Send back;
3. waits for the woken agent to push Version 2 once, reply on each Thread citing it, and resolve
   both.

It prints a JSON report (timings, every reply) and exits 0 only when the agent did all of it. It
needs the plugin installed and wake-ups on for the profile (`hermes annotary wake on`). It uses
the profile's model; `--model` overrides it for one session.

The session runs in a temporary folder, so files the agent writes stay out of your checkout. At
the end, every Document the profile shared during the run is permanently removed: from the
server, its staged files and its entry in `state.json`. Do not use the profile for real work
while the loop runs, or that work goes too. Earlier Documents and other profiles' are left alone.
A failed owner step stops the run at once, and a Document that cannot be removed fails the run
and is named on stderr.

## Which model

Live checks run on Nous's free models, which do not count against usage limits: provider `nous`,
model `meituan/longcat-2.5:free`.

| Model | One tool call | Full review loop |
|---|---|---|
| `meituan/longcat-2.5:free` | correct | passed three times: one push, a reply on each Thread citing v2, both resolved, 50 to 160 s after Send back |
| `stepfun/step-3.7-flash:free` | correct, but about 4 minutes | not run: too slow |

The demo recording uses `deepseek/deepseek-v4.1-flash-1017` (provider `nous`). Switch every
profile with `hermes -p <profile> config set model.default <model>` and back the same way.
