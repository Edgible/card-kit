#!/usr/bin/env python3
"""Test every card in a repo that needs it, and keep a status for each one.

Run it on a serving device, from the root of a cards or starters repo:

    python3 ../card-kit/test-cards.py --device macbookair --status ../status
    python3 ../card-kit/test-cards.py --device macbookair --status ../status --only gitea

A card needs a test when its status says it has not been tested, when its files changed
since (the files: fingerprint test-card records), or when `edgible --version` is not the
version it last passed or failed on. A new Edgible version therefore retests every card.
--all tests every card anyway, and --only tests the named ones.

The status directory holds status.json, every card's latest result, and one <card>.json
per card in the shape of a shields.io endpoint badge, labelled with the Edgible version:

    https://img.shields.io/endpoint?url=<raw URL of the status directory>/gitea.json

It runs test-card for each card, one at a time, and never changes the repo: test.yml is
the author's record of a version, and the status is CI's record of what still passes.
It exits 1 when a card it tested failed.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import re
import subprocess
import sys
from datetime import date
from pathlib import Path

HERE = Path(__file__).resolve().parent


def files_hash(card_dir: Path) -> str:
    spec = importlib.util.spec_from_file_location("test_card", HERE / "test-card.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.files_hash(card_dir)


def badge(cli: str, result: str) -> dict:
    return {"schemaVersion": 1, "label": f"Edgible {cli}",
            "message": "passing" if result == "pass" else "failing",
            "color": "brightgreen" if result == "pass" else "red"}


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--device", required=True, help="the serving device, as `edgible device list` names it")
    ap.add_argument("--status", type=Path, required=True, help="the status directory to read and write")
    ap.add_argument("--all", action="store_true", help="test every card, whether it needs it or not")
    ap.add_argument("--only", nargs="+", default=[], metavar="CARD", help="test only these cards")
    ap.add_argument("--by", choices=["agent", "person", "ci"], default="ci")
    args = ap.parse_args(argv)

    cards = sorted(p.parent.name for p in Path.cwd().glob("*/card.yml"))
    unknown = set(args.only) - set(cards)
    if unknown:
        print(f"no card named {', '.join(sorted(unknown))}", file=sys.stderr)
        return 2
    cli = subprocess.run(["edgible", "--version"], capture_output=True, text=True).stdout.strip()
    if not cli:
        print("edgible --version printed nothing; is the edgible CLI installed?", file=sys.stderr)
        return 2
    args.status.mkdir(parents=True, exist_ok=True)
    status_file = args.status / "status.json"
    status = json.loads(status_file.read_text()) if status_file.is_file() else {}

    failed = []
    for name in cards:
        files = files_hash(Path(name))
        entry = status.get(name)
        if args.only:
            reason = "asked for" if name in args.only else ""
        elif args.all:
            reason = "asked for all"
        elif not entry:
            reason = "no status yet"
        elif entry.get("files") != files:
            reason = "its files changed"
        elif entry.get("edgible-cli") != cli:
            reason = f"Edgible {entry.get('edgible-cli')} -> {cli}"
        else:
            reason = ""
        if not reason:
            print(f"== {name}: skip, still {entry['result']} on Edgible {cli} with these files", flush=True)
            continue

        print(f"== {name}: test, because {reason}", flush=True)
        run = subprocess.run([sys.executable, str(HERE / "test-card.py"), name, "--device", args.device,
                              "--by", args.by], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        print(run.stdout, end="", flush=True)
        match = re.search(r"^result: (pass|fail)", run.stdout, re.M)
        result = match.group(1) if match and run.returncode == 0 else "fail"
        if result == "fail":
            failed.append(name)
        status[name] = {"result": result, "tested": str(date.today()), "edgible-cli": cli, "files": files}
        # Write as it goes, so a run that stops part way keeps what it learned.
        status_file.write_text(json.dumps(dict(sorted(status.items())), indent=2) + "\n")
        (args.status / f"{name}.json").write_text(json.dumps(badge(cli, result)) + "\n")

    for gone in sorted(set(status) - set(cards)):
        del status[gone]
        (args.status / f"{gone}.json").unlink(missing_ok=True)
    status_file.write_text(json.dumps(dict(sorted(status.items())), indent=2) + "\n")
    print(f"\n{len(failed)} failed{': ' + ', '.join(failed) if failed else ''}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
