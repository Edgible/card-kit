#!/usr/bin/env python3
"""Test a card's whole lifecycle on this machine, and write test.yml.

Run it on a serving device, from the directory that holds the card:

    python3 test-card.py gitea --device macbookair
    python3 test-card.py wordpress --device macbookair --prepare '$COMPOSE --profile cli run --rm wordpress-cli wp core install ...'
    python3 test-card.py immich --device macbookair --write-places --gpu optional

It works on a copy of the card in a temporary directory, through every step a person
follows in the card's README:

  check-env   fills empty secrets the way card.env says, and stops on a conflict
  start       up --wait, as its own Compose project (cardtest-<card>-<file>), so the
              test never touches the machine's own containers or volumes
  prepare     an optional command between Start and Publish, such as making the admin
  publish     each app in card.yml; a name already taken in the org is published as
              test-<name>, and the existing app is never touched
  verify      each hostname by its auth mode: none answers, org redirects to the Edgible
              sign-in, api-key answers 401, tcp connects; udp is skipped
  teardown    deletes the apps it published and removes the containers and volumes it
              started, and nothing else

While it runs it measures each place: the peak memory of its containers together, the
size of its images, and the size of its data at the end. It writes test.yml (unless
nothing material changed since the last one), and prints a suggested places: section,
the measurement plus a margin. --write-places writes that into card.yml.

DNS: Edgible's zone caches "does not exist" for 15 minutes, so a hostname looked up too
early stays unresolvable. Verify asks Edgible's own nameservers and connects by address.

Needs python3, Docker with compose and buildx, dig, and edgible, logged in. Only the
standard library, because it checks the machine and so does not run in a container.
"""
from __future__ import annotations

import argparse
import json
import math
import platform
import re
import shutil
import socket
import ssl
import subprocess
import sys
import tempfile
import threading
import time
from datetime import date
from pathlib import Path

HERE = Path(__file__).resolve().parent
CHECK_ENV = HERE / "check-env.py"
ARCH = {"x86_64": "amd64", "amd64": "amd64", "aarch64": "arm64", "arm64": "arm64", "armv7l": "arm", "arm": "arm"}
MEM_UNIT = {"B": 1, "KiB": 1024, "MiB": 1024**2, "GiB": 1024**3, "kB": 1e3, "MB": 1e6, "GB": 1e9}


def sh(cmd: str, check: bool = True, timeout: int = 1800) -> subprocess.CompletedProcess:
    p = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=timeout)
    if check and p.returncode != 0:
        raise RuntimeError(f"{cmd}\n{p.stdout[-1500:]}\n{p.stderr[-1500:]}")
    return p


# --- The card ---------------------------------------------------------------

def read_apps(card_yml: Path) -> list[dict]:
    """The applications in card.yml. It is flat enough to read without pyyaml."""
    text = re.split(r"\nplaces:\s*\n", card_yml.read_text())[0]
    apps = []
    for block in re.split(r"\n\s*- name: ", text)[1:]:
        get = lambda k: (re.search(rf"\n\s+{k}:\s*(.+)", block) or [None, ""])[1].strip()
        apps.append({
            "name": block.split("\n", 1)[0].strip(),
            "port": int(get("port")),
            "protocol": get("protocol"),
            "auth": [m.strip() for m in get("authModes").strip("[]").split(",")],
            "place": get("place"),
            "from": get("from"),
        })
    return apps


def file_places(apps: list[dict], compose: Path) -> list[str]:
    """The places a Compose file runs, from the <APP>_PORT variable each app's file reads."""
    text, owners, found = compose.read_text(), {}, []
    for app in apps:
        owner = owners.setdefault((app["port"], app["place"], app["from"]), app["name"])
        if "${" + owner.upper().replace("-", "_") + "_PORT" in text and app["place"] not in found:
            found.append(app["place"])
    return found


def set_env(env_file: Path, key: str, value: str) -> None:
    text = env_file.read_text()
    if re.search(rf"^{key}=", text, re.M):
        env_file.write_text(re.sub(rf"^{key}=.*$", f"{key}={value}", text, flags=re.M))


