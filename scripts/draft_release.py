#!/usr/bin/env python3
"""Build evidence and publish only new, private API container drafts."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys

from trusted_ci import PROJECT_JOBS, pages, require, sha, timestamp

REPO = "minjunkim-dev/smallnext"
ASSETS = ("smallnext-api-image.tar.gz", "metadata.json", "SHA256SUMS")


def command(*args):
    return subprocess.check_output(args, text=True).strip()


def get(endpoint):
    return json.loads(command("gh", "api", f"repos/{REPO}" + (f"/{endpoint}" if endpoint else "")))


def inputs(version, source):
    require(isinstance(version, str) and len(version) < 80 and
            re.fullmatch(r"v(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)-alpha\.[1-9][0-9]*", version),
            "Use vMAJOR.MINOR.PATCH-alpha.N")
    return version, sha(source)


def check_ci(source, api):
    evidence = []
    required = {"project-checks.yml": {"scope", "Project checks"} |
                {name for names in PROJECT_JOBS.values() for name in names},
                "repository-checks.yml": {"Repository hygiene"}}
    for filename, expected in required.items():
        workflow = api(f"actions/workflows/{filename}")
        require(workflow["path"] == f".github/workflows/{filename}" and workflow["state"] == "active",
                "Unexpected or inactive CI workflow")
        runs = pages(api, f"actions/workflows/{workflow['id']}/runs?head_sha={source}&branch=main", "workflow_runs")
        runs = [run for run in runs if run["event"] in ("push", "workflow_dispatch")]
        require(runs, "No trusted main CI run for source")
        run = api(f"actions/runs/{max(runs, key=lambda item: item['id'])['id']}")
        require(run["workflow_id"] == workflow["id"] and run["path"] in
                (workflow["path"], f"{workflow['path']}@main", f"{workflow['path']}@refs/heads/main",
                 f"{workflow['path']}@{source}") and
                run["head_sha"] == source and run["head_branch"] == "main" and
                run["event"] in ("push", "workflow_dispatch") and
                run["head_repository"]["full_name"] == REPO and
                run["status"] == "completed" and run["conclusion"] == "success", "CI identity or result mismatch")
        jobs = pages(api, f"actions/runs/{run['id']}/attempts/{run['run_attempt']}/jobs", "jobs")
        require(len(jobs) == len(expected) and {job["name"] for job in jobs} == expected,
                "CI job inventory mismatch; run full Project checks on source")
        for job in jobs:
            require(job["run_id"] == run["id"] and job["run_attempt"] == run["run_attempt"] and
                    job["head_sha"] == source and job["status"] == "completed" and job["conclusion"] == "success" and
                    timestamp(job["started_at"]) >= timestamp(run["run_started_at"]) and
                    timestamp(job["completed_at"]) >= timestamp(job["started_at"]),
                    "CI job failed, skipped, cancelled, missing or copied from an older attempt")
        fresh = api(f"actions/runs/{run['id']}")
        require(fresh["run_attempt"] == run["run_attempt"] and fresh["conclusion"] == "success" and
                fresh["status"] == "completed", "CI changed during validation")
        evidence.append({"workflow": filename, "run_id": run["id"], "attempt": run["run_attempt"]})
    return evidence


def check_source(source, api):
    require(api("")["default_branch"] == "main", "Default branch changed")
    comparison = api(f"compare/{source}...main")
    require(comparison["status"] in ("ahead", "identical") and
            comparison["merge_base_commit"]["sha"] == source, "Source is not contained in main")


def preflight(version, source, api=get):
    inputs(version, source)
    check_source(source, api)
    releases = pages(api, "releases")
    require(not any(item["tag_name"] == version for item in releases), "Release or Draft already exists")
    refs = api(f"git/matching-refs/tags/{version}")
    require(not any(item["ref"] == f"refs/tags/{version}" for item in refs), "Tag already exists")
    return check_ci(source, api), releases


def digest(path):
    result = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            result.update(chunk)
    return result.hexdigest()


def package(directory, version, source):
    inputs(version, source)
    require(command("git", "rev-parse", "HEAD") == source, "Build checkout does not match source")
    require(not command("git", "status", "--porcelain", "--untracked-files=no"), "Build checkout is dirty")
    require((directory / ASSETS[0]).is_file(), "Container archive is missing")
    image = json.loads(command("docker", "image", "inspect", "smallnext-api:ci"))[0]
    require(image["Config"]["Labels"]["org.opencontainers.image.revision"] == source,
            "Container source label mismatch")
    metadata = {"version": version, "source_sha": source, "artifact": "api-container",
                "image_id": image["Id"], "os": image["Os"], "architecture": image["Architecture"],
                "docker_version": command("docker", "version", "--format", "{{.Server.Version}}"),
                "dependency_sha256": {name: digest(Path(name)) for name in
                    ("services/api/Cargo.lock", "services/api/Dockerfile", "rust-toolchain.toml")},
                "ci": check_ci(source, get)}
    (directory / ASSETS[1]).write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")
    (directory / ASSETS[2]).write_text("".join(f"{digest(directory / name)}  {name}\n" for name in ASSETS[:2]), encoding="utf-8")


def verify(directory, version, source):
    inputs(version, source)
    require({path.name for path in directory.iterdir()} == set(ASSETS), "Unexpected or missing assets")
    require(all((directory / name).is_file() and not (directory / name).is_symlink() for name in ASSETS),
            "Assets must be regular files")
    checksums = (directory / ASSETS[2]).read_text(encoding="utf-8")
    require(checksums == "".join(f"{digest(directory / name)}  {name}\n" for name in ASSETS[:2]),
            "Artifact checksum mismatch")
    metadata = json.loads((directory / ASSETS[1]).read_text(encoding="utf-8"))
    require(isinstance(metadata, dict) and metadata.get("version") == version and
            metadata.get("source_sha") == source and metadata.get("artifact") == "api-container",
            "Artifact metadata mismatch")
    require(isinstance(metadata.get("image_id"), str) and
            re.fullmatch(r"sha256:[0-9a-f]{64}", metadata["image_id"]) and
            metadata.get("os") == "linux" and metadata.get("architecture") in ("amd64", "arm64") and
            isinstance(metadata.get("docker_version"), str) and metadata["docker_version"].strip(),
            "Container build metadata missing or invalid")
    dependencies = metadata.get("dependency_sha256")
    require(isinstance(dependencies, dict) and set(dependencies) ==
            {"services/api/Cargo.lock", "services/api/Dockerfile", "rust-toolchain.toml"} and
            all(isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value)
                for value in dependencies.values()), "Dependency evidence missing or invalid")
    evidence = metadata.get("ci")
    require(isinstance(evidence, list) and len(evidence) == 2 and
            all(isinstance(item, dict) and isinstance(item.get("workflow"), str) and
                type(item.get("run_id")) is int and item["run_id"] > 0 and
                type(item.get("attempt")) is int and item["attempt"] > 0 for item in evidence) and
            {item.get("workflow") for item in evidence} == {"project-checks.yml", "repository-checks.yml"} and
            len({item["run_id"] for item in evidence}) == 2, "CI evidence missing or invalid")
    return metadata


def publish(directory, version, source, api=get, run=command):
    verify(directory, version, source)
    _, previous = preflight(version, source, api)
    # No overwrite, cleanup, public toggle, product execution or dependency install in this job.
    # gh create uploads to its returned release ID; a second tag lookup can select a concurrent replacement.
    created_url = run("gh", "release", "create", version, *(str(directory / name) for name in ASSETS),
                      "--repo", REPO, "--draft", "--prerelease", "--target", source,
                      "--title", f"Smallnext API {version}", "--notes",
                      f"Private API container verification. Source: {source}")
    matches = [item for item in pages(api, "releases") if item["tag_name"] == version]
    require(len(matches) == 1 and matches[0]["html_url"] == created_url, "New Draft identity mismatch")
    release = matches[0]
    require(release["draft"] is True and release["prerelease"] is True and release["target_commitish"] == source,
            "New release is not the requested private Draft")
    current = api(f"releases/{release['id']}")
    require(current["draft"] is True and current["prerelease"] is True and
            current["target_commitish"] == source and current["tag_name"] == version, "Draft changed during upload")
    assets = pages(api, f"releases/{release['id']}/assets")
    require(len(assets) == len(ASSETS) and {item["name"] for item in assets} == set(ASSETS), "Asset inventory mismatch")
    for asset in assets:
        path = directory / asset["name"]
        require(asset["size"] == path.stat().st_size and asset["state"] == "uploaded", "Asset upload incomplete")
        if asset.get("digest"):
            require(asset["digest"] == f"sha256:{digest(path)}", "GitHub asset digest mismatch")
    after = pages(api, "releases")
    require(all(any(item == old for item in after) for old in previous), "Existing Release changed")
    final = [item for item in after if item["tag_name"] == version]
    require(len(final) == 1 and final[0]["id"] == release["id"] and
            final[0]["draft"] is True and final[0]["prerelease"] is True and
            final[0]["target_commitish"] == source, "Draft changed during verification")
    # GitHub cannot atomically lock main, CI and tag creation with Release creation.
    require(not any(item["ref"] == f"refs/tags/{version}" for item in api(f"git/matching-refs/tags/{version}")),
            "A concurrent tag appeared; inspect the private Draft")
    check_source(source, api)
    check_ci(source, api)
    print(json.dumps({"release_id": release["id"], "draft": True, "source_sha": source}))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=("preflight", "package", "verify", "publish"))
    parser.add_argument("--directory", type=Path)
    args = parser.parse_args()
    version, source = inputs(os.environ["DRAFT_VERSION"], os.environ["SOURCE_SHA"])
    if args.mode == "preflight":
        print(json.dumps(preflight(version, source)[0]))
    else:
        require(args.directory is not None, "Artifact directory required")
        {"package": package, "verify": verify, "publish": publish}[args.mode](args.directory, version, source)


if __name__ == "__main__":
    try:
        main()
    except (ValueError, KeyError, OSError, subprocess.CalledProcessError) as error:
        print(f"FAIL: {error}", file=sys.stderr)
        sys.exit(1)
