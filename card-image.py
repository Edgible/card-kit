#!/usr/bin/env python3
"""Draw images/card-light.svg and images/card-dark.svg from a card.yml.

The picture lists the apps, ports, auth modes and places in the card. It draws
no caller, no hostname and no machine. Run it from the repo root:

    ../card-kit/run card-image website

A line that does not fit its box is an error. Shorten that app's `what` line.
"""

from __future__ import annotations

import sys
from pathlib import Path
from xml.sax.saxutils import escape

OPEN, LOGIN, KEY = "open", "login", "key"

PALETTES = {
    "light": {
        "panel": "#e4e8f2",
        "card": "#ffffff",
        "edge": "#c2c8d8",
        "rule": "#e0e3ea",
        "ink": "#000033",
        "muted": "#4a4f66",
        "machine": "#2e4a9e",
        "machine_ink": "#ffffff",
        OPEN: "#2f6fb0",
        LOGIN: "#000033",
        KEY: "#7a5cc0",
    },
    "dark": {
        "panel": "#1a1a2e",
        "card": "#22223c",
        "edge": "#3a3a5c",
        "rule": "#33334f",
        "ink": "#e7e7f0",
        "muted": "#a5a8bd",
        "machine": "#3a56ad",
        "machine_ink": "#ffffff",
        OPEN: "#7db2e8",
        LOGIN: "#c3c6d8",
        KEY: "#b39ce8",
    },
}

AUTH_FROM = {
    "none": OPEN,
    "org": LOGIN,
    "api-key": KEY,
}

AUTH_LABEL = {
    OPEN: "open to anyone",
    LOGIN: "org login",
    KEY: "bearer key",
}

NOTE = "no device name, no hostname, no organization id"

JOST_EM = 0.52
MONO_EM = 0.55


def too_wide(text: str, limit: int, size: int, mono: bool = False) -> bool:
    return len(text) * size * (MONO_EM if mono else JOST_EM) > limit


def parse_card(text: str) -> tuple[str, list[dict[str, str]]]:
    name = ""
    apps: list[dict[str, str]] = []
    current: dict[str, str] | None = None
    in_apps = False
    for raw in text.splitlines():
        if not raw.strip() or raw.strip().startswith("#"):
            continue
        stripped = raw.strip()
        if stripped == "applications:":
            in_apps = True
            continue
        if not in_apps:
            if stripped.startswith("name:"):
                name = stripped.split(":", 1)[1].strip()
            continue
        if stripped.startswith("- "):
            if current:
                apps.append(current)
            current = {}
            stripped = stripped[2:].strip()
        if current is None or ":" not in stripped:
            continue
        key, value = stripped.split(":", 1)
        key = key.strip()
        value = value.strip()
        current[key] = value
    if current:
        apps.append(current)
    if not name or not apps:
        raise SystemExit("card needs metadata.name and at least one application")
    return name, apps


def auth_of(raw: str) -> str:
    inner = raw.strip()
    if inner.startswith("[") and inner.endswith("]"):
        inner = inner[1:-1]
    modes = [part.strip() for part in inner.split(",") if part.strip()]
    if len(modes) != 1 or modes[0] not in AUTH_FROM:
        raise SystemExit(f"authModes must be one of none, org, api-key: {raw!r}")
    return AUTH_FROM[modes[0]]


def place_subtitles(places: list[str]) -> dict[str, str]:
    unique = list(dict.fromkeys(places))
    if len(unique) <= 1:
        return {place: "one serving device" for place in unique}
    out = {unique[0]: "one serving device"}
    for place in unique[1:]:
        out[place] = "may be another serving device"
    return out


def count_phrase(n: int, singular: str, plural: str) -> str:
    words = {1: "one", 2: "two", 3: "three", 4: "four", 5: "five", 6: "six"}
    word = words.get(n, str(n))
    return f"{word} {singular if n == 1 else plural}"


