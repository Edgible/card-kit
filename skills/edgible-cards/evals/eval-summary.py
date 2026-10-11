#!/usr/bin/env python3
"""Combine the last week of nightly eval runs into one report.

    python3 eval-summary.py results/            # results/<date>/results.json, from run-evals.py
    python3 eval-summary.py results/ --days 14

A nightly run scores only that night's share of the prompts (run-evals.py --rotate), so one
night says little. This takes each prompt's latest result within the window, and gives the
week's score, each prompt's result with what the judge found, and what would have made the
answers better. It prints Markdown, for the weekly report issue.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date, timedelta
from pathlib import Path


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("results", type=Path, help="directory of <date>/results.json")
    ap.add_argument("--days", type=int, default=7)
    args = ap.parse_args(argv)

    since = date.today() - timedelta(days=args.days - 1)
    runs = []
    for path in sorted(args.results.glob("*/results.json")):
        try:
            day = date.fromisoformat(path.parent.name)
        except ValueError:
            continue
        if day >= since:
            runs.append((day, json.loads(path.read_text())))
    latest: dict[str, tuple[date, dict, dict]] = {}
    for day, run in runs:
        for r in run["results"]:
            latest[r["id"]] = (day, r, run["meta"])
    not_run = sorted({n for _, run in runs for n in run["meta"].get("not_run", [])} - set(latest))

    lines = [f"# edgible-cards skill evals: {since} to {date.today()}", ""]
    if not latest:
        lines += ["No results in this window.", ""]
        print("\n".join(lines))
        return 0
    passed = sum(r["pass"] for _, r, _ in latest.values())
    kits = sorted({m["card_kit"] for _, _, m in latest.values()})
    lines += [f"**{passed} of {len(latest)}** held-out prompts pass, each at its latest run in the last "
              f"{args.days} days ({len(runs)} nightly runs). Skill from card-kit {', '.join(f'`{k}`' for k in kits)}.", ""]
    if not_run:
        lines += [f"Not run in this window (a run stopped early): {', '.join(not_run)}.", ""]
    lines += ["| Prompt | Run | Result | Skill loaded | expect | must_not broken |",
              "| --- | --- | --- | --- | --- | --- |"]
    for pid, (day, r, _) in sorted(latest.items(), key=lambda kv: (kv[1][1]["pass"], kv[0])):
        loaded = f"{'yes' if r['loaded'] else 'no'} ({'right' if r['loaded'] == r['should_load'] else 'WRONG'})"
        lines.append(f"| {pid} | {day} | {'pass' if r['pass'] else 'FAIL'} | {loaded} | "
                     f"{r['expect_passed']}/{r['expect_total']} | {len(r['must_not_violated'])} |")
    lines += ["", "## Failing prompts", ""]
    failing = [(pid, day, r) for pid, (day, r, _) in sorted(latest.items()) if not r["pass"]]
    if not failing:
        lines.append("None.")
    for pid, day, r in failing:
        v = r["verdict"]
        lines.append(f"**{pid}** ({day})")
        if "error" in v:
            lines.append(f"- Judge error: {v['error']}")
        for e in v.get("expect", []):
            if e.get("pass") is not True:
                lines.append(f"- Missed: {e['item']}. {e.get('evidence', '')}")
        for m in v.get("must_not", []):
            if m.get("violated") is True:
                lines.append(f"- Broke: {m['item']}. {m.get('evidence', '')}")
        lines.append("")
    lines += ["## What would make answers better", ""]
    lines += [f"- {pid}: {r['verdict']['better']}" for pid, (_, r, _) in sorted(latest.items())
              if r["verdict"].get("better")] or ["Nothing noted."]
    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
