"""Exercise production compose with an isolated PostgreSQL and synthetic settings."""
import argparse
import gzip
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
import uuid

ROOT = Path(__file__).resolve().parents[1]
AI_SETTINGS = (
    "USER_SERVER_AI", "SUPABASE_URL", "AI_ALLOWED_SUPABASE_UIDS",
    "SUPABASE_PUBLISHABLE_KEY", "AI_MODEL_CONFIRMED", "ANTHROPIC_API_KEY",
    "AI_MODEL_CONTEXT_TOKENS", "AI_MAX_OUTPUT_TOKENS",
    "AI_INPUT_MICRO_USD_PER_MILLION", "AI_OUTPUT_MICRO_USD_PER_MILLION",
    "AI_BUDGET_MICRO_USD", "AI_DAILY_BUDGET_MICRO_USD", "AI_USER_DAILY_REQUESTS",
    "AI_PUBLIC_ACCESS", "AI_USAGE_HASH_KEY",
)
DATABASE_URL = "postgres://smallnext:smallnext-local-only@postgres:5432/smallnext"


def run(command, env, *, timeout=120, check=True):
    result = subprocess.run(command, cwd=ROOT, env=env, capture_output=True,
                            text=True, timeout=timeout)
    if check and result.returncode:
        # Container output may contain credentials. Report only the operation's exit status.
        raise RuntimeError(f"container check command failed (exit {result.returncode})")
    return result


def status(url, method="GET"):
    try:
        request = urllib.request.Request(url, method=method, headers={"Host": "localhost"})
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open(request, timeout=2) as response:
            return response.status
    except urllib.error.HTTPError as error:
        return error.code


def deploy_fixture(image, project, temporary, override, empty_env, address, env, cleanup_images):
    from draft_release import ASSETS, digest

    source = run(["git", "rev-parse", "HEAD"], env).stdout.strip()
    tag = "smallnext-api:deploy-smoke-" + uuid.uuid4().hex[:12]
    cleanup_images.append(tag)
    container = "smallnext-deploy-fixture-" + uuid.uuid4().hex[:12]
    run(["docker", "create", "--name", container, image], env)
    try:
        run(["docker", "commit", "--change", "LABEL org.opencontainers.image.revision=" + source, container, tag], env)
    finally:
        run(["docker", "rm", "--force", container], env)
    built = json.loads(run(["docker", "image", "inspect", tag], env).stdout)[0]
    cleanup_images.append("smallnext-api:release-" + built["Id"].removeprefix("sha256:"))
    bundle = temporary / "draft-bundle"
    bundle.mkdir()
    archive = temporary / "image.tar"
    run(["docker", "image", "save", "--output", str(archive), tag], env)
    with archive.open("rb") as raw, (bundle / ASSETS[0]).open("wb") as compressed:
        with gzip.GzipFile(fileobj=compressed, mode="wb", mtime=0) as zipped:
            shutil.copyfileobj(raw, zipped)
    archive.unlink()
    metadata = {"version": "v0.0.0-alpha.1", "source_sha": source, "artifact": "api-container",
                "image_id": built["Id"], "os": built["Os"], "architecture": built["Architecture"],
                "docker_version": run(["docker", "version", "--format", "{{.Server.Version}}"], env).stdout.strip(),
                "dependency_sha256": {name: digest(ROOT / name) for name in
                    ("services/api/Cargo.lock", "services/api/Dockerfile", "rust-toolchain.toml")},
                "ci": [{"workflow": "project-checks.yml", "run_id": 1, "attempt": 1},
                       {"workflow": "repository-checks.yml", "run_id": 2, "attempt": 1}]}
    (bundle / ASSETS[1]).write_text(json.dumps(metadata))
    (bundle / ASSETS[2]).write_text("".join(f"{digest(bundle / name)}  {name}\n" for name in ASSETS[:2]))
    deployed = temporary / "deployed"
    result = run([sys.executable, str(ROOT / "scripts/deploy_production.py"), "--target", "local",
                  "--bundle", str(bundle), "--version", metadata["version"], "--source-sha", source,
                  "--deploy-dir", str(deployed), "--env-file", str(empty_env), "--project-name", project,
                  "--migration-env-file", env["MIGRATION_ENV_FILE"],
                  "--compose-override", str(override), "--url", "http://" + address.replace("127.0.0.1", "localhost")], env)
    print(result.stdout.strip())
    pointer = deployed / "infra/production/.env.image"
    selected = pointer.read_text().strip().split("=", 1)[1]
    scheduler_env = dict(env)
    scheduler_env.pop("SMALLNEXT_API_IMAGE", None)
    scheduler_compose = ["docker", "compose", "--project-name", project,
                         "--env-file", str(empty_env), "--env-file", str(pointer),
                         "-f", str(deployed / "infra/production/compose.yaml"), "-f", str(override)]
    configured = json.loads(run(scheduler_compose + ["config", "--format", "json"], scheduler_env).stdout)
    if configured["services"]["api"]["image"] != selected:
        raise RuntimeError("scheduler compose does not read the persisted image pointer")
    if json.loads(run(["docker", "image", "inspect", selected], env).stdout)[0]["Id"] != built["Id"]:
        raise RuntimeError("deployment image pointer does not select the verified image")
    print("PASS actual local load/up/status and scheduler image pointer (synthetic draft-format bundle; not CI provenance)")


