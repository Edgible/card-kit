#!/usr/bin/env python3
"""Write a card's README.md: the parts a person writes from a short YAML file, the rest from card.yml.

    ../card-kit/run card-readme gitea gitea-readme.yml

The YAML file holds what only a person knows:

    why: The problem the card solves, with a link to the app.
    what: The apps, the places, and the choices made, such as the auth mode.
    data: Where the data lives.
    edit: What to set in card.env.
    start: Anything after `up --wait`, such as making the admin before Publish.
    verify:
      gitea: What the check proves, and the first sign-in.
    docs: [Gitea, https://docs.gitea.com]

Everything else comes from card.yml and the Compose files, the same way on every card:
How (Fetch, Edit card.env, Check, Start, Publish), each app's Verify check by its auth
mode, Tear down, and the sizing sentence in What, from places:. Fetch reads from the
repo named by --repo (cards or starters).
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

import yaml

FENCE = "```"
ARCH_WORDS = {"arm64": "arm64", "amd64": "amd64", "arm": "32-bit arm"}
GPU_WORDS = {"none": "no GPU", "optional": "a GPU if you have one (it runs without)", "required": "a GPU"}


def env_name(name: str) -> str:
    return name.upper().replace("-", "_")


def sizing(card: dict) -> str:
    sentences = []
    for place, p in (card.get("places") or {}).items():
        archs = [ARCH_WORDS[a] for a in ("arm64", "amd64", "arm") if a in p.get("arch", [])]
        arch = archs[0] if len(archs) == 1 else ", ".join(archs[:-1]) + " or " + archs[-1] if archs else "any"
        sentences.append(
            f"Minimum recommended for the place `{place}`: {p.get('memory', '?')} of memory and "
            f"{p.get('disk', '?')} of disk, on an {arch} machine, with {GPU_WORDS[p.get('gpu', 'none')]}.")
    return " ".join(sentences)


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("card", type=Path)
    ap.add_argument("spec", type=Path, help="the YAML file with why, what, data, edit, start, verify, docs")
    ap.add_argument("--repo", default="", help="cards or starters; default: the name of the repo you run it in")
    args = ap.parse_args(argv)

    d = args.card
    name = d.resolve().name
    card = yaml.safe_load((d / "card.yml").read_text())
    spec = yaml.safe_load(args.spec.read_text())
    git_config = Path("/repo/.git/config")
    repo = args.repo or ("starters" if git_config.is_file() and "starters" in git_config.read_text() else "cards")
    apps = card["applications"]
    composes = sorted(p.name for p in d.glob("*compose*.yml"))
    env = f"--env-file {name}/card.env"
    owners: dict[tuple, str] = {}
    for a in apps:
        owners.setdefault((a["port"], a["place"], a["from"]), a["name"])
    projects = sorted({re.search(r"^name:\s*(\S+)", (d / f).read_text(), re.M).group(1) for f in composes})
    run = lambda verb: "\n".join(f"docker compose {env} -f {name}/{f} {verb}" for f in composes)

    creates = []
    for a in apps:
        var = env_name(owners[(a["port"], a["place"], a["from"])]) + "_PORT"
        creates.append(
            f"edgible app create existing \\\n  --non-interactive \\\n  --name {a['name']} \\\n"
            f"  --port \"${var}\" \\\n  --protocol {a['protocol']} \\\n"
            f"  --auth-modes {','.join(a['authModes'])} \\\n  --device-id \"$device_id\"")

    verify = []
    for a in apps:
        mode, host, note = a["authModes"][0], f"<{a['name']} hostname>", spec["verify"].get(a["name"], "")
        if a["protocol"] in ("tcp", "udp"):
            verify.append(f"`{a['name']}` is a {a['protocol'].upper()} app on port `{a['port']}`, "
                          f"with no auth mode.\n\n{note}")
            continue
        if mode == "org":
            head = f"`{a['name']}` uses `org`."
            note = ("That prints `302` and an `edgible.com/application-access/` address, "
                    "so the org sign-in is in front. " + note)
            check = f"curl -sS -o /dev/null -w '%{{http_code}} %{{redirect_url}}\\n' \"https://{host}\""
        elif mode == "api-key":
            head = f"`{a['name']}` uses `api-key`. Without a key, it answers `401`."
            check = f"curl -sS -o /dev/null -w '%{{http_code}}\\n' \"https://{host}\""
        else:
            head = f"`{a['name']}` uses `none`."
            check = f"curl -sS -o /dev/null -w '%{{http_code}}\\n' \"https://{host}\""
        verify.append(f"{head}\n\n{FENCE}bash\n{check}\n{FENCE}\n\n{note}")

    docs = spec["docs"]
    backup = "\n".join(
        f"for volume in $(docker volume ls -q --filter label=com.docker.compose.project={p}); do\n"
        f"  docker run --rm -v \"$volume:/data:ro\" -v \"$PWD:/backup\" alpine tar -czf \"/backup/$volume.tgz\" -C /data .\n"
        f"done" for p in projects)
    out = f"""# {name}

