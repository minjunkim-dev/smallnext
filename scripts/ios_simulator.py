#!/usr/bin/env python3
"""Select an iPhone only from the repository's pinned simulator runtime."""

import json
import os
import subprocess
from environment import config

def select(devices, runtime, requested=""):
    key = "com.apple.CoreSimulator.SimRuntime.iOS-" + runtime.replace(".", "-")
    available = [device for device in devices.get(key, [])
                 if device["name"].startswith("iPhone") and device.get("isAvailable", True)]
    if requested:
        available = [device for device in available
                     if requested in (device["name"], device["udid"])]
    if not available:
        raise ValueError(f"No matching iPhone simulator for iOS {runtime}. Install this runtime in Xcode.")
    return next((device for device in available if device["state"] == "Booted"), available[0])["udid"]


if __name__ == "__main__":
    try:
        data = json.loads(subprocess.check_output(
            ["xcrun", "simctl", "list", "devices", "available", "-j"], text=True))
        print(select(data["devices"], config()["ios_runtime"],
                     os.environ.get("IOS_SIMULATOR_ID") or os.environ.get("IOS_SIMULATOR", "")))
    except ValueError as error:
        raise SystemExit(str(error))
