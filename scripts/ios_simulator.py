#!/usr/bin/env python3
"""Print an available iPhone simulator ID, preferring a booted simulator."""

import json
import subprocess

result = subprocess.check_output(
    ["xcrun", "simctl", "list", "devices", "available", "-j"], text=True,
)
devices = [
    device for group in json.loads(result)["devices"].values() for device in group
    if device["name"].startswith("iPhone")
]
if not devices:
    raise SystemExit("No iPhone simulator installed. Add one in Xcode.")
selected = next((device for device in devices if device["state"] == "Booted"), devices[0])
print(selected["udid"])
