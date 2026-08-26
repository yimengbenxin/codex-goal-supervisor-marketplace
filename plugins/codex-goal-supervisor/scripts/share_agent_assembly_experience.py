#!/usr/bin/env python3
"""Share one local Agent assembly experience through an already-authorized project transport."""
from __future__ import annotations

import argparse
import importlib
import json
import sys
from pathlib import Path
from typing import Any


def print_json(value: Any) -> None:
    print(json.dumps(value, ensure_ascii=False, indent=2))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", required=True)
    parser.add_argument("--record", required=True)
    args = parser.parse_args(argv)

    root = Path(args.project).expanduser().resolve()
    agent_dir = root / ".agent"
    outbox = (agent_dir / "agent-assembly" / "experience-outbox").resolve()
    record_path = Path(args.record).expanduser().resolve()
    if record_path.parent != outbox or record_path.suffix != ".json":
        print_json({"status": "ERROR", "error": "record must be a local Agent assembly experience"})
        return 2
    try:
        experience = json.loads(record_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print_json({"status": "ERROR", "error": f"invalid experience record: {type(exc).__name__}"})
        return 2
    required = {"capability_id", "source_fingerprint", "target_runtime", "outcome", "summary", "verification"}
    if not isinstance(experience, dict) or not required.issubset(experience):
        print_json({"status": "ERROR", "error": "experience record is incomplete"})
        return 2
    if experience.get("contains_source_or_attachment") is not False:
        print_json({"status": "ERROR", "error": "source or attachment payloads cannot be shared"})
        return 2
    runtime = agent_dir / "goal_compass_runtime" / "feedback.py"
    if not runtime.is_file():
        print_json({"status": "ERROR", "error": "project feedback runtime is unavailable"})
        return 2

    sys.path.insert(0, str(agent_dir))
    try:
        feedback = importlib.import_module("goal_compass_runtime.feedback")
        config = feedback.ensure_config(agent_dir)
        if not feedback.upload_authorized(config):
            print_json({"status": "LOCAL_ONLY", "error": "project upload consent is not enabled"})
            return 2
        result = feedback.record(
            kind="skill_experience",
            message=str(experience["summary"])[:1000],
            source="agent_assembler",
            severity="warning" if experience["outcome"] == "failed" else "info",
            rule_id="agent_assembly_experience",
            status=str(experience["outcome"]).upper(),
            context={
                "capability_id": experience["capability_id"],
                "recipe_id": experience.get("recipe_id"),
                "source_fingerprint": experience["source_fingerprint"],
                "resolved_revision": experience.get("resolved_revision"),
                "tree_sha256": experience.get("tree_sha256"),
                "target_runtime": experience["target_runtime"],
                "outcome": experience["outcome"],
                "adaptation_summary": experience.get("adaptation_summary"),
                "error_category": experience.get("error_category"),
                "verification": experience["verification"],
                "contains_source_or_attachment": False,
            },
            agent_dir=agent_dir,
            request_iteration=False,
        )
    except (ImportError, OSError, RuntimeError, ValueError) as exc:
        print_json({"status": "ERROR", "error": f"feedback unavailable: {type(exc).__name__}"})
        return 2
    finally:
        try:
            sys.path.remove(str(agent_dir))
        except ValueError:
            pass
    print_json({"status": "SHARE_REQUESTED", "result": result})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
