#!/usr/bin/env python3
"""Build the catalog site: a static website of the cards, their test results, and the needs map.

    ../card-kit/run card-site --out _site --status _status.json --base-url https://edgible.github.io/cards

Run it from the root of the cards repo. It writes one page per card (its README, picture,
apps, and latest test), one page per need in the skill's needs map (what people say, whether
self-hosting suits it, how to publish it, and the cards for it), an index of each, and
llms.txt, sitemap.xml, and robots.txt.

The output is a plain folder with relative links, so the same build works at any address
and under any path: GitHub Pages, an nginx container, or a bucket. --base-url is used only
where a full address is required: the canonical link on each page, the sitemap, and
llms.txt. Without it, those are left out.

--status is the regression's status.json, from the cards repo's test-status branch. Without
it, every card shows as not tested yet. The needs map is the one beside the skill in this
kit, unless --needs names another.
"""
from __future__ import annotations

import argparse
import html
import json
import re
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

import markdown
import yaml

KIT = Path(__file__).resolve().parent
NEEDS_MAP = KIT / "skills" / "edgible-cards" / "needs-map.yaml"
REPO_URL = "https://github.com/Edgible/cards"
SKILL_URL = "https://github.com/Edgible/card-kit/tree/main/skills/edgible-cards"
AWESOME = "https://awesome-selfhosted.net/tags/{slug}.html"

AUTH_WORDS = {"none": "open to anyone", "org": "org login", "api-key": "API key"}
FIT_WORDS = {
    "good": "Good fit",
    "conditional": "Fits, with conditions",
    "poor": "Usually better elsewhere",
    "refused": "Not recommended",
}
DRIVER_WORDS = {
    "cost": "cost", "privacy": "privacy", "control": "control",
    "shut-down": "a service that shut down or got worse", "compliance": "compliance",
    "local": "it has to run at home",
}
RESERVED = {"needs", "style.css", "llms.txt", "sitemap.xml", "robots.txt", "404.html", "index.html"}


def esc(s: object) -> str:
    return html.escape(str(s), quote=True)


def given(v: object) -> object:
    """A needs-map value, or None when it is empty or says n/a."""
    return None if v is None or str(v).strip().lower() in ("", "n/a", "na", "none needed") else v


def slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")


def load_cards(root: Path) -> dict[str, dict]:
    cards = {}
    for f in sorted(root.glob("*/card.yml")):
        d = f.parent
        if d.name.startswith((".", "_")):
            continue
        if d.name in RESERVED:
            sys.exit(f"{d.name}: a card cannot be named {d.name}, the site uses that path")
        card = yaml.safe_load(f.read_text())
        readme = d / "README.md"
        cards[d.name] = {
            "name": d.name,
            "dir": d,
            "card": card,
            "type": card.get("metadata", {}).get("type", "app"),
            "description": card.get("metadata", {}).get("description", ""),
            "readme": readme.read_text() if readme.exists() else "",
        }
    return cards


def status_pill(st: dict | None, prefix: str = "") -> str:
    if not st:
        return '<span class="pill untested">not tested yet</span>'
    cls = "pass" if st.get("result") == "pass" else "fail"
    word = "passed" if cls == "pass" else "failed"
    ver = f", Edgible {esc(st['edgible-cli'])}" if st.get("edgible-cli") else ""
    return (f'<span class="pill {cls}" title="Latest lifecycle test on a real Edgible serving device">'
            f'{word} {esc(st.get("tested", ""))}{ver}</span>')


def status_text(st: dict | None) -> str:
    if not st:
        return "not tested yet"
    word = "passed" if st.get("result") == "pass" else "failed"
    ver = f" on Edgible {st['edgible-cli']}" if st.get("edgible-cli") else ""
    return f"test {word} {st.get('tested', '')}{ver}"


class Site:
    def __init__(self, root: Path, out: Path, cards: dict, needs: list, status: dict,
                 base_url: str, commit: str):
        self.root, self.out, self.cards, self.needs = root, out, cards, needs
        self.status, self.base = status, base_url.rstrip("/")
        self.commit = commit
        self.built = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        self.pages: list[str] = []
        # Which needs name each card, for the card pages.
        self.needs_of: dict[str, list[dict]] = {}
        for n in needs:
            for c in n.get("cards") or []:
                self.needs_of.setdefault(c, []).append(n)

    # Pages ----------------------------------------------------------------

    def page(self, path: str, title: str, description: str, body: str) -> None:
        """Write one page. path is its folder under the site ("" for the root, "umami/")."""
        depth = path.count("/")
        up = "../" * depth
        canonical = f'<link rel="canonical" href="{esc(self.base + "/" + path)}">' if self.base else ""
        commit = (f' at <a href="{REPO_URL}/commit/{esc(self.commit)}">{esc(self.commit[:7])}</a>'
                  if self.commit else "")
        doc = f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{esc(title)}</title>
