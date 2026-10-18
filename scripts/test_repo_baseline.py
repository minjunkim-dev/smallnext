"""The copied repo-baseline files in this repository must match the manifest."""

import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from check_repo_baseline import MANIFEST, ROOT, drift


class RepoBaselineTests(unittest.TestCase):
    def test_this_repository_matches_the_manifest(self):
        self.assertEqual(drift(ROOT), [], "Edit shared files in repo-baseline, then re-apply them")

    def test_changed_missing_and_invalid_entries_are_reported(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / ".github").mkdir()
            (root / "a.py").write_text("print(1)\n")

            def write(files, commit="0" * 40):
                (root / MANIFEST).write_text(json.dumps({"source_commit": commit, "files": files}))

            good = hashlib.sha256(b"print(1)\n").hexdigest()
            write({"a.py": {"sha256": good}})
            self.assertEqual(drift(root), [])
            (root / "a.py").write_text("print(2)\n")
            write({"a.py": {"sha256": good}, "gone.py": {"sha256": good}})
            self.assertEqual(drift(root), ["a.py", "gone.py"])
            for bad in [{}, {"../x.py": {"sha256": good}}]:
                with self.subTest(files=bad):
                    write(bad)
                    with self.assertRaises(ValueError):
                        drift(root)
            write({"a.py": {"sha256": good}}, commit=None)
            with self.assertRaises(ValueError):
                drift(root)


if __name__ == "__main__":
    unittest.main()
