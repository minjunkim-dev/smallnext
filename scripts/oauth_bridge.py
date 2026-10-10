#!/usr/bin/env python3
"""Manual Claude OAuth QA adapter for the unchanged development Rust pipeline."""

import argparse
import json
import os
from pathlib import Path
import sys
from time import monotonic, time

from oauth_quality import MODEL, call, digest, encoded, save, unique_object


class ParentCancelled:
    def __init__(self, parent):
        self.parent = parent

    def is_set(self):
        return os.getppid() != self.parent


def evaluate(args, data, claude, mode, parent):
    schema = json.loads(Path(args[args.index("--output-schema") + 1]).read_text())
    instructions = next(value for value in args if value.startswith("model_instructions_file="))
    prompt = Path(json.loads(instructions.split("=", 1)[1])).read_text()
    return call(claude, prompt, schema, data, monotonic() + 120, ParentCancelled(parent), mode)


def events(record):
    if record.get("error") or not record.get("process_reaped") or record.get("process_group_alive"):
        raise ValueError("failed")
    return [{"type": "item.completed", "item": {"type": "agent_message",
             "text": json.dumps(record["output"], ensure_ascii=False)}}, {"type": "turn.completed"}]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--claude", required=True)
    parser.add_argument("--output-mode", choices=["structured", "text-json"], default="text-json")
    parser.add_argument("--records", type=Path, required=True)
    options, args = parser.parse_known_args()
    raw = sys.stdin.buffer.read(192 * 1024 + 1)
    if len(raw) > 192 * 1024:
        raise ValueError("input limit")
    data = json.loads(raw, object_pairs_hook=unique_object)
    role = "check" if "candidate" in data else "generate"
    options.records.mkdir(parents=True, exist_ok=True, mode=0o700)
    path = options.records / f"{time():.6f}-{os.getpid()}-{role}.json"
    sources = {"bridge_sha256": digest(Path(__file__).read_bytes()),
               "runner_sha256": digest(Path(__file__).with_name("oauth_quality.py").read_bytes())}
    # Rust kills the adapter on disconnect. The worker detects lost ownership and reaps Claude.
    read_fd, write_fd = os.pipe()
    parent = os.getpid()
    worker = os.fork()
    if worker == 0:
        os.close(read_fd)
        os.close(sys.stdout.fileno())
        started = time()
        record = evaluate(args, data, options.claude, options.output_mode, parent)
        output = record.pop("output", None)
        record.update(role=role, started_at=started, finished_at=time(), requested_model=MODEL,
                      requested_effort="xhigh", decision=output.get("verdict", output.get("status")) if output else None,
                      **sources)
        save(path, record)
        try:
            payload = encoded({**record, "output": output})
            with os.fdopen(write_fd, "wb") as stream:
                stream.write(payload)
        except BrokenPipeError:
            pass
        os._exit(0)
    os.close(write_fd)
    try:
        with os.fdopen(read_fd, "rb") as stream:
            record = json.loads(stream.read())
        for event in events(record):
            print(json.dumps(event, ensure_ascii=False))
    finally:
        os.waitpid(worker, 0)


if __name__ == "__main__":
    try:
        main()
    except (ValueError, OSError, KeyError, StopIteration):
        print(json.dumps({"type": "turn.failed", "error": {"message": "Claude QA bridge failed"}}))
        sys.exit(1)