<meta name="description" content="{esc(description)}">
{canonical}
<link rel="stylesheet" href="{up}style.css">
</head>
<body>
<header class="top"><div class="wrap">
<a class="brand" href="{up}">Edgible cards</a>
<nav><a href="{up}#app-cards">Apps</a><a href="{up}#pattern-cards">Patterns</a><a href="{up}needs/">Needs</a><a href="{REPO_URL}">GitHub</a></nav>
</div></header>
<main class="wrap">
{body}
</main>
<footer class="wrap">
<p>Built {self.built} from <a href="{REPO_URL}">Edgible/cards</a>{commit}. Cards are free to run and share under the repo's license. Test results come from the nightly regression, on a real Edgible serving device.</p>
</footer>
</body>
</html>
"""
        f = self.out / path / "index.html" if not path.endswith(".html") else self.out / path
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(doc)
        if not path.endswith(".html"):
            self.pages.append(path)

    def card_tile(self, c: dict, up: str) -> str:
        return (f'<li class="tile"><a href="{up}{esc(c["name"])}/"><strong>{esc(c["name"])}</strong></a>'
                f'<span>{esc(c["description"])}</span>{status_pill(self.status.get(c["name"]))}</li>')

    def index(self) -> None:
        apps = [c for c in self.cards.values() if c["type"] == "app"]
        patterns = [c for c in self.cards.values() if c["type"] != "app"]
        tested = sum(1 for c in self.cards if self.status.get(c, {}).get("result") == "pass")
        body = f"""<section class="hero">
<h1>Self-hosted apps, tested on a real machine every week</h1>
<p>Each card runs one self-hosted app, or wires several together, on a machine you control: at home, in the office, or a small cloud server. It records the images, ports, and who may reach each hostname, and leaves out anything that is yours, so you can run it as it is. Edgible publishes the apps, with hostnames, TLS, and sign-in.</p>
<p class="stats">{len(apps)} app cards, {len(patterns)} pattern cards, {tested} passing their latest test, {len(self.needs)} needs mapped.</p>
</section>
<h2 id="app-cards">App cards</h2>
<p>One app each, ready on its own or as a building block. Every app card is tested end to end, and again when it changes or Edgible releases a new version.</p>
<ul class="tiles">{"".join(self.card_tile(c, "") for c in apps)}</ul>
<h2 id="pattern-cards">Pattern cards</h2>
<p>Several apps wired together for a purpose, built from app cards.</p>
<ul class="tiles">{"".join(self.card_tile(c, "") for c in patterns)}</ul>
<h2>Start from a need</h2>
<p>What people want to self-host, whether it suits a machine of your own, and how to publish it safely. <a href="needs/">All {len(self.needs)} needs</a>.</p>
{self.leaving_list("needs/")}
<h2>With an AI agent</h2>
<p>The <a href="{SKILL_URL}">edgible-cards skill</a> teaches an AI agent, such as Claude Code, to go from a need to a running, published card, and to look after it.</p>
"""
        self.page("", "Edgible cards: self-hosted apps, tested every week",
                  "Self-hosted apps you can run on a machine you control, each tested end to end on a real Edgible serving device.",
                  body)

    def leaving_list(self, up: str) -> str:
        """Hosted services people leave, each linked to its need: the way most people search."""
        items = []
        for n in self.needs:
            for r in n.get("replaces") or []:
                items.append((r.lower(), f'<li><a href="{up}{slug(n["category"])}/">{esc(r)}</a></li>'))
        items.sort()
        return f'<p class="leaving-label">Leaving a hosted service?</p><ul class="leaving">{"".join(i for _, i in items)}</ul>'

    def card_page(self, c: dict) -> None:
        name, card = c["name"], c["card"]
        st = self.status.get(name)
        apps = card.get("applications") or []
        rows = "".join(
            f'<tr><td><code>{esc(a.get("name"))}</code></td><td>{esc(a.get("what", ""))}</td>'
            f'<td>{esc(", ".join(AUTH_WORDS.get(m, m) for m in a.get("authModes") or []))}</td>'
            f'<td><code>{esc(a.get("place", ""))}</code></td></tr>'
            for a in apps)
        places = "".join(
            f'<tr><td><code>{esc(p)}</code></td><td>{esc(v.get("memory", ""))}</td><td>{esc(v.get("disk", ""))}</td>'
            f'<td>{esc(", ".join(v.get("arch") or []))}</td><td>{esc(v.get("gpu", "none"))}</td></tr>'
            for p, v in (card.get("places") or {}).items())
        needs = self.needs_of.get(name, [])
        needs_html = ""
        if needs:
            needs_html = "<h2>Needs it answers</h2><ul>" + "".join(
                f'<li><a href="../needs/{slug(n["category"])}/">{esc(n["category"])}</a></li>' for n in needs) + "</ul>"
        picture = ""
        img = c["dir"] / "images"
        if (img / "card-light.svg").exists():
            dest = self.out / name
            dest.mkdir(parents=True, exist_ok=True)
            for f in ("card-light.svg", "card-dark.svg"):
                if (img / f).exists():
                    shutil.copy(img / f, dest / f)
            dark = '<source srcset="card-dark.svg" media="(prefers-color-scheme: dark)">' if (img / "card-dark.svg").exists() else ""
            picture = (f'<picture class="card-image">{dark}<img src="card-light.svg" '
                       f'alt="The apps, ports, auth modes, and places in the {esc(name)} card"></picture>')
        kind = "App card" if c["type"] == "app" else "Pattern card"
        body = f"""<p class="crumbs"><a href="../">Cards</a> / {esc(name)}</p>