def org_label() -> str:
    """The org's hostname label, read off an app the org already has."""
    for app in json.loads(sh("edgible app list --json").stdout):
        for host in app.get("hostnames", []):
            m = re.fullmatch(rf"{re.escape(app['name'])}\.([a-z0-9-]+)\.edgible\.com", host)
            if m:
                return m.group(1)
    return ""


# --- Verify -----------------------------------------------------------------

def authoritative_ip(host: str) -> str:
    """The address as Edgible's own nameservers have it, past any resolver cache."""
    zone = ".".join(host.split(".")[-2:])
    for server in sh(f"dig +short NS {zone}", check=False).stdout.split():
        ip = sh(f"dig +short @{server} {host} A", check=False).stdout.split()
        if ip:
            return ip[-1]
    return ""


def https_get(ip: str, host: str) -> tuple[int, str]:
    with socket.create_connection((ip, 443), timeout=20) as raw:
        with ssl.create_default_context().wrap_socket(raw, server_hostname=host) as s:
            s.sendall(f"GET / HTTP/1.1\r\nHost: {host}\r\nUser-Agent: edgible-test-card\r\n"
                      f"Connection: close\r\n\r\n".encode())
            data = b""
            while b"\r\n\r\n" not in data:
                chunk = s.recv(4096)
                if not chunk:
                    break
                data += chunk
    head = data.split(b"\r\n\r\n")[0].decode(errors="replace").split("\r\n")
    location = next((h.split(":", 1)[1].strip() for h in head[1:] if h.lower().startswith("location:")), "")
    return int(head[0].split()[1]), location


def verify(app: dict, host: str) -> tuple[str, str]:
    ip = authoritative_ip(host)
    if not ip:
        raise RuntimeError("no DNS record yet")
    if app["protocol"] == "udp":
        return "skip", "udp needs a probe that speaks the app's protocol"
    if app["protocol"] == "tcp":
        with socket.create_connection((ip, app["port"]), timeout=15) as s:
            s.settimeout(5)
            try:
                banner = s.recv(64).decode(errors="replace").strip()
            except socket.timeout:
                banner = ""
        return "pass", "tcp connected" + (f", banner {banner[:24]}" if banner else "")
    code, location = https_get(ip, host)
    mode = app["auth"][0]
    if mode == "org":
        ok = code in (301, 302, 303, 307) and "application-access" in location
    elif mode == "api-key":
        ok = code == 401
    else:
        ok = code < 400 and "application-access" not in location
    return ("pass" if ok else "fail"), f"{code} {location.split('?')[0][:60]}"


# --- Measure ----------------------------------------------------------------

def mem_bytes(text: str) -> float:
    m = re.match(r"([0-9.]+)\s*([A-Za-z]+)", text.strip())
    return float(m.group(1)) * MEM_UNIT.get(m.group(2), 1) if m else 0.0


def human(n: float, small: bool = False) -> str:
    if n >= 1e9:
        return f"{n / 1e9:.1f} GB".replace(".0 ", " ")
    if n >= 1e6 or not small:
        return f"{max(1, round(n / 1e6))} MB"
    return f"{max(1, round(n / 1e3))} KB"


class Sampler:
    """Peak memory of each Compose project, sampled with docker stats."""

    def __init__(self, projects: list[str]):
        self.peak = {p: 0.0 for p in projects}
        self.stop = threading.Event()
        self.thread = threading.Thread(target=self.run, daemon=True)

    def run(self) -> None:
        while not self.stop.is_set():
            out = sh("docker stats --no-stream --format '{{.Name}} {{.MemUsage}}'", check=False).stdout
            totals = {p: 0.0 for p in self.peak}
            for line in out.splitlines():
                name, _, usage = line.partition(" ")
                for p in totals:
                    if name.startswith(p + "-"):
                        totals[p] += mem_bytes(usage.split("/")[0])
            for p, total in totals.items():
                self.peak[p] = max(self.peak[p], total)
            self.stop.wait(2)


