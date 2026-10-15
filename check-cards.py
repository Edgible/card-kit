#!/usr/bin/env python3
"""Check card.yml files against card.schema.json, which sits next to this file.

With no arguments, checks every <name>/card.yml in the current directory, which is
the root of a cards repo.
With arguments, checks those files.
metadata.name must match the directory name.

It also checks the naming conventions the tools rely on, so card.yml stays short:
- each app's port is <APP>_PORT in card.env, with the port in card.yml as its value.
  Apps that share a port, a place, and an image use the first one's variable.
- a Compose file in the card reads that variable.
- card.env has DEVICE for a card with one place, and <PLACE>_DEVICE for each place
  of a card with more.
- each Compose file sets a top-level name:, the Compose project name.
- a place in the optional places: section is one the apps use.

A card of metadata.type app is one app that other cards are built from, so it also must:
- have test.yml;
- have one Compose file and one place;
- name every service and volume <card> or <card>-<something>, and set no container_name,
  so two app cards drop into one Compose file without a clash.

A card with a native place (native: macos) runs its app on the machine itself, not in
Docker, so it has install.sh and uninstall.sh next to card.yml and no Compose file:
- install.sh pins the release (a VERSION= line with a version number) and checks its
  SHA-256 before installing, and reads each app's <APP>_PORT;
- card.env has SERVICE, the name of the service install.sh starts, so a test can run
  its own copy beside a person's;
- uninstall.sh removes nothing outside the card's directory by path: no rm of an
  absolute path, ~ or $HOME.

A card with Compose volumes says what they hold in data: (a note until every card has it):
- one entry under data.volumes for each named volume in its Compose files, and no others;
- a fingerprint when any volume is irreplaceable;
- each dump and the fingerprint run in a service of its Compose files.
A pattern card inherits data: from its app cards, so it gets no note.

--before-test leaves out the test.yml rule, for a card about to be tested for the
first time; test-card writes test.yml.

A card may also have test.yml, the latest run of its lifecycle. When it does,
it must match test.schema.json, give a Verify result for every app in card.yml,
say pass only when no step failed, and name no hostname.
"""

from __future__ import annotations

import importlib.util
import json
import re
import sys
from pathlib import Path

import yaml
from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError

SCHEMA_PATH = Path(__file__).resolve().parent / "card.schema.json"
TEST_SCHEMA_PATH = Path(__file__).resolve().parent / "test.schema.json"
HOSTNAME = re.compile(r"[a-z0-9-]+\.[a-z0-9-]+\.edgible\.com|\b\d{1,3}(?:\.\d{1,3}){3}\b")