def alt_text(card_name: str, groups: list[tuple[str, list[tuple]]], subtitles: dict[str, str]) -> str:
    total = sum(len(rows) for _, rows in groups)
    places = [place for place, _ in groups if place]
    bits = [
        f"The {card_name} card lists {count_phrase(total, 'app', 'apps')} in "
        f"{count_phrase(len(places) or 1, 'place', 'places')}, and no hostnames."
    ]
    for place, rows in groups:
        sentences = []
        for app_name, port, auth, what in rows:
            sentences.append(f"{app_name} is {what} on port {port}, {AUTH_LABEL[auth]}.")
        if place:
            lead = subtitles[place]
            if lead.startswith("may "):
                bits.append(f"Place {place} {lead}: " + " ".join(sentences))
            else:
                bits.append(f"Place {place} is {lead}: " + " ".join(sentences))
        else:
            bits.append(" ".join(sentences))
    bits.append("The card names no device and no organization.")
    return " ".join(bits)


def spec_from(name: str, apps: list[dict[str, str]]) -> dict:
    rows = []
    for app in apps:
        for field in ("name", "what", "port", "authModes", "place"):
            if field not in app:
                raise SystemExit(f"{app.get('name', '?')} needs {field}")
        rows.append(
            (
                app["name"],
                app["port"],
                auth_of(app["authModes"]),
                app["what"],
                app["place"],
            )
        )
    subtitles = place_subtitles([row[4] for row in rows])
    groups: list[tuple[str, list[tuple]]] = []
    for app_name, port, auth, what, place in rows:
        row = (app_name, port, auth, what)
        if groups and groups[-1][0] == place:
            groups[-1][1].append(row)
        else:
            groups.append((place, [row]))
    return {
        "card": f"{name.upper()} CARD",
        "apps": rows,
        "places": subtitles,
        "note": NOTE,
        "alt": alt_text(name, groups, subtitles),
    }


def check_card(spec: dict) -> list[str]:
    bad = []
    if too_wide(spec["card"], 480, 13):
        bad.append(f"card title does not fit: {spec['card']!r}")
    seen = set()
    for app_name, port, auth, what, place in spec["apps"]:
        if too_wide(app_name, 150, 13, mono=True):
            bad.append(f"app name does not fit: {app_name!r}")
        if too_wide(str(port), 80, 13, mono=True):
            bad.append(f"port does not fit: {port!r}")
        if too_wide(AUTH_LABEL[auth], 180, 13):
            bad.append(f"auth label does not fit: {AUTH_LABEL[auth]!r}")
        if too_wide(what, 420, 13):
            bad.append(f"what does not fit: {what!r}")
        if place and place not in seen:
            seen.add(place)
            if too_wide(place, 160, 15, mono=True):
                bad.append(f"place name does not fit: {place!r}")
            subtitle = spec["places"].get(place, "")
            if subtitle and too_wide(subtitle, 340, 13):
                bad.append(f"place note does not fit: {subtitle!r}")
    if too_wide(spec["note"], 560, 13):
        bad.append(f"card note does not fit: {spec['note']!r}")
    return bad


