#!/usr/bin/env python3
"""Score the edgible-cards skill's answers to the held-out prompts.

    python3 run-evals.py --out results/2026-10-11           # every prompt in held-out.yaml
    python3 run-evals.py --out results/try --only tennis-club physio-clinic

For each prompt, a fresh `claude -p` session with the skill installed as it really is answers
it, read-only (it may read files, including the skill's own folder, but has no shell, edits,
or web), and its transcript is saved. A second session judges the answer against the prompt's
`expect` and `must_not`, and against the skill's general principles, and says what would have
made it better. A check that needs no judgement is made from the transcript: whether the skill
loaded, against whether it should have.

It writes `report.md` and `results.json` in --out, and one transcript per prompt. A prompt
passes when the skill loaded as it should, every `expect` item holds, and no `must_not` item
happened. Never tune the skill against these prompts: they measure whether a change helped.

It uses the logged-in Claude subscription: two short sessions per prompt.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from datetime import date
from pathlib import Path

HERE = Path(__file__).resolve().parent
# The skill a session loads is the installed one, so that is the folder it may read and the
# version the report names. Without an installed copy, this folder's is used.
INSTALLED = Path.home() / ".claude" / "skills" / "edgible-cards"
SKILL_DIR = INSTALLED.resolve() if (INSTALLED / "SKILL.md").is_file() else HERE.parent
SKILL = "edgible-cards"
NO_SHELL = ["Bash", "Edit", "Write", "NotebookEdit", "WebFetch", "WebSearch"]
# Claude's own message when the subscription's limit is reached. Narrow on purpose: an
# answer about self-hosting may well mention rate limits.
LIMIT = re.compile(r"^\s*You've hit your [a-z ]*limit", re.I)

# The skill's own principles, from SKILL.md, judged on every answer where they apply.
PRINCIPLES = [
    "Answers the question the person asked first, before offering anything else.",
    "Gives honest options side by side, including hosted ones where they fit, and states the upkeep of self-hosting.",
    "Asks at most two or three questions, and only ones whose answers change the recommendation.",
    "Builds, deploys, or changes nothing before the person chooses, and does not claim to have done so.",
    "Chooses each hostname's auth mode by who uses it: org only for the person's own team; members, customers, or the public use the app's own accounts.",
    "Raises sensitivity (private or regulated data) and who sees what inside the app, when the need involves it.",
    "Says no plainly to a poor or refused fit, with the reason and what works instead.",
]


def load_scenarios(path: Path) -> list[dict]:
    """held-out.yaml: a list of maps with id, prompt, and lists expect and must_not.

    Read without a YAML library, so this runs with python3 alone. It understands exactly
    the shape held-out.yaml uses, and stops on anything else rather than guess.
    """
    scenarios, current, key = [], None, None
    for number, line in enumerate(path.read_text().splitlines(), 1):
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        m = re.match(r"^- id: (\S+)$", line)
        if m:
            current = {"id": m.group(1), "expect": [], "must_not": []}
            scenarios.append(current)
            key = None
            continue
        m = re.match(r"^  prompt: (.+)$", line)
        if m and current is not None:
            current["prompt"] = json.loads(m.group(1)) if m.group(1).startswith('"') else m.group(1)
            continue
        m = re.match(r"^  (expect|must_not):$", line)
        if m and current is not None:
            key = m.group(1)
            continue
        m = re.match(r"^    - (.+)$", line)
        if m and current is not None and key:
            current[key].append(m.group(1).strip())
            continue
        sys.exit(f"{path.name} line {number}: not in the shape run-evals.py reads: {line!r}")
    for s in scenarios:
        if "prompt" not in s or not s["expect"]:
            sys.exit(f"{path.name}: {s['id']} needs a prompt and at least one expect item")
    return scenarios


def claude(args: list[str], prompt: str, cwd: Path, timeout: int) -> str:
    env = {k: v for k, v in os.environ.items() if k != "CLAUDECODE"}
    try:
        done = subprocess.run(["claude", "-p", prompt, *args], capture_output=True, text=True,
                              env=env, cwd=cwd, timeout=timeout)
        return done.stdout
    except subprocess.TimeoutExpired as exc:
        return exc.stdout.decode() if isinstance(exc.stdout, bytes) else (exc.stdout or "")


def answer(prompt: str, max_turns: int, timeout: int, mcp: str) -> dict:
    """One read-only session with the installed skill. Returns the answer and what it did.

    With an Edgible MCP server (--mcp), the session may also find and describe cards, as a
    person's session would, through that server's two read-only tools and nothing else. Only
    that server is loaded, so no other MCP server the machine has can act.
    """
    tools = []
    with tempfile.TemporaryDirectory() as empty:
        if mcp:
            config = Path(empty) / "mcp.json"
            config.write_text(json.dumps({"mcpServers": {"edgible": {"command": mcp, "args": []}}}))
            tools = ["--strict-mcp-config", "--mcp-config", str(config),
                     "--allowedTools", "mcp__edgible__find", "mcp__edgible__describe"]
        else:
            tools = ["--strict-mcp-config"]
        out = claude(["--output-format", "stream-json", "--verbose", "--max-turns", str(max_turns),
                      # Both spellings of the folder: a session may read it through the
                      # skills symlink or through the path it points at.
                      "--add-dir", str(INSTALLED), str(SKILL_DIR.resolve()), *tools,
                      "--disallowedTools", *NO_SHELL, "mcp__edgible__whats_running"], prompt, Path(empty), timeout)
    events, tools, loaded_at, final, failed = [], [], None, "", False
    for line in out.splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        events.append(event)
        if event.get("type") == "assistant":
            for block in event["message"].get("content", []):
                if block.get("type") == "tool_use":
                    tools.append(block["name"])
                    if block["name"] == "Skill" and SKILL in json.dumps(block.get("input", {})) and loaded_at is None:
                        loaded_at = len(tools)
        if event.get("type") == "result":
            final = event.get("result") or ""
            failed = event.get("is_error") or event.get("subtype", "success") not in ("success", "error_max_turns")
    # A usage limit or an API error is not an answer, and must not be scored as one.
    if not final or failed or LIMIT.search(final):
        return {"error": final.strip() or "no answer", "events": events}
    return {"answer": final, "tools": tools, "skill_loaded_at": loaded_at, "events": events}


def judge(scenario: dict, reply: str, timeout: int) -> dict:
    """A separate session scores the answer. It has no tools: it judges only what it is shown."""
    items = {"expect": scenario["expect"], "must_not": scenario["must_not"], "principles": PRINCIPLES}
    prompt = f"""You are judging an AI assistant's answer to a person, for a test of an agent skill.
