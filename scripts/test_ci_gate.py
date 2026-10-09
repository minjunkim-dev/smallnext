#!/usr/bin/env python3
"""Exercise the final workflow step with GitHub's needs/output result contract."""

import copy
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
import textwrap
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
PROJECTS = ("api", "container", "ios", "android")


def indented_block(text, header):
    # shortcut: block mappings/literal run only; use a YAML parser if syntax expands.
    match = re.search(rf"(?m)^( *){header} *(?:#.*)?$", text)
    if match is None:
        raise AssertionError(f"Missing workflow block: {header}")
    lines = []
    for line in text[match.end():].splitlines():
        if line.lstrip().startswith("#") and len(line) - len(line.lstrip()) <= len(match[1]):
            continue
        if line.strip() and not line.lstrip().startswith("#"):
            if len(line) - len(line.lstrip()) <= len(match[1]):
                break
        lines.append(line)
    return textwrap.dedent("\n".join(lines))


class GateTests(unittest.TestCase):
    def test_gate_display_name_and_indentation_do_not_affect_contract(self):
        workflow = (ROOT / ".github/workflows/project-checks.yml").read_text()
        renamed = workflow.replace("Check selected job results", "Validate selected jobs")
        reindented = textwrap.indent(renamed, "  ")
        for label, candidate in (("renamed", renamed), ("reindented", reindented)):
            with self.subTest(format=label), patch.object(Path, "read_text", return_value=candidate):
                self.assert_gate(self.needs(), True)
                needs = self.needs(["ios"])
                needs["ios"]["result"] = "skipped"
                self.assert_gate(needs, False)

    def test_gate_id_bounds_command_and_env_to_one_step(self):
        workflow = (ROOT / ".github/workflows/project-checks.yml").read_text()
        workflow = re.sub(
            r"(?m)^( *)- name: [^\n]+\n +id: check-selected-jobs *$",
            r"\1- id: check-selected-jobs\n\1  # The display name is optional.",
            workflow,
        )
        step_indent = re.search(r"(?m)^( *)- id: check-selected-jobs *$", workflow)[1]
        job_indent = re.search(r"(?m)^( *)project-checks: *$", workflow)[1]
        workflow += "\n" + textwrap.indent(
            "- name: Unrelated step\n  env:\n    NEEDS_JSON: invalid\n  run: |\n    exit 99\n",
            step_indent,
        )
        workflow += "\n" + textwrap.indent(
            "unrelated-job:\n  steps:\n    - id: check-selected-jobs\n      run: |\n        exit 99\n",
            job_indent,
        )
        with patch.object(Path, "read_text", return_value=workflow):
            self.assert_gate(self.needs(), True)
            needs = self.needs(["ios"])
            needs["ios"]["result"] = "failure"
            self.assert_gate(needs, False)

    def test_missing_or_duplicate_gate_id_is_rejected(self):
        workflow = (ROOT / ".github/workflows/project-checks.yml").read_text()
        step_indent = re.search(r"(?m)^( *)- \w+:.*$", indented_block(workflow, "project-checks:"))[1]
        job_indent = re.search(r"(?m)^( *)project-checks: *$", workflow)[1]
        for candidate in (
            re.sub(r"(?m)^ +id: check-selected-jobs *\n", "", workflow),
            workflow + "\n" + textwrap.indent(
                "- id: check-selected-jobs\n  run: |\n    exit 0\n", job_indent + "  " + step_indent,
            ),
        ):
            with patch.object(Path, "read_text", return_value=candidate), self.assertRaises(AssertionError):
                self.run_gate(self.needs())

    def test_missing_or_wrong_env_binding_is_rejected(self):
        workflow = (ROOT / ".github/workflows/project-checks.yml").read_text()
        for key in ("BASE_SHA", "CURRENT_SHA", "EVENT_NAME", "NEEDS_JSON"):
            binding = re.findall(rf"(?m)^ +{key}: .*$", workflow)[-1]
            indent = binding[:len(binding) - len(binding.lstrip())]
            for replacement in ("", f"{indent}{key}: ${{{{ github.ref }}}}"):
                candidate = workflow.replace(binding, replacement)
                with self.subTest(key=key, replacement=replacement):
                    with patch.object(Path, "read_text", return_value=candidate), self.assertRaises(AssertionError):
                        self.run_gate(self.needs())

    def test_missing_gate_invocation_breaks_failure_contract(self):
        workflow = (ROOT / ".github/workflows/project-checks.yml").read_text()
        workflow = re.sub(r'(?m)^( +)python3 "\$RUNNER_TEMP/trusted-ci-gate.py" *$', r"\1:", workflow)
        needs = self.needs(["ios"])
        needs["ios"]["result"] = "failure"
        with patch.object(Path, "read_text", return_value=workflow), self.assertRaises(AssertionError):
            self.assert_gate(needs, False)

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
        gate = indented_block(workflow, "project-checks:")
        steps = indented_block(gate, "steps:")
        candidates = [
            step for step in re.split(r"(?m)^(?=- )", steps)
            if re.search(r"(?m)^(?:- | +)id: check-selected-jobs *(?:#.*)?$", step)
        ]
        self.assertEqual(len(candidates), 1, "Expected one check-selected-jobs step")
        env_block = indented_block(candidates[0], "env:")
        command = indented_block(candidates[0], r"run: \|")
        bindings = dict(re.findall(r"^ *(\w+): \$\{\{ (.+?) \}\} *(?:#.*)?$", env_block, re.MULTILINE))
        self.assertEqual(bindings, {
            "BASE_SHA": "github.event.pull_request.base.sha || github.event.before || github.sha",
            "CURRENT_SHA": "github.sha",
            "EVENT_NAME": "github.event_name",
            "NEEDS_JSON": "toJSON(needs)",
        })
        env = os.environ.copy()
        env.update(BASE_SHA=base_sha, CURRENT_SHA=current_sha,
                   EVENT_NAME=event_name, NEEDS_JSON=json.dumps(needs))
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
