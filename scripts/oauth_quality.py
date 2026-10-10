#!/usr/bin/env python3
"""Opt-in synthetic QA with the developer's Claude Code subscription OAuth."""
import argparse
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import math
import os
import pwd
import selectors
import shutil
import signal
import subprocess
import tempfile
import threading
from time import monotonic
from concurrent.futures import ThreadPoolExecutor


REPO = Path(__file__).resolve().parents[1]
MODEL = "claude-haiku-5-5"
EFFORT = "xhigh"


def encoded(value):
    return (json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode()


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def save(path, value):
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, prefix=path.name + ".tmp-", delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(encoded(value))
            stream.flush()
            os.fsync(stream.fileno())
        # Same-directory hard link publishes complete bytes atomically and refuses replacement.
        os.link(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def payload(case, role, candidate=None):
    original = case.get("input", case.get("original_request"))
    if role == "generate":
        return deepcopy(original)
    if role == "check":
        return {"original_request": deepcopy(original),
                "candidate": deepcopy(case["candidate"] if candidate is None else candidate)}
    raise ValueError("unknown role")


def freeze(directory, suite, comparison=None, repetitions=2):
    if suite not in {"quality", "latency"} or repetitions < 1:
        raise ValueError("invalid suite or repetition count")
    if suite == "quality" and comparison is not None:
        raise ValueError("comparison is only for paired latency replay")
    sources = {}

    def source(name, parse=True):
        raw = (REPO / name).read_bytes()
        sources[name] = {"sha256": digest(raw), "utf8": raw.decode("utf-8")}
        return json.loads(raw) if parse else raw.decode("utf-8")

    source("scripts/oauth_quality.py", False)
    base = "docs/research/fixtures/"
    contracts = source(base + "generation-check-contracts.json")
    quantity = source(base + "quantity-reduction-checks.json")
    status = source(base + "status-contract-checks.json")
    latency = source(base + "checker-latency-checks.json")
    references = source(base + "oauth-quality-references.json")
    prompt_dir = "services/api/src/development_ai/"
    contract = source(prompt_dir + "contract.md", False)
    prompts = {role: source(prompt_dir + role + ".md", False) + "\n" + contract
               for role in ("generate", "check")}
    schemas = {role: source(prompt_dir + role + ".json") for role in prompts}
    checkers = deepcopy(contracts["checker_cases"] + quantity["cases"])
    for parent in status["cases"]:
        checkers.extend(dict(deepcopy(c), original_request=deepcopy(parent["input"]))
                        for c in parent["checker_cases"])
    known = next(c for c in status["cases"] if c["id"] == "useful-minimum-known")
    for c in references["checker_cases"]:
        checkers.append(dict(deepcopy(c), original_request=deepcopy(known["input"])))
    generators = deepcopy(contracts["generator_cases"])
    generators.extend(deepcopy(c) for c in status["cases"] if c["id"] != "deferred-alias"
                      and c["id"] != "real-reduction")
    generators.append(deepcopy(status["original_simulator"]))
    generators.append(dict(deepcopy(next(c for c in generators if c["id"] == "generate-replacement")),
                           id="generate-replacement-repeat"))
    generators.append(dict(deepcopy(status["original_simulator"]), id="original-report-smaller-repeat"))
    for c in generators:
        c.pop("checker_cases", None)
        c["legacy_statuses"] = c["expected_statuses"][:]
        if c["id"] in references["status_overrides"]:
            c.update(deepcopy(references["status_overrides"][c["id"]]))
    variants = {"baseline": prompts["check"]}
    if comparison is not None:
        variants["comparison"] = Path(comparison).read_text(encoding="utf-8") + "\n" + contract
    cases = checkers + generators if suite == "quality" else [
        dict(deepcopy(c), original_request=deepcopy(latency["original_request"]))
        for c in latency["cases"]]
    schedule = []
    for repeat in range(1 if suite == "quality" else repetitions):
        for index, case in enumerate(cases):
            order = list(variants)
            if (repeat + index) % 2:
                order.reverse()
            for variant in order:
                schedule.append({"case": case["id"], "variant": variant, "repeat": repeat})
    manifest = {"version": 1, "suite": suite, "model": MODEL, "effort": EFFORT,
                "pipeline_seconds": 120, "parallelism": 2 if suite == "quality" else 1,
                "sources": sources, "prompts": prompts, "schemas": schemas,
                "variants": variants, "cases": cases, "schedule": schedule,
                "legacy_baseline": references["legacy_baseline"],
                "boundary": "synthetic manual Claude CLI evaluation; not Rust HTTP or device validation"}
    directory.mkdir(mode=0o700, parents=True, exist_ok=False)
    save(directory / "manifest.json", manifest)
    save(directory / "integrity.json", {"manifest_sha256": digest((directory / "manifest.json").read_bytes())})


def load(directory):
    raw = (directory / "manifest.json").read_bytes()
    integrity = json.loads((directory / "integrity.json").read_bytes())
    if digest(raw) != integrity["manifest_sha256"]:
        raise ValueError("frozen manifest changed")
    manifest = json.loads(raw)
    if manifest["model"] != MODEL or manifest["effort"] != EFFORT:
        raise ValueError("model or effort changed")
    for source in manifest["sources"].values():
        if digest(source["utf8"].encode()) != source["sha256"]:
            raise ValueError("frozen source bytes changed")
    runner = manifest["sources"].get("scripts/oauth_quality.py")
    if runner is not None and digest(Path(__file__).read_bytes()) != runner["sha256"]:
        raise ValueError("runner differs from frozen version")
    return manifest


class Tracker:
    """Retain timings and counts, never provider text or error messages."""
    def __init__(self):
        self.messages = 0
        self.retries = 0
        self.max_tokens = 0
        self.first_response = None
        self.last_thinking = None
        self.characters = {}
        self.result = None

    def consume(self, event, seconds):
        if not isinstance(event, dict):
            raise ValueError("invalid_stream")
        if event.get("type") == "system" and event.get("subtype") == "api_retry":
            self.retries += 1
            raise ValueError("provider_retry")
        if event.get("type") == "stream_event":
            detail = event.get("event", {})
            if not isinstance(detail, dict) or not isinstance(detail.get("delta", {}), dict):
                raise ValueError("invalid_stream")
            if detail.get("type") == "message_start":
                self.messages += 1
                if self.first_response is None:
                    self.first_response = seconds
                if self.messages > 1:
                    raise ValueError("additional_provider_request")
            if detail.get("type") == "content_block_delta":
                delta = detail.get("delta", {})
                for kind, key in (("thinking_delta", "thinking"), ("text_delta", "text"),
                                  ("input_json_delta", "partial_json")):
                    if delta.get("type") == kind:
                        self.characters[kind] = self.characters.get(kind, 0) + len(delta.get(key, ""))
                        if kind == "thinking_delta":
                            self.last_thinking = seconds
            if detail.get("delta", {}).get("stop_reason") == "max_tokens":
                self.max_tokens += 1
                raise ValueError("max_tokens")
        if event.get("type") == "result":
            if self.result is not None:
                raise ValueError("duplicate_result")
            self.result = event

    def metadata(self):
        result = self.result or {}
        usage = result.get("usage") if isinstance(result.get("usage"), dict) else {}
        models = result.get("modelUsage") if isinstance(result.get("modelUsage"), dict) else {}
        return {"provider_messages": self.messages, "provider_retries": self.retries,
                "additional_provider_requests": max(0, self.messages - 1) + self.retries,
                "max_tokens": self.max_tokens, "first_response_seconds": self.first_response,
                "last_thinking_seconds": self.last_thinking, "delta_characters": self.characters,
                "actual_models": sorted({name if name == MODEL else "unexpected_model" for name in models}),
                "api_seconds": numeric(result.get("duration_api_ms"), 1000),
                "usage": {key: numeric(usage.get(key)) for key in (
                    "input_tokens", "output_tokens", "cache_read_input_tokens", "cache_creation_input_tokens")}}


def numeric(value, divisor=1):
    return value / divisor if type(value) in (int, float) and math.isfinite(value) and value >= 0 else None


def validate(value, schema):
    """Validate the small committed schemas, rejecting unknown schema features."""
    if set(schema) - {"type", "properties", "required", "additionalProperties", "items",
                      "enum", "minimum", "maximum"}:
        raise ValueError("unsupported_schema")
    kind = schema["type"]
    valid = {"object": type(value) is dict, "array": type(value) is list,
             "string": type(value) is str, "boolean": type(value) is bool,
             "number": type(value) in (int, float) and math.isfinite(value),
             "integer": type(value) is int}.get(kind, False)
    if not valid or ("enum" in schema and value not in schema["enum"]):
        raise ValueError("invalid_output")
    if kind == "object":
        properties = schema["properties"]
        if not set(schema["required"]).issubset(value) or (
                schema["additionalProperties"] is False and set(value) - set(properties)):
            raise ValueError("invalid_output")
        for key in value:
            validate(value[key], properties[key])
    if kind == "array":
        for item in value:
            validate(item, schema["items"])
    if kind in {"number", "integer"}:
        if value < schema.get("minimum", -math.inf) or value > schema.get("maximum", math.inf):
            raise ValueError("invalid_output")


def environment():
    env = {key: os.environ[key] for key in (
        "PATH", "HOME", "TMPDIR", "SSL_CERT_FILE", "SSL_CERT_DIR", "HTTP_PROXY",
        "HTTPS_PROXY", "ALL_PROXY", "NO_PROXY") if key in os.environ}
    env["USER"] = env["LOGNAME"] = pwd.getpwuid(os.getuid()).pw_name
    return env


def call(claude, prompt, schema, data, deadline, cancelled):
    tracker = Tracker()
    started = monotonic()
    child = None
    record = {"payload_sha256": digest(encoded(data)), "prompt_sha256": digest(prompt.encode()),
              "schema_sha256": digest(encoded(schema)), "process_reaped": False}
    command = [claude, "-p", "--model", MODEL, "--effort", EFFORT, "--tools", "",
               "--disable-slash-commands", "--strict-mcp-config", "--mcp-config", '{"mcpServers":{}}',
               "--setting-sources", "", "--settings",
               '{"forcedLoginMethod":"claudeai","disableAllHooks":true}',
               "--no-session-persistence", "--output-format", "stream-json", "--verbose",
               "--include-partial-messages", "--json-schema", json.dumps(schema),
               "--system-prompt", prompt]
    try:
        if cancelled.is_set():
            raise ValueError("cancelled")
        if monotonic() >= deadline:
            raise ValueError("timed_out")
        with tempfile.TemporaryDirectory(prefix="smallnext-oauth-") as workspace:
            child = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                     stderr=subprocess.DEVNULL, start_new_session=True,
                                     cwd=workspace, env=environment())
            record["cli_pid"] = child.pid
            child.stdin.write(encoded(data))
            child.stdin.close()
            buffer = b""
            total_bytes = 0
            with selectors.DefaultSelector() as selector:
                selector.register(child.stdout, selectors.EVENT_READ)
                eof = False
                while not eof:
                    if cancelled.is_set():
                        raise ValueError("cancelled")
                    if monotonic() >= deadline:
                        raise ValueError("timed_out")
                    if not selector.select(min(.1, max(0, deadline - monotonic()))):
                        continue
                    raw = os.read(child.stdout.fileno(), 65536)
                    if not raw:
                        eof = True
                    buffer += raw
                    total_bytes += len(raw)
                    if total_bytes > 4 * 1024 * 1024 or len(buffer) > 512 * 1024:
                        raise ValueError("output_limit")
                    while b"\n" in buffer:
                        line, buffer = buffer.split(b"\n", 1)
                        if line.strip():
                            tracker.consume(json.loads(line), round(monotonic() - started, 3))
                if buffer.strip():
                    tracker.consume(json.loads(buffer), round(monotonic() - started, 3))
        result = tracker.result or {}
        if result.get("subtype") != "success" or result.get("is_error") is not False:
            raise ValueError("provider_failed")
        if not isinstance(result.get("modelUsage"), dict) or set(result["modelUsage"]) != {MODEL}:
            raise ValueError("wrong_model")
        if tracker.messages != 1:
            raise ValueError("unverified_message_count")
        output = result.get("structured_output")
        validate(output, schema)
        record["output"] = output
    except ValueError as error:
        # Provider exception text can contain secrets; only our own codes leave this process.
        allowed = {"cancelled", "timed_out", "output_limit", "provider_failed", "wrong_model",
                   "unverified_message_count", "unsupported_schema", "invalid_output", "provider_retry",
                   "additional_provider_request", "max_tokens", "duplicate_result"}
        record["error"] = str(error) if str(error) in allowed else "invalid_stream"
    except subprocess.TimeoutExpired:
        record["error"] = "timed_out"
    except (OSError, TypeError, KeyError, AttributeError):
        record["error"] = "runner_failed"
    finally:
        if child is not None:
            for sig in (signal.SIGTERM, signal.SIGKILL):
                try:
                    os.killpg(child.pid, sig)
                except (ProcessLookupError, PermissionError):
                    # macOS can return EPERM for a group containing only an unreaped zombie.
                    pass
                if sig == signal.SIGTERM:
                    # Keep the group leader unreaped until both signals to prevent PID reuse.
                    threading.Event().wait(.05)
            child.wait()
            if child.returncode != 0 and "error" not in record:
                record.pop("output", None)
                record["error"] = "provider_failed"
            child.stdout.close()
            record["process_reaped"] = True
            try:
                os.killpg(child.pid, 0)
                record["process_group_alive"] = True
            except ProcessLookupError:
                record["process_group_alive"] = False
            except PermissionError:
                record["process_group_alive"] = True
        record.update(tracker.metadata())
        record["seconds"] = round(monotonic() - started, 3)
    return record


def check_valid(output):
    return bool(output and output["evidence"].strip() and output["reason"].strip()
                and output["criteria"] and (output["verdict"] != "accept"
                                            or set(output["criteria"]) == {1, 2, 3, 4, 5}))


def schema_for(manifest, original):
    schema = deepcopy(manifest["schemas"]["generate"])
    schema["properties"]["status"]["enum"] = (
        ["goal_summary", "need_info"] if original.get("request_kind") == "goal_preparation" else
        ["action", "need_info", "minimum", "no_action"] if original.get("request_kind") == "replacement" else
        ["action", "need_info", "minimum"])
    return schema


def proposal_valid(original, proposal):
    return (all(proposal[key].strip() for key in ("action", "completion_condition", "reason"))
            and 0 <= proposal["estimated_minutes"] <= original["available_minutes"]
            and proposal["remaining_work"] == original["remaining_work"]
            and proposal["preserved_completed_ids"] == original["completed_ids"]
            and proposal["goal_completed"] is False and proposal["current_action_completed"] is False)


def evaluate(directory, manifest, index, row, claude, cancelled):
    case = next(c for c in manifest["cases"] if c["id"] == row["case"])
    started = monotonic()
    deadline = started + manifest["pipeline_seconds"]
    record = dict(row, index=index, calls=[], matched=False, legacy_matched=False,
                  manifest_sha256=digest((directory / "manifest.json").read_bytes()))
    candidate = None
    try:
        if "input" in case:
            generated = call(claude, manifest["prompts"]["generate"], schema_for(manifest, case["input"]),
                             payload(case, "generate"), deadline, cancelled)
            record["calls"].append(dict(generated, role="generate"))
            candidate = generated.get("output")
            if candidate is not None and not proposal_valid(case["input"], candidate):
                record["error"] = "invalid_proposal"
                candidate = None
        if "input" not in case or candidate is not None:
            checked = call(claude, manifest["variants"][row["variant"]], manifest["schemas"]["check"],
                           payload(case, "check", candidate), deadline, cancelled)
            record["calls"].append(dict(checked, role="check"))
            output = checked.get("output")
            if check_valid(output):
                if "input" in case:
                    record["accepted"] = output["verdict"] == "accept"
                    record["matched"] = record["accepted"] and candidate["status"] in case["expected_statuses"]
                    record["legacy_matched"] = record["accepted"] and candidate["status"] in case["legacy_statuses"]
                else:
                    record["matched"] = output["verdict"] == case["expected"]
            elif output is not None:
                record["error"] = "invalid_check"
    except Exception:
        # Preserve paid partial calls and classify the case without leaking exception text.
        record["error"] = "runner_failed"
    record["seconds"] = round(monotonic() - started, 3)
    save(directory / "results" / f"{index:03d}.json", record)
    print(json.dumps({key: record[key] for key in ("index", "case", "variant", "matched", "seconds")}), flush=True)
    return record


def process_birth(pid):
    result = subprocess.run(["ps", "-p", str(pid), "-o", "lstart="], capture_output=True,
                            env={"PATH": os.environ.get("PATH", ""), "LC_ALL": "C"}, timeout=5)
    if result.returncode not in (0, 1):
        raise ValueError("process identity unavailable")
    return result.stdout.decode().strip()


def run(directory, claude):
    manifest = load(directory)
    status = subprocess.run([claude, "auth", "status"], stdout=subprocess.PIPE,
                            stderr=subprocess.DEVNULL, env=environment(), timeout=15, check=True)
    account = json.loads(status.stdout)
    if not (account.get("loggedIn") is True and account.get("authMethod") == "claude.ai"
            and account.get("apiProvider") == "firstParty"):
        raise ValueError("Claude Code subscription OAuth login required")
    # Exclusive claim prevents retries, concurrent runs and replacement of failed measurements.
    save(directory / "run-started.json", {"manifest_sha256": digest((directory / "manifest.json").read_bytes()),
                                          "controller_pid": os.getpid(), "controller_birth": process_birth(os.getpid())})
    (directory / "results").mkdir(mode=0o700)
    cancelled = threading.Event()
    previous = {sig: signal.signal(sig, lambda *_: cancelled.set()) for sig in (signal.SIGINT, signal.SIGTERM)}
    try:
        with ThreadPoolExecutor(max_workers=manifest["parallelism"]) as pool:
            records = list(pool.map(lambda indexed: evaluate(directory, manifest, *indexed, claude, cancelled),
                                    enumerate(manifest["schedule"])))
    finally:
        for sig, handler in previous.items():
            signal.signal(sig, handler)
    return summarize(directory, manifest, records)


def summarize(directory, manifest, records, unreadable=(), target="summary.json"):
    import statistics
    indices = [record.get("index") for record in records]
    if any(type(index) is not int or not 0 <= index < len(manifest["schedule"]) for index in indices):
        raise ValueError("invalid record identity")
    if len(set(indices)) != len(indices) or any(
            any(record.get(key) != manifest["schedule"][record["index"]][key]
                for key in ("case", "variant", "repeat")) for record in records):
        raise ValueError("duplicate or unrelated record")
    calls = [call for record in records for call in record["calls"]]
    pipelines = [record for record in records if any(c["role"] == "generate" for c in record["calls"])]
    summary = {"scheduled": len(manifest["schedule"]), "recorded": len(records),
               "missing_cases": len(manifest["schedule"]) - len(records),
               "unreadable_records": list(unreadable),
               "matched": sum(r["matched"] for r in records),
               "failed_cases": sum("error" in r or any("error" in c for c in r["calls"]) for r in records),
               "reference_mismatches": sum(not r["matched"] and "error" not in r
                                           and not any("error" in c for c in r["calls"]) for r in records),
               "pipeline_accepted": sum(r.get("accepted", False) for r in pipelines),
               "pipeline_reference_matched": sum(r["matched"] for r in pipelines),
               "pipeline_legacy_matched": sum(r["legacy_matched"] for r in pipelines),
               "legacy_baseline": manifest["legacy_baseline"], "role_calls": len(calls),
               "completed_role_calls": sum("output" in c for c in calls),
               "failed_role_calls": sum("error" in c and c["error"] not in {"cancelled", "timed_out"} for c in calls),
               "cancelled_role_calls": sum(c.get("error") == "cancelled" for c in calls),
               "timed_out_role_calls": sum(c.get("error") == "timed_out" for c in calls),
               "provider_messages": sum(c["provider_messages"] for c in calls),
               "provider_retries": sum(c["provider_retries"] for c in calls),
               "additional_provider_requests": sum(c["additional_provider_requests"] for c in calls),
               "max_tokens": sum(c["max_tokens"] for c in calls),
               "unreaped_processes": sum("cli_pid" in c and not c["process_reaped"] for c in calls),
               "live_process_groups": sum(c.get("process_group_alive", False) for c in calls),
               "timings": {}}
    for variant in manifest["variants"]:
        rows = [r for r in records if r["variant"] == variant]
        values = [c["api_seconds"] for r in rows for c in r["calls"]
                  if c["role"] == "check" and c["api_seconds"] is not None and "output" in c]
        summary["timings"][variant] = {"checker_api_seconds": values,
            "median": statistics.median(values) if values else None, "samples": len(values),
            "all_matched": len(rows) > 0 and all(r["matched"] for r in rows)}
    summary["passed"] = (not unreadable and len(records) == len(manifest["schedule"]) and all(r["matched"] for r in records)
                         and not summary["live_process_groups"] and not summary["unreaped_processes"])
    save(directory / target, summary)
    print(json.dumps(summary, ensure_ascii=False))
    return summary["passed"]


def recover_summary(directory):
    manifest = load(directory)
    claim = json.loads((directory / "run-started.json").read_bytes())
    target = "summary.json"
    if (directory / target).exists():
        try:
            summary = json.loads((directory / target).read_bytes())
            if not isinstance(summary, dict) or type(summary.get("passed")) is not bool:
                raise ValueError("invalid summary")
        except (ValueError, UnicodeDecodeError):
            target = "summary-recovered.json"
        else:
            print(json.dumps(summary))
            return
    if target == "summary-recovered.json" and (directory / target).exists():
        print(json.dumps(json.loads((directory / target).read_bytes())))
        return
    if "controller_birth" in claim:
        birth = process_birth(claim["controller_pid"])
        if birth and birth == claim["controller_birth"]:
            raise ValueError("controller still alive; do not summarize an active run")
    elif "controller_pid" in claim:
        try:
            os.kill(claim["controller_pid"], 0)
        except ProcessLookupError:
            pass
        else:
            raise ValueError("controller still alive; do not summarize an active run")
    records = []
    unreadable = []
    for path in sorted((directory / "results").glob("*.json")):
        try:
            record = json.loads(path.read_bytes())
        except (json.JSONDecodeError, UnicodeDecodeError):
            unreadable.append(path.name)
            continue
        records.append(record)
    if any(record["manifest_sha256"] != claim["manifest_sha256"] for record in records):
        raise ValueError("record belongs to a different manifest")
    try:
        summarize(directory, manifest, records, unreadable, target)
    except FileExistsError:
        print((directory / target).read_text())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    frozen = sub.add_parser("freeze")
    frozen.add_argument("directory", type=Path)
    frozen.add_argument("--suite", choices=("quality", "latency"), required=True)
    frozen.add_argument("--comparison-role", type=Path)
    frozen.add_argument("--repetitions", type=int, default=2)
    checked = sub.add_parser("verify")
    checked.add_argument("directory", type=Path)
    runner = sub.add_parser("run", help="explicitly start subscription model calls; never run by default CI")
    runner.add_argument("directory", type=Path)
    runner.add_argument("--claude", default=shutil.which("claude"))
    recovery = sub.add_parser("summarize", help="recover an interrupted summary without any provider calls")
    recovery.add_argument("directory", type=Path)
    args = parser.parse_args()
    if args.command == "freeze":
        freeze(args.directory, args.suite, args.comparison_role, args.repetitions)
    if args.command == "run":
        if not args.claude:
            parser.error("Claude Code executable not found")
        raise SystemExit(0 if run(args.directory, args.claude) else 1)
    if args.command == "summarize":
        recover_summary(args.directory)
        return
    manifest = load(args.directory)
    print(json.dumps({"suite": manifest["suite"], "scheduled_cases": len(manifest["schedule"]),
                      "manifest_sha256": digest((args.directory / "manifest.json").read_bytes())}))


if __name__ == "__main__":
    main()
