"""Reject toolchain drift and simulator selection across runtime versions."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import environment
from ios_simulator import select

ROOT = Path(__file__).resolve().parents[1]


class EnvironmentTests(unittest.TestCase):
    def test_wrong_java_is_rejected(self):
        with patch.object(environment, "output", return_value="java.runtime.version = 21.0.1+12"):
            with self.assertRaisesRegex(ValueError, "Java runtime: expected"):
                environment.check_java()

    def test_java_runtime_uses_full_version_instead_of_action_selector(self):
        runtime = environment.config()["java_runtime"]
        with patch.object(environment, "output", return_value=f"java.runtime.version = {runtime}"):
            environment.check_java()
        with patch.object(environment, "output", return_value="java.runtime.version = 17.0.20+1"):
            with self.assertRaises(ValueError):
                environment.check_java()

    def test_wrong_xcode_is_rejected_before_sdk_lookup(self):
        with patch.object(environment, "output", return_value="Xcode 26.6\nBuild version 17F113") as command:
            with self.assertRaisesRegex(ValueError, "Xcode: expected"):
                environment.check_ios()
            self.assertEqual(command.call_count, 1)

    def test_missing_android_sdk_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(environment, "check_java"), patch.dict(os.environ, ANDROID_HOME=directory):
                with self.assertRaisesRegex(ValueError, "Missing Android SDK package"):
                    environment.check_android()

    def test_make_ios_blocks_mismatch_before_simulator_and_build(self):
        with tempfile.TemporaryDirectory() as directory:
            commands = Path(directory)
            log = commands / "calls"
            for name in ("xcodebuild", "xcrun"):
                executable = commands / name
                executable.write_text(f'#!/bin/sh\necho "{name} $*" >> "$CALL_LOG"\n'
                                      'echo "Xcode 26.6"\necho "Build version 17F113"\n')
                executable.chmod(0o755)
            env = dict(os.environ, PATH=f"{commands}:{os.environ['PATH']}",
                       DEVELOPER_DIR=os.environ.get("DEVELOPER_DIR", "/Applications/Xcode.app/Contents/Developer"),
                       CALL_LOG=str(log))
            result = subprocess.run(["make", "ios-check"], cwd=ROOT, env=env, capture_output=True, text=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("Xcode: expected", result.stderr)
            self.assertEqual(log.read_text().splitlines(), ["xcodebuild -version"])

    def test_repository_declarations_match_the_pins(self):
        pins = environment.config()
        app = (ROOT / "apps/android/app/build.gradle.kts").read_text()
        self.assertIn(f'compileSdk = {pins["android_compile_sdk"]}', app)
        self.assertIn(f'buildToolsVersion = "{pins["android_build_tools"]}"', app)
        dockerfile = (ROOT / "services/api/Dockerfile").read_text()
        self.assertIn(f'FROM rust:{environment.rust_version()}-bookworm@sha256:', dockerfile)
        dev = (ROOT / "infra/dev/compose.yaml").read_text()
        ci = (ROOT / ".github/workflows/api-checks.yml").read_text()
        image = next(line.strip() for line in dev.splitlines() if "image: postgres:" in line)
        self.assertIn(image, ci)


class SimulatorTests(unittest.TestCase):
    RUNTIMES = [{"version": "26.4.1", "identifier": "com.apple.CoreSimulator.SimRuntime.iOS-26-4", "isAvailable": True}]

    def devices(self):
        return {
            "com.apple.CoreSimulator.SimRuntime.iOS-26-4": [
                {"name": "iPhone 17 Pro", "udid": "pinned", "state": "Shutdown", "isAvailable": True}],
            "com.apple.CoreSimulator.SimRuntime.iOS-27-0": [
                {"name": "iPhone 18 Pro", "udid": "different", "state": "Booted", "isAvailable": True}],
        }

    def test_booted_other_runtime_cannot_replace_pinned_runtime(self):
        self.assertEqual(select(self.devices(), "26.4.1", runtimes=self.RUNTIMES), "pinned")

    def test_explicit_wrong_runtime_device_is_rejected(self):
        for requested in ("different", "iPhone 18 Pro"):
            with self.assertRaises(ValueError):
                select(self.devices(), "26.4.1", requested, self.RUNTIMES)

    def test_missing_or_unavailable_pinned_runtime_is_rejected(self):
        with self.assertRaises(ValueError):
            select(self.devices(), "26.5", runtimes=self.RUNTIMES)
        devices = self.devices()
        devices["com.apple.CoreSimulator.SimRuntime.iOS-26-4"][0]["isAvailable"] = False
        with self.assertRaises(ValueError):
            select(devices, "26.4.1", runtimes=self.RUNTIMES)
