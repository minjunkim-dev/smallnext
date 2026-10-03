#!/usr/bin/env python3
"""Validate repository hygiene without selecting an app toolchain."""

from pathlib import Path
import re
import subprocess
import sys
from urllib.parse import unquote, urlsplit


ROOT = Path(__file__).resolve().parents[1]
TEXT_SUFFIXES = {".md", ".py", ".yml", ".yaml", ".json", ".toml"}
TEXT_NAMES = {".gitignore", ".gitattributes", ".editorconfig", "CODEOWNERS"}
LINK_PATTERN = re.compile(r"!?\[[^\]]*\]\(([^\s)]+)(?:\s+[^)]*)?\)")
ACTION_PATTERN = re.compile(r"^\s*(?:-\s*)?uses:\s*([^\s#]+)", re.MULTILINE)


def main():
    tracked = subprocess.run(
        ["git", "ls-files", "-z"],
        cwd=ROOT,
        check=True,
        stdout=subprocess.PIPE,
    ).stdout.decode("utf-8").split("\0")
    paths = [ROOT / name for name in tracked if name]
    errors = []
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
        if raw and not raw.endswith(b"\n"):
            errors.append(f"{name}: missing final newline")
        if b"\r" in raw:
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

    if errors:
        print("FAIL: repository hygiene")
        print("\n".join(errors))
        return 1
    print(f"PASS: {checked} tracked text files; whitespace, local links, action pins.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