def volume_bytes(project: str) -> float:
    total = 0.0
    for volume in sh(f"docker volume ls -q --filter label=com.docker.compose.project={project}",
                     check=False).stdout.split():
        du = sh(f"docker run --rm -v {volume}:/v:ro alpine du -sk /v", check=False).stdout.split()
        total += float(du[0]) * 1024 if du else 0
    return total


def image_archs(image: str) -> set[str]:
    out = sh(f"docker buildx imagetools inspect {image} --format '{{{{json .Manifest}}}}'", check=False).stdout
    try:
        manifests = json.loads(out).get("manifests", [])
    except json.JSONDecodeError:
        return set()
    return {ARCH.get(m["platform"]["architecture"], m["platform"]["architecture"])
            for m in manifests if m.get("platform", {}).get("architecture") not in (None, "unknown")}


def suggest(memory: float, disk: float, archs: set[str], gpu: str) -> dict:
    """The minimum recommended: measured memory plus half, at least 256 MB; disk plus 1 GB."""
    mem = max(256e6, memory * 1.5)
    return {
        "memory": f"{math.ceil(mem / 128e6) * 128} MB" if mem < 1e9 else f"{math.ceil(mem / 0.5e9) * 0.5:g} GB",
        "disk": f"{math.ceil((disk + 1e9) / 0.5e9) * 0.5:g} GB",
        "arch": [a for a in ("amd64", "arm64", "arm") if a in archs],
        "gpu": gpu,
    }


def places_yaml(places: dict[str, dict]) -> str:
    lines = ["places:"]
    for name, p in places.items():
        lines += [f"  {name}:", f"    memory: {p['memory']}", f"    disk: {p['disk']}",
                  f"    arch: [{', '.join(p['arch'])}]", f"    gpu: {p['gpu']}"]
    return "\n".join(lines) + "\n"


# --- test.yml ---------------------------------------------------------------

