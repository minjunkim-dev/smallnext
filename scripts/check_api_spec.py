#!/usr/bin/env python3
"""Compare the committed OpenAPI document with the Rust-generated contract."""

import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def main():
    result = subprocess.run(
        ["cargo", "run", "--quiet", "--locked", "--manifest-path",
         str(ROOT / "services/api/Cargo.toml"), "--bin", "export-openapi"],
        cwd=ROOT, check=True, capture_output=True, text=True,
    )
    expected = json.loads((ROOT / "contracts/openapi.json").read_text())
    generated = json.loads(result.stdout)
    if expected != generated:
        print("FAIL: OpenAPI contract changed. Run make api-spec and review the diff.")
        return 1
    print("PASS: OpenAPI contract matches the API source.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
