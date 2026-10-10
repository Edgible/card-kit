# card-kit

The format of an Edgible card, and the tools that check and build one. [Edgible/cards](https://github.com/Edgible/cards) holds the cards people share. [Edgible/starters](https://github.com/Edgible/starters) holds single-app starters to build cards from. Both follow what is written here, and both run these tools.

## What a card is

A card records a deployment pattern so someone else can reproduce it: the programs, the images, the ports, the auth mode on each hostname, and which apps share a serving device. It leaves out device names, hostnames, the organization id, and passwords, so the next person maps each place to a serving device they have.

Most apps are web apps published over `https`. An app that is not web, such as a game server or SSH, is published over `tcp` or `udp`. Such an app has no auth mode, so its `authModes` is `[none]`, and its port must be from `20000` to `29999`, the range the managed gateway opens. Treat it as reachable by anyone.

A card is a directory whose name is the card's name. In a cards or starters repo, every top-level directory that holds a `card.yml` is one card.

| File | What it is |
| --- | --- |
| `card.yml` | The apps, ports, auth modes, and places. [card.schema.json](card.schema.json) is the source of truth for it. |
| `README.md` | How to run the card, under five headings: Why, What, How, Verify, and Tear down. |
| `card.env` | Machine settings, read by the Compose file. Secrets are empty in git. |
| `*compose*.yml` | The Compose files the card runs, next to `card.yml`. |
| `prepare.sh` | Optional: what runs after Start and before Publish, such as making the admin so no setup page is ever public. See [Prepare](#prepare). |
| `images/` | Optional pictures drawn from `card.yml` by `card-image`. |
| `etc/` | Optional sample files the card hands you, such as a PDF or a page. |
| `test/` | Optional inputs for `test-card`: values only a person may fill, and the card's own checks. See [Test inputs](#test-inputs). |
| `test.yml` | Optional: the latest run of the card's lifecycle. Every starter has one. See [Test results](#test-results). |

## The README

Copy the shape from a card like yours and change the names, so every card reads the same way.

- **Why** is the problem the card solves.
- **What** is the apps and the places.
- **How** is how to fetch the card, edit `card.env`, check the machine, start the Compose file, and publish.
- **Verify** comes after Publish. It checks the card, not the apps. Each app gets one check that its hostname answers the way its auth mode says: `none` with the app, `org` with a redirect to the Edgible sign-in, and `api-key` with `401` until a key is sent. Add the first sign-in when the app makes its admin on the first visit. End with a link to that app's docs.
- **Tear down** is last, with the same four steps as every other card: Unpublish each app, Stop with `down`, Delete the data after copying each volume to a `.tgz`, and Remove the card.

A card holds what depends on Edgible or on another app in the card: hostnames, auth modes, devices, and how the apps reach each other. What is the same on any host belongs to the app: its users, its settings, and how to use it. Link to the app's docs. Do not copy them.

Leave device names, hostnames, organization ids, and passwords out of the README, the Compose files, and `card.env` in git. The schema does not check the README.

## Prepare

Some apps let the first visitor set them up: make the admin, or finish an install wizard. Published first, that is anyone on the internet. Such a card makes it safe before Publish, in `prepare.sh`, a short `sh` script next to `card.yml`. The README's Start step runs it with `sh <card>/prepare.sh` and shows it in full, and `test-card` runs the same file, so what a person runs is what was tested.

It starts the same way in every card, so it runs from anywhere and in a test:

```sh
#!/bin/sh
# Prepare for the gitea starter: make the admin.
# Run it after Start and before Publish, from the directory that holds gitea/:
#   sh gitea/prepare.sh
set -eu
cd "$(dirname "$0")"
set -a; . ./card.env; set +a
COMPOSE=${COMPOSE:-docker compose --env-file card.env -f docker-compose.yml}

$COMPOSE exec -T -u git gitea gitea admin user create --admin --username gitadmin ...
```

Use `$COMPOSE` for every Compose command: `test-card` sets it to the test's own project. Use `-T` with `exec` and `run`, because a test has no terminal. Keep what only a person can do, such as adding their own name to a whitelist, in the README instead.

## Minimum recommended

A card can say how big a machine each place needs, in an optional `places:` section at the end of `card.yml`. The numbers are the minimum recommended for everything in that place together: every app, database, and helper that runs there.

```yaml
places:
  web:
    memory: 2 GB             # for all the containers in the place together
    disk: 6 GB               # the images and the data to start with
    arch: [amd64, arm64]     # architectures every image in the place runs on
    gpu: none                # none, optional, or required
```

Sizes are a number, a space, and `MB`, `GB`, or `TB`. Each field is optional, and a card without `places:` is still valid. `check-cards` checks that each place named there is one the apps use. `check-env` compares the places being started with the machine, adding them up when two places share it, and reports a shortfall as a warning, not a conflict.

The README's What section says the same numbers in words, so a reader who never opens `card.yml` sees them. A starter always has `places:`, from the sizes its test measured (see `measured:` under [Test results](#test-results)) plus a margin.

## Places with no app

Some services publish nothing: they only connect out. A CI runner asks a forge for jobs, a backup job sends copies away, a worker takes tasks from a queue. When one of them runs beside a published app, it is just another service in that app's Compose file, and it goes wherever that file goes. When it should run on a machine of its own, give it a place with no app, and say which Compose files it runs:

```yaml
places:
  forge:
    memory: 512 MB
  runner:
    runs: [runner-compose.yml]   # a place no app uses
    memory: 1 GB
```

- A place no app uses must have `runs:`. A place with apps may have it too, to tie a Compose file to it explicitly.
- `card.env` has a device line for every place, these included: `FORGE_DEVICE`, `RUNNER_DEVICE`.
- These places start after Publish, because what they connect to is usually an app the card has just published. The README says so, in a step after Publish: Start the runner.
- `check-env`, `test-card`, and Tear down treat them like any other place. There is just nothing to publish or verify by hostname.

A service that mounts the Docker socket, runs privileged, or uses the host's network has full control of its machine. A runner usually needs the socket. That is allowed, but the README must say so in words, and `check-cards` fails a card whose README does not mention it. `check-env` notes it too.

## Conventions

`card.yml` stays short because the tools read the rest from names. `<APP>` is the app name in capitals, with `-` written `_`. `check-cards` checks the first four.

| What | Name |
| --- | --- |
| The host port of an app | `<APP>_PORT` in `card.env`, set to the port in `card.yml`. Apps that are one process share the first one's variable, so list that app first. |
| The Compose file that runs an app | The one that reads `${<APP>_PORT`. |
| The serving device | `DEVICE` for a card with one place. `<PLACE>_DEVICE` for each place of a card with more. |
| The Compose project | A top-level `name:` in each Compose file. Pick one that says which card it is, because two Compose files with the same `name:` on one machine replace each other's containers. |
| The URL an app gives out | Built from `ORG_LABEL`: `https://<app>.${ORG_LABEL}.edgible.com` is the hostname Publish generates, so nothing changes after Publish. For your own domain, an `<APP>_URL` override wins over it, such as `${ACCOUNTS_URL:-https://accounts.${ORG_LABEL:?set ORG_LABEL in card.env}.edgible.com}`. |
| A secret | Empty in git, with a `# Generate with: <command>` comment above it. `check-env` fills it with that command. |
| A value the card cannot run without | `${VAR:?set VAR in card.env}` in the Compose file. |

A card that may be combined with others reads better with names that say which app they belong to: `UMAMI_DB_PASSWORD` rather than `POSTGRES_PASSWORD`, a service called `umami-db` rather than `db`, and no `container_name`. Starters follow this so they combine cleanly. For a card it is advice, not a check.

## Test results

A card can carry `test.yml`, the latest result of its whole lifecycle: Check, Start, Publish, Verify, and Tear down. Git history holds the earlier ones.

Commit `test.yml` only when something material changes: the result, a step's outcome, the images, or the files. A rerun with the same outcome and the same images leaves the file alone, so `tested` is the day of the run that produced this result, not the most recent run. [test.schema.json](test.schema.json) is its source of truth, and `check-cards` checks it when it is there. Starters always have one; for a card it is optional.

```yaml
tested: 2026-10-10
result: pass                 # pass only when no step failed
card-kit: 3f2a9c1            # the card-kit commit the checks came from
edgible-cli: 1.4.6
files: sha256:e0a0fb12ab72ca14  # the card's files when tested
machine: linux/amd64, docker 29.4
images:
  - gitea/gitea:1.24.6
  - postgres:17-alpine
steps:
  check-env: pass
  start: pass                # up --wait, every service running or healthy
  publish: pass
  verify:                    # one entry per app in card.yml
    gitea: pass
    gitea-ssh: pass
  teardown: pass
duration: 4m12s
by: agent                    # agent, person, or ci
```

A run can also record what it measured for each place, which is where the numbers in `places:` come from:

```yaml
measured:
  gitea:
    memory: 310 MB           # peak memory of the place's containers together
    images: 420 MB           # the images, as stored on the machine
    data: 64 MB              # the volumes at the end of the run
```

A card can also record checks only it knows how to make, under `steps:`, run after Verify:

```yaml
steps:
  ...
  checks:
    runner-online: pass      # the runner registered with Gitea
    workflow-runs: pass      # a workflow ran on it to the end
```

`files` is a fingerprint of every file in the card but `README.md`, `images/`, `test.yml`, and hidden files. When it no longer matches, the card changed since its test: `check-cards` says so in a note, and `check-cards --fresh` fails it, for a repo such as starters where every card must carry a current test.

### Test inputs

Everything `test-card` needs is in the card, so anyone, or a CI job, runs the same test with no options. Besides `prepare.sh`, which people run too, it is in the card's `test/` directory:

- **`test/inputs.env`** sets values in the test's copy of `card.env`, for the ones only a person may fill: accepting a licence (`MINECRAFT_EULA=TRUE`), or a folder a person picks (`JELLYFIN_MEDIA_DIR=./test-media`, which lands inside the test's copy). Each key must already be a line in `card.env`. It is never a secret; `check-env` generates those.
- **`test/<name>.sh`** is a check only the card knows how to make, recorded as `<name>` under `checks:`. It runs after Verify with `card.env` exported and `HOSTNAME_<APP>` set to each published hostname, and is retried until it exits 0. Its `curl` reaches each https hostname at the address Edgible's own nameservers give, through a `.curlrc` in `CURL_HOME`, so a resolver that still remembers the name as missing does not fail it. A helper it needs, such as a small Python script, sits beside it in `test/` and is found from `$(dirname "$0")`; only `.sh` files are checks.

`--set` and `--check` add to these from the command line.

Each step is `pass`, `fail`, or `skip`. `check-cards` fails a `test.yml` that gives no Verify result for an app, says `pass` while a step failed, or names a hostname or an address. Like the rest of a card, it leaves out device names, hostnames, and the organization id: `machine` is the operating system, architecture, and Docker version, not the device.

## Tools

There are two kinds of tool, and the difference decides how each one runs.

A tool that works on files in a repo runs through `run`, in the image from [Dockerfile](Dockerfile). It may use any package; add the package to the Dockerfile. Docker is the only thing an author installs.

A tool that checks the machine a card runs on does not run in a container, because a container sees its own ports, processes, and files, not the machine's. That tool is one Python file that uses only the standard library, so it runs with `python3` anywhere, and a card README can fetch it with `curl`. `check-env` and `test-card` are these; `run` refuses them.

### run

Clone this repo beside the repo you work in, and run a tool by its name from that repo's root:

```bash
git clone https://github.com/Edgible/card-kit ../card-kit
../card-kit/run check-cards
../card-kit/run card-image website
```

`run` mounts the repo you run it from and the kit, separately. Paths are relative to the directory you run it from. The first run builds the image, which takes about half a minute; later runs reuse it, and an edit to the Dockerfile builds a new one. A change to a tool script needs no rebuild. The tool runs as your user, so the files it writes are yours.

### card-readme

Writes a card's `README.md`. The parts only a person knows come from a short YAML file; the rest comes from `card.yml` and the Compose files, the same way on every card: How (Fetch, Edit card.env, Check, Start with `prepare.sh` when the card has one, Publish), each app's Verify check by its auth mode, Tear down, and the sizing sentence in What, from `places:`.

```yaml
why: The problem the card solves, with a link to the app.
what: The apps, the places, and the choices made, such as the auth mode.
data: Where the data lives.
edit: What to set in card.env.
start: Anything after `up --wait`, such as why the admin is made before Publish.
after-prepare: What prepare.sh prints, and anything left for a person to do.
verify:
  gitea: What the check proves, and the first sign-in.
docs: [Gitea, https://docs.gitea.com]
```

```bash
../card-kit/run card-readme gitea gitea-readme.yml
```

The YAML file must be inside the repo, because `run` mounts only the repo and the kit. Keep it out of the commit unless you want it there. Fetch reads from `Edgible/starters` when you run it in a starters repo, and from `Edgible/cards` otherwise.

### check-cards

Checks each `card.yml` against [card.schema.json](card.schema.json), checks that `metadata.name` matches the directory name, and checks the first four conventions above. When a card has `test.yml`, it checks that too. With no arguments it checks every top-level `*/card.yml` in the current directory. Each failure says what to change. The cards and starters repos run this on every pull request.

```bash
../card-kit/run check-cards
../card-kit/run check-cards website/card.yml
```

### card-image

Writes `images/card-light.svg` and `images/card-dark.svg` for a card. The picture lists the apps, ports, auth modes, and places, from `card.yml`. If a `what` line does not fit its row, the command fails and you shorten that line.

```bash
../card-kit/run card-image website
```

### check-env

Checks a fetched card against the machine it is about to run on, after `card.env` is edited and before the containers start. A card README fetches it on its own:

```bash
curl -fsSLo check-env.py https://raw.githubusercontent.com/Edgible/card-kit/main/check-env.py
python3 check-env.py website
python3 check-env.py website -f kuma-compose.yml
```

Compose resolves each file with `card.env`, so the ports and names it checks are the ones `docker compose up` would use. When `card.yml` has `places:`, a Sizing section compares them with the machine: memory and CPU type from `docker info`, free disk where Docker keeps its data, and the architectures each image is published for. A shortfall is a warning, never a conflict. It looks for empty required values, host ports already in use, container names already taken, Compose project names used by another file, volumes left by an earlier run, `DEVICE` values that match no device, and Edgible apps with the same name. Each conflict prints a remedy. `--project-prefix <prefix>` checks each Compose file as project `<prefix><file stem>` instead of its `name:`, as `test-card` runs it.

A Notes section adds what is worth knowing but is not a problem: a service the card starts that already runs elsewhere on the machine, an image tag such as `latest` that moves with each release, and where each service's healthcheck comes from. Notes never count as conflicts or warnings.

The report ends with the remedies as lines to paste into a shell. A value that `card.env` says how to generate is generated there, and a taken port moves to a free one. All `card.env` edits are one `sed`, so `card.env.bak` is the copy from before them. A line that stops or deletes something starts with `#`. `--commands` prints only those lines, for `> fix.sh`. Exit 0 means no conflicts, 1 means at least one, and 2 means the check could not run.

It needs only `python3` and Docker, and uses `edgible` when that is installed and logged in.

### test-card

Tests a card's whole lifecycle on a serving device and writes `test.yml`. Like `check-env`, it checks the machine, so it runs directly with `python3`, from the directory that holds the card, and `run` refuses it.

```bash
python3 ../card-kit/test-card.py gitea --device macbookair
```

It works on a copy of the card, through the same steps a person follows. Places with no app start after Verify, and `--check NAME=COMMAND` (repeatable) runs a card's own check after that, retrying until it passes or `--check-wait` runs out; `card.env` is exported, and `HOSTNAME_<APP>` holds each published hostname.

1. **Check:** runs `check-env` with `--project-prefix`, so it checks the test's own Compose projects and a copy of the card already running on the machine is no conflict. It fills empty secrets the way `card.env` says, moves a taken host port, and stops on a conflict. Publish and Verify use the moved port, not the one in `card.yml`.
2. **Start:** `up --wait`, as its own Compose project (`cardtest-<card>-<file>`), so a test never touches the machine's own containers or volumes.
3. **Prepare:** the card's [`prepare.sh`](#prepare), when it has one. `$COMPOSE` is the test's compose command; `card.env` is exported. `--prepare COMMAND` runs a command in its place.
4. **Publish:** each app in `card.yml`. A name already taken in the org is published as `test-<name>`, and the existing app is never touched.
5. **Verify:** each hostname by its auth mode. `none` answers, `org` redirects to the Edgible sign-in, `api-key` answers `401`, and `tcp` connects. `udp` is skipped. It asks Edgible's own nameservers for the address, because resolvers keep a "does not exist" for 15 minutes when a new name is looked up too early.
6. **Tear down:** deletes the apps it published, and removes the containers and volumes it started, and nothing else.

While it runs, it measures each place: the peak memory of its containers together, its images, and its data at the end. It writes `test.yml` with `measured:`, unless nothing material (the result, a step, the images) changed since the last one. It prints a suggested `places:`: memory with half again as headroom, at least 256 MB; disk as images and data plus 1 GB; the architectures every image has. `--write-places` writes that into `card.yml`. Raise a number if the app documents a higher minimum.

`--org-label` is read off an app the org already has, if you leave it out. `--by agent` marks a run made by an agent. `--keep` leaves the card running and published after Verify. It needs `dig` and `edgible`, logged in, besides Docker.

### test-cards

Tests every card in a repo that needs it, one at a time, and keeps a status for each: the command a CI job runs. Like `test-card`, it runs with `python3` on a serving device, from the repo's root.

```bash
python3 ../card-kit/test-cards.py --device macbookair --status ../status
```

A card needs a test when it has no status yet, when its files changed since its last status, or when `edgible --version` differs from the version of its last status, so a new Edgible version retests every card. `--all` tests every card, and `--only gitea immich` tests those.

The status directory holds `status.json`, every card's latest result, Edgible version, date and fingerprint, and one `<card>.json` per card in the shape of a [shields.io endpoint badge](https://shields.io/badges/endpoint-badge), labelled with the Edgible version it ran on: `Edgible 1.4.6 | passing`. Keep the directory on a branch of its own, such as `status`, and a README can show each card's badge from it without a commit to `main`.

It never changes the repo. `test.yml` is the author's record of a version of a card, and the status is CI's record of whether it still passes. It exits 1 when a card it tested failed.

## Agent skill

[skills/edgible-cards](skills/edgible-cards/SKILL.md) teaches an AI agent to self-host with Edgible the way this README says. It finds a starter or card that fits. When the person describes a need that none meets, it shortlists apps from awesome-selfhosted for them to choose from. It puts the open choices to the person. Then it deploys and verifies by the card's README. After that, it answers what is running and whether it works, troubleshoots, and handles sign-in and API keys, settings, pausing, backup and restore, upgrades, moves, and removal. When nothing fits, it builds a starter and tests it with `test-card`, and with the person's yes it offers the starter, or a fix, as a pull request. It is a plain `SKILL.md` in the open Agent Skills format, with shell commands only, so agents that read that format can use it.

For Claude Code, clone this repo and link the skill into your skills directory. A `git pull` then updates it:

```bash
git clone https://github.com/Edgible/card-kit ~/.card-kit
mkdir -p ~/.claude/skills
ln -s ~/.card-kit/skills/edgible-cards ~/.claude/skills/edgible-cards
```

For another agent, put the `edgible-cards` directory where that agent reads skills.

The skill links here for the format rather than copying it. A change to the format or a tool that changes what a person does goes into the skill in the same pull request.

## License

[MIT](LICENSE).
