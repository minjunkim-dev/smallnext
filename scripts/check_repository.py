#!/usr/bin/env python3
"""Validate text files, local documentation links, CI action pins, and feature flags."""

from datetime import date, datetime
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
from urllib.parse import unquote, urlsplit
from zoneinfo import ZoneInfo


ROOT = Path(__file__).resolve().parents[1]
TEXT_SUFFIXES = {
    ".md", ".py", ".yml", ".yaml", ".json", ".toml", ".rs", ".swift",
    ".kt", ".kts", ".sql", ".xml", ".properties", ".pbxproj", ".xcscheme",
    ".xcworkspacedata", ".sh",
}
TEXT_NAMES = {
    ".gitignore", ".gitattributes", ".editorconfig", ".dockerignore", "CODEOWNERS",
    "Dockerfile", "Makefile", "Caddyfile", "gradlew", "Cargo.lock",
}
LINK_PATTERN = re.compile(r"!?\[[^\]]*\]\(([^\s)]+)(?:\s+[^)]*)?\)")
ACTION_PATTERN = re.compile(r"^\s*(?:-\s*)?uses:\s*([^\s#]+)", re.MULTILINE)


def crlf_paths(root):
    """Return files whose index or working copy has CRLF, whatever their suffix."""
    listing = subprocess.run(
        ["git", "ls-files", "--eol", "--cached", "--others", "--exclude-standard", "-z"],
        cwd=root,
        check=True,
        stdout=subprocess.PIPE,
    ).stdout.decode("utf-8")
    found = []
    for entry in filter(None, listing.split("\0")):
        info, name = entry.split("\t", 1)
        fields = info.split()
        # Bot commits made through the API skip .gitattributes normalization.
        if "attr/-text" not in fields and {"i/crlf", "i/mixed", "w/crlf", "w/mixed"} & set(fields[:2]):
            found.append(name)
    return found


def positive_integer(value):
    return type(value) is int and value > 0


def validate_flags(registry, today=None):
    today = today or datetime.now(ZoneInfo("Asia/Seoul")).date()
    if not isinstance(registry, dict) or type(registry.get("version")) is not int or registry["version"] != 1 or not isinstance(registry.get("flags"), list):
        return ["Feature flags: expected version 1 and a flags array"]
    errors, keys = [], set()
    for index, flag in enumerate(registry["flags"]):
        prefix = f"Feature flag {index}"
        if not isinstance(flag, dict):
            errors.append(f"{prefix}: expected an object")
            continue
        key = flag.get("key")
        if not isinstance(key, str) or not re.fullmatch(r"[a-z][a-z0-9]*(?:_[a-z0-9]+)*", key) or key in keys:
            errors.append(f"{prefix}: key must be unique snake_case")
        elif key:
            keys.add(key)
        phase = flag.get("phase")
        if phase not in ("development", "released") or type(flag.get("default")) is not bool:
            errors.append(f"{prefix}: expected a valid phase and boolean default")
        if phase == "development" and flag.get("default") is not False:
            errors.append(f"{prefix}: unfinished features must default to OFF")
        if phase == "released" and not positive_integer(flag.get("release_issue")):
            errors.append(f"{prefix}: link the release approval issue")
        if not isinstance(flag.get("owner"), str) or not flag["owner"].strip() or not positive_integer(flag.get("issue")):
            errors.append(f"{prefix}: owner and issue are required")
        try:
            remove_by = date.fromisoformat(flag.get("remove_by", ""))
            if remove_by < today:
                errors.append(f"{prefix}: remove_by has expired; remove the flag or record a new date")
        except (TypeError, ValueError):
            errors.append(f"{prefix}: remove_by must be YYYY-MM-DD")
    return errors


def codeql_source_drift(root):
    """The settings baseline pins the CodeQL workflow blob; init and analyze must share one action commit."""
    source = json.loads((root / ".github/repository-settings.json").read_text(encoding="utf-8"))["expected"]["codeql_main_source"]
    data = (root / source["path"]).read_bytes()
    errors = []
    if hashlib.sha1(b"blob %d\0" % len(data) + data).hexdigest() != source["sha"]:
        errors.append(f"{source['path']}: update codeql_main_source.sha in .github/repository-settings.json")
    if len(set(re.findall(r"uses:\s*github/codeql-action/[\w-]+@([0-9a-f]{40})", data.decode("utf-8")))) > 1:
        errors.append(f"{source['path']}: every github/codeql-action step must use one commit")
    return errors


def main():
    tracked = subprocess.run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"],
        cwd=ROOT,
        check=True,
        stdout=subprocess.PIPE,
    ).stdout.decode("utf-8").split("\0")
    paths = [ROOT / name for name in tracked if name]
    crlf = crlf_paths(ROOT)
    errors = [f"{name}: use LF line endings" for name in crlf]
    checked = 0

    if not paths:
        print("FAIL: no tracked files; stage repository files before checking.")
        return 1

    for path in paths:
        name = path.relative_to(ROOT).as_posix()
        if path.suffix not in TEXT_SUFFIXES and path.name not in TEXT_NAMES:
            continue
        checked += 1
        if path.is_symlink():
            errors.append(f"{name}: text files must not be symlinks")
            continue
        try:
            raw = path.read_bytes()
            text = raw.decode("utf-8")
        except (OSError, UnicodeDecodeError) as error:
            errors.append(f"{name}: cannot read UTF-8 text ({error})")
            continue
        room_schema = name.startswith("apps/android/app/schemas/") and path.suffix == ".json"
        # Room's schema exporter writes JSON without a final newline.
        if raw and not raw.endswith(b"\n") and not room_schema:
            errors.append(f"{name}: missing final newline")
        if b"\r" in raw and name not in crlf:
            errors.append(f"{name}: use LF line endings")
        for number, line in enumerate(text.splitlines(), 1):
            if line.rstrip(" \t") != line:
                errors.append(f"{name}:{number}: trailing whitespace")

        if path.suffix == ".md":
            without_fences = re.sub(r"```[^\n]*\n.*?```", "", text, flags=re.DOTALL)
            for target in LINK_PATTERN.findall(without_fences):
                parts = urlsplit(target)
                if parts.scheme or parts.netloc or not parts.path:
                    continue
                if parts.path.startswith("/"):
                    errors.append(f"{name}: use repository-relative links ({target})")
                    continue
                destination = (path.parent / unquote(parts.path)).resolve()
                if not destination.is_relative_to(ROOT):
                    errors.append(f"{name}: link leaves repository ({target})")
                elif not destination.exists():
                    errors.append(f"{name}: broken local link ({target})")

        if name.startswith(".github/workflows/"):
            for action in ACTION_PATTERN.findall(text):
                if action.startswith("./"):
                    continue
                if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_./-]+@[0-9a-f]{40}", action):
                    errors.append(f"{name}: pin external actions to full commit SHA ({action})")

    flags = ROOT / "config/feature-flags.json"
    try:
        if flags.is_symlink():
            raise ValueError("refusing to follow a symlink")
        errors.extend(validate_flags(json.loads(flags.read_text(encoding="utf-8"))))
    except (OSError, ValueError) as error:
        errors.append(f"Feature flags: {error}")
    errors.extend(codeql_source_drift(ROOT))

    if errors:
        print("FAIL: repository hygiene")
        print("\n".join(errors))
        return 1
    print(f"PASS: {checked} repository text files; whitespace, local links, action pins, feature flags.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
