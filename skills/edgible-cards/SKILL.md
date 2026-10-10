---
name: edgible-cards
description: Self-host an app on a machine you own with Edgible, from a tested Edgible starter or card. Use when someone asks to self-host, run, or publish an app (Gitea, Umami, WordPress, a CI runner, and so on) with Edgible, when no starter or card fits and one should be built, or when a starter, card, or card-kit tool needs fixing.
---

# Self-host with Edgible starters and cards

A **starter** is one self-hosted app, tested end to end on a real Edgible serving device: [Edgible/starters](https://github.com/Edgible/starters). A **card** is a pattern of several apps wired together, often across several machines: [Edgible/cards](https://github.com/Edgible/cards). Both use one format, written down in [Edgible/card-kit](https://github.com/Edgible/card-kit), which also holds the tools that check and test them. The card-kit README is the source of truth for the format. Read it rather than guessing.

Work from a starter or card whenever one fits. Its README is a tested path, and following it gives the same result for everyone. Improvise only where the card leaves a choice open, and say so when you do.

## Rules

- **Ask first** before any of these: publishing an admin or personal interface with auth mode `none`; mounting the Docker socket (a CI runner does), because that gives full control of the machine; stopping, deleting, or changing anything this task did not create; and anything that leaves the machine for other people, such as a pull request or an issue.
- **Never print a secret.** Secrets live in `card.env`. Run `chmod 600` on it, and tell the person where it is and which line holds what they need, such as the admin password.
- **Run every step the README gives, in order.** Never skip Check. Stop at the first step that fails, and fix it or report it. Do not work around it silently.
- **Change only `card.env`** for this machine's settings. A change to any other file in a card is a fix: see [Fix a card or card-kit](#fix-a-card-or-card-kit).
- **Fetch from upstream `main`.** A local clone of a cards or starters repo may be old.

## 1. Find

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

If nothing fits, go to [Build a starter](#build-a-starter).

## 2. Decide with the person

Before anything starts, put the card's open choices to the person in one message, with your recommendation for each:

- **Which device runs each place.** `edgible device list` prints the names. One machine can hold every place of a small, trusted setup. Say what the card's README says about keeping places apart.
- **Each hostname's auth mode**, and what it means: `none` is the open internet, protected only by the app's own login.
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

## Build a starter

When nothing fits, offer to build a starter. First check the starters README's **What is not a starter** list: an open resolver or relay, an app with no maintained container image, or an archived project gets a plain no, with the reason.

1. Read the [starters README](https://github.com/Edgible/starters#what-a-starter-is) and the [card-kit README](https://github.com/Edgible/card-kit), then copy the shape of the starter closest to the new app.
2. Follow the format: pinned image versions; every variable, service and volume prefixed with the app's name; no `container_name`; each secret empty with a `# Generate with:` comment; each hostname's auth mode chosen from the starters README's table; and `prepare.sh` when the first visitor would otherwise make the admin.
3. Write the README with `card-readme`, and check the files with `check-cards` (see the card-kit README for `run`).
4. Test it on the person's serving device until it passes: `python3 test-card.py <name> --device <device> --by agent`. Put inputs only a person may fill in `test/inputs.env`, and the app's own end-to-end checks in `test/<name>.sh`.
5. Deploy it for the person from the tested files. Their app comes first, and contributing is optional.

## Contribute

Offer this, and do it only with the person's yes.

- **Scrub before anything leaves the machine.** Remove device names, hostnames, the organization id, secrets, and the person's own domain from every file. `check-cards` catches some of them, and you check the rest.
- **Check the name is free:** a 404 from `gh api repos/Edgible/starters/contents/<name>` means it is.
- **Use a fork** unless the person can push to the Edgible repo: `gh repo fork Edgible/starters --clone`. Work on a branch, and never push to `main`.
- **Open the pull request** with `test.yml` from the passing run and the starters README's **Reviewing a starter** checklist, each item filled in for what you checked.
- **If you could not make it pass,** do not open a pull request. Offer an issue instead, "Starter request: <app>", with what you tried and where it failed.

A maintainer tests a new starter on their own device before merging. Once merged, the nightly regression keeps testing it.

## Fix a card or card-kit

When a card's steps or a card-kit tool are wrong, and not the person's machine:

1. Find the cause in the files, not just a workaround.
2. Fix it on a branch, and prove the fix with a real run (`test-card`, or the card's own steps) on the case that failed.
3. Offer the pull request, with what failed, why, and the run that proves the fix. Open it only with the person's yes.
