#!/usr/bin/env python3
"""Measure whether the installed edgible-cards skill loads for each prompt in a trigger set.

    python3 trigger-probe.py                     # trigger-set.json beside this file, 2 runs each
    python3 trigger-probe.py --runs 3 --only 1 5 # the 1st and 5th prompts, 3 runs each

Each run is a fresh, read-only `claude -p` session (no shell, no edits, no web) with the
skill installed as it really is, so it measures what a person's session does. A run counts
as triggered when the session calls Skill(edgible-cards) at any step, and the report gives
the step. A prompt passes when most of its runs match should_trigger.

skill-creator's run_eval.py measures something narrower: it installs the description as a
temporary command file, and counts a run only when that is the session's very first action.
For this skill it reported 1 of 12 should-trigger prompts while real sessions loaded the
skill first in every run. See README.md.

It uses the logged-in Claude subscription. Each run is one short session.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SKILL = "edgible-cards"
READ_ONLY = ["Bash", "Edit", "Write", "NotebookEdit", "WebFetch", "WebSearch"]


def run_once(prompt: str, max_turns: int, timeout: int) -> tuple[int | None, str]:
    """The step at which the skill loaded (1 = first tool call), or None, and the first tool."""
    env = {k: v for k, v in os.environ.items() if k != "CLAUDECODE"}
    cmd = ["claude", "-p", prompt, "--output-format", "stream-json", "--verbose",
           "--max-turns", str(max_turns), "--disallowedTools", *READ_ONLY]
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, env=env, timeout=timeout).stdout
    except subprocess.TimeoutExpired as exc:
        out = exc.stdout.decode() if isinstance(exc.stdout, bytes) else (exc.stdout or "")
    step, first = 0, ""
    for line in out.splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if event.get("type") != "assistant":
            continue
        for block in event["message"].get("content", []):
            if block.get("type") != "tool_use":
                continue
            step += 1
            first = first or block["name"]
            if block["name"] == "Skill" and SKILL in json.dumps(block.get("input", {})):
                return step, first
    return None, first or "(answered without tools)"


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--set", type=Path, default=HERE / "trigger-set.json")
    ap.add_argument("--runs", type=int, default=2)
    ap.add_argument("--only", type=int, nargs="+", default=[], metavar="N", help="1-based prompt numbers")
    ap.add_argument("--max-turns", type=int, default=3)
    ap.add_argument("--timeout", type=int, default=240)
    args = ap.parse_args(argv)

    items = json.loads(args.set.read_text())
    chosen = [(n, i) for n, i in enumerate(items, 1) if not args.only or n in args.only]
    passed = 0
    for n, item in chosen:
        results = [run_once(item["query"], args.max_turns, args.timeout) for _ in range(args.runs)]
        hits = sum(step is not None for step, _ in results)
        ok = (hits * 2 > args.runs) == item["should_trigger"]
        passed += ok
        steps = ",".join(str(s) if s else "-" for s, _ in results)
        print(f"{'PASS' if ok else 'FAIL'} #{n:<2} {'should' if item['should_trigger'] else 'not   '} "
              f"{hits}/{args.runs} at step {steps} | {item['query'][:80]}", flush=True)
    print(f"\n{passed}/{len(chosen)} prompts passed")
    return 0 if passed == len(chosen) else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
