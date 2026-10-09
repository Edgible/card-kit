#!/usr/bin/env python3
"""Check a fetched card against the machine it is about to run on.

Run it after card.env is edited and before the containers start:

    python3 check-env.py website
    python3 check-env.py website -f kuma-compose.yml

The argument is the card directory. With no -f, every *compose*.yml in it is
checked. Compose reads card.env and resolves each file, so the ports and names
checked are the ones `docker compose up` would use.

It looks for host ports already taken, container names already taken, Compose
project names already used by other files, leftover volumes, serving devices
that do not match, and Edgible applications with the same name. Each conflict
prints a remedy. A container, project, or volume from the same Compose file is
this card already running, and is not a conflict.

A Notes section tells what is worth knowing but is not a problem: a service that
already runs elsewhere on this machine, an image tag such as latest that moves
with each release, and where each service's healthcheck comes from. Notes
change no exit code and no remedy.

The report ends with the remedies as lines to paste into a shell. Edits to
card.env and restarts run as they are. A line that stops or deletes something
starts with #, so it runs only when you remove that #. With --commands, only
those lines are printed:

    python3 check-env.py website --commands > fix.sh

Only the standard library. Exit 0 when nothing conflicts, 1 when something
does, 2 when the check cannot run.
"""

from __future__ import annotations

import argparse
import errno
import json
import os
import re
import shlex
import shutil
import socket
import subprocess
import sys
from pathlib import Path

REQUIRED_VAR = re.compile(r"\$\{([A-Z][A-Z0-9_]*):\?")
PORT_VAR = re.compile(r"\$\{([A-Z][A-Z0-9_]*)[^}]*\}:\d+")
DEVICE_VAR = re.compile(r"^(?:[A-Z0-9_]+_)?DEVICE$")
TOP_NAME = re.compile(r"^name:\s*\S", re.MULTILINE)
PUBLISHED = re.compile(r"(?:^|:)(\d+)->\d+/(?:tcp|udp)")
# Images every card may run its own copy of, so a second copy is not worth a note.
SHARED_EVERYWHERE = {"postgres", "mysql", "mariadb", "redis", "valkey/valkey", "mongo", "alpine"}
GENERATE = re.compile(r"Generate (?:each |(two) values )?with: (.+)$")


class Edit:
    """Set a line in card.env. shell is a value the shell makes, such as $(openssl rand -hex 16)."""

    def __init__(self, var: str, why: str, value: str = "", shell: str = "") -> None:
        self.var = var
        self.why = why
        self.value = value
        self.shell = shell

    def __str__(self) -> str:
        return f"set {self.var}={self.shell or self.value} in card.env"

    def sed(self) -> str:
        if self.shell:
            return f'"s|^{self.var}=.*|{self.var}={self.shell}|"'
        return shlex.quote(f"s|^{self.var}=.*|{self.var}={self.value}|")


class Cmd:
    """A shell command. safe is False when it stops or deletes something."""

    def __init__(self, text: str, cmd: str, safe: bool = True) -> None:
        self.text = text
        self.cmd = cmd
        self.safe = safe

    def __str__(self) -> str:
        return f"{self.text}: {self.cmd}"