Judge only the answer below, strictly and fairly. Quote the answer as evidence.

The person asked:
<prompt>
{scenario['prompt']}
</prompt>

The assistant answered:
<answer>
{reply or '(no answer)'}
</answer>

Judge three lists:
- expect: what a good answer does. For each, pass is true only if the answer clearly does it.
- must_not: what fails an answer outright. For each, violated is true if the answer does it.
- principles: general principles. For each, pass is true, false, or null when it does not apply to this prompt.

{json.dumps(items, indent=2)}

Then give better: one sentence on what would most have improved this answer, or "" if nothing.

Reply with only this JSON, no other text:
{{"expect": [{{"item": "...", "pass": true, "evidence": "..."}}],
  "must_not": [{{"item": "...", "violated": false, "evidence": "..."}}],
  "principles": [{{"item": "...", "pass": null, "evidence": "..."}}],
  "better": "..."}}"""
    with tempfile.TemporaryDirectory() as empty:
        out = claude(["--output-format", "json", "--max-turns", "1",
                      "--disallowedTools", *NO_SHELL, "Read", "Grep", "Glob", "Skill", "Task"],
                     prompt, Path(empty), timeout)
    try:
        text = json.loads(out).get("result", "")
        return json.loads(text[text.index("{"):text.rindex("}") + 1])
    except (ValueError, KeyError, AttributeError):
        return {"error": "the judge did not return JSON", "raw": out[-2000:]}


def score(scenario: dict, run: dict, verdict: dict) -> dict:
    should_load = not any("does not load" in e for e in scenario["expect"])
    loaded = run["skill_loaded_at"] is not None
    expect = verdict.get("expect", [])
    must_not = verdict.get("must_not", [])
    principles = verdict.get("principles", [])
    passed = (loaded == should_load and "error" not in verdict and bool(expect)
              and all(e.get("pass") is True for e in expect)
              and not any(m.get("violated") is True for m in must_not))
    return {
        "id": scenario["id"], "pass": passed, "should_load": should_load, "loaded": loaded,
        "loaded_at": run["skill_loaded_at"], "tools": run["tools"],
        "expect_passed": sum(e.get("pass") is True for e in expect), "expect_total": len(scenario["expect"]),
        "must_not_violated": [m["item"] for m in must_not if m.get("violated") is True],
        "principles_failed": [p["item"] for p in principles if p.get("pass") is False],
        "verdict": verdict,
    }


def report(results: list[dict], meta: dict) -> str:
    lines = [f"# edgible-cards skill evals, {meta['date']}", "",
             f"{sum(r['pass'] for r in results)} of {len(results)} held-out prompts pass. "
             f"Skill from card-kit `{meta['card_kit']}`, `claude` {meta['claude']}. "
             f"Answering sessions: read-only, MCP tools: {meta.get('mcp', 'none')}.", ""]
    if meta.get("not_run"):
        lines += [f"**Stopped early, not scored:** {meta['stopped']}. Not run: {', '.join(meta['not_run'])}.", ""]
    lines += [
             "| Prompt | Result | Skill loaded | expect | must_not broken | Principles missed |",
             "| --- | --- | --- | --- | --- | --- |"]
    for r in results:
        loaded = f"{'yes' if r['loaded'] else 'no'} ({'right' if r['loaded'] == r['should_load'] else 'WRONG'})"
        lines.append(f"| {r['id']} | {'pass' if r['pass'] else 'FAIL'} | {loaded} | "
                     f"{r['expect_passed']}/{r['expect_total']} | {len(r['must_not_violated'])} | "
                     f"{len(r['principles_failed'])} |")
    lines += ["", "## Details", ""]
    for r in results:
        v = r["verdict"]
        lines.append(f"### {r['id']}: {'pass' if r['pass'] else 'FAIL'}")
        if "error" in v:
            lines += ["", f"- Judge error: {v['error']}", ""]
            continue
        misses = [e for e in v.get("expect", []) if e.get("pass") is not True]
        broken = [m for m in v.get("must_not", []) if m.get("violated") is True]
        missed_p = [p for p in v.get("principles", []) if p.get("pass") is False]
        for label, group in (("Missed", misses), ("Broke", broken), ("Principle missed", missed_p)):
            for item in group:
                lines.append(f"- {label}: {item['item']}. {item.get('evidence', '')}")
        if v.get("better"):
            lines.append(f"- Would be better: {v['better']}")
        if not (misses or broken or missed_p or v.get("better")):
            lines.append("- Nothing to note.")
        lines.append("")
    lines += ["## What would make answers better", ""]
    lines += [f"- {r['id']}: {r['verdict']['better']}" for r in results if r["verdict"].get("better")]
    return "\n".join(lines) + "\n"


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--out", type=Path, required=True, help="directory for the report and transcripts")
    ap.add_argument("--set", type=Path, default=HERE / "held-out.yaml")
    ap.add_argument("--only", nargs="+", default=[], metavar="ID")
    ap.add_argument("--rotate", type=int, choices=range(7), metavar="DAY",
                    help="run only the prompts for this day of a 7-day rotation (0 = Monday): prompt i "
                         "runs on day i mod 7, so each one runs once a week. --rotate today uses today")
    ap.add_argument("--max-turns", type=int, default=20)
    ap.add_argument("--timeout", type=int, default=900)
    ap.add_argument("--mcp", default=shutil.which("edgible-mcp") or "",
                    help="command of a stdio Edgible MCP server whose find and describe tools answering "
                         "sessions may use; default: edgible-mcp on PATH, if any. Pass '' for none")
    argv = [str(date.today().weekday()) if a == "today" else a for a in argv]
    args = ap.parse_args(argv)

    scenarios = [s for s in load_scenarios(args.set) if not args.only or s["id"] in args.only]
    if args.rotate is not None:
        scenarios = [s for i, s in enumerate(scenarios) if i % 7 == args.rotate]
    if not scenarios:
        sys.exit("no prompts to run")
    args.out.mkdir(parents=True, exist_ok=True)
    git = lambda *a: subprocess.run(["git", "-C", str(SKILL_DIR), *a], capture_output=True, text=True).stdout.strip()
    meta = {"date": str(date.today()), "rotation_day": args.rotate, "card_kit": git("rev-parse", "--short", "HEAD") or "unknown",
            "claude": subprocess.run(["claude", "--version"], capture_output=True, text=True).stdout.strip(),
            "mcp": "edgible find and describe" if args.mcp else "none"}
    results, stopped = [], ""
    for s in scenarios:
        print(f"{s['id']}: answering", flush=True)
        run = answer(s["prompt"], args.max_turns, args.timeout, args.mcp)
        (args.out / f"{s['id']}.transcript.jsonl").write_text("\n".join(json.dumps(e) for e in run["events"]) + "\n")
        if "error" in run:
            # Stop: a limit will not lift for the next prompt either. The rest are not run.
            stopped = f"{s['id']}: {run['error']}"
            print(f"stopped, not scored: {stopped}", flush=True)
            break
        (args.out / f"{s['id']}.answer.md").write_text(run["answer"] + "\n")
        print(f"{s['id']}: judging", flush=True)
        verdict = judge(s, run["answer"], args.timeout)
        if "error" in verdict and LIMIT.search(json.loads(verdict["raw"]).get("result", "") if verdict["raw"].strip().startswith("{") else verdict["raw"]):
            stopped = f"{s['id']}: the judge hit the usage limit"
            print(f"stopped, not scored: {stopped}", flush=True)
            break
        r = score(s, run, verdict)
        results.append(r)
        print(f"{s['id']}: {'pass' if r['pass'] else 'FAIL'} (expect {r['expect_passed']}/{r['expect_total']}, "
              f"skill {'loaded' if r['loaded'] else 'not loaded'})", flush=True)
    meta["not_run"] = [s["id"] for s in scenarios[len(results):]]
    meta["stopped"] = stopped
    # results.json and report.md may be published: no home folder in them.
    home = lambda text: text.replace(str(Path.home()), "~")
    (args.out / "results.json").write_text(home(json.dumps({"meta": meta, "results": results}, indent=2)) + "\n")
    (args.out / "report.md").write_text(home(report(results, meta)))
    print(f"\n{sum(r['pass'] for r in results)}/{len(results)} pass. Report: {args.out / 'report.md'}")
    if stopped:
        print(f"Not run: {', '.join(meta['not_run'])}. Run them again with --only once the cause is gone.")
        return 2
    return 0 if all(r["pass"] for r in results) else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
