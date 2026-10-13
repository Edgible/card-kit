# Evals for the edgible-cards skill

The prompts the skill is measured against, and how to measure it. [EXAMPLES.md](../EXAMPLES.md) shows the same prompts to people, with what a good answer does.

| File | What it is |
|---|---|
| [trigger-set.json](trigger-set.json) | 27 prompts, each marked `should_trigger`: 15 that should load the skill (needs described in people's words, a named app, a day-two problem, sharing an app you built, AI tools) and 12 near-misses on the same topics that should not. Reviewed by a person. |
| [held-out.yaml](held-out.yaml) | 10 prompts, mostly real, with what a good answer does (`expect`) and what fails it (`must_not`). Answers are scored against them, and the skill is never tuned to them. |
| [run-evals.py](run-evals.py) | Answers each held-out prompt in a fresh read-only session with the skill, has a second session judge the answer against its `expect`, `must_not`, and the skill's principles, and writes a report. |
| [eval-summary.py](eval-summary.py) | Combines the last week of nightly runs into one report, from each prompt's latest result. |
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

```bash
python3 skills/edgible-cards/evals/run-evals.py --out results/$(date +%F)
python3 skills/edgible-cards/evals/run-evals.py --out results/try --only tennis-club
```

Each prompt gets two sessions on the logged-in subscription: one answers, one judges. The answering session is read-only: it may read the skill's folder, and, when an Edgible MCP server is on the machine (`edgible-mcp`, or `--mcp <command>`), use its `find` and `describe` tools to look up cards, as a person's session would. It has no shell, edits, web, or any other MCP server. The judge has no tools.

A prompt passes when the skill loaded as it should, every `expect` item holds, and no `must_not` item happened. `report.md` gives each result, the items missed with the judge's evidence, and one line per answer on what would have made it better. Transcripts and answers are saved beside it.

**Nightly, in small batches.** `--rotate today` runs only today's share of the prompts: prompt *i* runs on weekday *i* mod 7, so each runs once a week and a night costs about N/7 prompts, two sessions each. `eval-summary.py results/` then combines the last seven nights, each prompt at its latest result. edgible-org/cards runs this every night ([skill-evals.yml](https://github.com/edgible-org/cards/blob/main/.github/workflows/skill-evals.yml)) and keeps the report in a public issue. `results.json` and `report.md` have no home folder in them, so they can be published; transcripts stay on the machine.

If the subscription's usage limit is reached, the run stops, reports the prompts it did not run, and exits 2. Nothing is scored from a limit message.

A session must be able to read the skill's folder by both of its paths (the skills symlink and where it points), or it answers without the needs map: `run-evals.py` passes both with `--add-dir`. Headless sessions refuse anything not allowed.

## Rules

- A person reviews any change to these prompts, as a pull request: they are what the scores mean.
- Never tune the skill against `held-out.yaml`. A fix must help a pattern seen in generated prompts, and the held-out scores show whether it helped or hurt.
- Write prompts in everyday language, the way people ask. Real ones may be tidied for spelling and punctuation, keeping their wording. Leave out real names, domains, and anything private.
