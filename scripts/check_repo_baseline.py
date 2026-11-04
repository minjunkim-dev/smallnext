#!/usr/bin/env python3
"""Fail when a file copied from repo-baseline no longer matches its recorded hash."""

import hashlib
import json
from pathlib import Path
import re
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


def mcp_literal_fields(root=ROOT):
    """Paths (server.field.key, never the value) of .mcp.json env and header entries holding anything
    but ${VAR} references, optionally after an auth scheme. A :-default could hold a credential.
    shortcut: secrets inside `args` or URLs are not detected; review covers those."""
    path = root / ".mcp.json"
    if not path.exists():
        return []
    servers = json.loads(path.read_text(encoding="utf-8"))
    servers = servers.get("mcpServers") if isinstance(servers, dict) else None
    if not isinstance(servers, dict):
        raise ValueError(".mcp.json must hold an mcpServers object")
    found = []
    for name, server in sorted(servers.items()):
        for field in ("env", "headers"):
            values = server.get(field, {}) if isinstance(server, dict) else None
            if not isinstance(values, dict):
                raise ValueError(f".mcp.json {name}.{field} must be an object")
            found += [f"{name}.{field}.{key}" for key, value in values.items()
                      if not isinstance(value, str)
                      or not re.fullmatch(r"(?:(?:Bearer|Basic|Token) )?(?:\$\{[A-Za-z_]\w*\})+", value)]
    return found


def main():
    try:
        changed = drift()
        literal_fields = mcp_literal_fields()
    except (OSError, ValueError) as error:
        print(f"repo-baseline UNVERIFIED: {error}", file=sys.stderr)
        return 2
    if literal_fields:
        print("repo-baseline MCP: .mcp.json values that are not only ${VAR} references: " + ", ".join(literal_fields))
    if changed:
        print("repo-baseline DRIFT: " + ", ".join(changed)
              + "; change the file in repo-baseline, then re-run tools/apply_baseline.py")
    if literal_fields or changed:
        return 1
    print("repo-baseline PASS: copied files match the recorded hashes")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
