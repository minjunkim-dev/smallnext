#!/usr/bin/env python3
"""Validate bounded core/scoped Bugbot rules without importing detailed docs."""

import json
from pathlib import Path
import re
import subprocess
import sys
from urllib.parse import urlsplit

TOTAL_LIMIT = 95_000
RULE_LIMIT = 30_000
ROOT_RULE = ".cursor/BUGBOT.md"
MANIFEST = ".github/repo-baseline.json"


def required_rules(root):
    """Each project lists its scoped rules in the repo-baseline manifest."""
    manifest = json.loads((root / MANIFEST).read_text(encoding="utf-8"))
    rules = manifest.get("bugbot_rules") if isinstance(manifest, dict) else None
    if (not isinstance(rules, list) or ROOT_RULE not in rules
            or any(not isinstance(name, str) or not (name == ROOT_RULE or name.endswith("/" + ROOT_RULE))
                   for name in rules)):
        raise ValueError(f"{MANIFEST} bugbot_rules must list {ROOT_RULE} and scoped rule paths")
    return set(rules)


def markdown_targets(text, *, coverage=False):
    """Read inline/reference links; examples in code and images are not rules."""
    lines = []
    fence = None
    for line in text.splitlines() if coverage else []:
        marker = re.match(r"^ {0,3}(`{3,}|~{3,})", line)
        if marker:
            lines.extend(["", ""])
            token = marker[1]
            if fence is None:
                fence = token
            elif token[0] == fence[0] and len(token) >= len(fence):
                fence = None
            continue
        if fence is None and not line.startswith(("    ", "\t")):
            lines.append(line)
    if coverage:
        text = re.sub(r"(?<![\\`])(`+)(?!`)(?:(?!\n[ \t]*\n).)*?(?<!`)\1(?!`)",
                      "", "\n".join(lines), flags=re.DOTALL)
        text = re.sub(r"<!--.*?(?:-->|$)", "", text, flags=re.DOTALL)
    definitions = {}
    for match in re.finditer(r"^ {0,3}\[([^\]\n]+)\]:\s*(<[^>\n]+>|\S+)", text, re.MULTILINE):
        definitions.setdefault(" ".join(match[1].split()).casefold(), match[2])
    text = re.sub(r"^ {0,3}\[[^\]\n]+\]:[^\n]*", "", text, flags=re.MULTILINE)
    for match in re.finditer(r"(?<![!\\])\[[\s\S]*?\]\(\s*", text):
        start = match.end()
        if start == len(text):
            continue
        if text[start] == "<":
            end = text.find(">", start + 1)
            if end == -1:
                raise ValueError("Unclosed angle Markdown destination")
            yield text[start + 1:end]
            continue
        end = start
        depth = 0
        while end < len(text):
            char = text[end]
            if char == "\\":
                end += 2
                continue
            if char.isspace():
                break
            if char == "(":
                depth += 1
            elif char == ")":
                if depth == 0:
                    break
                depth -= 1
            end += 1
        if depth:
            raise ValueError("Unbalanced Markdown destination")
        yield re.sub(r"\\([() ])", r"\1", text[start:end])
    for match in re.finditer(r"(?<![!\\])\[([^\]]+)\](?:\[([^\]]*)\])?(?!\()", text):
        label = " ".join((match[2] or match[1]).split()).casefold()
        if label in definitions:
            yield definitions[label].strip("<>")


def check_rules(root):
    root = root.resolve()
    tracked = set(subprocess.check_output(
        ["git", "ls-files", "-z"], cwd=root, text=True).split("\0")) - {""}
    roots = {name for name in tracked if name == ROOT_RULE or name.endswith("/" + ROOT_RULE)}
    missing = required_rules(root) - roots
    if missing:
        raise ValueError(f"Missing tracked rule files: {sorted(missing)!r}")
    sizes = {}
    for name in sorted(roots):
        path = root / name
        if not path.is_file() or path.resolve() != path:
            raise ValueError(f"Missing or symlink rule: {name!r}")
        text = path.read_text(encoding="utf-8")
        if not text.strip():
            raise ValueError(f"Empty rule: {name!r}")
        sizes[name] = len(text)
        if len(text) > RULE_LIMIT:
            raise ValueError(f"Rule exceeds {RULE_LIMIT} characters: {name!r}")
        # Scan both visible Markdown and examples conservatively. Rules must not
        # link local docs or other scopes; Bugbot selects scopes by changed paths.
        targets = set(markdown_targets(text)) | set(markdown_targets(text, coverage=True))
        for target in targets:
            url = urlsplit(target)
            if not url.scheme and not url.netloc and url.path:
                raise ValueError(f"Local rule link is not allowed in {name!r}: {target!r}; "
                                 "keep detailed-document links in the local review guide")
    total = sum(sizes.values())
    if total > TOTAL_LIMIT:
        raise ValueError(f"Rule total {total} exceeds {TOTAL_LIMIT} characters")
    return sizes


def main():
    try:
        sizes = check_rules(Path.cwd())
    except (OSError, ValueError, subprocess.CalledProcessError) as error:
        print(f"Bugbot rules FAILED: {error}", file=sys.stderr)
        return 1
    print(f"Bugbot rules PASS: {len(sizes)} core/scoped files, "
          f"{sum(sizes.values())}/{TOTAL_LIMIT} characters; "
          f"largest {max(sizes.values())}/{RULE_LIMIT}; no local document expansion")
    return 0


if __name__ == "__main__":
    sys.exit(main())
