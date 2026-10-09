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
| `images/` | Optional pictures drawn from `card.yml` by `card-image`. |
| `etc/` | Optional sample files the card hands you, such as a PDF or a page. |
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

Commit `test.yml` only when something material changes: the result, a step's outcome, or the images. A rerun with the same outcome and the same images leaves the file alone, so `tested` is the day of the run that produced this result, not the most recent run. [test.schema.json](test.schema.json) is its source of truth, and `check-cards` checks it when it is there. Starters always have one; for a card it is optional.

```yaml
tested: 2026-10-10
result: pass                 # pass only when no step failed
card-kit: 3f2a9c1            # the card-kit commit the checks came from
edgible-cli: 1.4.6
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
by: agent                    # agent or person
```

A run can also record what it measured for each place, which is where the numbers in `places:` come from:

```yaml
measured:
  gitea:
    memory: 310 MB           # peak memory of the place's containers together
    images: 420 MB           # the images, as stored on the machine
    data: 64 MB              # the volumes at the end of the run
```

Each step is `pass`, `fail`, or `skip`. `check-cards` fails a `test.yml` that gives no Verify result for an app, says `pass` while a step failed, or names a hostname or an address. Like the rest of a card, it leaves out device names, hostnames, and the organization id: `machine` is the operating system, architecture, and Docker version, not the device.

## Tools

There are two kinds of tool, and the difference decides how each one runs.

A tool that works on files in a repo runs through `run`, in the image from [Dockerfile](Dockerfile). It may use any package; add the package to the Dockerfile. Docker is the only thing an author installs.

A tool that checks the machine a card runs on does not run in a container, because a container sees its own ports, processes, and files, not the machine's. That tool is one Python file that uses only the standard library, so a card README can fetch it with `curl` and run it with `python3`. `run` refuses to run it.

### run

Clone this repo beside the repo you work in, and run a tool by its name from that repo's root:

```bash
git clone https://github.com/Edgible/card-kit ../card-kit
../card-kit/run check-cards
../card-kit/run card-image website
```

`run` mounts the repo you run it from and the kit, separately. Paths are relative to the directory you run it from. The first run builds the image, which takes about half a minute; later runs reuse it, and an edit to the Dockerfile builds a new one. A change to a tool script needs no rebuild. The tool runs as your user, so the files it writes are yours.

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

Compose resolves each file with `card.env`, so the ports and names it checks are the ones `docker compose up` would use. When `card.yml` has `places:`, a Sizing section compares them with the machine: memory and CPU type from `docker info`, free disk where Docker keeps its data, and the architectures each image is published for. A shortfall is a warning, never a conflict. It looks for empty required values, host ports already in use, container names already taken, Compose project names used by another file, volumes left by an earlier run, `DEVICE` values that match no device, and Edgible apps with the same name. Each conflict prints a remedy.

A Notes section adds what is worth knowing but is not a problem: a service the card starts that already runs elsewhere on the machine, an image tag such as `latest` that moves with each release, and where each service's healthcheck comes from. Notes never count as conflicts or warnings.

The report ends with the remedies as lines to paste into a shell. A value that `card.env` says how to generate is generated there, and a taken port moves to a free one. All `card.env` edits are one `sed`, so `card.env.bak` is the copy from before them. A line that stops or deletes something starts with `#`. `--commands` prints only those lines, for `> fix.sh`. Exit 0 means no conflicts, 1 means at least one, and 2 means the check could not run.

It needs only `python3` and Docker, and uses `edgible` when that is installed and logged in.

## License

[MIT](LICENSE).
