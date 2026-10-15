import argparse
import hashlib
import io
import json
from pathlib import Path
import shlex
import subprocess
import tarfile
import tempfile
import unittest
from unittest.mock import patch

import deploy_production as deploy
from draft_release import ASSETS, digest


SOURCE = "a" * 40
VERSION = "v0.1.0-alpha.1"


def bundle(directory):
    config = json.dumps({"Labels": {"org.opencontainers.image.revision": SOURCE}}).encode()
    image_id = "sha256:" + hashlib.sha256(config).hexdigest()
    manifest = json.dumps([{"Config": "config.json", "RepoTags": ["smallnext-api:fixture"], "Layers": []}]).encode()
    with tarfile.open(directory / ASSETS[0], "w:gz") as archive:
        for name, value in (("manifest.json", manifest), ("config.json", config)):
            entry = tarfile.TarInfo(name)
            entry.size = len(value)
            archive.addfile(entry, io.BytesIO(value))
    metadata = {"version": VERSION, "source_sha": SOURCE, "artifact": "api-container",
                "image_id": image_id, "os": "linux", "architecture": "arm64", "docker_version": "28",
                "dependency_sha256": {name: "b" * 64 for name in
                    ("services/api/Cargo.lock", "services/api/Dockerfile", "rust-toolchain.toml")},
                "ci": [{"workflow": "project-checks.yml", "run_id": 1, "attempt": 1},
                       {"workflow": "repository-checks.yml", "run_id": 2, "attempt": 1}]}
    (directory / ASSETS[1]).write_text(json.dumps(metadata))
    (directory / ASSETS[2]).write_text("".join(f"{digest(directory / name)}  {name}\n" for name in ASSETS[:2]))
    return metadata


