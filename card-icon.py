#!/usr/bin/env python3
"""Fetch a card's icon, its app's own logo, into images/icon.svg (or icon.png).

The catalog site shows it on the card's tile and page; a card without one shows the
Edgible symbol instead. Run it from the repo root:

    ../card-kit/run card-icon umami
    ../card-kit/run card-icon ci --slug gitea      # a pattern named after its main app

It looks the slug up (the card's name, unless --slug says otherwise) in two open icon
sets of self-hosted app logos, SVG first:

    dashboard-icons  https://github.com/homarr-labs/dashboard-icons  (Apache-2.0)
    selfh.st icons   https://github.com/selfhst/icons                 (CC BY 4.0)

The logos stay the trademarks of their apps, used to name the app. A card for something
that is not one app (a pattern, a generic service) needs no icon: the placeholder suits it.
"""

from __future__ import annotations

import argparse
import sys
import urllib.error
import urllib.request
from pathlib import Path

SOURCES = [
    ("dashboard-icons", "https://cdn.jsdelivr.net/gh/homarr-labs/dashboard-icons/{fmt}/{slug}.{fmt}"),
    ("selfh.st icons", "https://cdn.jsdelivr.net/gh/selfhst/icons/{fmt}/{slug}.{fmt}"),
]


def fetch(url: str) -> bytes | None:
    try:
        with urllib.request.urlopen(url, timeout=20) as r:
            return r.read() if r.status == 200 else None
    except urllib.error.URLError:
        return None


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("card", help="the card's directory")
    ap.add_argument("--slug", help="the app's name in the icon sets, if it differs from the card's")
    args = ap.parse_args(argv)

    card = Path(args.card)
    if not (card / "card.yml").is_file():
        print(f"no card.yml in {card}", file=sys.stderr)
        return 2
    slug = (args.slug or card.name).lower()
    images = card / "images"
    for fmt in ("svg", "png"):
        for name, pattern in SOURCES:
            url = pattern.format(fmt=fmt, slug=slug)
            data = fetch(url)
            if not data:
                continue
            if fmt == "svg" and b"<svg" not in data[:2000]:
                continue
            images.mkdir(exist_ok=True)
            for old in images.glob("icon.*"):
                old.unlink()
            out = images / f"icon.{fmt}"
            out.write_bytes(data)
            print(f"wrote {out} from {name}: {url}")
            return 0
    print(f"no icon named {slug} in dashboard-icons or selfh.st icons; the site shows the Edgible "
          "placeholder. Try --slug with the app's name as those sets spell it.", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