class Report:
    def __init__(self, quiet: bool = False) -> None:
        self.conflicts = 0
        self.warnings = 0
        self.quiet = quiet
        self.findings: list[tuple[str, tuple]] = []

    def say(self, text: str) -> None:
        if not self.quiet:
            print(text)

    def section(self, title: str) -> None:
        self.say(f"\n{title}")

    def ok(self, text: str) -> None:
        self.say(f"  ok        {text}")

    def warn(self, text: str, *remedies) -> None:
        self.warnings += 1
        self.finding("warning", text, remedies)

    def conflict(self, text: str, *remedies) -> None:
        self.conflicts += 1
        self.finding("conflict", text, remedies)

    def finding(self, kind: str, text: str, remedies: tuple) -> None:
        self.findings.append((text, remedies))
        self.say(f"  {kind:<9} {text}")
        for remedy in remedies:
            self.say(f"            -> {remedy}")

    def skip(self, text: str) -> None:
        self.say(f"  skipped   {text}")

    def note(self, text: str) -> None:
        """Information for the user. Not a conflict or a warning, and no remedy."""
        self.say(f"  note      {text}")

    def commands(self, env_file: Path, rerun: str) -> list[str]:
        """The remedies as shell lines. One sed makes every card.env edit, so .bak is the file before them."""
        edits = [
            (text, r) for text, remedies in self.findings for r in remedies if isinstance(r, Edit)
        ]
        lines = [
            "# Paste these lines into a shell on this machine.",
            "# A line that starts with # stops or deletes something. Read it, and remove the # to run it.",
        ]
        if edits:
            lines += ["", f"# Edit {env_file.name}. {env_file.name}.bak keeps the copy from before."]
            lines += [f"#   {r.var}: {r.why}" for _, r in edits]
            lines.append("sed -i.bak \\")
            lines += [f"  -e {r.sed()} \\" for _, r in edits]
            lines.append(f"  {shlex.quote(str(env_file))}")
        seen: set[str] = set()
        for text, remedies in self.findings:
            if not any(isinstance(r, Cmd) for r in remedies):
                continue
            lines += ["", f"# {text}"]
            # The first safe command runs, unless a card.env edit above already fixes this.
            active = any(isinstance(r, Edit) for r in remedies)
            for r in remedies:
                if isinstance(r, str):
                    lines.append(f"# {r}")
                elif isinstance(r, Cmd) and r.cmd in seen:
                    lines.append(f"# {r.text}: same command as above")
                elif isinstance(r, Cmd):
                    seen.add(r.cmd)
                    if r.safe and not active:
                        lines += [f"# {r.text}", r.cmd]
                        active = True
                    else:
                        lines.append(f"# {r.text}: {r.cmd}")
        by_hand = [
            (text, [r for r in remedies if isinstance(r, str)])
            for text, remedies in self.findings
            if not any(isinstance(r, (Edit, Cmd)) for r in remedies)
        ]
        if by_hand:
            lines += ["", "# Still to do by hand:"]
            for text, advice in by_hand:
                lines.append(f"#   {text}")
                lines += [f"#     {a}" for a in advice]
        lines += ["", "# Check again.", rerun]
        return lines


def run(cmd: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, capture_output=True, text=True)


def read_env(path: Path) -> dict[str, str]:
    env: dict[str, str] = {}
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        env[key.strip()] = value.strip().strip("'\"")
    return env


def generators(path: Path) -> dict[str, str]:
    """A shell value for each card.env line whose comment says how to make it, such as
    `# Generate with: openssl rand -hex 16`. A blank line ends that comment."""
    found: dict[str, str] = {}
    value = ""
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line:
            value = ""
        elif line.startswith("#"):
            match = GENERATE.search(line)
            if match:
                one = f"$({match.group(2).strip()})"
                value = f"{one},{one}" if match.group(1) else one
        elif "=" in line and value:
            found[line.split("=", 1)[0].strip()] = value
    return found


def read_apps(card_yml: Path) -> list[dict[str, str]]:
    """name and place of each application. card.yml is flat enough to read without pyyaml."""
    apps: list[dict[str, str]] = []
    for line in card_yml.read_text().splitlines():
        match = re.match(r"^\s*-\s+name:\s*(\S+)", line)
        if match:
            apps.append({"name": match.group(1)})
            continue
        match = re.match(r"^\s+place:\s*(\S+)", line)
        if match and apps:
            apps[-1]["place"] = match.group(1)
    return apps


def device_var(place: str, env: dict[str, str]) -> str | None:
    """WEB_DEVICE for place web on a card with several places, DEVICE on a card with one."""
    specific = place.upper().replace("-", "_") + "_DEVICE"
    if specific in env:
        return specific
    if "DEVICE" in env:
        return "DEVICE"
    return None


