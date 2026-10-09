import os
from pathlib import Path
import subprocess
import unittest


class CrashlyticsSymbolsTests(unittest.TestCase):
    script = Path(__file__).resolve().parents[1] / "apps/ios/scripts/upload-crashlytics-symbols.sh"

    def test_default_build_needs_no_firebase_configuration(self):
        result = subprocess.run(["bash", str(self.script)], env={"PATH": os.defpath}, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, b"")

    def test_opt_in_without_build_metadata_fails_before_upload(self):
        result = subprocess.run(["bash", str(self.script)], env={"PATH": os.defpath,
                                "SMALLNEXT_UPLOAD_CRASHLYTICS_SYMBOLS": "YES"}, capture_output=True)
        self.assertNotEqual(result.returncode, 0)


if __name__ == "__main__":
    unittest.main()