def material(text: str) -> tuple:
    """What decides whether test.yml is committed: the result, the steps, and the images."""
    result = (re.search(r"^result:\s*(\S+)", text, re.M) or [None, ""])[1]
    steps = (re.search(r"^steps:\n((?:  .*\n?)+)", text, re.M) or [None, ""])[1]
    images = sorted(re.findall(r"^  - (\S+)", (re.search(r"^images:\n((?:  - .*\n?)+)", text, re.M)
                                               or [None, ""])[1], re.M))
    return result, steps.strip(), tuple(images)


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("card", type=Path, help="the card directory")
    ap.add_argument("--device", required=True, help="the serving device, as `edgible device list` names it")
    ap.add_argument("--org-label", default="", help="the org's hostname label; read off an existing app if left out")
    ap.add_argument("--prepare", default="",
                    help="shell to run between Start and Publish, with card.env exported and $COMPOSE set "
                         "to the test's compose command for the first Compose file")
    ap.add_argument("--verify-wait", type=int, default=300, help="seconds to wait for each hostname")
    ap.add_argument("--by", choices=["agent", "person"], default="person")
    ap.add_argument("--gpu", choices=["none", "optional", "required"], default="none",
                    help="the gpu value in the suggested places:")
    ap.add_argument("--write-places", action="store_true", help="write the suggested places: into card.yml")
    ap.add_argument("--keep", action="store_true", help="leave it running and published after Verify")
    args = ap.parse_args(argv)

    src = args.card.resolve()
    if not (src / "card.yml").is_file():
        print(f"{src} has no card.yml", file=sys.stderr)
        return 2
    label = args.org_label or org_label()
    if not label:
        print("pass --org-label: no existing app shows the org's hostname label", file=sys.stderr)
        return 2

    started = time.time()
    work = Path(tempfile.mkdtemp(prefix="test-card-"))
    shutil.copytree(src, work / src.name, ignore=shutil.ignore_patterns("test.yml", "images"))
    card = work / src.name
    env_file = card / "card.env"
    set_env(env_file, "DEVICE", args.device)
    set_env(env_file, "ORG_LABEL", label)
    apps = read_apps(card / "card.yml")
    composes = sorted(card.glob("*compose*.yml"))
    project = f"cardtest-{src.name}"
    projects = {f: f"{project}-{f.stem}" for f in composes}
    dc = lambda f, rest: f"docker compose -p {projects[f]} --env-file {env_file} -f {f} {rest}"
    hide = lambda s: s.replace(label, "<org>")
    steps: dict = {"check-env": "fail", "start": "skip", "publish": "skip", "verify": {}, "teardown": "skip"}
    notes, published, started_compose = [], [], False
    sampler = Sampler(list(projects.values()))
    data: dict[Path, float] = {}

    try:
        fixes = sh(f"cd {work} && python3 {CHECK_ENV} {src.name} --commands", check=False).stdout.splitlines()
        if any(l and not l.startswith("#") and "check-env.py" not in l for l in fixes):
            (work / "fix.sh").write_text("\n".join(fixes[:-1]) + "\n")
            sh(f"cd {work} && sh fix.sh", check=False)
        report = sh(f"cd {work} && python3 {CHECK_ENV} {src.name}", check=False).stdout
        conflicts = [l for l in report.splitlines()
                     if "conflict " in l and not re.search(r"app \S+ already exists", l)]
        if conflicts:
            print(hide(report))
            raise RuntimeError("check-env found conflicts")
        steps["check-env"] = "pass"
        print("check-env: pass")

        sampler.thread.start()
        t = time.time()
        steps["start"], started_compose = "fail", True
        for f in composes:
            sh(dc(f, "up -d --wait --wait-timeout 1200"), timeout=2400)
        steps["start"] = "pass"
        print(f"start: pass ({int(time.time() - t)}s)")

        if args.prepare:
            prepare = sh(f"cd {work} && set -a && . {env_file} && set +a && "
                         f"COMPOSE='docker compose -p {projects[composes[0]]} --env-file {env_file} -f {composes[0]}' "
                         f"&& {args.prepare}", check=False, timeout=900)
            print("prepare:", "ok" if prepare.returncode == 0 else "FAILED",
                  hide((prepare.stdout + prepare.stderr).strip()[-300:]))
            if prepare.returncode != 0:
                raise RuntimeError("prepare failed")

        existing = {a["name"] for a in json.loads(sh("edgible app list --json").stdout)}
        devices = [d for d in json.loads(sh("edgible device list --json").stdout) if d["name"] == args.device]
        if len(devices) != 1:
            raise RuntimeError(f"need exactly one device named {args.device}")
        for app in apps:
            name = app["name"] if app["name"] not in existing else f"test-{app['name']}"
            if name != app["name"]:
                notes.append(f"{app['name']} is taken in the test org, so it was published as {name}.")
            steps["publish"] = "fail"
            sh(f"edgible app create existing --non-interactive --name {name} --port {app['port']} "
               f"--protocol {app['protocol']} --auth-modes {','.join(app['auth'])} "
               f"--device-id {devices[0]['id']}", timeout=900)
            published.append((app, name))
        steps["publish"] = "pass"
        print("publish: pass", [n for _, n in published])

        listing = {a["name"]: a for a in json.loads(sh("edgible app list --json").stdout)}
        for app, name in published:
            host, deadline, result, detail = listing[name]["hostnames"][0], time.time() + args.verify_wait, "fail", ""
            while time.time() < deadline:
                try:
                    result, detail = verify(app, host)
                except Exception as exc:  # not reachable yet
                    result, detail = "fail", str(exc)[:80]
                if result in ("pass", "skip"):
                    break
                time.sleep(10)
            steps["verify"][app["name"]] = result
            print(f"verify {app['name']}: {result} ({hide(detail)})")
    except Exception as exc:
        print(hide(f"stopped: {exc}"))
    finally:
        sampler.stop.set()
        if started_compose:
            data = {f: volume_bytes(projects[f]) for f in composes}
        if not args.keep:
            ok = True
            for _, name in published:
                ok &= sh(f"edgible app delete {name} --yes", check=False, timeout=600).returncode == 0
            if started_compose:
                for f in composes:
                    ok &= sh(dc(f, "down --volumes"), check=False).returncode == 0
            if started_compose or published:
                steps["teardown"] = "pass" if ok else "fail"
            print(f"teardown: {steps['teardown']}")

    # Images, as they ran, and what each place measured.
    images, per_place = [], {}
    for f in composes:
        config = json.loads(sh(dc(f, "config --format json"), check=False).stdout or "{}")
        place = (file_places(apps, f) or [apps[0]["place"]])[0]
        entry = per_place.setdefault(place, {"memory": 0.0, "images": 0.0, "data": 0.0, "archs": None})
        entry["memory"] += sampler.peak.get(projects[f], 0.0)
        entry["data"] += data.get(f, 0.0)
        for service in config.get("services", {}).values():
            image = service.get("image")
            if not image:
                continue
            digest = sh(f"docker image inspect {image} --format '{{{{index .RepoDigests 0}}}}'",
                        check=False).stdout.strip()
            images.append(f"{image}@{digest.split('@')[1]}" if "@" in digest and "@" not in image else image)
            entry["images"] += float(sh(f"docker image inspect {image} --format '{{{{.Size}}}}'",
                                        check=False).stdout.strip() or 0)
            archs = image_archs(image)
            entry["archs"] = archs if entry["archs"] is None else entry["archs"] & archs
    for app in apps:
        steps["verify"].setdefault(app["name"], "skip")
    core = [steps[k] for k in ("check-env", "start", "publish", "teardown")]
    result = ("pass" if all(c == "pass" for c in core) and "fail" not in steps["verify"].values()
              and "pass" in steps["verify"].values() else "fail")

    docker_version = sh("docker version --format '{{.Server.Version}}'", check=False).stdout.strip()
    lines = [
        f"tested: {date.today()}", f"result: {result}",
        f"card-kit: {sh(f'git -C {HERE} rev-parse --short HEAD', check=False).stdout.strip() or 'unknown'}",
        f"edgible-cli: {sh('edgible --version', check=False).stdout.strip()}",
        f"machine: {platform.system().lower()}/{ARCH.get(platform.machine(), platform.machine())}, docker {docker_version}",
        "images:", *[f"  - {i}" for i in sorted(set(images))],
        "steps:", f"  check-env: {steps['check-env']}", f"  start: {steps['start']}",
        f"  publish: {steps['publish']}", "  verify:", *[f"    {k}: {v}" for k, v in steps["verify"].items()],
        f"  teardown: {steps['teardown']}",
    ]
    if started_compose:
        lines.append("measured:")
        for place, m in per_place.items():
            lines += [f"  {place}:", f"    memory: {human(m['memory'])}", f"    images: {human(m['images'])}",
                      f"    data: {human(m['data'], small=True)}"]
    lines += [f"duration: {max(1, round((time.time() - started) / 60))}m", f"by: {args.by}"]
    if notes:
        lines.append("notes: " + " ".join(notes))
    new = "\n".join(lines) + "\n"
    target = src / "test.yml"
    if target.is_file() and material(target.read_text()) == material(new):
        print(f"\nresult: {result}. Nothing material changed, so {target} stays as it was.")
    else:
        target.write_text(new)
        print(f"\nresult: {result}. Wrote {target}.")

    if started_compose:
        suggestion = {p: suggest(m["memory"], m["images"] + m["data"], m["archs"] or set(), args.gpu)
                      for p, m in per_place.items()}
        print("\nsuggested " + places_yaml(suggestion), end="")
        if args.write_places and result == "pass":
            card_yml = src / "card.yml"
            body = re.split(r"\nplaces:\s*\n", card_yml.read_text())[0].rstrip("\n")
            card_yml.write_text(body + "\n\n" + places_yaml(suggestion))
            print(f"Wrote places: into {card_yml}. Raise a number if the app documents a higher minimum.")
    if not args.keep:
        shutil.rmtree(work, ignore_errors=True)
    return 0 if result == "pass" else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
