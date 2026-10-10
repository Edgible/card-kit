#!/usr/bin/env python3
"""Check the edgible-cards skill's needs map against the sources it names.

    ../card-kit/run check-map          # from any repo, with card-kit beside it
    ./run check-map                    # from card-kit itself

Each entry in skills/edgible-cards/needs-map.yaml must have every field, a fit rating the
skill knows, and both exposure choices. Its category must be a category name in
awesome-selfhosted's data, which renames one now and then. Its starters and cards must
exist in Edgible/starters and Edgible/cards. It also lists the starters and cards that no
entry names, so a new one gets a place in the map.

It reads awesome-selfhosted-data and the GitHub API over the network, and exits 1 on a
problem.
"""
from __future__ import annotations

import io
import json
import sys
import tarfile
import urllib.request
from pathlib import Path

import yaml

MAP = Path(__file__).resolve().parent / "skills" / "edgible-cards" / "needs-map.yaml"
TAGS = "https://github.com/awesome-selfhosted/awesome-selfhosted-data/archive/refs/heads/master.tar.gz"
FIELDS = {"category", "jobs", "replaces", "drivers", "fit", "exposure", "machine", "starters", "cards", "ask"}
FITS = {"good", "conditional", "poor", "refused"}


def get(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "edgible-card-kit"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return r.read()


def categories() -> set[str]:
    names = set()
    with tarfile.open(fileobj=io.BytesIO(get(TAGS)), mode="r:gz") as tar:
        for m in tar.getmembers():
            if m.isfile() and "/tags/" in m.name and m.name.endswith(".yml"):
                names.add(yaml.safe_load(tar.extractfile(m))["name"])
    return names


def cards(repo: str) -> set[str]:
    """The top-level directories of an Edgible repo: each one with a card.yml is a card."""
    items = json.loads(get(f"https://api.github.com/repos/Edgible/{repo}/contents"))
    return {i["name"] for i in items if i["type"] == "dir" and not i["name"].startswith(".")}


def main() -> int:
    entries = yaml.safe_load(MAP.read_text())
    known, starters, card_names = categories(), cards("starters"), cards("cards")
    problems = []
    for e in entries:
        c = e.get("category", "?")
        problems += [f"{c}: no {k}" for k in sorted(FIELDS - set(e))]
        problems += [f"{c}: unknown field {k}" for k in sorted(set(e) - FIELDS)]
        if c not in known:
            problems.append(f"{c}: not a category in awesome-selfhosted")
        if e.get("fit", {}).get("rating") not in FITS:
            problems.append(f"{c}: fit rating must be one of {', '.join(sorted(FITS))}")
        if not {"default", "sensitive"} <= set(e.get("exposure", {})):
            problems.append(f"{c}: exposure needs default and sensitive")
        problems += [f"{c}: no starter {s} in Edgible/starters" for s in e.get("starters", []) if s not in starters]
        problems += [f"{c}: no card {s} in Edgible/cards" for s in e.get("cards", []) if s not in card_names]
    for p in problems:
        print(p)
    named = {s for e in entries for s in e.get("starters", []) + e.get("cards", [])}
    for missing in sorted((starters | card_names) - named):
        print(f"note: {missing} is in no entry of the map")
    print(f"{len(entries)} entries: " + ("ok" if not problems else f"{len(problems)} problem(s)"))
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