def card_svg(spec: dict, palette: dict) -> str:
    p = palette
    groups: list[tuple[str, list[tuple]]] = []
    for app_name, port, auth, what, place in spec["apps"]:
        row = (app_name, port, auth, what)
        if groups and groups[-1][0] == place:
            groups[-1][1].append(row)
        else:
            groups.append((place, [row]))
    subtitles = spec["places"]
    note = spec["note"]
    width = 720
    pad = 28
    row_h = 72
    row_gap = 12
    place_h = 32
    place_gap = 10
    group_gap = 18
    header_h = 44
    rows_top = pad + header_h + 36
    rows_h = 0
    for i, (place, rows) in enumerate(groups):
        if i:
            rows_h += group_gap
        if place:
            rows_h += place_h + place_gap
        rows_h += len(rows) * row_h + max(len(rows) - 1, 0) * row_gap
    note_block = 36 if note else 0
    height = rows_top + rows_h + 20 + note_block + pad

    parts: list[str] = []
    add = parts.append
    add(
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height:.0f}" '
        f'width="{width}" height="{height:.0f}" role="img" aria-labelledby="t d">'
    )
    add(f"<title id=\"t\">{escape(spec['alt'])}</title>")
    add(f"<desc id=\"d\">{escape(spec['alt'])}</desc>")
    add(
        "<style>"
        f".label{{font-family:Jost,system-ui,sans-serif;font-size:15px;fill:{p['ink']}}}"
        f".small{{font-family:Jost,system-ui,sans-serif;font-size:13px;fill:{p['muted']}}}"
        f".mono{{font-family:Iosevka,ui-monospace,monospace;font-size:15px;fill:{p['ink']}}}"
        f".head{{font-family:Jost,system-ui,sans-serif;font-size:13px;font-weight:600;"
        f"fill:{p['machine_ink']};letter-spacing:.04em}}"
        f".place{{font-family:Jost,system-ui,sans-serif;font-size:13px;fill:{p['ink']}}}"
        f".card{{fill:{p['card']};stroke:{p['edge']};stroke-width:1.5}}"
        "</style>"
    )
    add(f'<rect x="0" y="0" width="{width}" height="{height:.0f}" rx="10" fill="{p["panel"]}"/>')
    add(
        f'<path d="M10 0 h{width - 20} a10 10 0 0 1 10 10 v{header_h - 10} '
        f'h-{width} v-{header_h - 10} a10 10 0 0 1 10 -10 z" fill="{p["machine"]}"/>'
    )
    add(f'<text class="head" x="{pad}" y="28">{escape(spec["card"])}</text>')

    col_app = pad + 28
    col_port = 250
    col_auth = width - pad - 8
    add(f'<text class="small" x="{col_app}" y="{pad + header_h + 22:.0f}">app</text>')
    add(f'<text class="small" x="{col_port}" y="{pad + header_h + 22:.0f}">port</text>')
    add(
        f'<text class="small" x="{col_auth}" y="{pad + header_h + 22:.0f}" '
        f'text-anchor="end">auth</text>'
    )

    y = rows_top
    inner_w = width - 2 * pad
    for gi, (place, rows) in enumerate(groups):
        if gi:
            y += group_gap
        if place:
            add(
                f'<rect x="{pad}" y="{y:.0f}" width="{inner_w}" height="{place_h}" '
                f'rx="6" fill="{p["rule"]}"/>'
            )
            add(f'<text class="place" x="{pad + 14}" y="{y + 21:.0f}">place</text>')
            add(f'<text class="mono" x="{pad + 62}" y="{y + 22:.0f}">{escape(place)}</text>')
            subtitle = subtitles.get(place, "")
            if subtitle:
                add(
                    f'<text class="place" x="{width - pad - 14}" y="{y + 21:.0f}" '
                    f'text-anchor="end">{escape(subtitle)}</text>'
                )
            y += place_h + place_gap
        for i, (app_name, port, auth, what) in enumerate(rows):
            add(
                f'<rect class="card" x="{pad}" y="{y:.0f}" width="{inner_w}" '
                f'height="{row_h}" rx="8"/>'
            )
            add(
                f'<rect x="{pad}" y="{y:.0f}" width="6" height="{row_h}" rx="3" fill="{p[auth]}"/>'
            )
            baseline = y + 30
            add(f'<text class="mono" x="{col_app}" y="{baseline:.0f}">{escape(app_name)}</text>')
            add(f'<text class="mono" x="{col_port}" y="{baseline:.0f}">{escape(port)}</text>')
            add(
                f'<text class="small" x="{col_auth}" y="{baseline:.0f}" text-anchor="end">'
                f'{escape(AUTH_LABEL[auth])}</text>'
            )
            add(f'<text class="small" x="{col_app}" y="{baseline + 20:.0f}">{escape(what)}</text>')
            y += row_h
            if i < len(rows) - 1:
                y += row_gap

    if note:
        rule_y = rows_top + rows_h + 16
        add(
            f'<line x1="{pad}" y1="{rule_y:.0f}" x2="{width - pad}" y2="{rule_y:.0f}" '
            f'stroke="{p["rule"]}" stroke-width="1.5"/>'
        )
        add(f'<text class="small" x="{pad}" y="{rule_y + 22:.0f}">{escape(note)}</text>')

    add("</svg>")
    return "\n".join(parts) + "\n"


def draw(directory: Path) -> None:
    card_path = directory / "card.yml"
    if not card_path.is_file():
        raise SystemExit(f"no card.yml in {directory}")
    spec = spec_from(*parse_card(card_path.read_text()))
    bad = check_card(spec)
    if bad:
        raise SystemExit("\n".join(bad))
    images = directory / "images"
    images.mkdir(exist_ok=True)
    for theme, palette in PALETTES.items():
        (images / f"card-{theme}.svg").write_text(card_svg(spec, palette))
    print(f"wrote {images / 'card-light.svg'} and {images / 'card-dark.svg'}")


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("usage: ../card-kit/run card-image <card>")
    draw(Path(sys.argv[1]))


if __name__ == "__main__":
    main()