def port_free(host: str, port: int) -> bool:
    family = socket.AF_INET6 if ":" in host else socket.AF_INET
    with socket.socket(family, socket.SOCK_STREAM) as sock:
        try:
            sock.bind((host, port))
        except OSError as err:
            if err.errno == errno.EADDRINUSE:
                return False
            raise
    return True


def listener(port: int) -> str | None:
    if not shutil.which("lsof"):
        return None
    out = run(["lsof", "+c", "0", "-nP", f"-iTCP:{port}", "-sTCP:LISTEN"]).stdout.splitlines()
    if len(out) < 2:
        return None
    fields = out[1].split()
    return f"{fields[0]} (pid {fields[1]})"


def docker_containers() -> tuple[list[dict], str]:
    """Every container, and the daemon error if `docker ps -a` failed.

    One damaged container makes `docker ps -a` fail for all of them. Listing one
    status at a time still works, so the check falls back to that.
    """
    proc = run(["docker", "ps", "-a", "--format", "{{json .}}"])
    error = ""
    out = proc.stdout
    if proc.returncode != 0:
        error = proc.stderr.strip()
        out = ""
        for status in ("created", "restarting", "running", "removing", "paused", "exited", "dead"):
            out += run(
                ["docker", "ps", "-a", "--filter", f"status={status}", "--format", "{{json .}}"]
            ).stdout
    containers = []
    for line in out.splitlines():
        row = json.loads(line)
        labels = dict(
            item.split("=", 1) for item in row.get("Labels", "").split(",") if "=" in item
        )
        row["Project"] = labels.get("com.docker.compose.project", "")
        row["Service"] = labels.get("com.docker.compose.service", "")
        # A stopped container still lists the ports it would publish, but holds none.
        holds = row.get("State") in ("running", "restarting", "paused")
        row["HostPorts"] = {int(p) for p in PUBLISHED.findall(row.get("Ports", ""))} if holds else set()
        containers.append(row)
    return containers, error


def edgible_lists() -> tuple[list | None, dict, str]:
    """Devices and apps from the logged-in CLI, or None and the reason it could not list them."""
    if not shutil.which("edgible"):
        return None, {}, "edgible is not installed; the device and app name checks need it"
    devices_out = run(["edgible", "device", "list", "--json"])
    apps_out = run(["edgible", "app", "list", "--json"])
    if devices_out.returncode != 0 or apps_out.returncode != 0:
        return None, {}, "edgible could not list devices and apps; run `edgible login`"
    apps = {a["name"]: a for a in json.loads(apps_out.stdout)}
    return json.loads(devices_out.stdout), apps, ""


def compose_config(
    compose: Path, env_file: Path, placeholders: dict[str, str] | None = None
) -> tuple[dict | None, str]:
    """The file as Compose resolves it. placeholders fill empty values; the shell environment wins over --env-file."""
    proc = subprocess.run(
        [
            "docker", "compose",
            "--env-file", str(env_file),
            "-f", str(compose),
            "config", "--format", "json",
        ],
        capture_output=True, text=True,
        env={**os.environ, **(placeholders or {})},
    )
    if proc.returncode != 0:
        return None, proc.stderr.strip()
    return json.loads(proc.stdout), ""


def next_free_port(start: int, taken: set[int], host: str) -> int:
    port = start + 1
    while port < 65535:
        if port not in taken and port_free(host, port):
            return port
        port += 1
    return start


def image_repo(image: str) -> str:
    """ollama/ollama:latest and docker.io/ollama/ollama:0.4 are both ollama/ollama."""
    repo = image.split("@", 1)[0]
    if ":" in repo.rsplit("/", 1)[-1]:
        repo = repo.rsplit(":", 1)[0]
    for prefix in ("docker.io/library/", "docker.io/", "library/"):
        if repo.startswith(prefix):
            return repo[len(prefix):]
    return repo


