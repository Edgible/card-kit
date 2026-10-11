# Evals for the edgible-cards skill

The prompts the skill is measured against, and how to measure it. [EXAMPLES.md](../EXAMPLES.md) shows the same prompts to people, with what a good answer does.

| File | What it is |
|---|---|
| [trigger-set.json](trigger-set.json) | 27 prompts, each marked `should_trigger`: 15 that should load the skill (needs described in people's words, a named app, a day-two problem, sharing an app you built, AI tools) and 12 near-misses on the same topics that should not. Reviewed by a person. |
| [held-out.yaml](held-out.yaml) | 10 prompts, mostly real, with what a good answer does (`expect`) and what fails it (`must_not`). Answers are scored against them, and the skill is never tuned to them. |
| [trigger-probe.py](trigger-probe.py) | Runs each trigger prompt in fresh, read-only `claude -p` sessions with the skill installed, and reports whether and at which step it loaded. |

## Measure triggering

With the skill installed (see the card-kit README's Agent skill section) and `claude` logged in:

```bash
python3 skills/edgible-cards/evals/trigger-probe.py            # every prompt, 2 runs each
python3 skills/edgible-cards/evals/trigger-probe.py --only 3 7 # just those prompts
```

Sessions get no shell, edits, or web access, so nothing is deployed. Each run is one short session on the logged-in subscription.

Use this, not skill-creator's `run_eval.py`. That tool installs the description under test as a temporary command file and counts a run only if loading it is the session's very first action. On 2026-10-11 it scored 1 of 12 should-trigger prompts, while the real skill loaded first in every probe run (8 of 8). Optimising the description against it would fix a problem real sessions do not have.

## Score answers

A quality run must let the skill read its own folder, or it answers without the needs map. Headless sessions refuse to read outside the working directory unless told: pass `--add-dir <path to skills/edgible-cards>`, and allow `Read`, `Grep`, and `Glob`. Keep the shell, edits, and web disallowed.

## Rules

- A person reviews any change to these prompts, as a pull request: they are what the scores mean.
- Never tune the skill against `held-out.yaml`. A fix must help a pattern seen in generated prompts, and the held-out scores show whether it helped or hurt.
- Write prompts in everyday language, the way people ask. Real ones may be tidied for spelling and punctuation, keeping their wording. Leave out real names, domains, and anything private.
