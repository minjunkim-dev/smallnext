#!/usr/bin/env python3
"""Exercise the final workflow step with GitHub's needs/output result contract."""

import copy
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
PROJECTS = ("api", "container", "ios", "android")


class GateTests(unittest.TestCase):
    def needs(self, selected=()):
        return {
            "scope": {
                "result": "success",
                "outputs": {project: "true" if project in selected else "false" for project in PROJECTS},
            },
            **{project: {"result": "success" if project in selected else "skipped"} for project in PROJECTS},
        }

    def run_gate(self, needs, base_sha="HEAD", cwd=ROOT, bootstrap_sha=None,
                 event_name="pull_request", current_sha="HEAD"):
        # Execute the actual gate step, so dropping an output binding or replacing
        # the helper with a permissive shell loop also breaks these tests.
        workflow = (ROOT / ".github/workflows/project-checks.yml").read_text()
        gate = workflow.split("\n  project-checks:\n", 1)[1]
        step = gate.split("      - name: Check selected job results\n", 1)[1]
        env_block, command = step.split("        run: |\n", 1)
        env = os.environ.copy()
        for key, expression in re.findall(r"^          (\w+): \$\{\{ (.+?) \}\}$", env_block, re.MULTILINE):
            if expression == "toJSON(needs)":
                env[key] = json.dumps(needs)
            elif key == "BASE_SHA":
                self.assertEqual(expression, "github.event.pull_request.base.sha || github.event.before || github.sha")
                env[key] = base_sha
            elif key == "CURRENT_SHA":
                self.assertEqual(expression, "github.sha")
                env[key] = current_sha
            elif key == "EVENT_NAME":
                self.assertEqual(expression, "github.event_name")
                env[key] = event_name
            else:
                self.assertTrue(expression.startswith("needs."), expression)
                value = needs
                for part in expression.split(".")[1:]:
                    value = value.get(part, {}) if isinstance(value, dict) else {}
                env[key] = value if isinstance(value, str) else ""
        command = "\n".join(line[10:] for line in command.splitlines())
        if bootstrap_sha is not None:
            command = command.replace("547fdc9bf908ed36d155259a83052102d7c139c3", bootstrap_sha)
        with tempfile.TemporaryDirectory() as runner_temp:
            env["RUNNER_TEMP"] = runner_temp
            return subprocess.run(
                ["bash", "-e", "-o", "pipefail", "-c", command], cwd=cwd, env=env,
                text=True, capture_output=True,
            )

    def test_pr_working_tree_cannot_replace_trusted_gate(self):
        needs = self.needs(["ios"])
        needs["ios"]["result"] = "failure"
        with tempfile.TemporaryDirectory() as clone:
            subprocess.run(["git", "clone", "--shared", "--quiet", str(ROOT), clone], check=True)
            (Path(clone) / "scripts/ci_gate.py").write_text("raise SystemExit(0)\n")
            result = self.run_gate(needs, cwd=clone)
            self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_first_adoption_uses_reviewed_helper(self):
        with tempfile.TemporaryDirectory() as clone:
            subprocess.run(["git", "clone", "--shared", "--quiet", str(ROOT), clone], check=True)
            bootstrap = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=clone, text=True).strip()
            subprocess.run(["git", "rm", "--quiet", "scripts/ci_gate.py"], cwd=clone, check=True)
            subprocess.run([
                "git", "-c", "user.name=gate-test", "-c", "user.email=gate-test@example.invalid",
                "-c", "commit.gpgsign=false", "commit", "--quiet", "-m", "test base without gate",
            ], cwd=clone, check=True)
            self.assertEqual(self.run_gate(self.needs(), cwd=clone, bootstrap_sha=bootstrap).returncode, 0)
            needs = self.needs(["ios"])
            needs["ios"]["result"] = "skipped"
            self.assertNotEqual(self.run_gate(needs, cwd=clone, bootstrap_sha=bootstrap).returncode, 0)
            # A first main push must work without the deleted PR's bootstrap object.
            for success in (True, False):
                candidate = self.needs() if success else needs
                result = self.run_gate(
                    candidate, cwd=clone, bootstrap_sha="missing-bootstrap",
                    event_name="push", current_sha=bootstrap,
                )
                self.assertEqual(result.returncode == 0, success, result.stdout + result.stderr)

    def test_invalid_base_commit_fails_closed(self):
        self.assertNotEqual(self.run_gate(self.needs(), "missing-base-commit").returncode, 0)

    def assert_gate(self, needs, success):
        result = self.run_gate(needs)
        self.assertEqual(result.returncode == 0, success, result.stdout + result.stderr)

    def test_intentionally_unselected_projects_pass_when_skipped(self):
        self.assert_gate(self.needs(), True)

    def test_each_selected_project_passes_only_after_success(self):
        for project in PROJECTS:
            with self.subTest(project=project):
                self.assert_gate(self.needs([project]), True)

    def test_selected_skipped_failure_cancelled_or_missing_result_fails(self):
        for project in PROJECTS:
            for result in ("skipped", "failure", "cancelled", "", "neutral"):
                with self.subTest(project=project, result=result):
                    needs = self.needs([project])
                    needs[project]["result"] = result
                    self.assert_gate(needs, False)

    def test_missing_selected_job_fails(self):
        needs = self.needs(["ios"])
        del needs["ios"]
        self.assert_gate(needs, False)

    def test_scope_failure_cancelled_skipped_or_missing_result_fails(self):
        for result in ("failure", "cancelled", "skipped", ""):
            with self.subTest(result=result):
                needs = self.needs()
                needs["scope"]["result"] = result
                self.assert_gate(needs, False)

    def test_every_scope_output_must_be_a_boolean_string(self):
        for project in PROJECTS:
            for output in ("", "True", "FALSE", "yes", True, None):
                with self.subTest(project=project, output=output):
                    needs = self.needs()
                    needs["scope"]["outputs"][project] = output
                    self.assert_gate(needs, False)

    def test_missing_scope_outputs_fail(self):
        baseline = self.needs()
        for project in PROJECTS:
            with self.subTest(project=project):
                needs = copy.deepcopy(baseline)
                del needs["scope"]["outputs"][project]
                self.assert_gate(needs, False)
        del baseline["scope"]["outputs"]
        self.assert_gate(baseline, False)

    def test_unselected_failed_or_cancelled_job_fails(self):
        for result in ("failure", "cancelled"):
            with self.subTest(result=result):
                needs = self.needs()
                needs["api"]["result"] = result
                self.assert_gate(needs, False)

    def test_unselected_success_is_not_an_intentional_skip(self):
        needs = self.needs()
        needs["api"]["result"] = "success"
        self.assert_gate(needs, False)


if __name__ == "__main__":
    unittest.main()