class DeployTests(unittest.TestCase):
    def args(self, directory):
        return argparse.Namespace(target="local", bundle=str(directory / "bundle"), version=VERSION,
                                  source_sha=SOURCE, deploy_dir=str(directory), env_file=str(directory / "private.env"),
                                  project_name="local-check", compose_override=None, ssh_host=None,
                                  migration_env_file=str(directory / "migration.env"),
                                  url="http://127.0.0.1:8080")

    def prepared(self, directory):
        (directory / "bundle").mkdir()
        (directory / "infra/production").mkdir(parents=True)
        migration = directory / "migration.env"
        migration.touch(mode=0o600)
        return bundle(directory / "bundle")

    def runner(self, metadata, *, enabled=False, label=SOURCE):
        def run(args, **kwargs):
            output = ""
            if "config" in args:
                output = json.dumps({"services": {"api": {"environment": {"USER_SERVER_AI": "1" if enabled else None}}}})
            elif args[:3] == ["docker", "image", "inspect"]:
                output = json.dumps([{"Id": metadata["image_id"], "Os": "linux", "Architecture": "arm64",
                                      "Config": {"Labels": {"org.opencontainers.image.revision": label}}}])
            elif args[:2] == ["docker", "run"]:
                output = "10001\n"
            elif "ps" in args:
                output = "test-container\n"
            elif args[:2] == ["docker", "inspect"]:
                output = metadata["image_id"]
            return subprocess.CompletedProcess(args, 0, output, "")
        return run

    def test_exact_image_starts_without_build_and_persists_private_pointer(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            metadata = self.prepared(directory)
            with patch.object(deploy, "command", side_effect=self.runner(metadata)) as run, \
                 patch.object(deploy, "response_status", side_effect=[200, 200, 200, 404]) as status, \
                 patch("sys.stdout", new_callable=io.StringIO):
                deploy.apply(self.args(directory), directory, metadata, ["smallnext-api:fixture"])
            up = next(call for call in run.call_args_list if "up" in call.args[0])
            self.assertEqual(up.args[0][-7:], ["up", "-d", "--no-build", "--pull", "never", "api", "caddy"])
            pointer = directory / "infra/production/.env.image"
            self.assertEqual(pointer.stat().st_mode & 0o777, 0o600)
            self.assertIn(metadata["image_id"][7:], pointer.read_text())
            self.assertEqual(up.args[0].count("--env-file"), 2)
            migrate = next(call for call in run.call_args_list if "migrate" in call.args[0])
            self.assertLess(run.call_args_list.index(migrate), run.call_args_list.index(up))
            self.assertEqual(migrate.args[0][-4:], ["--rm", "-T", "--no-deps", "migrate"])
            self.assertEqual(status.call_args_list[-1].args, ("http://127.0.0.1:8080/v1/suggestions", "POST"))

    def test_migration_failure_keeps_previous_pointer_and_stops_startup(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            metadata = self.prepared(directory)
            pointer = directory / "infra/production/.env.image"
            pointer.write_text("SMALLNEXT_API_IMAGE=previous\n")
            runner = self.runner(metadata)

            def fail(args, **kwargs):
                if args[-1] == "migrate":
                    raise RuntimeError("deployment command failed")
                return runner(args, **kwargs)

            with patch.object(deploy, "command", side_effect=fail) as run, self.assertRaises(RuntimeError):
                deploy.apply(self.args(directory), directory, metadata, ["smallnext-api:fixture"])
            self.assertFalse(any("up" in call.args[0] for call in run.call_args_list))
            self.assertEqual(pointer.read_text(), "SMALLNEXT_API_IMAGE=previous\n")

    def test_ai_on_and_wrong_source_stop_before_compose_up(self):
        for enabled, label in ((True, SOURCE), (False, "b" * 40)):
            with self.subTest(enabled=enabled), tempfile.TemporaryDirectory() as temporary:
                directory = Path(temporary)
                metadata = self.prepared(directory)
                with patch.object(deploy, "command", side_effect=self.runner(metadata, enabled=enabled, label=label)) as run:
                    with self.assertRaises(ValueError):
                        deploy.apply(self.args(directory), directory, metadata, ["smallnext-api:fixture"])
                self.assertFalse(any("up" in call.args[0] for call in run.call_args_list))
                if enabled:
                    self.assertFalse(any("load" in call.args[0] for call in run.call_args_list))

    def test_corrupt_bundle_is_rejected_before_docker(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            self.prepared(directory)
            (directory / "bundle" / ASSETS[0]).write_bytes(b"changed")
            with patch.object(deploy, "command") as run, self.assertRaises(ValueError):
                deploy.deploy(self.args(directory))
            run.assert_not_called()

    def test_existing_different_tag_prevents_image_load(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            metadata = self.prepared(directory)
            runner = self.runner(metadata)

            def conflict(args, **kwargs):
                if args[:3] == ["docker", "image", "inspect"]:
                    return subprocess.CompletedProcess(args, 0, json.dumps([{"Id": "sha256:" + "f" * 64}]), "")
                return runner(args, **kwargs)

            with patch.object(deploy, "command", side_effect=conflict) as run, self.assertRaises(ValueError):
                deploy.apply(self.args(directory), directory, metadata, ["smallnext-api:fixture"])
            self.assertFalse(any("load" in call.args[0] for call in run.call_args_list))

    def test_oci_index_must_reference_the_saved_config(self):
        for related in (True, False):
            with self.subTest(related=related), tempfile.TemporaryDirectory() as temporary:
                directory = Path(temporary)
                metadata = bundle(directory)
                with tarfile.open(directory / ASSETS[0]) as archive:
                    entries = [(member.name, archive.extractfile(member).read()) for member in archive]
                config_digest = metadata["image_id"] if related else "sha256:" + "f" * 64
                manifest = json.dumps({"config": {"digest": config_digest}}).encode()
                manifest_digest = "sha256:" + hashlib.sha256(manifest).hexdigest()
                index = json.dumps({"manifests": [{"digest": manifest_digest}]}).encode()
                metadata["image_id"] = "sha256:" + hashlib.sha256(index).hexdigest()
                entries += [("blobs/sha256/" + manifest_digest[7:], manifest),
                            ("blobs/sha256/" + metadata["image_id"][7:], index)]
                with tarfile.open(directory / ASSETS[0], "w:gz") as archive:
                    for name, value in entries:
                        member = tarfile.TarInfo(name)
                        member.size = len(value)
                        archive.addfile(member, io.BytesIO(value))
                if related:
                    self.assertEqual(deploy.archive_tags(directory, metadata), ["smallnext-api:fixture"])
                else:
                    with self.assertRaises(ValueError):
                        deploy.archive_tags(directory, metadata)

    def test_ssh_host_validation_and_remote_argv_quoting(self):
        for host in ("-oProxyCommand=bad", "host;echo bad", "user@host\ncommand"):
            with self.subTest(host=host), patch.object(deploy, "command") as run, self.assertRaises(ValueError):
                deploy.ssh(host, ["true"])
            run.assert_not_called()
        remote = ["python3", "/opt/a directory/script.py", "--env-file", "/safe/$(touch bad);x"]
        with patch.object(deploy, "command") as run:
            deploy.ssh("operator@server.example", remote)
        self.assertEqual(shlex.split(run.call_args.args[0][-1]), remote)

    def test_public_http_and_credential_origins_are_rejected(self):
        for url, local in (("http://example.com", True), ("http://localhost", False),
                           ("https://user:secret@example.com", False), ("https://example.com/path", False)):
            with self.subTest(url=url), self.assertRaises(ValueError):
                deploy.origin(url, local)
        self.assertEqual(deploy.origin("http://127.0.0.1:8080/", True), "http://127.0.0.1:8080")


if __name__ == "__main__":
    unittest.main()
