#!/usr/bin/env python3
"""Explicit offline rejudgment of one frozen OAuth quality evaluation."""
import argparse
import json
from pathlib import Path
import sys

import launch_evaluation as launch
import oauth_quality as qa


# Reviewed runner bytes: #186/#218/#252/#260/#273/#288/#285 record cancellation; #135 kept it only in memory.
PROTOCOLS = {
    "a77278906d6c5e64ea12b538f50d773afc032ad990b039a7e49f0a9adeb128b5": "cancellation-marker-v1",
    "ca5053bc80470d0cf3d98dee4c12f52b770010a8eecc8c1b35a85e57ca38d069": "cancellation-marker-v1",
    "2a34ea2fbd59884994e88329a4f9d2a86d457d035634ef469d3d2831bf678929": "cancellation-marker-v1",
    "5c2b737f0e2a37f97d0315ed8ff2a3ff22379c8778577a6f4956b863a0c6a9ab": "cancellation-marker-v1",
    "a5aa0d74c2f6aaf1feef8d83498a81229109c3f1969e1b16b2adc5d4c8560aa8": "cancellation-marker-v1",
    "808ff25eddb8506820027e0a153b45bcf139e04207ef64550be379b360c1598b": "cancellation-marker-v1",
    "b4befc291a69c3cfeb4d2f8bc9b105d31d8e5f4213958a49d3a0a973726b39f8": "cancellation-marker-v1",
    "1799cb2c4ef7c5cddd58f2a275cdad37750bae8b45d26286f21fcfd69d18afe2": "cancellation-marker-v1",
    "1e2d25eb61b3c52ef34fe1f54f1e1ebc73c9e938108da58f8768bedaa5d6ddff": "cancellation-marker-v1",
    "a52650b83cca7c5213aad7009853e0e8c4db74ae66e592f11793b814c8586927": "cancellation-marker-v1",
    "375f9752e5512160c1b1e55cb33ade85ebd41cc8a31ad1b00e1ac92e4af89ea1": "cancellation-marker-v1",
    "efd3c86de40152cc86f619622c03ea16b7ce3bd6766c70f3159d30d8f7e91037": "volatile-cancellation-v1",
}


def parsed(raw):
    def invalid_constant(_):
        raise ValueError("invalid_json")
    return json.loads(raw, object_pairs_hook=qa.unique_object, parse_constant=invalid_constant)


def observed_object(raw):
    try:
        value = parsed(raw) if raw is not None else None
        return value if isinstance(value, dict) else {}
    except (ValueError, UnicodeDecodeError, RecursionError):
        return {}


def record_failures(record):
    reasons = []
    pending = [record]
    while pending:
        node = pending.pop()
        if not isinstance(node, dict):
            continue
        # Missing cleanup evidence is handled separately from an explicit failure.
        failure = qa.result_failure({key: value for key, value in node.items()
                                     if key not in {"calls", "subcalls"}})
        if failure is not None and "error" in node:
            error = node["error"]
            reasons.append(error if isinstance(error, str) and error in {"cancelled", "timed_out"}
                           else "explicit_error")
        if node.get("process_group_alive") is True or node.get("process_reaped") is False:
            reasons.append("process_cleanup")
        for key in ("calls", "subcalls"):
            if isinstance(node.get(key), list):
                pending.extend(node[key])
    return reasons


def completed(record, case, manifest):
    calls = record.get("calls")
    roles = ["generate", "check"] if "input" in case else ["check"]
    if (not isinstance(calls, list) or any(not isinstance(call, dict) for call in calls)
            or [call.get("role") for call in calls] != roles):
        return False
    try:
        for call in calls:
            schema = (qa.schema_for(manifest, case["input"]) if call["role"] == "generate"
                      else manifest["schemas"]["check"])
            qa.validate(call.get("output"), schema)
            if call["role"] == "check" and not qa.check_valid(call["output"]):
                return False
    except (ValueError, KeyError, TypeError, AttributeError):
        return False
    pending = list(calls)
    while pending:
        node = pending.pop()
        if (not isinstance(node, dict) or "calls" in node
                or not isinstance(node.get("output"), dict) or not node["output"]):
            return False
        if "subcalls" in node:
            if not isinstance(node["subcalls"], list) or not node["subcalls"]:
                return False
            pending.extend(node["subcalls"])
        if (type(node.get("cli_pid")) is not int or node["cli_pid"] <= 0
                or node.get("process_reaped") is not True or node.get("process_group_alive") is not False
                or node.get("actual_models") != [manifest["model"]]):
            return False
        for key, expected in (("provider_messages", 1), ("provider_retries", 0),
                              ("additional_provider_requests", 0), ("max_tokens", 0)):
            if type(node.get(key)) is not int or node[key] != expected:
                return False
    return True


