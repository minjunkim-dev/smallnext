#!/usr/bin/env python3
"""Exercise the final workflow step with GitHub's needs/output result contract."""

import copy
import json
import os
from pathlib import Path
import re
import subprocess
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

    def run_gate(self, needs):
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
            else:
                self.assertTrue(expression.startswith("needs."), expression)
                value = needs
                for part in expression.split(".")[1:]:
                    value = value.get(part, {}) if isinstance(value, dict) else {}
                env[key] = value if isinstance(value, str) else ""
        command = "\n".join(line[10:] for line in command.splitlines())
        return subprocess.run(
            ["bash", "-e", "-o", "pipefail", "-c", command], cwd=ROOT, env=env,
            text=True, capture_output=True,
        )

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