## Why

{spec['why'].strip()}

## What

{spec['what'].strip()}

{spec['data'].strip()} {sizing(card)}

The Compose file is [{composes[0]}]({composes[0]}), the settings [card.env](card.env), the card [card.yml](card.yml){', and the last test [test.yml](test.yml)' if (d / 'test.yml').exists() else ''}.

## How

Five steps. Edit [card.env](card.env) before you start.

### 1. Fetch

{FENCE}bash
mkdir -p {name}
curl -fsSL https://github.com/Edgible/{repo}/archive/refs/heads/main.tar.gz \\
  | tar -xz --strip-components=2 -C {name} {repo}-main/{name}
{FENCE}

### 2. Edit card.env

{spec['edit'].strip()}

{FENCE}bash
nano {name}/card.env
{FENCE}

### 3. Check

{FENCE}bash
curl -fsSLo check-env.py https://raw.githubusercontent.com/Edgible/card-kit/main/check-env.py
python3 check-env.py {name}
{FENCE}

It fills each empty secret and moves a taken port, as lines to paste. Run it again until it says `no conflicts`.

### 4. Start

{FENCE}bash
{run('up -d --wait')}
{run('ps')}
{FENCE}

`--wait` returns when each service is running, and healthy when it has a healthcheck. {spec.get('start', '').strip()}

### 5. Publish

{FENCE}bash
set -euo pipefail
set -a
. {name}/card.env
set +a
device_id=$(edgible device list --json | jq -er --arg name "$DEVICE" '
  map(select(.name == $name))
  | if length == 1 then .[0].id
    else error("need exactly one device named " + $name + " (" + (map(.status + " " + .id) | join(", ")) + ")")
    end
')
{chr(10).join(creates)}
edgible app list
{FENCE}

## Verify

{(chr(10) * 2).join(verify)}

The rest of the setup is in the [{docs[0]} docs]({docs[1]}).

## Tear down

Four steps, in this order. Step 1 runs wherever `edgible` is logged in. Steps 2 to 4 run on the machine that runs the containers. Steps 2 and 3 read `card.env`, so keep it until step 4.

### 1. Unpublish

{FENCE}bash
{chr(10).join(f"edgible app delete {a['name']} --yes" for a in apps)}
{FENCE}

### 2. Stop

{FENCE}bash
{run('down')}
{FENCE}

### 3. Delete the data

Skip this step to keep the data. The loop copies each volume to a `.tgz` file in this directory first.

{FENCE}bash
{backup}
{run('down --volumes')}
{FENCE}

### 4. Remove the {'starter' if repo == 'starters' else 'card'}

{FENCE}bash
rm -rf {name}
{FENCE}
"""
    (d / "README.md").write_text(out)
    print(f"wrote {d / 'README.md'}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