<h1>{esc(name)}</h1>
<p class="lead">{esc(c["description"])}</p>
<p class="meta"><span class="kind">{kind}</span>{status_pill(st)}<a href="{REPO_URL}/tree/main/{esc(name)}">Source on GitHub</a></p>
{picture}
<h2>Apps</h2>
<div class="scroll"><table><thead><tr><th>App</th><th>What</th><th>Who can reach it</th><th>Place</th></tr></thead><tbody>{rows}</tbody></table></div>
<h2>Machine</h2>
<p>A place is one serving device. Minimum recommended for each:</p>
<div class="scroll"><table><thead><tr><th>Place</th><th>Memory</th><th>Disk</th><th>Architecture</th><th>GPU</th></tr></thead><tbody>{places}</tbody></table></div>
{needs_html}
<article class="readme">
{self.readme_html(c)}
</article>
"""
        title = f"{name}: {c['description']}"
        self.page(f"{name}/", f"{title} | Edgible cards", c["description"], body)

    def readme_html(self, c: dict) -> str:
        text = c["readme"]
        # The page has its own heading; drop the README's.
        text = re.sub(r"\A# [^\n]*\n", "", text)
        out = markdown.markdown(text, extensions=["tables", "fenced_code", "toc"])

        def fix(m: re.Match) -> str:
            attr, href = m.group(1), html.unescape(m.group(2))
            if re.match(r"^([a-z]+:|#|/)", href):
                return m.group(0)
            path, _, frag = href.partition("#")
            target = (c["dir"] / path).resolve()
            try:
                rel = target.relative_to(self.root.resolve())
            except ValueError:
                return m.group(0)
            parts = rel.parts
            # A link to another card goes to its page here.
            if len(parts) == 1 and parts[0] in self.cards:
                new = f"../{parts[0]}/" + (f"#{frag}" if frag else "")
            elif rel == Path("."):
                new = "../"
            else:
                kind = "tree" if target.is_dir() else "blob"
                new = f"{REPO_URL}/{kind}/main/{rel.as_posix()}" + (f"#{frag}" if frag else "")
            return f'{attr}="{esc(new)}"'

        out = re.sub(r'(href|src)="([^"]*)"', fix, out)
        # A wide table scrolls in its own box, not the page.
        return out.replace("<table>", '<div class="scroll"><table>').replace("</table>", "</table></div>")

    def needs_index(self) -> None:
        order = ["good", "conditional", "poor", "refused"]
        groups = []
        for rating in order:
            ns = [n for n in self.needs if (n.get("fit") or {}).get("rating") == rating]
            if not ns:
                continue
            items = "".join(
                f'<li class="tile"><a href="{slug(n["category"])}/"><strong>{esc(n["category"])}</strong></a>'
                f'<span>{esc(", ".join((n.get("jobs") or [])[:2]))}</span>{self.card_count(n)}</li>'
                for n in ns)
            groups.append(f'<h2>{FIT_WORDS[rating]}</h2><ul class="tiles">{items}</ul>')
        body = f"""<p class="crumbs"><a href="../">Cards</a> / needs</p>
