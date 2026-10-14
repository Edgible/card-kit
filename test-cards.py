#!/usr/bin/env python3
"""Test every card in a repo that needs it, and keep a status for each one.

Run it on a serving device, from the root of a cards repo:

    python3 ../card-kit/test-cards.py --device macbookair --status ../status
    python3 ../card-kit/test-cards.py --device macbookair --status ../status --only gitea

It tests the cards that carry test.yml: every app card, and each pattern card that has one.
A card needs a test when its status says it has not been tested, when its files changed
since (the files: fingerprint test-card records), or when `edgible --version` is not the
version it last passed or failed on. A new Edgible version therefore retests every card.
--all tests every card anyway, and --only tests the named ones.

The status directory holds status.json, every card's latest result, and one <card>.json
per card in the shape of a shields.io endpoint badge, labelled with the Edgible version:

    https://img.shields.io/endpoint?url=<raw URL of the status directory>/gitea.json

--spread DAYS spreads that work over the days: a new card, or one whose files changed, is tested at once,
and every other test waits for the card's turn (card i on day i mod DAYS), which also retests
each card once in every DAYS days, to catch an image that changed under the same tag.

It runs test-card for each card, one at a time, and never changes the repo: test.yml is
the author's record of a version, and the status is CI's record of what still passes.
It exits 1 when a card it tested failed.

A fleet of machines splits that work in two modes, with test-card unchanged:

    python3 ../card-kit/test-cards.py --status ../status --spread 7 --plan plan.json --machines runners.json
    python3 ../card-kit/test-cards.py --status ../status --merge results/*

--plan writes the cards due tonight as a GitHub Actions matrix, each job with the runner labels
its cards need (see labels()), and tests nothing. Cards that publish an app of the same name
share a job, so two machines never publish it at once. --machines, the label sets of the
machines online, leaves out a card that none of them can run, with "no machine". Each job then
runs this script with --only on its cards and a status directory of its own, and --merge
copies the results from those directories into the status.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import re
import subprocess
import sys
from datetime import date, datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent


def test_card():
    spec = importlib.util.spec_from_file_location("test_card", HERE / "test-card.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def files_hash(card_dir: Path) -> str:
    return test_card().files_hash(card_dir)


MEM_TIERS = [2, 4, 8, 16, 32, 64]   # GB, the mem-<n>g runner labels


def labels(card_dir: Path) -> list[str]:
    """The runner labels a machine needs to test this card, from its places:. test-card runs
    every place on one machine, so the memory is theirs together, rounded up to a mem-<n>g
    label; a machine carries the label of every tier it meets, such as mem-2g,mem-4g,mem-8g on
    a 9 GB one. 1 GB or less needs none. A card whose images miss amd64 or arm64 needs the
    other one, gpu: required needs gpu-nvidia, and a tcp or udp app needs tcp."""
    tc = test_card()
    places = tc.read_places(card_dir / "card.yml").values()
    need = ["self-hosted", "edgible-test"]
    gb = sum(tc.mem_bytes(p.get("memory", "0 B")) for p in places) / 1e9
    if gb > 1:
        tier = next((t for t in MEM_TIERS if gb <= t), None)
        need.append(f"mem-{tier}g" if tier else "mem-too-big")
    archs = set.intersection(*[set(p["arch"]) for p in places if p.get("arch")] or [set()])
    if archs and "amd64" not in archs:
        need.append("ARM64")
    elif archs and "arm64" not in archs:
        need.append("X64")
    if any(p.get("gpu") == "required" for p in places):
        need.append("gpu-nvidia")
    # A machine whose Edgible agent forwards tcp and udp apps to 127.0.0.1, where every card
    # binds them, carries tcp. The Linux agent does not yet: it forwards to the host's address.
    if any(a["protocol"] in ("tcp", "udp") for a in tc.read_apps(card_dir / "card.yml")):
        need.append("tcp")
    return need


def app_names(card_dir: Path) -> set[str]:
    return {a["name"] for a in test_card().read_apps(card_dir / "card.yml")}


def write_status(status_dir: Path, status: dict) -> None:
    (status_dir / "status.json").write_text(json.dumps(dict(sorted(status.items())), indent=2) + "\n")


def badge(cli: str, result: str) -> dict:
    return {"schemaVersion": 1, "label": f"Edgible {cli}",
            "message": "passing" if result == "pass" else "failing",
            "color": "brightgreen" if result == "pass" else "red"}


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--device", help="the serving device, as `edgible device list` names it; needed to test")
    ap.add_argument("--status", type=Path, required=True, help="the status directory to read and write")
    ap.add_argument("--all", action="store_true", help="test every card, whether it needs it or not")
    ap.add_argument("--only", nargs="+", default=[], metavar="CARD", help="test only these cards")
    ap.add_argument("--by", choices=["agent", "person", "ci"], default="ci")
    ap.add_argument("--spread", type=int, default=0, metavar="DAYS",
                    help="spread the work over this many days: a card whose files changed is tested at "
                         "once, as is a new card; any other test (a new Edgible version, or none for DAYS days) "
                         "waits for the card's turn, card i on day i mod DAYS")
    ap.add_argument("--plan", type=Path, metavar="FILE",
                    help="test nothing: write the cards due as a GitHub Actions matrix, with the labels each job needs")
    ap.add_argument("--machines", type=Path, metavar="FILE",
                    help="with --plan: a JSON list of the label lists of the machines online")
    ap.add_argument("--cli", help="with --plan: the Edgible version to compare with; else the newest in the status")
    ap.add_argument("--merge", nargs="+", type=Path, metavar="DIR",
                    help="test nothing: copy the results in these status directories into --status")
    args = ap.parse_args(argv)

    every = sorted(p.parent.name for p in Path.cwd().glob("*/card.yml"))
    unknown = set(args.only) - set(every)
    if unknown:
        print(f"no card named {', '.join(sorted(unknown))}", file=sys.stderr)
        return 2
    # A card is tested when it carries test.yml, or when --only names it.
    cards = [c for c in every if (Path.cwd() / c / "test.yml").is_file() or c in args.only]
    args.status.mkdir(parents=True, exist_ok=True)
    status_file = args.status / "status.json"
    status = json.loads(status_file.read_text()) if status_file.is_file() else {}

    if args.merge:
        return merge(args.merge, args.status, status, cards)

    if args.plan:
        cli = args.cli or max((e.get("edgible-cli", "") for e in status.values()),
                              key=lambda v: [int(x) for x in re.findall(r"\d+", v)], default="")
    else:
        if not args.device:
            print("--device is needed to test; --plan and --merge test nothing", file=sys.stderr)
            return 2
        cli = subprocess.run(["edgible", "--version"], capture_output=True, text=True).stdout.strip()
        if not cli:
            print("edgible --version printed nothing; is the edgible CLI installed?", file=sys.stderr)
            return 2

    failed, due = [], []
    # UTC, so machines in different time zones agree on the day.
    today = datetime.now(timezone.utc).date()
    for index, name in enumerate(cards):
        files = files_hash(Path(name))
        entry = status.get(name)
        turn = not args.spread or index % args.spread == today.toordinal() % args.spread
        if args.only:
            reason = "asked for" if name in args.only else ""
        elif args.all:
            reason = "asked for all"
        elif not entry:
            reason = "no status yet"
        elif entry.get("files") != files:
            reason = "its files changed"
        elif not turn:
            reason = ""
        elif entry.get("edgible-cli") != cli:
            reason = f"Edgible {entry.get('edgible-cli')} -> {cli}"
        elif args.spread and (today - date.fromisoformat(entry["tested"])).days >= args.spread:
            reason = f"last tested {entry['tested']}"
        else:
            reason = ""
        if not reason:
            # With --only, a card not named may have no status yet.
            if args.only:
                why = "not asked for"
            elif not turn:
                why = "not its turn tonight"
            else:
                why = f"still {entry['result']} on Edgible {cli} with these files"
            print(f"== {name}: skip, {why}", flush=True)
            continue

        print(f"== {name}: test, because {reason}", flush=True)
        if args.plan:
            due.append(name)
            continue
        run = subprocess.run([sys.executable, str(HERE / "test-card.py"), name, "--device", args.device,
                              "--by", args.by], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        print(run.stdout, end="", flush=True)
        match = re.search(r"^result: (pass|fail)", run.stdout, re.M)
        result = match.group(1) if match and run.returncode == 0 else "fail"
        if result == "fail":
            failed.append(name)
        status[name] = {"result": result, "tested": str(today), "edgible-cli": cli, "files": files,
                        "device": args.device}
        # Write as it goes, so a run that stops part way keeps what it learned.
        write_status(args.status, status)
        (args.status / f"{name}.json").write_text(json.dumps(badge(cli, result)) + "\n")

    if args.plan:
        return plan(due, args.plan, args.machines)

    for gone in sorted(set(status) - set(cards)):
        del status[gone]
        (args.status / f"{gone}.json").unlink(missing_ok=True)
    write_status(args.status, status)
    print(f"\n{len(failed)} failed{': ' + ', '.join(failed) if failed else ''}")
    return 1 if failed else 0


def plan(due: list[str], out: Path, machines_file: Path | None) -> int:
    """Group the cards due into jobs and write them as a matrix: {"include": [{"cards", "labels"}]}."""
    # Cards that publish an app of the same name go in one job, one after the other.
    groups: list[tuple[set[str], list[str]]] = []
    for name in due:
        names = app_names(Path(name))
        joined = [g for g in groups if g[0] & names]
        for g in joined:
            groups.remove(g)
            names |= g[0]
        groups.append((names, [c for g in joined for c in g[1]] + [name]))
    machines = json.loads(machines_file.read_text()) if machines_file else None
    jobs = []
    for _, group in groups:
        need: list[str] = []
        for card in group:
            need += [l for l in labels(Path(card)) if l not in need]
        # Two memory tiers in one job: the larger covers both.
        mems = sorted((l for l in need if re.fullmatch(r"mem-\d+g", l)), key=lambda l: int(l[4:-1]))
        need = [l for l in need if l not in mems[:-1]]
        if machines is not None and not any(set(need) <= set(m) for m in machines):
            print(f"== {' '.join(group)}: no machine online has {', '.join(need)}", flush=True)
            continue
        jobs.append({"cards": " ".join(group), "labels": need})
        print(f"== job: {' '.join(group)} on {', '.join(need)}", flush=True)
    out.write_text(json.dumps({"include": jobs}) + "\n")
    print(f"\n{len(jobs)} job{'s' if len(jobs) != 1 else ''} for {sum(len(j['cards'].split()) for j in jobs)} cards")
    return 0


def merge(dirs: list[Path], status_dir: Path, status: dict, cards: list[str]) -> int:
    """Copy each card's result from the jobs' status directories into the status."""
    failed = []
    for d in dirs:
        results = d / "status.json"
        if not results.is_file():
            print(f"{d}: no status.json, so that job tested nothing", flush=True)
            continue
        for name, entry in json.loads(results.read_text()).items():
            status[name] = entry
            (status_dir / f"{name}.json").write_text(json.dumps(badge(entry["edgible-cli"], entry["result"])) + "\n")
            print(f"{name}: {entry['result']} on {entry.get('device', '?')}, Edgible {entry['edgible-cli']}", flush=True)
            if entry["result"] == "fail":
                failed.append(name)
    for gone in sorted(set(status) - set(cards)):
        del status[gone]
        (status_dir / f"{gone}.json").unlink(missing_ok=True)
    write_status(status_dir, status)
    print(f"\n{len(failed)} failed{': ' + ', '.join(failed) if failed else ''}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
