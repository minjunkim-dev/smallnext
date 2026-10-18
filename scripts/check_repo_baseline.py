#!/usr/bin/env python3
"""Fail when a file copied from repo-baseline no longer matches its recorded hash."""

import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ".github/repo-baseline.json"


def drift(root=ROOT):
    root = root.resolve()
    manifest = json.loads((root / MANIFEST).read_text(encoding="utf-8"))
    files = manifest.get("files") if isinstance(manifest, dict) else None
    if not isinstance(files, dict) or not files or not isinstance(manifest.get("source_commit"), str):
        raise ValueError(f"{MANIFEST} must record source_commit and files")
    changed = []
    for name, entry in sorted(files.items()):
        path = root / name
        if not path.is_symlink() and root not in path.resolve().parents:
            raise ValueError(f"{MANIFEST} path escapes the repository: {name!r}")
        digest = entry.get("sha256") if isinstance(entry, dict) else None
        if path.is_symlink() or not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != digest:
            changed.append(name)
    return changed


def main():
    try:
        changed = drift()
    except (OSError, ValueError) as error:
        print(f"repo-baseline UNVERIFIED: {error}", file=sys.stderr)
        return 2
    if changed:
        print("repo-baseline DRIFT: " + ", ".join(changed)
              + "; change the file in repo-baseline, then re-run tools/apply_baseline.py")
        return 1
    print("repo-baseline PASS: copied files match the recorded hashes")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
