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
    project_of = {f: re.search(r"^name:\s*(\S+)", (d / f).read_text(), re.M).group(1) for f in composes}
    declared = card.get("places") or {}
    app_places = list(dict.fromkeys(a["place"] for a in apps))
    helper_places = [pl for pl, s in declared.items() if pl not in app_places and s.get("runs")]
    all_places = app_places + helper_places

    def place_of(f: str) -> str:
        for pl, s in declared.items():
            if f in s.get("runs", []):
                return pl
        text = (d / f).read_text()
        for a in apps:
            if "${" + env_name(owners[(a["port"], a["place"], a["from"])]) + "_PORT" in text:
                return a["place"]
        return app_places[0]

    files_of = {pl: [f for f in composes if place_of(f) == pl] for pl in all_places}
    multi = len(all_places) > 1
    run_files = lambda files, verb: "\n".join(f"docker compose {env} -f {name}/{f} {verb}" for f in files)
    run = lambda verb: run_files(composes, verb)
    on = lambda pl: f"On the machine for place `{pl}`:\n\n" if multi else ""
    per_place = lambda places, verb: "\n\n".join(
        f"{on(pl)}{FENCE}bash\n{run_files(files_of[pl], verb)}\n{FENCE}" for pl in places if files_of[pl])
    backup_of = lambda files: "\n".join(
        f"for volume in $(docker volume ls -q --filter label=com.docker.compose.project={pr}); do\n"
        f"  docker run --rm -v \"$volume:/data:ro\" -v \"$PWD:/backup\" alpine tar -czf \"/backup/$volume.tgz\" -C /data .\n"
        f"done" for pr in sorted({project_of[f] for f in files}))
    var_of = lambda pl: "DEVICE" if not multi else env_name(pl) + "_DEVICE"
    id_of = lambda pl: "device_id" if not multi else env_name(pl).lower() + "_id"

    creates = []
    for a in apps:
        var = env_name(owners[(a["port"], a["place"], a["from"])]) + "_PORT"
        creates.append(
            f"edgible app create existing \\\n  --non-interactive \\\n  --name {a['name']} \\\n"
            f"  --port \"${var}\" \\\n  --protocol {a['protocol']} \\\n"
            f"  --auth-modes {','.join(a['authModes'])} \\\n  --device-id \"${id_of(a['place'])}\"")

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
    words = {5: "Five", 6: "Six", 7: "Seven", 8: "Eight"}
    if multi:
        lookup = ("device_id() {\n  edgible device list --json | jq -er --arg name \"$1\" '\n"
                  "    map(select(.name == $name))\n    | if length == 1 then .[0].id\n"
                  "      else error(\"need exactly one device named \" + $name + \" (\" + (map(.status + \" \" + .id) | join(\", \")) + \")\")\n"
                  "      end\n  '\n}\n" + "\n".join(f"{id_of(pl)}=$(device_id \"${var_of(pl)}\")" for pl in app_places))
    else:
        lookup = ("device_id=$(edgible device list --json | jq -er --arg name \"$DEVICE\" '\n  map(select(.name == $name))\n"
                  "  | if length == 1 then .[0].id\n    else error(\"need exactly one device named \" + $name + \" (\" + (map(.status + \" \" + .id) | join(\", \")) + \")\")\n"
                  "    end\n')")
    helper_steps = ""
    for i, pl in enumerate(helper_places):
        where = on(pl).rstrip("\n") + " " if multi else ""
        note = ((spec.get("helpers") or {}).get(pl) or "").strip()
        helper_steps += (f"\n### {6 + i}. Start the {pl}\n\n{where}Its services connect out to what Publish "
                         f"published, so they start now.\n\n{FENCE}bash\n{run_files(files_of[pl], 'up -d --wait')}\n"
                         f"{run_files(files_of[pl], 'ps')}\n{FENCE}\n\n{note}\n")
    fetch_note = ("\n\nOn each machine that runs a place, fetch the card and set up `card.env` the same way: "
                  "the places share its settings." if multi else "")
    stop_order = helper_places + app_places
    out = f"""# {name}

## Why

{spec['why'].strip()}

## What

{spec['what'].strip()}

{spec['data'].strip()} {sizing(card)}

The Compose file is [{composes[0]}]({composes[0]}), the settings [card.env](card.env), the card [card.yml](card.yml){', and the last test [test.yml](test.yml)' if (d / 'test.yml').exists() else ''}.

## How

{words[5 + len(helper_places)]} steps. Edit [card.env](card.env) before you start.

### 1. Fetch

{FENCE}bash
mkdir -p {name}
curl -fsSL https://github.com/Edgible/{repo}/archive/refs/heads/main.tar.gz \\
  | tar -xz --strip-components=2 -C {name} {repo}-main/{name}
{FENCE}{fetch_note}

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

{per_place(app_places, 'up -d --wait') if multi else FENCE + 'bash' + chr(10) + run('up -d --wait') + chr(10) + run('ps') + chr(10) + FENCE}

`--wait` returns when each service is running, and healthy when it has a healthcheck. {spec.get('start', '').strip()}

### 5. Publish

{FENCE}bash
set -euo pipefail
set -a
. {name}/card.env
set +a
{lookup}
{chr(10).join(creates)}
edgible app list
{FENCE}
{helper_steps}
## Verify

{(chr(10) * 2).join(verify)}

The rest of the setup is in the [{docs[0]} docs]({docs[1]}).

## Tear down

Four steps, in this order. Step 1 runs wherever `edgible` is logged in. Steps 2 to 4 run on {'the machine for each place' if multi else 'the machine that runs the containers'}. Steps 2 and 3 read `card.env`, so keep it until step 4.

### 1. Unpublish

{FENCE}bash
{chr(10).join(f"edgible app delete {a['name']} --yes" for a in apps)}
{FENCE}

### 2. Stop

{per_place(stop_order, 'down') if multi else FENCE + 'bash' + chr(10) + run('down') + chr(10) + FENCE}

### 3. Delete the data

Skip this step to keep the data. The loop copies each volume to a `.tgz` file in this directory first.

{chr(10).join(f"{on(pl)}{FENCE}bash{chr(10)}{backup_of(files_of[pl])}{chr(10)}{run_files(files_of[pl], 'down --volumes')}{chr(10)}{FENCE}{chr(10)}" for pl in stop_order if files_of[pl]) if multi else FENCE + 'bash' + chr(10) + backup_of(composes) + chr(10) + run('down --volumes') + chr(10) + FENCE + chr(10)}
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
