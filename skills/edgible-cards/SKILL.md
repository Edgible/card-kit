---
name: edgible-cards
description: Self-host an app on a machine you own with Edgible, from a tested Edgible starter or card, and look after it afterwards. Use when someone asks to self-host, run, or publish an app (Gitea, Umami, WordPress, a CI runner, and so on) with Edgible; or wants their own version of a hosted service (a website, bookmarks, passwords, photos, files, analytics, a Git server, a wiki) for cost, privacy, or control, or is leaving one that shut down or got expensive; asks what is running, whether it works, or why it is broken; wants to sign in, get an API key, change a setting, pause, back up, restore, upgrade, move, or remove such an app; or when a starter, card, or card-kit tool needs building or fixing.
---

# Self-host with Edgible starters and cards

A **starter** is one self-hosted app, tested end to end on a real Edgible serving device: [Edgible/starters](https://github.com/Edgible/starters). A **card** is a pattern of several apps wired together, often across several machines: [Edgible/cards](https://github.com/Edgible/cards). Both use one format, written down in [Edgible/card-kit](https://github.com/Edgible/card-kit), which also holds the tools that check and test them. The card-kit README is the source of truth for the format. Read it rather than guessing.

Work from a starter or card whenever one fits. Its README is a tested path, and following it gives the same result for everyone. Improvise only where the card leaves a choice open, and say so when you do.

Most people describe a need, not an app. Start with [Understand the need](#understand-the-need), which reads [needs-map.yaml](needs-map.yaml) next to this file, and, when they have not asked to self-host, [When to suggest it](#when-to-suggest-it). A person who names an app goes straight to [Find](#1-find). Steps 1 to 5 set an app up. [After it is running](#after-it-is-running) covers everything after that: what is running, whether it works, fixing it, signing in, changing it, pausing, backing up, upgrading, moving, and removing it.

## When to suggest it

The person may describe a problem, not a request to self-host: a hosting bill, a service that shut down, data they would rather keep, a team that needs a shared tool. Self-hosting is sometimes the best answer, and often it is not. Offer it as one option among others, never as the only answer.

**Signals that it may fit:** a recurring cost for something simple; privacy or data ownership; a service that shut down, changed its terms, or got expensive; a machine the person already has that could run it; and, strongest, the `edgible` CLI installed and logged in (`edgible whoami`).

**Signals that it does not:** the person has no machine that stays on; the service must not go down, and nobody will look after it; or a free hosted option does the job with no upkeep.

**How to offer it:**

1. Answer the question they asked, with the options side by side: hosted, and self-hosted with Edgible. If one detail decides it, ask that one question.
2. For self-hosting, be plain about what it costs: they keep the app updated and backed up, it is down while the machine is, and it uses that machine's power and bandwidth.
3. Name what Edgible would run, from the need's entry in the needs map: its starter or card if one fits ([Find](#1-find)), or the shortlist from [Choose an app](#choose-an-app). Say what its fit and exposure mean for this person.
4. Do nothing until the person chooses. If they choose self-hosting, continue at [Find](#1-find).

**Example.** "Hosting my small marketing website costs $40 a month. Is there a better way?"

- **If the site is static** (pages, no logins, no editing in a CMS): free static hosting, such as Cloudflare Pages, Netlify, or GitHub Pages, is usually best. It has no machine to keep up and no bill.
- **If it is edited in a CMS such as WordPress:** the `wordpress` starter on a machine they already own can take the bill to nearly nothing, in return for the upkeep above. A managed WordPress host is the middle way.
- Ask which it is, and recommend from the answer.

Do not suggest self-hosting when the person's problem has nothing to do with running a service.

## Rules

- **Ask first** before any of these: publishing an admin or personal interface with auth mode `none`; mounting the Docker socket (a CI runner does), because that gives full control of the machine; stopping, deleting, or changing anything this task did not create; deleting data, upgrading, or moving an app; and anything that leaves the machine for other people, such as a pull request or an issue.
- **Back up before anything that can lose data:** an upgrade, a restore, a move, or deleting volumes. See [Back up and restore](#back-up-and-restore).
- **Never print a secret.** Secrets live in `card.env`. Run `chmod 600` on it. Tell the person where it is and which line holds what they need, such as the admin password, and give them the command that shows that one line.
- **Run every step the README gives, in order.** Never skip Check. Stop at the first step that fails, and fix it or report it. Do not work around it silently.
- **Change only `card.env`** for this machine's settings. A change to any other file in a card is a fix: see [Fix a card or card-kit](#fix-a-card-or-card-kit).
- **Fetch from upstream `main`.** A local clone of a cards or starters repo may be old.

## Understand the need

Skip this step when the person names an app ("self-host Miniflux"). Go to [Find](#1-find).

Otherwise, look the need up in [needs-map.yaml](needs-map.yaml), next to this file. Each entry is an awesome-selfhosted category, with the needs people describe (`jobs`), the services they leave (`replaces`), why they self-host it (`drivers`), how well it suits Edgible (`fit`), how to publish it (`exposure`), what the machine needs, its starters and cards, and the questions that change the answer (`ask`). Match on `jobs` and `replaces`, in the person's words: "Pocket shut down" is Bookmarks and Link Sharing, and "home automation" is Internet of Things (IoT). Read the whole entry.

- **Ask at most two or three questions**, and only ones whose answers change the recommendation: the entry's `ask`, plus how sensitive the data is when a driver is privacy, plus which machine would run it when you do not know. Do not hand the person a questionnaire.
- **Fit `poor` or `refused`:** say so plainly, with the entry's reason, and recommend what does work, such as a hosted provider, or running it on the home network only. Do not build it.
- **Fit `good` or `conditional`:** offer it as [When to suggest it](#when-to-suggest-it) says, with the entry's conditions stated.
- **Sensitive data:** offer the entry's `exposure.sensitive` choices, including not publishing at all, before the default.
- **No entry matches:** pick the category from awesome-selfhosted's `tags/` instead, as in [Choose an app](#choose-an-app), and reason about fit and exposure the same way.

Then go to [Find](#1-find), with the entry's `starters` and `cards` as the first candidates. If none fits, go to [Choose an app](#choose-an-app) with the entry's category.

When someone asks what Edgible's gateway can see, or where TLS ends, point to Edgible's documentation. Do not answer from memory.

## 1. Find

The person names an app ("self-host Miniflux") or describes a need ("something for bookmarks"). Either way, look for a starter or card first. For a need, read each candidate's **Why** to see whether it meets that need.

List what exists. Starters and cards are the top-level directories that hold a `card.yml`:

```bash
for repo in starters cards; do
  echo "== $repo"
  gh api "repos/Edgible/$repo/contents" \
    --jq '.[] | select(.type == "dir" and (.name | startswith(".") | not)) | .name'
done
```

Read the README of each candidate: the **Why** and **What** sections say what it does, which places (machines) it needs, and the auth mode on each hostname. If a starter fits but the person wants several apps together, the starters README says how to combine starters into a card.

The Edgible catalog (`edgible template list`) has managed templates. Read a template's description for its limits before you offer it. A template's choices are fixed, and a starter or card can be changed.

If nothing fits:

- **The person described a need:** go to [Choose an app](#choose-an-app), then [Build a starter](#build-a-starter) for the app they choose.
- **The person named an app:** go to [Build a starter](#build-a-starter). If that app is unsuitable (archived, no maintained container image, or on the starters README's **What is not a starter** list), say why, and offer alternatives from its category with [Choose an app](#choose-an-app).

## 2. Decide with the person

Before anything starts, put the card's open choices to the person in one message, with your recommendation for each:

- **Which device runs each place.** `edgible device list` prints the names. One machine can hold every place of a small, trusted setup. Say what the card's README says about keeping places apart.
- **Each hostname's auth mode**, and what it means: `none` is the open internet, protected only by the app's own login. When the data is sensitive, offer the needs map's `exposure.sensitive` choices, including not publishing at all, even when the starter uses `none`.
- **Anything the README marks as a trade-off**, such as a runner with the Docker socket.
- **Whether it must stay up** after a restart. If so, check the machine first: see [Keep it running](#keep-it-running).

## 3. Deploy

Follow the card's README **How** section exactly: Fetch, Edit `card.env`, Check, Start (and `prepare.sh` when the card has one), Publish. Notes:

- Find `ORG_LABEL` in a hostname `edgible app list` prints: it is the part after the app name, such as `example` in `umami.example.edgible.com`.
- Check: run `check-env` until it says `no conflicts`. Its fixes can come in more than one pass. Secrets come first, and a moved port can come next once the Compose file resolves. Paste the lines it prints, and read any line that starts with `#` before running it.
- Publish: if `edgible app create existing --help` lists `--tag`, add `--tag starter=<name>` or `--tag card=<name>` to every app the card publishes, so the deployment can be counted and found later.
- **Do not look up a hostname before Publish has created it.** Resolvers remember "does not exist" for up to 15 minutes. After Publish, ask Edgible's own nameservers:

  ```bash
  host=umami.example.edgible.com
  ns=$(dig +short NS "${host#*.*.}" | head -1)   # the zone's nameserver
  ip=$(dig +short "@$ns" "$host" A | tail -1)
  curl -sS -o /dev/null -w '%{http_code}\n' --resolve "$host:443:$ip" "https://$host"
  ```

## 4. Verify

Run the card's README **Verify** section. Each hostname answers the way its auth mode says: `none` with the app, `org` with a redirect to the Edgible sign-in, `api-key` with `401` until a key is sent, and `tcp` with a connection. Run the card's own checks too, in `etc/` or `test/`, when it has them.

Then check what the person actually asked for, end to end. For a Git forge, that is a real `git clone` and `git push`. For a CI runner, it is a workflow that runs to success. A green Verify is necessary but is not the whole answer.

## Keep it running

When the setup must survive a restart:

- **macOS with Docker Desktop:** in Docker Desktop's Settings → General, turn on "Start Docker Desktop when you sign in". If that option is greyed out, macOS has refused Docker's background item. Turn on Docker under System Settings → General → Login Items & Extensions → Allow in the Background. Or, with the person's agreement, add Docker to Open at Login: `osascript -e 'tell application "System Events" to make login item at end with properties {path:"/Applications/Docker.app", hidden:true}'`. Check sleep with `pmset -g`, because a sleeping Mac serves nothing.
- **Linux:** `systemctl is-enabled docker` should print `enabled`.
- The Edgible agent: `edgible agent status` says how it is installed. A user-level agent runs only while that user is logged in.
- The Compose services use `restart: unless-stopped` in every card, so they come back with Docker.

## 5. Report

Tell the person, briefly:

- what runs where, with each hostname and its auth mode;
- how to sign in the first time, and which `card.env` line holds the password;
- what is still theirs to decide or do, such as changing the admin password;
- where the card's files are, and that its README's **Tear down** removes it.

## After it is running

Each card runs from a directory on its machine: the one that holds its `card.yml`, its Compose files, and its `card.env`. The commands below use `dir` for that directory and `f` for a Compose file in it. Run them once per Compose file when the card has several, such as the ci card's `runner-compose.yml`:

```bash
dir=~/umami                    # the card's directory
f=docker-compose.yml
C="docker compose --env-file $dir/card.env -f $dir/$f"
project=$($C config --format json | jq -r .name)
```

### What is running

```bash
docker compose ls --all    # each Compose project, with the path of its Compose file
edgible app list           # each published app: name, port, device, status
```

The path `docker compose ls` prints leads to the card's directory, and `metadata.name` in its `card.yml` names the card. An Edgible app on the same device with the port that the card's `card.env` sets (`<APP>_PORT`) is that card's app. Once apps carry tags, `--tag card=` or `starter=` says so directly. A project named `cardtest-*` is left over from an interrupted `test-card` run, not a deployment. Tell the person, and remove it only if they agree.

Answer with a short table: each card, its directory, its apps with hostname and auth mode, and whether each is up.

### Is it working

To prove an app works, show evidence from each layer:

1. **Containers:** `$C ps` shows each service running, and healthy when it has a healthcheck.
2. **Hostnames:** each hostname answers the way its auth mode says, checked through Edgible's nameservers as in [Deploy](#3-deploy).
3. **The card's own checks:** the scripts its README's Verify runs, in `etc/`, and those in `test/`. Run them with `card.env` exported and `HOSTNAME_<APP>` set to each hostname: `set -a; . $dir/card.env; set +a; export HOSTNAME_UMAMI=umami.example.edgible.com`.
4. **The goal:** what the person uses it for, end to end, such as signing in, a `git push`, a workflow run, or an event that shows up on a dashboard.
5. **The data path:** `edgible app doctor <app>` checks the deployment, certificates, and the path from the gateway to the workload.

Report each check with its result and the evidence, such as the status code or the line printed. Do not use `test-card` for this. It tests a fresh copy of the card and publishes apps of its own, not the person's running instance.

### Something is wrong

Work from the app outwards, and stop at the first layer that is broken:

1. **Containers:** `$C ps`, then `$C logs --tail 100 <service>`.
2. **On the machine:** `curl -sS -o /dev/null -w '%{http_code}\n' http://127.0.0.1:<port>`, with the port from `card.env`. An `https` app is plain HTTP on the machine.
3. **Edgible:** `edgible app doctor <app>`, `edgible app events <app>`, and `edgible certs`.
4. **The machine:** Docker is running, `edgible agent status`, `edgible doctor`, and [Keep it running](#keep-it-running) after a restart.
5. **DNS:** ask Edgible's nameservers before you decide a hostname is broken. The person's resolver may still remember it as missing.

Fix the cause, then run [Is it working](#is-it-working). If the card itself is wrong, see [Fix a card or card-kit](#fix-a-card-or-card-kit).

### Sign in, passwords, and keys

- **The first sign-in:** the card's README says who the admin is, in How or Verify. List the secret names with `grep -oE '^[A-Z0-9_]+(PASSWORD|SECRET|TOKEN|KEY)[A-Z0-9_]*=' $dir/card.env`, and give the person the command that shows the line they need, such as `grep '^GITEA_ADMIN_PASSWORD=' ~/ci/card.env`.
- **Changing a password** happens in the app, by its own docs. The value in `card.env` only made the first admin. After a change, update that line too when the card's checks or `prepare.sh` read it.
- **An `api-key` hostname:** `edgible app api-keys create --app <app> --name <who-calls-it>` prints the key once. Give it to the person and do not store it. `edgible app api-keys list --app <app>` and `delete` manage the keys.
- **An `org` hostname** lets in the members of the person's Edgible organization. `--allowed-orgs` on `edgible app update` adds other organizations.

### Change a setting

- **Auth mode:** `edgible app update <app> --auth-modes org`. Ask first before changing it to `none`.
- **A value in `card.env`:** edit it, then run `$C up -d --wait`, which recreates the services the change affects. Run `check-env` first when the change is a port.
- **Host port or hostname:** the CLI cannot change a published app's port or hostnames. Change `<APP>_PORT` (or the card's `<APP>_URL`, for the person's own domain), run `$C up -d --wait`, then `edgible app delete <app> --yes` and publish it again as in the README, with `--hostnames` for an own domain. The generated hostname comes from the app's name, so it stays the same. Expect a short outage, and verify through Edgible's nameservers.
- **Pause:** `edgible app update <app> --target-state suspended`, then `$C stop`. **Resume:** `$C start`, then `--target-state running`. The data stays.

### Back up and restore

A copy is whole only while the containers are stopped, so a backup is a short outage. Keep `card.env` with the copies: the databases in them expect its passwords.

```bash
backups=$dir-backups; stamp=$(date +%Y%m%d-%H%M); mkdir -p "$backups"
$C stop
for v in $(docker volume ls -q --filter "label=com.docker.compose.project=$project"); do
  docker run --rm -v "$v:/data:ro" -v "$backups:/backup" alpine tar -czf "/backup/$v-$stamp.tgz" -C /data .
done
cp "$dir/card.env" "$backups/card.env-$stamp"; chmod 600 "$backups/card.env-$stamp"
$C start
```

A copy on the same machine does not survive the loss of that machine. Suggest the person also copies `$backups` somewhere else.

**Restore** replaces the current data. Ask first, and make a fresh backup first unless the data is already lost. Use the `card.env` that was saved with the copy:

```bash
$C stop
for v in $(docker volume ls -q --filter "label=com.docker.compose.project=$project"); do
  docker run --rm -v "$v:/data" -v "$backups:/backup" alpine \
    sh -c "find /data -mindepth 1 -delete && tar -xzf /backup/$v-$stamp.tgz -C /data"
done
$C start
```

Then run [Is it working](#is-it-working).

### Upgrade

1. **See what changed.** Fetch the card from upstream `main` into a new directory, and compare it with `$dir`. Its Fetch step replaces `card.env`, so never fetch over `$dir` itself.

   ```bash
   new=$(mktemp -d)
   curl -fsSL https://github.com/Edgible/starters/archive/refs/heads/main.tar.gz \
     | tar -xz --strip-components=2 -C "$new" starters-main/umami   # cards: Edgible/cards and cards-main/<card>
   diff -ru -x card.env -x images -x test.yml "$dir" "$new"
   diff <(grep -oE '^[A-Z0-9_]+=' "$dir/card.env") <(grep -oE '^[A-Z0-9_]+=' "$new/card.env")
   ```

2. **Tell the person** what will change, especially image versions and new settings. **If a database image changes major version**, such as `postgres:17` to `postgres:18`, stop: the data needs that database's own upgrade, which a new image alone does not do. Point the person to the database's docs.
3. **Back up**, and keep the old files: `cp -R "$dir" "$dir.before-upgrade"`.
4. **Copy the new files in, keeping `card.env`:** `rsync -a --exclude card.env "$new/" "$dir/"`. Add each new `card.env` line with its default, and run `check-env` to fill any new secret.
5. **Start:** `$C up -d --wait` pulls the new images. Run `prepare.sh` again only if the card's README says an upgrade needs it, because it usually makes the first admin.
6. Run [Is it working](#is-it-working). If it fails, put back `$dir.before-upgrade` and the backup, start, and check again.

The published apps stay as they are, unless the card's ports or apps changed.

### Move to another machine

Ask first. The app is down between the old copy stopping and the new one answering.

1. The new machine is a serving device that `edgible device list` shows online, with Docker.
2. [Back up](#back-up-and-restore) on the old machine. Copy `$dir` with its `card.env` and the backups to the new machine.
3. On the new machine, `$C create` makes the volumes without starting anything. Restore each copy into its volume, run `$C up -d --wait`, and check it on `127.0.0.1`.
4. Switch the hostnames: `edgible app delete <app> --yes`, then publish again as in the README, with the new device's id. The generated hostname stays the same.
5. Run [Is it working](#is-it-working). Then, on the old machine, `$C down`, and keep its volumes until the person is satisfied.

### Remove

Follow the card's README **Tear down**, in order: Unpublish, Stop, Delete the data (it backs up each volume to `.tgz` first), and Remove the card. Ask before deleting data. Before `rm -rf` of the card, tell the person that `card.env` holds the passwords any kept backup needs. Remove only the apps, containers, and volumes this card made.

## Choose an app

Use this step only when the person described a need and no starter or card meets it, or when the app they named is unsuitable. Do not pick from memory. Shortlist from [awesome-selfhosted](https://awesome-selfhosted.net), a curated list of free self-hosted software, through its machine-readable data. That data has one YAML file per app, with its categories (`tags`), platforms, licence, stars, last update, and whether it is archived.

```bash
ash=$(mktemp -d)
curl -fsSL https://github.com/awesome-selfhosted/awesome-selfhosted-data/archive/refs/heads/master.tar.gz \
  | tar -xz --strip-components=1 -C "$ash"
ls "$ash/tags"    # the categories; the needs map names the category for the needs it covers
```

Then list that category's apps, most starred first:

```bash
tag="Bookmarks and Link Sharing"   # the name: line of the category's file in tags/
for f in $(grep -l -- "- $tag\$" "$ash"/software/*.yml); do
  awk -v app="$(basename "$f" .yml)" '
    /^stargazers_count:/ {stars = $2}
    /^updated_at:/       {updated = $2}
    /^  - Docker$/       {docker = "docker"}
    /^archived: true/    {note = note " archived"}
    /^depends_3rdparty: true/ {note = note " needs-3rd-party"}
    END {printf "%s\t%s\t%s\t%s\t%s\n", stars, app, updated, (docker ? docker : "-"), note}' "$f"
done | sort -rn | head -15
```

Keep only apps that list `Docker`, are not archived, were updated within about six months, and do not need a third-party service. Read the shortlisted apps' own docs for what the list does not say: the containers and database they need, how the first admin is made, and whether they have phone or desktop apps. Apps with their own clients need an auth mode other than `org` on some hostname: see the starters README's auth table.

Offer two or three candidates in one message. For each, give what it is best at and what it costs to run: containers, database, memory, and the auth trade-off. Recommend one and say why, and let the person choose. A simple app that meets the need usually beats the one with the most features.

## Build a starter

When nothing fits, offer to build a starter. First check the starters README's **What is not a starter** list: an open resolver or relay, an app with no maintained container image, or an archived project gets a plain no, with the reason.

1. Read the [starters README](https://github.com/Edgible/starters#what-a-starter-is) and the [card-kit README](https://github.com/Edgible/card-kit), then copy the shape of the starter closest to the new app.
2. Follow the format: pinned image versions; every variable, service and volume prefixed with the app's name; no `container_name`; each secret empty with a `# Generate with:` comment; each hostname's auth mode chosen from the starters README's table; and `prepare.sh` when the first visitor would otherwise make the admin.
3. Write the README with `card-readme`, and check the files with `check-cards` (see the card-kit README for `run`).
4. Test it on the person's serving device until it passes: `python3 test-card.py <name> --device <device> --by agent`. Put inputs only a person may fill in `test/inputs.env`, and the app's own end-to-end checks in `test/<name>.sh`.
5. Deploy it for the person from the tested files. Their app comes first, and contributing is optional.

## Contribute

Offer this, and do it only with the person's yes.

Each repo's `CONTRIBUTING.md` is the process: [Edgible/starters](https://github.com/Edgible/starters/blob/main/CONTRIBUTING.md) for a starter, [Edgible/cards](https://github.com/Edgible/cards/blob/main/CONTRIBUTING.md) for a card. Read it and follow it. Where it differs from what is written here, it wins. In short:

- **Scrub before anything leaves the machine.** Remove device names, hostnames, the organization id, secrets, and the person's own domain from every file. `check-cards` catches some of them, and you check the rest.
- **Check the name is free:** a 404 from `gh api repos/Edgible/starters/contents/<name>` means it is.
- **Use a fork** unless the person can push to the Edgible repo: `gh repo fork Edgible/starters --clone`. Work on a branch, and never push to `main`.
- **Fill in the repo's pull request template.** Read `.github/PULL_REQUEST_TEMPLATE.md`, write its sections into the body with the `result:` lines of the passing `test-card` run, tick only the checklist items you actually checked, and tick the box that says an AI agent made it. Pass that as `gh pr create --body-file`.
- **If you could not make it pass,** do not open a pull request. Offer an issue from the repo's request template instead: read `.github/ISSUE_TEMPLATE/starter-request.md` (or `card-request.md` in cards), fill in its sections with what you tried and where it failed, and run `gh issue create --title "Starter request: <app>" --label starter-request --body-file <file>`.

A maintainer tests a new starter on their own device before merging. Once merged, the nightly regression keeps testing it.

## Fix a card or card-kit

When a card's steps or a card-kit tool are wrong, and not the person's machine:

1. Find the cause in the files, not just a workaround.
2. Fix it on a branch, and prove the fix with a real run (`test-card`, or the card's own steps) on the case that failed.
3. Offer the pull request, with what failed, why, and the run that proves the fix. Open it only with the person's yes.