def image_tag(image: str) -> str:
    if "@" in image:
        return "@" + image.split("@", 1)[1]
    last = image.rsplit("/", 1)[-1]
    return last.rsplit(":", 1)[1] if ":" in last else ""


def image_healthcheck(image: str) -> bool | None:
    """Whether a local image has its own healthcheck. None when the image is not on this machine."""
    proc = run(["docker", "image", "inspect", "--format", "{{json .Config.Healthcheck}}", image])
    if proc.returncode != 0:
        return None
    test = json.loads(proc.stdout.strip() or "null") or {}
    return bool(test.get("Test")) and test["Test"] != ["NONE"]


def notes(
    report: Report, files: list[Path], env_file: Path, env: dict[str, str], containers: list[dict]
) -> None:
    """Information for whoever runs the card. It changes no exit code and no remedy.

    Images and healthchecks do not depend on passwords, so a value card.env still lacks
    gets a placeholder here, and a card fresh from Fetch has its notes too.
    """
    report.section("Notes")
    resolved = []
    for compose in files:
        empty = {v: "placeholder" for v in REQUIRED_VAR.findall(compose.read_text()) if not env.get(v)}
        config, _ = compose_config(compose, env_file, empty)
        if config is not None:
            resolved.append((compose, config))
    ours = {config["name"] for _, config in resolved}
    running = [c for c in containers if c["State"] == "running" and c["Project"] not in ours]
    said = False
    for compose, config in resolved:
        health: list[str] = []
        for service, spec in config.get("services", {}).items():
            image = spec.get("image", "")
            built = "build" in spec
            # A service that already runs elsewhere on this machine. Each card keeps its own database.
            if image and not built and image_repo(image) not in SHARED_EVERYWHERE:
                for other in running:
                    if image_repo(other["Image"]) == image_repo(image):
                        ports = ", ".join(str(p) for p in sorted(other["HostPorts"]))
                        owner = f"project {other['Project']}" if other["Project"] else "no Compose project"
                        report.note(
                            f"{service} starts {image_repo(image)}, which container {other['Names']} "
                            f"({owner}) already runs" + (f" on port {ports}" if ports else "")
                            + ". Running both works. Sharing one is up to the card's author."
                        )
                        said = True
                        break
            # An image tag that can change under the card.
            tag = image_tag(image)
            if image and not built and not tag.startswith("@") and not any(ch.isdigit() for ch in tag):
                report.note(
                    f"{service} uses {image_repo(image)}:{tag or 'latest'}, which moves with each release. "
                    "What you get may differ from what the card's author tested."
                )
                said = True
            # Where each service's healthcheck comes from.
            if spec.get("healthcheck") and not spec["healthcheck"].get("disable"):
                health.append(f"{service} from Compose")
            else:
                own = image_healthcheck(image) if image else None
                health.append(
                    f"{service} from the image" if own
                    else f"{service} none" if own is False
                    else f"{service} not known until the image is pulled"
                )
        if health:
            report.note(f"healthchecks in {compose.name}: {', '.join(health)}")
            said = True
    if not said:
        report.ok("nothing to note")


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("card", type=Path, help="the card directory, such as website")
    parser.add_argument(
        "-f", "--file", action="append", default=[],
        help="a Compose file in the card to check; repeat for more (default: all)",
    )
    parser.add_argument(
        "--env-file", type=Path, help="defaults to card.env in the card directory"
    )
    parser.add_argument(
        "--commands", action="store_true",
        help="print only the remedies, as lines to paste into a shell",
    )
    args = parser.parse_args(argv)

    card = args.card.resolve()
    env_file = (args.env_file or card / "card.env").resolve()
    card_yml = card / "card.yml"
    for path in (card_yml, env_file):
        if not path.is_file():
            print(f"{path} not found", file=sys.stderr)
            return 2
    if args.file:
        files = [(card / name).resolve() for name in args.file]
    else:
        files = sorted(card.glob("*compose*.yml"))
    missing = [str(f) for f in files if not f.is_file()]
    if missing or not files:
        print(f"no Compose file: {', '.join(missing) or card}", file=sys.stderr)
        return 2
    if not shutil.which("docker") or run(["docker", "info"]).returncode != 0:
        print("docker is not running on this machine", file=sys.stderr)
        return 2

    env = read_env(env_file)
    apps = read_apps(card_yml)
    report = Report(quiet=args.commands)
    report.say(f"card {card.name}, settings {env_file}")
    generate = generators(env_file)

    # Resolve every file first. A missing value stops the rest for that file.
    report.section("card.env")
    resolved: list[tuple[Path, dict]] = []
    for compose in files:
        config, error = compose_config(compose, env_file)
        # Compose stops at the first empty value, so list every required one here.
        # Only when Compose fails: a required value inside a default that is not used,
        # such as ${URL:-https://app.${ORG_LABEL:?}.edgible.com} with URL set, is not needed.
        required = dict.fromkeys(REQUIRED_VAR.findall(compose.read_text()))
        empty = [var for var in required if not env.get(var)] if config is None else []
        if empty:
            made = [var for var in empty if var in generate]
            by_hand = [var for var in empty if var not in generate]
            report.conflict(
                f"{compose.name} needs a value for {', '.join(empty)}",
                *[Edit(var, "empty; a new value, made the way its comment says", shell=generate[var])
                  for var in made],
                *(
                    [f"fill {', '.join(by_hand)} in {env_file.name} by hand; "
                     "its comment says what goes there"]
                    if by_hand else []
                ),
            )
            continue
        if config is None:
            last = error.splitlines()[-1] if error else "docker compose config failed"
            report.conflict(f"{compose.name}: {last}", f"fix that in {env_file.name} or {compose.name}")
            continue
        resolved.append((compose, config))
        report.ok(f"{compose.name} resolves")
    devices, existing_apps, edgible_note = edgible_lists()
    device_names = ", ".join(sorted(d["name"] for d in devices or [])) or "none"
    for key, value in env.items():
        if DEVICE_VAR.match(key) and not value:
            report.conflict(
                f"{key} is empty",
                f"set {key} to one of: {device_names}"
                if devices is not None
                else f"set {key} to a name that `edgible device list` prints",
            )

    containers, ps_error = docker_containers()
    if ps_error:
        report.section("Docker")
        damaged = re.search(r"container ([0-9a-f]{12})", ps_error)
        report.warn(
            f"`docker ps -a` fails: {ps_error}",
            "the check listed containers one status at a time instead",
            Cmd("remove the damaged container", f"docker rm -f {damaged.group(1)}", safe=False)
            if damaged
            else "restart Docker, then run this again",
        )
    projects = {
        p["Name"]: p
        for p in json.loads(run(["docker", "compose", "ls", "-a", "--format", "json"]).stdout or "[]")
    }
    volumes = set(run(["docker", "volume", "ls", "-q"]).stdout.split())

    # Compose project names.
    report.section("Compose projects")
    own_projects: set[str] = set()
    for compose, config in resolved:
        project = config["name"]
        if not TOP_NAME.search(compose.read_text()):
            report.warn(
                f"{compose.name} has no top-level name:, so this check assumes the project "
                f"is named after its directory ({project})",
                f"add `name: <project>` as the first line of {compose.name}, using the "
                "--project-name its README passes, or the directory name if it passes none",
            )
        existing = projects.get(project)
        if existing is None:
            own_projects.add(project)
            report.ok(f"{project} is free")
            continue
        config_files = [Path(p).resolve() for p in existing["ConfigFiles"].split(",") if p]
        if compose.resolve() in config_files:
            own_projects.add(project)
            report.ok(f"{project} is this file, already {existing['Status']}")
            continue
        others = ", ".join(str(p) for p in config_files)
        if any(p.name == compose.name and p.parent.name == card.name for p in config_files):
            report.conflict(
                f"{project} is running from another copy of this card: {others}",
                "start it from that directory instead, so it keeps its data",
                Cmd("or stop that copy first (its volumes stay)",
                    f"docker compose -p {shlex.quote(project)} down", safe=False),
            )
        else:
            report.conflict(
                f"{project} is already used by {others}",
                f"change `name: {project}` in {compose.name} to a name that is free",
                "Compose would otherwise replace that project's containers",
            )

    # Container names.
    report.section("Container names")
    by_name = {c["Names"]: c for c in containers}
    found = False
    for compose, config in resolved:
        project = config["name"]
        for service, spec in config.get("services", {}).items():
            name = spec.get("container_name")
            if not name:
                continue
            found = True
            other = by_name.get(name)
            if other is None:
                report.ok(f"{name} is free")
            elif other["Project"] == project and project in own_projects:
                report.ok(f"{name} is this card, already {other['State']}")
            else:
                owner = f"project {other['Project']}" if other["Project"] else "no Compose project"
                rename = f"or change container_name for {service} in {compose.name}"
                if other["Project"] in projects:
                    first = Cmd("stop that project first (its volumes stay)",
                                f"docker compose -p {shlex.quote(other['Project'])} down", safe=False)
                elif other["State"] == "running":
                    first = Cmd("stop and remove it if you no longer need it",
                                f"docker rm -f {shlex.quote(name)}", safe=False)
                else:
                    first = Cmd("it is stopped; remove it if it is left over",
                                f"docker rm {shlex.quote(name)}", safe=False)
                report.conflict(
                    f"{name} is taken by a container from {owner} ({other['State']})",
                    first,
                    rename,
                )
    if not found:
        report.ok("no fixed container names; Compose prefixes them with the project")

    # Host ports.
    report.section("Host ports")
    wanted: dict[int, list[str]] = {}
    suggested: set[int] = set()
    for compose, config in resolved:
        project = config["name"]
        port_vars = PORT_VAR.findall(compose.read_text())
        for service, spec in config.get("services", {}).items():
            for mapping in spec.get("ports", []):
                if not mapping.get("published"):
                    continue
                port = int(mapping["published"])
                host = mapping.get("host_ip") or "0.0.0.0"
                var = next((v for v in port_vars if env.get(v) == str(port)), None)
                wanted.setdefault(port, []).append(f"{project}/{service}")
                setting = f"{var}={port}" if var else f"port {port}"
                taken = set(wanted) | suggested | {p for c in containers for p in c["HostPorts"]}
                remedy_port = next_free_port(port, taken, host)
                change = (
                    Edit(var, f"{port} is taken; {remedy_port} is free", value=str(remedy_port))
                    if var
                    else f"change the host port for {service} in {compose.name}"
                )
                users = [c for c in containers if port in c["HostPorts"]]
                ours = [c for c in users if c["Project"] == project and project in own_projects]
                theirs = [c for c in users if c not in ours]
                if theirs or (not ours and not port_free(host, port)):
                    suggested.add(remedy_port)
                if theirs:
                    other = theirs[0]
                    owner = f" in project {other['Project']}" if other["Project"] else ""
                    report.conflict(
                        f"{setting} ({service}) is published by container {other['Names']}{owner}",
                        change,
                        Cmd("or stop that container", f"docker stop {shlex.quote(other['Names'])}", safe=False),
                    )
                elif ours:
                    report.ok(f"{setting} ({service}) is this card, already published")
                elif not port_free(host, port):
                    who = listener(port)
                    report.conflict(
                        f"{setting} ({service}) is in use on {host}"
                        + (f" by {who}" if who else ""),
                        change,
                        "or stop the program that listens there",
                    )
                else:
                    stale = [
                        c for c in containers
                        if c["Project"] == project and project in own_projects
                        and c["Service"] == service and c["State"] == "running"
                    ]
                    if stale:
                        report.warn(
                            f"{setting} ({service}) is free, but container {stale[0]['Names']} "
                            "is running without it; the published app cannot reach it",
                            Cmd("restart it", f"docker restart {shlex.quote(stale[0]['Names'])}"),
                        )
                    else:
                        report.ok(f"{setting} ({service}) is free")
    for port, users in wanted.items():
        if len(users) > 1:
            report.conflict(
                f"port {port} is used twice in this card: {', '.join(users)}",
                "give each one its own port in card.env",
            )

    # Volumes left by an earlier run. Postgres keeps the old password in them.
    report.section("Volumes")
    found = False
    for compose, config in resolved:
        project = config["name"]
        running = project in projects and project in own_projects
        for volume in config.get("volumes", {}).values():
            name = volume.get("name")
            if not name or volume.get("external"):
                continue
            found = True
            if name not in volumes:
                report.ok(f"{name} is new")
            elif running:
                report.ok(f"{name} is this card's data")
            elif project in projects:
                report.warn(
                    f"{name} belongs to project {project}, which runs from "
                    f"{projects[project]['ConfigFiles']}; starting here would share that data",
                    "fix the Compose project conflict above first",
                )
            else:
                report.warn(
                    f"{name} is left from an earlier run; it is reused as it is, "
                    "including any database password it was made with",
                    "keep it if you want that data",
                    Cmd("to start empty, delete it and its data", f"docker volume rm {shlex.quote(name)}", safe=False),
                )
    if not found:
        report.ok("no named volumes")

    # Edgible: devices and application names.
    report.section("Edgible")
    if devices is None:
        report.skip(edgible_note)
    else:
        for key, value in env.items():
            if not DEVICE_VAR.match(key) or not value:
                continue
            matches = [d for d in devices if d["name"] == value]
            if len(matches) == 1:
                report.ok(f"{key}={value} is device {matches[0]['id']} ({matches[0]['status']})")
            elif not matches:
                report.conflict(
                    f"{key}={value} matches no device",
                    f"use one of: {device_names}",
                )
            else:
                report.conflict(
                    f"{key}={value} matches {len(matches)} devices",
                    "rename one with `edgible device` so each name is unique",
                )
        for app in apps:
            other = existing_apps.get(app["name"])
            if other is None:
                report.ok(f"app {app['name']} is free")
                continue
            key = device_var(app.get("place", ""), env)
            device = env.get(key, "") if key else ""
            on = ", ".join(d["name"] for d in other.get("devices", [])) or "no device"
            if device and device in on.split(", "):
                report.warn(
                    f"app {app['name']} already exists on {device} ({other['status']}, "
                    f"port {other.get('port')})",
                    "if this card published it before, skip it in the Publish step",
                    Cmd("to publish it again, delete it first",
                        f"edgible app delete {shlex.quote(app['name'])}", safe=False),
                )
            else:
                report.conflict(
                    f"app {app['name']} already exists on {on} ({other['status']})",
                    Cmd("if it is unused", f"edgible app delete {shlex.quote(app['name'])}", safe=False),
                    f"or publish this one under another name, such as --name {card.name}-{app['name']}",
                )

    notes(report, files, env_file, env, containers)

    rerun = shlex.join(["python3", sys.argv[0], *[a for a in argv if a != "--commands"]])
    has_remedy = any(
        isinstance(r, (Edit, Cmd)) for _, remedies in report.findings for r in remedies
    )
    if args.commands:
        print("\n".join(report.commands(env_file, rerun)))
    else:
        print()
        if report.conflicts:
            print(f"{report.conflicts} conflict(s), {report.warnings} warning(s). "
                  "Fix the conflicts, then run this again.")
        else:
            print(f"no conflicts, {report.warnings} warning(s). Start the containers.")
        if has_remedy:
            print("\nTo apply the remedies, paste these lines into a shell:\n")
            print("\n".join(report.commands(env_file, rerun)))
    return 1 if report.conflicts else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
