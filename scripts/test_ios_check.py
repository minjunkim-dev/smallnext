"""Exercise build/boot overlap and failure propagation through make ios-check."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
FAKE_TOOL = r'''
import json, os
from pathlib import Path
import sys, time
tool, args = Path(sys.argv[0]).name, sys.argv[1:]
root = Path(os.environ["PROBE"])
with (root / "calls").open("a") as output:
    output.write(json.dumps([tool, *args]) + "\n")
pins = json.loads(os.environ["PINS"])
def wait_for(name):
    for _ in range(200):
        if (root / name).exists():
            return
        time.sleep(0.01)
    sys.exit(90)
if tool == "xcodebuild":
    if args == ["-version"]:
        print(f'Xcode {pins["xcode"]}\nBuild version {pins["xcode_build"]}')
    elif "build-for-testing" in args:
        if "-destination" in args and "-arch" in args:
            print("destination implies architecture, architecture must not also be specified.", file=sys.stderr)
            sys.exit(70)
        wait_for("boot-started")
        (root / "build-started").touch()
        sys.exit(int(os.environ["BUILD_EXIT"]))
    elif "test-without-building" in args:
        assert (root / "build-started").exists()
        assert (root / "boot-finished").exists()
        sys.exit(int(os.environ["TEST_EXIT"]))
    else:
        sys.exit(91)
elif args[:1] == ["--sdk"]:
    print(pins["ios_sdk"])
elif args[1:3] == ["list", "devices"]:
    print(json.dumps({"devices": {"com.apple.CoreSimulator.SimRuntime.iOS-pinned": [
        {"name": "iPhone Fixture", "udid": "pinned-device", "state": "Shutdown"}]}}))
elif args[1:3] == ["list", "runtimes"]:
    print(json.dumps({"runtimes": [{"identifier": "com.apple.CoreSimulator.SimRuntime.iOS-pinned",
        "version": pins["ios_runtime"], "isAvailable": True}]}))
elif args[1:2] == ["bootstatus"]:
    (root / "boot-started").touch()
    wait_for("build-started")
    (root / "boot-finished").touch()
    sys.exit(int(os.environ["BOOT_EXIT"]))
else:
    sys.exit(92)
'''


class IOSCheckTests(unittest.TestCase):
    def run_check(self, build_exit=0, boot_exit=0, test_exit=0):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for tool in ("xcodebuild", "xcrun"):
                executable = root / tool
                executable.write_text(f"#!{sys.executable}\n" + FAKE_TOOL)
                executable.chmod(0o755)
            env = dict(os.environ, PATH=f"{root}:{os.environ['PATH']}", PROBE=str(root),
                       PINS=(ROOT / ".ci/toolchains.json").read_text(),
                       BUILD_EXIT=str(build_exit), BOOT_EXIT=str(boot_exit), TEST_EXIT=str(test_exit),
                       IOS_DERIVED_DATA=str(root / "derived"), IOS_PACKAGES_DIR=str(root / "packages"),
                       IOS_RESULTS=str(root / "results.xcresult"),
                       DEVELOPER_DIR=os.environ.get("DEVELOPER_DIR", "/Applications/Xcode.app/Contents/Developer"),
                       IOS_SIMULATOR_ID="pinned-device")
            result = subprocess.run(["make", "ios-check"], cwd=ROOT, env=env,
                                    capture_output=True, text=True, timeout=10)
            self.assertTrue((root / "calls").exists(), result.stdout + result.stderr)
            calls = [json.loads(line) for line in (root / "calls").read_text().splitlines()]
            return result, [call for call in calls if call[0] == "xcodebuild" and call[1:] != ["-version"]]

    def test_build_overlaps_boot_and_tests_reuse_outputs(self):
        result, calls = self.run_check()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(len(calls), 2)
        build, test = calls
        self.assertEqual(build[-1], "build-for-testing")
        self.assertIn("generic/platform=iOS Simulator", build)
        self.assertNotIn("-resultBundlePath", build)
        self.assertEqual(test[-1], "test-without-building")
        self.assertIn("platform=iOS Simulator,id=pinned-device", test)
        self.assertIn("-resultBundlePath", test)
        for flag in ("-derivedDataPath", "-clonedSourcePackagesDirPath"):
            self.assertEqual(build[build.index(flag) + 1], test[test.index(flag) + 1])
        self.assertIn("iOS build-for-testing:", result.stdout)
        self.assertIn("iOS test-without-building:", result.stdout)

    def test_build_and_boot_failures_block_testing(self):
        for build_exit, boot_exit in ((3, 0), (0, 4)):
            with self.subTest(build_exit=build_exit, boot_exit=boot_exit):
                result, calls = self.run_check(build_exit=build_exit, boot_exit=boot_exit)
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(len(calls), 1)
                self.assertEqual(calls[0][-1], "build-for-testing")

    def test_test_failure_propagates(self):
        result, calls = self.run_check(test_exit=5)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(calls[-1][-1], "test-without-building")


if __name__ == "__main__":
    unittest.main()