def files_hash(card_dir: Path) -> str:
    """The fingerprint test-card writes as files: in test.yml, from the same function."""
    spec = importlib.util.spec_from_file_location("test_card", Path(__file__).resolve().parent / "test-card.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.files_hash(card_dir)


def freshness(card_dir: Path) -> str:
    """Why test.yml may not describe these files, or "" when it does or there is no test.yml."""
    path = card_dir / "test.yml"
    if not path.is_file():
        return ""
    recorded = (re.search(r"^files:\s*(\S+)", path.read_text(), re.M) or [None, ""])[1]
    if not recorded:
        return "test.yml has no files: fingerprint; run test-card to record one"
    if recorded != files_hash(card_dir):
        return "the card's files changed since test.yml was written; run test-card again"
    return ""


def card_paths(argv: list[str]) -> list[Path]:
    if argv:
        return [Path(arg).resolve() for arg in argv]
    found = sorted(Path.cwd().glob("*/card.yml"))
    if not found:
        sys.exit("no cards found")
    return found


def env_name(name: str) -> str:
    return name.upper().replace("-", "_")


def read_env(path: Path) -> dict[str, str]:
    env = {}
    for line in path.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            env[key.strip()] = value.strip()
    return env


def convention_errors(card_dir: Path, card: dict) -> list[str]:
    """What breaks the naming conventions, as messages that say what to change."""
    errors = []
    env_path = card_dir / "card.env"
    if not env_path.is_file():
        return [f"{env_path.name} is missing"]
    env = read_env(env_path)
    composes = {f.name: f.read_text() for f in sorted(card_dir.glob("*compose*.yml"))}
    native = any(spec.get("native") for spec in (card.get("places") or {}).values())
    if native:
        return native_errors(card_dir, card, env, composes)
    # Publish reads card.env in the shell (. card.env), so a value with a space needs quotes.
    for number, line in enumerate(env_path.read_text().splitlines(), 1):
        if "=" in line and not line.lstrip().startswith("#"):
            value = line.split("=", 1)[1]
            if re.search(r"\s", value) and not re.fullmatch(r"\s*(\"[^\"]*\"|'[^']*')\s*", value):
                errors.append(f"card.env line {number}: quote the value, because the shell reads card.env too")
    if not composes:
        errors.append("no *compose*.yml file next to card.yml")
    for name, text in composes.items():
        if not re.search(r"^name:\s*\S", text, re.MULTILINE):
            errors.append(f"{name} has no top-level name:, the Compose project name")

    owners: dict[tuple, str] = {}
    for app in card["applications"]:
        owner = owners.setdefault((app["port"], app["place"], app["from"]), app["name"])
        var = env_name(owner) + "_PORT"
        shared = f" (shared with {owner})" if owner != app["name"] else ""
        if var not in env:
            errors.append(f"app {app['name']}: card.env has no {var}{shared}")
        elif env[var] != str(app["port"]):
            errors.append(
                f"app {app['name']}: card.env has {var}={env[var]}, card.yml has port {app['port']}"
            )
        if not any("${" + var in text for text in composes.values()):
            errors.append(f"app {app['name']}: no Compose file reads ${{{var}}}")

    app_places = {app["place"] for app in card["applications"]}
    declared = card.get("places", {})
    for place, spec in declared.items():
        runs = spec.get("runs", [])
        if place not in app_places and not runs:
            errors.append(f"places names {place}, which no app uses; a place with no app says what it runs with runs:")
        for name in runs:
            if name not in composes:
                errors.append(f"place {place} runs {name}, which is not a Compose file next to card.yml")
    places = sorted(app_places | {p for p, spec in declared.items() if spec.get("runs")})
    wanted = {places[0]: "DEVICE"} if len(places) == 1 else {p: env_name(p) + "_DEVICE" for p in places}
    for place, var in wanted.items():
        if var not in env:
            errors.append(f"card.env has no {var}, the serving device for place {place}")
    errors += risky_errors(card_dir, composes)
    if card["metadata"].get("type") == "app":
        errors += app_errors(card_dir, card, composes)
    return errors


NO_TEST = "an app card must have test.yml: run test-card"


def native_errors(card_dir: Path, card: dict, env: dict[str, str], composes: dict[str, str]) -> list[str]:
    """The rules for a card whose place runs natively: see the module's docstring."""
    errors = []
    places = card.get("places") or {}
    install, uninstall = card_dir / "install.sh", card_dir / "uninstall.sh"
    if composes:
        errors.append(f"a native card runs no Compose file, but has {', '.join(composes)}")
    if not install.is_file() or not uninstall.is_file():
        errors.append("a native card has install.sh and uninstall.sh next to card.yml")
        return errors
    script = install.read_text()
    if not re.search(r"^VERSION=[\"']?v?\d", script, re.M):
        errors.append("install.sh pins its release with a VERSION= line, such as VERSION=0.40.4")
    if not re.search(r"sha256|shasum", script):
        errors.append("install.sh checks the release's SHA-256 before it installs it")
    if not env.get("SERVICE"):
        errors.append("card.env has no SERVICE, the name of the service install.sh starts")
    owners: dict[tuple, str] = {}
    for app in card["applications"]:
        owner = owners.setdefault((app["port"], app["place"], app["from"]), app["name"])
        var = env_name(owner) + "_PORT"
        if env.get(var) != str(app["port"]):
            errors.append(f"app {app['name']}: card.env has no {var}={app['port']}")
        if "$" + var not in script and "${" + var not in script:
            errors.append(f"app {app['name']}: install.sh does not read {var}")
        if not places.get(app["place"], {}).get("native"):
            errors.append(f"app {app['name']}: place {app['place']} is not native, and a card is native or Compose, not both")
    if len(places) == 1 and "DEVICE" not in env:
        errors.append("card.env has no DEVICE, the serving device")
    for number, line in enumerate(uninstall.read_text().splitlines(), 1):
        if re.search(r"\brm\b[^#\n]*\s(/|~|\"?\$HOME)", line):
            errors.append(f"uninstall.sh line {number} removes a path outside the card's directory")
    if card["metadata"].get("type") == "app":
        if len(places) != 1:
            errors.append("an app card has one place")
        if not (card_dir / "test.yml").is_file():
            errors.append(NO_TEST)
    return errors


def app_errors(card_dir: Path, card: dict, composes: dict[str, str]) -> list[str]:
    """What an app card breaks of the rules that let it be combined with others."""
    name = card["metadata"]["name"]
    errors = []
    if not (card_dir / "test.yml").is_file():
        errors.append(NO_TEST)
    if len(composes) != 1:
        errors.append(f"an app card has one Compose file, not {len(composes)}")
    places = {app["place"] for app in card["applications"]} | set(card.get("places") or {})
    if len(places) != 1:
        errors.append(f"an app card has one place, not {len(places)}: {', '.join(sorted(places))}")
    ours = re.compile(rf"^{re.escape(name)}(-[a-z0-9-]+)?$")
    for file, text in composes.items():
        compose = yaml.safe_load(text) or {}
        for kind in ("services", "volumes"):
            for item in (compose.get(kind) or {}):
                if not ours.match(item):
                    errors.append(f"{file}: {kind[:-1]} {item} must be named {name} or {name}-<something>")
        for service, spec in (compose.get("services") or {}).items():
            if isinstance(spec, dict) and "container_name" in spec:
                errors.append(f"{file}: service {service} sets container_name; an app card must not")
    return errors


def data_problems(card: dict, composes: dict[str, str]) -> tuple[list[str], list[str]]:
    """What is wrong with data:, and a note when a card with volumes has none yet."""
    volumes, services = set(), set()
    for text in composes.values():
        compose = yaml.safe_load(text) or {}
        volumes |= set(compose.get("volumes") or {})
        services |= set(compose.get("services") or {})
    data = card.get("data")
    if not data:
        if volumes and card["metadata"].get("type") != "pattern":
            return [], [f"no data: section yet for its volumes ({', '.join(sorted(volumes))})"]
        return [], []
    errors = []
    declared = data.get("volumes") or {}
    for name in sorted(volumes - set(declared)):
        errors.append(f"data.volumes has no entry for volume {name}")
    for name in sorted(set(declared) - volumes):
        errors.append(f"data.volumes names {name}, which is not a volume in the Compose files")
    if any(v.get("class") == "irreplaceable" for v in declared.values()) and not data.get("fingerprint"):
        errors.append("data has irreplaceable volumes but no fingerprint")
    runs = [(f"data.volumes.{n}.dump", v["dump"]["service"]) for n, v in declared.items() if v.get("dump")]
    if data.get("fingerprint"):
        runs.append(("data.fingerprint", data["fingerprint"]["service"]))
    for where, service in runs:
        if service not in services:
            errors.append(f"{where} runs in service {service}, which is not in the Compose files")
    return errors, []


RISKY = [
    (re.compile(r"/var/run/docker\.sock"), "mounts the Docker socket", ("docker socket",)),
    (re.compile(r"^\s*privileged:\s*true", re.M), "runs privileged", ("privileged",)),
    (re.compile(r"^\s*network_mode:\s*[\"']?host", re.M), "uses the host's network", ("host network", "host's network")),
]


def risky_errors(card_dir: Path, composes: dict[str, str]) -> list[str]:
    """A service with full control of its machine must be named in the README."""
    readme = (card_dir / "README.md").read_text().lower() if (card_dir / "README.md").is_file() else ""
    errors = []
    for name, text in composes.items():
        for pattern, what, words in RISKY:
            if pattern.search(text) and not any(w in readme for w in words):
                errors.append(f"{name} {what}, which gives it full control of its machine; "
                              f"the README must say so (mention: {words[0]})")
    return errors


def untrusted_errors(card_dir: Path, composes: dict[str, str]) -> list[str]:
    """For a card nobody has reviewed yet, such as one an agent just wrote, before it runs on a
    machine: nothing in it may reach outside the card. Only named volumes and paths inside the
    card's own directory may be mounted, and no service may get the host's network, processes,
    devices, extra capabilities, or the Docker socket."""
    errors = []
    for file, text in composes.items():
        compose = yaml.safe_load(text) or {}
        for name, spec in (compose.get("services") or {}).items():
            if not isinstance(spec, dict):
                continue
            where = f"{file}: service {name}"
            for key in ("privileged", "cap_add", "devices", "security_opt", "userns_mode", "cgroup_parent"):
                if spec.get(key):
                    errors.append(f"{where} sets {key}")
            for key in ("network_mode", "pid", "ipc"):
                if str(spec.get(key, "")).startswith(("host", "container:", "service:")):
                    errors.append(f"{where} uses the host's or another container's {key}")
            for volume in spec.get("volumes") or []:
                source = volume.get("source", "") if isinstance(volume, dict) else str(volume).split(":")[0]
                kind = volume.get("type", "") if isinstance(volume, dict) else ""
                named = re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", source or "") and kind != "bind"
                inside = (source.startswith("./") and ".." not in source.split("/")) or source == "."
                if source and not named and not inside:
                    errors.append(f"{where} mounts {source}, outside the card; use a named volume or a path under ./")
                if "docker.sock" in str(volume):
                    errors.append(f"{where} mounts the Docker socket")
    return errors


def test_errors(card_dir: Path, card: dict, validator: Draft202012Validator) -> list[str]:
    """What is wrong with test.yml, if the card has one."""
    path = card_dir / "test.yml"
    if not path.is_file():
        return []
    text = path.read_text()
    try:
        test = yaml.safe_load(text)
        # YAML reads an unquoted date as a date; the schema checks the text.
        if test and not isinstance(test.get("tested"), str) and test.get("tested") is not None:
            test["tested"] = str(test["tested"])
        # An unquoted short commit id that is all digits reads as a number; it is still an id.
        if test and isinstance(test.get("card-kit"), int):
            test["card-kit"] = str(test["card-kit"])
        validator.validate(test)
    except (yaml.YAMLError, ValidationError) as exc:
        return [f"test.yml: {getattr(exc, 'message', exc)}"]
    errors = []
    apps = {app["name"] for app in card["applications"]}
    verified = set(test["steps"]["verify"])
    for name in sorted(apps - verified):
        errors.append(f"test.yml: no verify result for app {name}")
    for name in sorted(verified - apps):
        errors.append(f"test.yml: verify names {name}, which is not an app in card.yml")
    outcomes = [v for k, v in test["steps"].items() if k != "verify"] + list(test["steps"]["verify"].values())
    if test["result"] == "pass" and "fail" in outcomes:
        errors.append("test.yml: result is pass, but a step failed")
    if test["result"] == "fail" and "fail" not in outcomes:
        errors.append("test.yml: result is fail, but no step failed")
    known = {app["place"] for app in card["applications"]} | {
        p for p, spec in (card.get("places") or {}).items() if spec.get("runs")}
    for place in test.get("measured", {}):
        if place not in known:
            errors.append(f"test.yml: measured names {place}, which no app in card.yml uses")
    match = HOSTNAME.search(text)
    if match:
        errors.append(f"test.yml: names a hostname or address ({match.group(0)}); leave those out")
    return errors


def main(argv: list[str]) -> int:
    schema = json.loads(SCHEMA_PATH.read_text())
    validator = Draft202012Validator(
        schema, format_checker=Draft202012Validator.FORMAT_CHECKER
    )
    test_validator = Draft202012Validator(
        json.loads(TEST_SCHEMA_PATH.read_text()), format_checker=Draft202012Validator.FORMAT_CHECKER
    )
    # --fresh: a card whose files changed since its test.yml fails. Without it, that is a note.
    fresh = "--fresh" in argv
    # --untrusted: the card has not been reviewed (an agent wrote it), so nothing in it may
    # reach outside the card before it runs anywhere.
    untrusted = "--untrusted" in argv
    # --before-test: the card is about to be tested for the first time, so it has no
    # test.yml yet. Every other rule still applies.
    before_test = "--before-test" in argv
    argv = [a for a in argv if a not in ("--fresh", "--untrusted", "--before-test")]
    failed = False
    for path in card_paths(argv):
        try:
            card = yaml.safe_load(path.read_text())
            name = card["metadata"]["name"]
            if name != path.parent.name:
                raise SystemExit(
                    f"{path}: metadata.name is {name}, directory is {path.parent.name}"
                )
            validator.validate(card)
            errors = convention_errors(path.parent, card) + test_errors(path.parent, card, test_validator)
            data_errors, data_notes = data_problems(
                card, {f.name: f.read_text() for f in sorted(path.parent.glob("*compose*.yml"))})
            errors += data_errors
            for note in data_notes:
                print(f"note {path}: {note}")
            if before_test:
                errors = [e for e in errors if e != NO_TEST]
            if untrusted and any(s.get("native") for s in (card.get("places") or {}).values()):
                errors.append("a native card installs software on the machine itself, so it is never "
                              "made or run unreviewed")
            if untrusted:
                composes = {f.name: f.read_text() for f in sorted(path.parent.glob("*compose*.yml"))}
                errors += untrusted_errors(path.parent, composes)
            stale = freshness(path.parent)
            if stale and fresh:
                errors.append(stale)
            elif stale:
                print(f"note {path}: {stale}")
            if errors:
                for error in errors:
                    print(f"{path}: {error}", file=sys.stderr)
                failed = True
                continue
        except ValidationError as exc:
            where = "/".join(str(part) for part in exc.absolute_path) or "the top level"
            print(f"{path}: {exc.message} (at {where})", file=sys.stderr)
            failed = True
            continue
        except (OSError, KeyError, TypeError, yaml.YAMLError) as exc:
            print(f"{path}: {exc}", file=sys.stderr)
            failed = True
            continue
        print(f"ok {path}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