<h1>Start from a need</h1>
<p class="lead">What people want to self-host, in their words, with an honest answer on whether a machine of your own suits it. Some needs are better met elsewhere, and their pages say so.</p>
{self.leaving_list("")}
{"".join(groups)}
"""
        self.page("needs/", "Self-hosting, need by need | Edgible cards",
                  "What people want to self-host, whether it suits a machine of your own, and how to publish it safely.",
                  body)

    def card_count(self, n: dict) -> str:
        cs = [c for c in n.get("cards") or [] if c in self.cards]
        if not cs:
            return '<span class="pill untested">no card yet</span>'
        return f'<span class="pill neutral">{len(cs)} card{"s" if len(cs) > 1 else ""}</span>'

    def need_page(self, n: dict) -> None:
        cat = n["category"]
        fit = n.get("fit") or {}
        rating = fit.get("rating", "conditional")
        exposure = n.get("exposure") or {}
        jobs = n.get("jobs") or []
        replaces = n.get("replaces") or []
        drivers = [DRIVER_WORDS.get(d, d) for d in n.get("drivers") or []]

        sec = []
        if jobs:
            sec.append("<h2>What people say</h2><ul>" + "".join(f"<li>{esc(j)}</li>" for j in jobs) + "</ul>")
        if replaces or drivers:
            p = []
            if replaces:
                p.append(f"People leave {esc(', '.join(replaces))} for it.")
            if drivers:
                p.append(f"Why, strongest first: {esc(', '.join(drivers))}.")
            sec.append("<h2>Why people self-host it</h2><p>" + " ".join(p) + "</p>")
        sec.append(f'<h2>Does it suit a machine of your own?</h2><p><span class="fit {esc(rating)}">'
                   f'{FIT_WORDS.get(rating, rating)}</span> {esc(fit.get("why", ""))}</p>')
        if n.get("ask"):
            sec.append("<h2>Questions that decide it</h2><ul>" + "".join(f"<li>{esc(a)}</li>" for a in n["ask"]) + "</ul>")
        if any(given(v) for v in exposure.values()) and rating != "refused":
            rows = [("Usually", exposure.get("default")), ("When the data is private or sensitive", exposure.get("sensitive")),
                    ("When the data is regulated", exposure.get("regulated"))]
            sec.append("<h2>How to publish it</h2><dl>" + "".join(
                f"<dt>{esc(k)}</dt><dd>{esc(v)}</dd>" for k, v in rows if given(v)) + "</dl>")
        for key, head in (("permissions", "Who sees what inside it"), ("machine", "The machine"),
                          ("builders", "For builders")):
            if given(n.get(key)):
                sec.append(f"<h2>{head}</h2><p>{esc(n[key])}</p>")
        cs = [self.cards[c] for c in n.get("cards") or [] if c in self.cards]
        if cs:
            sec.append('<h2>Cards for it</h2><ul class="tiles">' + "".join(self.card_tile(c, "../../") for c in cs) + "</ul>")
        elif rating not in ("poor", "refused"):
            where = (esc(n["find"]) if n.get("find") else
                     f'Apps for it are listed on <a href="{AWESOME.format(slug=slug(cat))}">awesome-selfhosted</a>.')
            sec.append(f'<h2>Cards for it</h2><p>No card yet. {where} An agent with the '
                       f'<a href="{SKILL_URL}">edgible-cards skill</a> can shortlist apps and build one, '
                       f'or you can <a href="{REPO_URL}/issues/new?template=app-request.md">ask for one</a>.</p>')
        if not n.get("source"):
            sec.append(f'<p class="source">Category from <a href="{AWESOME.format(slug=slug(cat))}">awesome-selfhosted</a>.</p>')

        lead = jobs[0][0].upper() + jobs[0][1:] + "?" if jobs else ""
        title = f"Self-hosting {cat.lower()}" + (f": leaving {replaces[0]}?" if replaces else "")
        body = f"""<p class="crumbs"><a href="../../">Cards</a> / <a href="../">needs</a> / {esc(cat)}</p>
