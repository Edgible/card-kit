#!/usr/bin/env python3
"""Pick the next app to make an app card for: the first gap in the skill's needs map.

    ../card-kit/run pick-app                       # from the root of a cards repo
    ../card-kit/run pick-app --exclude linkwarden wallabag
    ../card-kit/run pick-app --app ownCloud           # a named app, and its category

A gap is a needs-map category that people ask about (its fit is good or conditional) and
that no card covers yet. The map's order is its priority. For the first gap with any
candidate, it lists the apps awesome-selfhosted has in that category that a card can be
made from: a Docker image, not archived, updated in the last six months, no third-party
service needed, not already a card, and not excluded (such as an app already proposed).
It prints JSON: the category, its needs-map entry, and up to --count candidates, most
starred first. Stars only order the list: whoever builds the card picks the app that does
the category's jobs best.

With --app, it picks that app instead, by its name on awesome-selfhosted, and gives the
needs-map category it belongs to: the first of its awesome-selfhosted categories that is in
the map, preferring one no card covers yet. So a card made for a named app still lands in
its category. An app it cannot find, or one in no mapped category, gets category null.

Categories Edgible adds (source: edgible, mostly AI tools) have no awesome-selfhosted data,
so they are listed under "unlisted_gaps" for a person or a later version to handle.
It reads awesome-selfhosted's data over the network, and exits 1 when there is no gap left.
"""
from __future__ import annotations

import argparse
import io
import json
import re
import sys
import tarfile
import urllib.request
from datetime import date, datetime, timedelta
from pathlib import Path

import yaml

MAP = Path(__file__).resolve().parent / "skills" / "edgible-cards" / "needs-map.yaml"
DATA = "https://github.com/awesome-selfhosted/awesome-selfhosted-data/archive/refs/heads/master.tar.gz"


def slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


def apps() -> list[dict]:
    req = urllib.request.Request(DATA, headers={"User-Agent": "edgible-card-kit"})
    with urllib.request.urlopen(req, timeout=120) as r:
        data = r.read()
    found = []
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as tar:
        for m in tar.getmembers():
            if m.isfile() and "/software/" in m.name and m.name.endswith(".yml"):
                found.append(yaml.safe_load(tar.extractfile(m)))
    return found


def recent(value, days: int = 183) -> bool:
    if not value:
        return False
    day = value if isinstance(value, date) else datetime.fromisoformat(str(value)[:10]).date()
    return day >= date.today() - timedelta(days=days)


def candidate(app: dict) -> dict:
    return {
        "name": app["name"], "card": slug(app["name"]), "description": app.get("description", ""),
        "website": app.get("website_url", ""), "source": app.get("source_code_url", ""),
        "licenses": app.get("licenses", []), "stars": app.get("stargazers_count", 0),
        "updated": str(app.get("updated_at", ""))[:10],
    }


def named(name: str) -> int:
    """The app someone asked for, with the needs-map category it belongs to."""
    entries = yaml.safe_load(MAP.read_text())
    app = next((a for a in apps() if slug(a["name"]) == slug(name)), None)
    if not app:
        print(f"{name}: not on awesome-selfhosted; its card will have no category", file=sys.stderr)
        print(json.dumps({"category": None, "candidates": [{"name": name}]}, indent=2))
        return 0
    tags = app.get("tags") or []
    mapped = [e for e in entries if e["category"] in tags]
    # A category no card covers yet first, so the card fills a gap when it can.
    mapped.sort(key=lambda e: bool(e.get("cards")))
    entry = mapped[0] if mapped else None
    print(json.dumps({"category": entry["category"] if entry else None, "entry": entry,
                      "candidates": [candidate(app)]}, indent=2, default=str))
    return 0


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--exclude", nargs="*", default=[], metavar="NAME",
                    help="apps not to pick, such as ones already proposed (names or card names)")
    ap.add_argument("--count", type=int, default=5)
    ap.add_argument("--app", metavar="NAME", help="pick this app, by its name on awesome-selfhosted, and find its category")
    args = ap.parse_args(argv)
    if args.app:
        return named(args.app)

    entries = yaml.safe_load(MAP.read_text())
    cards = {p.parent.name for p in Path.cwd().glob("*/card.yml")}
    excluded = {slug(n) for n in args.exclude} | cards
    gaps = [e for e in entries if not e.get("cards") and e["fit"]["rating"] in ("good", "conditional")]
    unlisted = [e["category"] for e in gaps if e.get("source") == "edgible"]
    listed = [e for e in gaps if e.get("source") != "edgible"]
    software = apps()

    for entry in listed:
        candidates = []
        for app in software:
            if entry["category"] not in (app.get("tags") or []):
                continue
            if app.get("archived") or app.get("depends_3rdparty"):
                continue
            if "Docker" not in (app.get("platforms") or []) or not recent(app.get("updated_at")):
                continue
            if slug(app["name"]) in excluded:
                continue
            candidates.append(candidate(app))
        if candidates:
            candidates.sort(key=lambda a: -(a["stars"] or 0))
            print(json.dumps({"category": entry["category"], "entry": entry,
                              "candidates": candidates[:args.count], "unlisted_gaps": unlisted},
                             indent=2, default=str))
            return 0
    print(json.dumps({"category": None, "candidates": [], "unlisted_gaps": unlisted}, indent=2))
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