def rejudge(frozen, output):
    if output.is_symlink():
        raise ValueError("unsafe_output")
    frozen, output = frozen.resolve(), output.resolve()
    if not frozen.is_dir():
        raise ValueError("unsupported_input")
    # Case aliases can name the same directory on case-insensitive filesystems.
    if (any(path.exists() and path.samefile(frozen) for path in (output, *output.parents))
            or (output.exists() and any(path.samefile(output) for path in frozen.parents))):
        raise ValueError("output_overlaps_input")
    files = {}

    def read(name, *, required=False):
        path = frozen / name
        if path.is_symlink() or (path.exists() and not path.is_file()):
            raise ValueError("unsafe_input_file")
        if not path.exists():
            files[name] = None
            if required:
                raise ValueError("missing_frozen_input")
            return None
        raw = launch.private_bytes(frozen, name)
        files[name] = qa.digest(raw)
        return raw

    raw = read("manifest.json", required=True)
    manifest = parsed(raw)
    integrity = parsed(read("integrity.json", required=True))
    if integrity.get("manifest_sha256") != qa.digest(raw):
        raise ValueError("manifest_integrity")
    if (type(manifest.get("version")) is not int or manifest["version"] != 1
            or manifest.get("suite") not in {"quality", "latency"}
            or manifest.get("model") != qa.MODEL or manifest.get("effort") != qa.EFFORT
            or not isinstance(manifest.get("schedule"), list) or not manifest["schedule"]
            or not isinstance(manifest.get("sources"), dict)
            or "scripts/oauth_quality.py" not in manifest["sources"]
            or not isinstance(manifest.get("cases"), list) or not manifest["cases"]
            or not isinstance(manifest.get("variants"), dict) or not manifest["variants"]
            or not isinstance(manifest.get("output_modes"), dict)
            or any(not isinstance(manifest.get(key), dict) or set(manifest[key]) != {"generate", "check"}
                   for key in ("prompts", "schemas"))):
        raise ValueError("unsupported_input")
    case_ids = [case["id"] for case in manifest["cases"]]
    if (any(not isinstance(ident, str) or not ident for ident in case_ids)
            or len(set(case_ids)) != len(case_ids)):
        raise ValueError("unsupported_input")
    identities = []
    for row in manifest["schedule"]:
        if (set(row) != {"case", "variant", "repeat"} or row["case"] not in case_ids
                or row["variant"] not in manifest["variants"] or type(row["repeat"]) is not int
                or row["repeat"] < 0):
            raise ValueError("unsupported_input")
        identities.append((row["case"], row["variant"], row["repeat"]))
    if (len(set(identities)) != len(identities)
            or any(manifest["output_modes"].get(variant) not in {"structured", "text-json"}
                   for variant in manifest["variants"])):
        raise ValueError("unsupported_input")
    for source in manifest["sources"].values():
        if qa.digest(source["utf8"].encode("utf-8")) != source["sha256"]:
            raise ValueError("source_integrity")
    runner_sha = manifest["sources"]["scripts/oauth_quality.py"]["sha256"]
    protocol = PROTOCOLS.get(runner_sha, "unknown")
    summary_raw = read("summary.json")
    summary = observed_object(summary_raw)
    claim_raw = read("run-started.json")
    claim = observed_object(claim_raw)
    cancelled = read("run-cancelled.json") is not None
    if (frozen / "results").is_symlink():
        raise ValueError("unsafe_input_file")
    inventory = sorted(path.name for path in (frozen / "results").iterdir()) if (frozen / "results").exists() else []
    inventory_sha = qa.digest(qa.encoded(inventory))
    unexpected = set(inventory) - {f"{index:03d}.json" for index in range(len(manifest["schedule"]))}
    global_reasons = {"unexpected_results"} if unexpected else set()
    if cancelled or summary.get("cancelled") is True:
        global_reasons.add("cancelled")
    cases = []
    for index, scheduled in enumerate(manifest["schedule"]):
        raw = read(f"results/{index:03d}.json")
        row = observed_object(raw)
        matched = row.get("matched")
        original = "passed" if matched is True else "failed" if matched is False else "indeterminate"
        reasons = []
        if raw is None:
            reasons.append("missing_result")
        elif not row:
            reasons.append("unreadable_result")
        if (type(row.get("index")) is not int or row["index"] != index or type(row.get("repeat")) is not int
                or row.get("manifest_sha256") != files["manifest.json"]
                or any(row.get(key) != scheduled[key] for key in ("case", "variant", "repeat"))):
            reasons.append("record_identity")
        if protocol == "unknown":
            reasons.append("unknown_protocol")
        if protocol != "cancellation-marker-v1" or type(summary.get("cancelled")) is not bool:
            reasons.append("cancellation_unverifiable")
        if claim.get("manifest_sha256") != files["manifest.json"]:
            reasons.append("missing_run_identity")
        case = next(case for case in manifest["cases"] if case["id"] == scheduled["case"])
        completion = completed(row, case, manifest)
        if not completion:
            reasons.append("completion_unverifiable")
        failures = record_failures(row)
        if matched is False and completion:
            failures.append("reference_mismatch")
        if type(matched) is not bool:
            reasons.append("missing_reference_match")
        reasons.extend(failures)
        verdict = "failed" if failures else "indeterminate" if reasons else original
        cases.append({"index": index, "original_verdict": original, "new_verdict": verdict,
                      "reasons": sorted(set(reasons))})
    new = ("failed" if cancelled or summary.get("cancelled") is True else
           "failed" if any(case["new_verdict"] == "failed" for case in cases) else
           "indeterminate" if any(case["new_verdict"] == "indeterminate" for case in cases) else "passed")
    original = ("passed" if summary.get("passed") is True else
                "failed" if summary.get("passed") is False else "indeterminate")
    if new == "passed" and (unexpected or original != "passed"):
        new = "indeterminate"
        if original != "passed":
            global_reasons.add("original_summary_unverifiable")
    policy_files = {name: qa.digest(Path(path).read_bytes()) for name, path in
                    (("rejudge_oauth_quality.py", __file__), ("oauth_quality.py", qa.__file__),
                     ("launch_evaluation.py", launch.__file__))}
    report = {"version": 1, "input_sha256": qa.digest(qa.encoded([files, inventory_sha])), "input_files": files,
              "result_inventory_sha256": inventory_sha,
              "policy_sha256": qa.digest(qa.encoded(policy_files)), "policy_files": policy_files,
              "original_runner_sha256": runner_sha, "protocol": protocol,
              "original_verdict": original, "new_verdict": new, "cases": cases,
              "reasons": sorted({reason for case in cases for reason in case["reasons"]}
                                | global_reasons),
              "fingerprint_scope": "observed_bytes_only; not_historical_authenticity"}
    encoded = qa.encoded(report)
    try:
        output.mkdir(mode=0o700, parents=True)
    except FileExistsError:
        if ((output / "report.json").is_symlink() or not output.is_dir()
                or set(path.name for path in output.iterdir()) != {"report.json"}
                or launch.private_bytes(output, "report.json") != encoded):
            raise ValueError("output_conflict") from None
    else:
        qa.save(output / "report.json", report)
    return new


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--frozen", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        verdict = rejudge(args.frozen, args.output)
    except (OSError, ValueError, TypeError, KeyError, AttributeError, RecursionError):
        print("rejudgment rejected: invalid input or output", file=sys.stderr)
        return 2
    print(json.dumps({"new_verdict": verdict}))
    return 0 if verdict == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