<h1>{esc(cat)}</h1>
<p class="lead">{esc(lead)}</p>
{"".join(sec)}
"""
        desc = f"{FIT_WORDS.get(rating, rating)} for self-hosting. {fit.get('why', '')}"
        self.page(f"needs/{slug(cat)}/", f"{title} | Edgible cards", desc, body)

    # Files for machines -----------------------------------------------------

    def llms_txt(self) -> None:
        base = self.base + "/" if self.base else ""

        def line(c):
            return f"- [{c['name']}]({base}{c['name']}/): {c['description']}. {status_text(self.status.get(c['name']))[:1].upper()}{status_text(self.status.get(c['name']))[1:]}."
        apps = [line(c) for c in self.cards.values() if c["type"] == "app"]
        patterns = [line(c) for c in self.cards.values() if c["type"] != "app"]
        needs = [f"- [{n['category']}]({base}needs/{slug(n['category'])}/): "
                 f"{FIT_WORDS.get((n.get('fit') or {}).get('rating'), '')}. "
                 + (f"Replaces {', '.join(n['replaces'])}. " if n.get("replaces") else "")
                 + (f"Cards: {', '.join(n['cards'])}." if n.get("cards") else "No card yet.")
                 for n in self.needs]
        text = f"""# Edgible cards

> Self-hosted apps to run on a machine you control (at home, in the office, or a small cloud server), published through Edgible. Each card records the images, ports, and auth mode of each hostname, and is tested end to end on a real Edgible serving device.

Each card page has how to start, publish, check, and remove the card. Each need page says whether self-hosting suits that need, which questions decide it, and how to publish it safely. The source of every card is {REPO_URL}. An AI agent can do the whole flow with the edgible-cards skill: {SKILL_URL}

## App cards

{chr(10).join(apps)}

## Pattern cards

{chr(10).join(patterns)}

## Needs