def check(image, check_purge, check_deploy=False):
    project = "smallnext-smoke-" + uuid.uuid4().hex[:12]
    # Do not inherit operator AI settings, database URLs or Compose overrides.
    env = {key: value for key, value in os.environ.items()
           if key not in AI_SETTINGS and not key.startswith("COMPOSE_")
           and key not in {"DATABASE_URL", "API_DOMAIN", "SMALLNEXT_API_IMAGE"}}
    env.update(DATABASE_URL=DATABASE_URL, API_DOMAIN="http://localhost", SMALLNEXT_API_IMAGE=image)
    with tempfile.TemporaryDirectory(prefix="smallnext-compose-") as directory:
        temporary = Path(directory)
        empty_env = temporary / "empty.env"
        empty_env.touch()
        migration_env = temporary / "migration.env"
        migration_env.touch(mode=0o600)
        migration_env.write_text("DATABASE_URL=" + DATABASE_URL + "\n")
        env["MIGRATION_ENV_FILE"] = str(migration_env)
        override = temporary / "compose.yaml"
        override.write_text('''services:
  api:
    restart: "no"
  caddy:
    ports: !override
      - "127.0.0.1::80"
    volumes:
      - "CADDY_FILE:/etc/caddy/Caddyfile:ro"
      - "CAPTCHA_DIRECTORY:/srv/smallnext-captcha:ro"
      - "SITE_DIRECTORY:/srv/smallnext-site:ro"
  postgres:
    image: postgres:18-alpine@sha256:77f585114c32fbca283dc835b0596f4e52b51b4c6662d7810b2f4084f60a1873
    environment:
      POSTGRES_USER: smallnext
      POSTGRES_DB: smallnext
      POSTGRES_PASSWORD: smallnext-local-only
    healthcheck:
      test: ["CMD", "pg_isready", "-U", "smallnext", "-d", "smallnext"]
      interval: 1s
      timeout: 3s
      retries: 60
'''.replace("CADDY_FILE", str(ROOT / "infra/production/Caddyfile"))
           .replace("CAPTCHA_DIRECTORY", str(ROOT / "infra/production/captcha"))
           .replace("SITE_DIRECTORY", str(ROOT / "infra/production/site")))
        compose = ["docker", "compose", "--project-name", project, "--env-file", str(empty_env),
                   "-f", str(ROOT / "infra/production/compose.yaml"), "-f", str(override)]
        cleanup_images = []
        try:
            # Resolve every AI variable from a Git-external env file, without displaying its values.
            forwarded = {key: f"synthetic-{index}" for index, key in enumerate(AI_SETTINGS)}
            values = temporary / "settings.env"
            values.write_text("".join(f"{key}={value}\n" for key, value in forwarded.items()))
            config_command = compose.copy()
            config_command[config_command.index(str(empty_env))] = str(values)
            configured = json.loads(run(config_command + ["config", "--format", "json"], env).stdout)
            actual = configured["services"]["api"]["environment"]
            if any(actual.get(key) != value for key, value in forwarded.items()):
                raise RuntimeError("production compose did not forward all AI settings")
            print("PASS production compose forwards all AI environment settings")

            run(compose + ["up", "-d", "--wait", "--wait-timeout", "90", "postgres"], env)
            run(compose + ["run", "--rm", "-T", "--no-deps", "migrate"], env)
            run(compose + ["up", "-d", "--no-build", "--pull", "missing", "api", "caddy"], env)
            address = run(compose + ["port", "caddy", "80"], env).stdout.strip()
            deadline = time.monotonic() + 60
            while True:
                try:
                    if status(f"http://{address}/ready") == 200:
                        break
                except (OSError, urllib.error.URLError):
                    pass
                if time.monotonic() >= deadline:
                    raise RuntimeError("AI OFF API did not become ready")
                time.sleep(0.25)
            for path, method, expected in (("/health", "GET", 200), ("/ready", "GET", 200),
                                           ("/v1/suggestions", "POST", 404)):
                if status(f"http://{address}{path}", method) != expected:
                    raise RuntimeError(f"AI OFF response mismatch: {path}")
            print("PASS production Caddy to AI OFF API: health=200 ready=200 suggestions=404")
            for path in ("/privacy/", "/support/", "/style.css"):
                if status(f"http://{address}{path}") != 200:
                    raise RuntimeError(f"static page missing: {path}")
            print("PASS production Caddy static pages: privacy=200 support=200 style=200")
            volumes = configured["services"]["api"].get("volumes", [])
            if (len(volumes) != 1 or volumes[0].get("target") != "/etc/smallnext/tls"
                    or not volumes[0].get("read_only") or actual.get("API_AUTO_MIGRATE") != "0"):
                raise RuntimeError("production API must use only the read-only CA mount and separate migration")
            print("PASS runtime API skips migrations and mounts only read-only CA files")
            required = {
                "SUPABASE_URL": "https://test-project.supabase.co",
                "SUPABASE_PUBLISHABLE_KEY": "sb_publishable_synthetic",
                "AI_ALLOWED_SUPABASE_UIDS": "00000000-0000-0000-0000-000000000001",
                "AI_USAGE_HASH_KEY": "synthetic-usage-key-of-at-least-32-chars",
                "AI_MODEL_CONFIRMED": "1", "ANTHROPIC_API_KEY": "synthetic-provider",
            }
            for missing in required:
                settings = dict(required, **{missing: ""})
                command = compose + ["run", "--rm", "-T", "--no-deps", "-e", "USER_SERVER_AI=1"]
                for key, value in settings.items():
                    command += ["-e", f"{key}={value}"]
                result = run(command + ["api"], env, timeout=60, check=False)
                if not result.returncode or "missing or invalid user AI configuration" not in result.stderr:
                    raise RuntimeError(f"API did not reject missing {missing} through its existing validation")
                print(f"PASS AI ON refuses missing {missing}")
            if check_deploy:
                deploy_fixture(image, project, temporary, override, empty_env, address, env, cleanup_images)
            if check_purge:
                run(compose + ["stop", "api"], env)
                purge_env = dict(env, TEST_DATABASE_URL=DATABASE_URL)
                result = run([sys.executable, str(ROOT / "scripts/check_production_purge.py"),
                              "--image", cleanup_images[-1] if cleanup_images else image,
                              "--network", project + "_default"], purge_env)
                print(result.stdout.strip())
        finally:
            run(compose + ["down", "--volumes", "--remove-orphans"], env)
            for tag in cleanup_images:
                run(["docker", "image", "rm", tag], env, check=False)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", default="smallnext-api:ci")
    parser.add_argument("--check-purge", action="store_true")
    parser.add_argument("--check-deploy", action="store_true")
    arguments = parser.parse_args()
    try:
        check(arguments.image, arguments.check_purge, arguments.check_deploy)
    except (OSError, RuntimeError, subprocess.TimeoutExpired, ValueError) as error:
        # Do not print subprocess command/env or captured logs.
        message = str(error) if isinstance(error, RuntimeError) else type(error).__name__
        print(f"Production compose check failed: {message}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
