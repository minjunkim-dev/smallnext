#!/usr/bin/env python3
"""Exercise the iOS command boundary with stand-ins for external tool binaries."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class IOSCommandTests(unittest.TestCase):
    def invoke(self, codeql):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name in ["python3", "xcrun", "xcodebuild"]:
                tool = root / name
                tool.write_text(f"#!{sys.executable}\n" + "import json, os, pathlib, sys\n" +
                                "name = pathlib.Path(sys.argv[0]).name\n" +
                                "if name == 'python3' and sys.argv[1].endswith('ios_simulator.py'): print('test-simulator')\n" +
                                "if name == 'xcodebuild': pathlib.Path(os.environ['ARGUMENT_LOG']).write_text(json.dumps(sys.argv[1:]))\n")
                tool.chmod(0o755)
            env = dict(os.environ, PATH=f"{root}:/usr/bin:/bin", DEVELOPER_DIR="/mock/Xcode",
                       ARGUMENT_LOG=str(root / "args.json"), IOS_CODEQL_ANALYSIS=str(codeql).lower(),
                       IOS_PACKAGES_DIR=str(root / "packages with spaces"),
                       IOS_DERIVED_DATA=str(root / "derived"), IOS_RESULTS=str(root / "results.xcresult"))
            subprocess.run(["/bin/bash", str(ROOT / "scripts/check_ios.sh")], env=env,
                           cwd=ROOT, check=True, capture_output=True, text=True)
            return json.loads((root / "args.json").read_text())

    def test_codeql_disables_driver_and_caches_without_changing_regular_build(self):
        flags = {"SWIFT_USE_INTEGRATED_DRIVER=NO", "COMPILATION_CACHE_ENABLE_CACHING=NO", "SWIFT_ENABLE_COMPILE_CACHE=NO"}
        for enabled in [False, True]:
            args = self.invoke(enabled)
            self.assertEqual(flags.intersection(args), flags if enabled else set())
            self.assertIn("CODE_SIGNING_ALLOWED=NO", args)
            self.assertIn("-onlyUsePackageVersionsFromResolvedFile", args)
            self.assertEqual(args[-1], "test")
            self.assertTrue(args[args.index("-clonedSourcePackagesDirPath") + 1].endswith("packages with spaces"))


if __name__ == "__main__":
    unittest.main()
