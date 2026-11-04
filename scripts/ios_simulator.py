#!/usr/bin/env python3
"""Select an iPhone only from the repository's pinned simulator runtime."""

import json
import os
import subprocess
from environment import config

def select(devices, runtime, requested="", runtimes=()):
    keys = {item["identifier"] for item in runtimes
            if item.get("version") == runtime and item.get("isAvailable", False)
            and item["identifier"].startswith("com.apple.CoreSimulator.SimRuntime.iOS-")}
    if not keys:
        raise ValueError(f"Expected one available iOS {runtime} runtime; install it in Xcode.")
    # Xcode can ship a device-specific build of the same version (e.g. iOS-27-2-iPhone19-4 for
    # iPhone Duo). Stay on the shorter general runtime. A booted device there wins; otherwise
    # use that runtime's first iPhone. Fall back only when the general runtime has no match.
    chosen = []
    for key in sorted(keys, key=lambda identifier: (len(identifier), identifier)):
        group = [device for device in devices.get(key, [])
                 if device["name"].startswith("iPhone") and device.get("isAvailable", True)]
        if requested:
            group = [device for device in group if requested in (device["name"], device["udid"])]
        if group:
            chosen = group
            break
    if not chosen:
        raise ValueError(f"No matching iPhone simulator for iOS {runtime}. Install this runtime in Xcode.")
    return next((device for device in chosen if device["state"] == "Booted"), chosen[0])["udid"]


if __name__ == "__main__":
    try:
        data = json.loads(subprocess.check_output(
            ["xcrun", "simctl", "list", "devices", "available", "-j"], text=True))
        runtimes = json.loads(subprocess.check_output(
            ["xcrun", "simctl", "list", "runtimes", "-j"], text=True))["runtimes"]
        print(select(data["devices"], config()["ios_runtime"],
                     os.environ.get("IOS_SIMULATOR_ID") or os.environ.get("IOS_SIMULATOR", ""), runtimes))
    except ValueError as error:
        raise SystemExit(str(error))
