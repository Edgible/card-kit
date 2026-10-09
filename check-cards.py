#!/usr/bin/env python3
"""Check card.yml files against card.schema.json, which sits next to this file.

With no arguments, checks every <name>/card.yml in the current directory, which is
the root of a cards or starters repo.
With arguments, checks those files.
metadata.name must match the directory name.

It also checks the naming conventions the tools rely on, so card.yml stays short:
- each app's port is <APP>_PORT in card.env, with the port in card.yml as its value.
  Apps that share a port, a place, and an image use the first one's variable.
- a Compose file in the card reads that variable.
- card.env has DEVICE for a card with one place, and <PLACE>_DEVICE for each place
  of a card with more.
- each Compose file sets a top-level name:, the Compose project name.

A card may also have test.yml, the latest run of its lifecycle. When it does,
it must match test.schema.json, give a Verify result for every app in card.yml,
say pass only when no step failed, and name no hostname.
"""

from __future__ import annotations

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

    places = sorted({app["place"] for app in card["applications"]})
    wanted = {places[0]: "DEVICE"} if len(places) == 1 else {p: env_name(p) + "_DEVICE" for p in places}
    for place, var in wanted.items():
        if var not in env:
            errors.append(f"card.env has no {var}, the serving device for place {place}")
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