{chr(10).join(needs)}
"""
        (self.out / "llms.txt").write_text(text)

    def sitemap(self) -> None:
        urls = "".join(f"<url><loc>{esc(self.base + '/' + p)}</loc><lastmod>{self.built}</lastmod></url>\n"
                       for p in self.pages)
        (self.out / "sitemap.xml").write_text(
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            f'<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n{urls}</urlset>\n')

    def robots(self) -> None:
        text = "User-agent: *\nAllow: /\n"
        if self.base:
            text += f"Sitemap: {self.base}/sitemap.xml\n"
        (self.out / "robots.txt").write_text(text)

    def not_found(self) -> None:
        # Served from any depth, so its links are absolute when the base is known.
        body = '<h1>Not found</h1><p>That page is not here. The <a href="./">cards</a> and the <a href="needs/">needs</a> are.</p>'
        self.page("404.html", "Not found | Edgible cards", "Page not found.", body)
        if self.base:
            f = self.out / "404.html"
            f.write_text(f.read_text().replace('href="./', f'href="{self.base}/').replace(
                'href="needs/', f'href="{self.base}/needs/').replace('href="style.css', f'href="{self.base}/style.css'))

    def build(self) -> None:
        if self.out.exists():
            shutil.rmtree(self.out)
        self.out.mkdir(parents=True)
        (self.out / "style.css").write_text(STYLE)
        # GitHub Pages runs Jekyll on a branch build unless this is present; harmless elsewhere.
        (self.out / ".nojekyll").write_text("")
        self.index()
        for c in self.cards.values():
            self.card_page(c)
        self.needs_index()
        for n in self.needs:
            self.need_page(n)
        self.not_found()
        self.llms_txt()
        if self.base:
            self.sitemap()
        self.robots()


STYLE = """:root{--bg:#f6f7fb;--panel:#ffffff;--ink:#000033;--muted:#4a4f66;--edge:#d6dae6;--brand:#2e4a9e;--link:#2f5fb0;
--pass-bg:#e3f4e8;--pass:#1d6b37;--fail-bg:#fbe5e3;--fail:#9b2318;--none-bg:#eceef4;--none:#4a4f66;--code:#eef0f6}
@media (prefers-color-scheme:dark){:root{--bg:#0d1020;--panel:#151a2e;--ink:#e8eaf4;--muted:#a3a8bf;--edge:#2a3150;--brand:#9db2ff;
--link:#9db2ff;--pass-bg:#173524;--pass:#8fdca8;--fail-bg:#3d1a17;--fail:#f2a59c;--none-bg:#232a44;--none:#b6bbd2;--code:#1d2340}}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);font:16px/1.6 system-ui,-apple-system,"Segoe UI",sans-serif}
a{color:var(--link)}
.wrap{max-width:960px;margin:0 auto;padding:0 16px}
.top{background:var(--panel);border-bottom:1px solid var(--edge)}
.top .wrap{display:flex;flex-wrap:wrap;gap:8px 24px;align-items:center;justify-content:space-between;padding-top:12px;padding-bottom:12px}
.brand{font-weight:700;color:var(--brand);text-decoration:none;font-size:18px}
nav{display:flex;flex-wrap:wrap;gap:16px}nav a{text-decoration:none;color:var(--muted)}nav a:hover{color:var(--ink)}
main{padding-top:24px;padding-bottom:48px}
h1{font-size:2rem;line-height:1.2;margin:.2em 0 .3em}h2{font-size:1.3rem;margin:2em 0 .5em}h3{font-size:1.1rem}
.hero h1{font-size:2.3rem;max-width:20ch}.hero p{max-width:65ch}
.lead{font-size:1.15rem;color:var(--muted);max-width:65ch}
.stats{font-weight:600}
.crumbs{color:var(--muted);font-size:.9rem;margin:0}
.meta{display:flex;flex-wrap:wrap;gap:8px 16px;align-items:center}
.kind{font-weight:600}
.tiles{list-style:none;padding:0;display:grid;grid-template-columns:repeat(auto-fill,minmax(260px,1fr));gap:12px}
.tile{background:var(--panel);border:1px solid var(--edge);border-radius:10px;padding:14px 16px;display:flex;flex-direction:column;gap:6px;align-items:flex-start}
.tile a{text-decoration:none}.tile span:not(.pill){color:var(--muted);font-size:.93rem}
.pill{display:inline-block;border-radius:999px;padding:1px 10px;font-size:.8rem;font-weight:600;white-space:nowrap}
.pill.pass{background:var(--pass-bg);color:var(--pass)}.pill.fail{background:var(--fail-bg);color:var(--fail)}
.pill.untested,.pill.neutral{background:var(--none-bg);color:var(--none)}
.fit{display:inline-block;border-radius:6px;padding:1px 8px;font-weight:600;margin-right:6px}
.fit.good{background:var(--pass-bg);color:var(--pass)}.fit.conditional{background:var(--none-bg);color:var(--ink)}
.fit.poor,.fit.refused{background:var(--fail-bg);color:var(--fail)}
.leaving-label{font-weight:600;margin-bottom:4px}
.leaving{list-style:none;padding:0;display:flex;flex-wrap:wrap;gap:6px 14px;margin-top:0}
.card-image img{max-width:100%;height:auto;display:block;margin:16px 0}
.scroll{overflow-x:auto}
table{border-collapse:collapse;width:100%;background:var(--panel);font-size:.95rem}
th,td{border:1px solid var(--edge);padding:6px 10px;text-align:left;vertical-align:top}th{font-weight:600}
code{background:var(--code);border-radius:4px;padding:1px 4px;font-size:.9em}
pre{background:var(--code);border-radius:8px;padding:12px 14px;overflow-x:auto}pre code{padding:0;background:none}
dt{font-weight:600;margin-top:10px}dd{margin:2px 0 0 0}
.readme{border-top:1px solid var(--edge);margin-top:32px}
.readme img{max-width:100%}
.source{color:var(--muted);font-size:.9rem;margin-top:2em}
footer{color:var(--muted);font-size:.85rem;border-top:1px solid var(--edge);padding-top:16px;padding-bottom:32px}
"""


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--out", type=Path, default=Path("_site"), help="the folder to write; it is replaced")
    ap.add_argument("--status", type=Path, help="the regression's status.json")
    ap.add_argument("--needs", type=Path, default=NEEDS_MAP, help="the needs map; default: the one in this kit")
    ap.add_argument("--base-url", default="", help="the site's address, such as https://edgible.github.io/cards")
    ap.add_argument("--commit", default="", help="the cards commit being built, shown in the footer")
    args = ap.parse_args(argv)

    root = Path.cwd()
    cards = load_cards(root)
    if not cards:
        print("no */card.yml here: run it from the root of the cards repo", file=sys.stderr)
        return 1
    needs = yaml.safe_load(args.needs.read_text()) or []
    status = json.loads(args.status.read_text()) if args.status and args.status.exists() else {}
    if args.status and not args.status.exists():
        print(f"{args.status} not found: every card shows as not tested yet", file=sys.stderr)

    Site(root, args.out, cards, needs, status, args.base_url, args.commit).build()
    print(f"wrote {args.out}: {len(cards)} cards, {len(needs)} needs")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
