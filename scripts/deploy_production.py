#!/usr/bin/env python3
"""Load a verified draft image and start production compose with server AI OFF."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request

from draft_release import ASSETS, verify


ROOT = Path(__file__).resolve().parents[1]
SNAPSHOT = (
    "infra/production/compose.yaml", "infra/production/Caddyfile",
    "infra/production/captcha/index.html", "infra/production/captcha/bridge.js",
    "infra/production/captcha/style.css", "infra/production/tls/README.md",
    "infra/production/systemd/smallnext-backup-ai-budget.service",
    "infra/production/systemd/smallnext-backup-ai-budget.timer",
    "scripts/backup_ai_budget.py",
    "infra/production/systemd/smallnext-purge-ai-budget.service",
    "infra/production/systemd/smallnext-purge-ai-budget.timer",
    "scripts/deploy_production.py", "scripts/draft_release.py", "scripts/trusted_ci.py",
    "scripts/ci_scope.py", "scripts/review_context.py",
)


def command(args, *, env=None, input_stream=None, check=True):
    result = subprocess.run(args, env=env, stdin=input_stream, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, text=True, timeout=180)
    if check and result.returncode:
        raise RuntimeError("deployment command failed")
    return result


def origin(value, local):
    parsed = urllib.parse.urlsplit(value)
    if (not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment
            or parsed.path not in ("", "/") or parsed.port == 0
            or (parsed.scheme != "https" and not
                (local and parsed.scheme == "http" and parsed.hostname in ("localhost", "127.0.0.1", "::1")))):
        raise ValueError("use an HTTPS origin; local checks may use loopback HTTP")
    return value.rstrip("/")


def ssh(host, args, *, input_stream=None):
    if not re.fullmatch(r"(?:[A-Za-z_][A-Za-z0-9_.-]*@)?[A-Za-z0-9][A-Za-z0-9.-]*", host or ""):
        raise ValueError("use an SSH host or user@host; configure ports in SSH config")
    return command(["ssh", "-o", "BatchMode=yes", "-T", "--", host, shlex.join(args)],
                   input_stream=input_stream)


def archive_tags(directory, metadata):
    with tarfile.open(directory / ASSETS[0], "r:gz") as archive:
        manifest_file = archive.getmember("manifest.json")
        if not manifest_file.isfile() or manifest_file.size > 1024 * 1024:
            raise ValueError("image manifest is too large")
        manifest = json.load(archive.extractfile(manifest_file))
        if not isinstance(manifest, list) or len(manifest) != 1 or not isinstance(manifest[0], dict):
            raise ValueError("the draft must contain one image")
        entry = manifest[0]
        config_file = archive.getmember(entry["Config"])
        if not config_file.isfile() or config_file.size > 1024 * 1024:
            raise ValueError("image config is too large")
        image_id = "sha256:" + hashlib.sha256(archive.extractfile(config_file).read()).hexdigest()

        def references_config(digest, depth=0):
            if depth > 4 or not isinstance(digest, str) or not re.fullmatch(r"sha256:[0-9a-f]{64}", digest):
                return False
            member = archive.getmember("blobs/sha256/" + digest[7:])
            if not member.isfile() or member.size > 1024 * 1024:
                return False
            raw = archive.extractfile(member).read()
            if "sha256:" + hashlib.sha256(raw).hexdigest() != digest:
                return False
            document = json.loads(raw)
            if not isinstance(document, dict):
                return False
            config = document.get("config")
            if isinstance(config, dict) and config.get("digest") == image_id:
                return True
            descriptors = document.get("manifests", [])
            return (isinstance(descriptors, list) and len(descriptors) <= 32 and
                    any(isinstance(item, dict) and references_config(item.get("digest", ""), depth + 1)
                        for item in descriptors))

        # Docker's containerd store can identify the image by its OCI index rather than config digest.
        if image_id != metadata["image_id"] and not references_config(metadata["image_id"]):
            raise ValueError("archive image ID differs from metadata")
        tags = entry.get("RepoTags")
        if not isinstance(tags, list) or not tags or any(
                not isinstance(tag, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:/-]*", tag)
                for tag in tags):
            raise ValueError("image tags are missing or invalid")
        return tags


def response_status(url, method):
    # Redirects must not change the origin being checked.
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, req, fp, code, msg, headers, newurl):
            return None
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
    try:
        with opener.open(urllib.request.Request(url, method=method), timeout=3) as response:
            return response.status
    except urllib.error.HTTPError as error:
        return error.code


def apply(args, directory, metadata, tags):
    image = "smallnext-api:release-" + metadata["image_id"].removeprefix("sha256:")
    migration_file = Path(args.migration_env_file)
    if (migration_file.is_symlink() or not migration_file.is_file()
            or migration_file.stat().st_mode & 0o077):
        raise ValueError("use a private migration environment file with mode 0600")
    env = dict(os.environ, SMALLNEXT_API_IMAGE=image, MIGRATION_ENV_FILE=str(migration_file))
    compose = ["docker", "compose", "--project-name", args.project_name, "--env-file", args.env_file,
               "-f", str(directory / "infra/production/compose.yaml")]
    pointer = directory / "infra/production/.env.image"
    had_pointer = pointer.exists()
    if had_pointer:
        compose[compose.index("-f"):compose.index("-f")] = ["--env-file", str(pointer)]
    if args.compose_override:
        compose += ["-f", str(Path(args.compose_override).resolve())]
    configured = json.loads(command(compose + ["config", "--format", "json"], env=env).stdout)
    if configured["services"]["api"]["environment"].get("USER_SERVER_AI") == "1":
        raise ValueError("this deployment step requires server AI OFF; activation belongs to #47")
    for tag in tags:
        existing = command(["docker", "image", "inspect", tag], check=False)
        if existing.returncode == 0 and json.loads(existing.stdout)[0]["Id"] != metadata["image_id"]:
            raise ValueError("archive tag conflicts with an existing image; preserve it before loading")
    command(["docker", "image", "load", "--input", str(directory / "bundle" / ASSETS[0])])
    actual = json.loads(command(["docker", "image", "inspect", metadata["image_id"]]).stdout)[0]
    if (actual["Id"] != metadata["image_id"] or actual.get("Os") != metadata["os"]
            or actual.get("Architecture") != metadata["architecture"]
            or (actual.get("Config", {}).get("Labels") or {}).get("org.opencontainers.image.revision") != args.source_sha):
        raise ValueError("loaded image identity or source label mismatch")
    if command(["docker", "run", "--rm", "--entrypoint", "id", metadata["image_id"], "-u"]).stdout.strip() != "10001":
        raise ValueError("runtime user differs from the draft image contract")
    command(["docker", "image", "tag", metadata["image_id"], image])
    # Only this one-shot service receives the schema owner's connection URL.
    command(compose + ["run", "--rm", "-T", "--no-deps", "migrate"], env=env)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", dir=pointer.parent, delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(f"SMALLNEXT_API_IMAGE={image}\n")
        os.replace(temporary, pointer)
    finally:
        if temporary and temporary.exists():
            temporary.unlink()
    if not had_pointer:
        compose[compose.index("-f"):compose.index("-f")] = ["--env-file", str(pointer)]
    command(compose + ["up", "-d", "--no-build", "--pull", "never", "api", "caddy"], env=env)
    container = command(compose + ["ps", "--quiet", "api"], env=env).stdout.strip()
    if command(["docker", "inspect", "--format", "{{.Image}}", container]).stdout.strip() != metadata["image_id"]:
        raise ValueError("running API image differs from the verified draft")
    deadline = time.monotonic() + 60
    while True:
        try:
            if response_status(args.url + "/ready", "GET") == 200:
                break
        except (OSError, urllib.error.URLError):
            pass
        if time.monotonic() >= deadline:
            raise RuntimeError("deployed API readiness check failed")
        time.sleep(0.5)
    for path, method, expected in (("/health", "GET", 200), ("/ready", "GET", 200),
                                   ("/v1/suggestions", "POST", 404)):
        if response_status(args.url + path, method) != expected:
            raise RuntimeError("deployed API status check failed")
        print(f"PASS {method} {path} = {expected}")
    print("Deployment completed with server AI OFF; verified image ID and source label")


def deploy(args):
    args.url = origin(args.url, args.target == "local")
    if not re.fullmatch(r"[a-z0-9][a-z0-9_-]*", args.project_name):
        raise ValueError("invalid compose project name")
    if any(not Path(value).is_absolute() or any(char in value for char in "\r\n\0")
           for value in (args.deploy_dir, args.env_file, args.migration_env_file)):
        raise ValueError("use absolute deployment and environment file paths")
    bundle = Path(args.bundle).resolve()
    metadata = verify(bundle, args.version, args.source_sha)
    tags = archive_tags(bundle, metadata)
    files = {name: ROOT / name for name in SNAPSHOT}
    files.update({"bundle/" + name: bundle / name for name in ASSETS})
    if args.target == "ssh":
        if args.compose_override:
            raise ValueError("compose overrides are only supported for local checks")
        # Only fixed snapshot names enter this tar; the Docker archive is never extracted here.
        ssh(args.ssh_host, ["mkdir", "-p", "--", args.deploy_dir])
        with tempfile.TemporaryFile() as transfer:
            with tarfile.open(fileobj=transfer, mode="w") as archive:
                for name, source in files.items():
                    archive.add(source, arcname=name, recursive=False)
            transfer.seek(0)
            ssh(args.ssh_host, ["tar", "--extract", "--file", "-", "--directory", args.deploy_dir,
                                "--no-same-owner"], input_stream=transfer)
        remote = ["python3", str(Path(args.deploy_dir) / "scripts/deploy_production.py"),
                  "--target", "local", "--bundle", str(Path(args.deploy_dir) / "bundle"),
                  "--version", args.version, "--source-sha", args.source_sha,
                  "--deploy-dir", args.deploy_dir, "--env-file", args.env_file,
                  "--migration-env-file", args.migration_env_file,
                  "--url", args.url, "--project-name", args.project_name]
        # The remote program emits only fixed status messages; never relay arbitrary SSH output.
        ssh(args.ssh_host, remote)
        print("Remote deployment passed: health=200 ready=200 suggestions=404; server AI OFF")
    else:
        directory = Path(args.deploy_dir)
        for name, source in files.items():
            destination = directory / name
            destination.parent.mkdir(parents=True, exist_ok=True)
            if source.resolve() != destination.resolve():
                shutil.copyfile(source, destination)
        # Verify the staged bytes again before Docker consumes them.
        staged = verify(directory / "bundle", args.version, args.source_sha)
        apply(args, directory, staged, archive_tags(directory / "bundle", staged))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target", choices=("local", "ssh"), required=True)
    parser.add_argument("--bundle", required=True)
    parser.add_argument("--version", required=True)
    parser.add_argument("--source-sha", required=True)
    parser.add_argument("--deploy-dir", required=True)
    parser.add_argument("--env-file", required=True)
    parser.add_argument("--migration-env-file", required=True)
    parser.add_argument("--url", required=True)
    parser.add_argument("--ssh-host")
    parser.add_argument("--project-name", default="smallnext")
    parser.add_argument("--compose-override")
    try:
        deploy(parser.parse_args())
    except (AssertionError, KeyError, OSError, RuntimeError, ValueError, TypeError,
            tarfile.TarError, subprocess.TimeoutExpired):
        # Paths, command output, URLs and exceptions can contain private settings.
        print("Deployment failed; inspect settings locally. No automatic rollback was performed.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
