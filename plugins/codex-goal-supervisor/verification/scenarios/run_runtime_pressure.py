#!/usr/bin/env python3
"""Heavy, opt-in pressure test for the Goal Supervisor runtime.

This scenario is intentionally kept out of the default unittest discovery. It
creates large fixtures and concurrent hook traffic, then emits one machine-
readable report that can be compared between releases.
"""
from __future__ import annotations

import argparse
import concurrent.futures
import json
import os
import statistics
import sys
import tempfile
import time
from pathlib import Path
from typing import Any, Callable


PLUGIN_ROOT = Path(__file__).resolve().parents[2]
TEST_ROOT = PLUGIN_ROOT / "verification" / "tests"
if str(TEST_ROOT) not in sys.path:
    sys.path.insert(0, str(TEST_ROOT))

from helpers import (  # noqa: E402
    DEFAULT_TIMEOUT,
    copy_goal_compass_runtime,
    run_cmd,
    run_goal_compass,
)
from goal_compass_runtime.goal_return import (  # noqa: E402
    CLOSED,
    MAX_CONTEXT_CHARS,
    MAX_EVENTS,
    MAX_EVENT_BYTES,
    MAX_INTERRUPTS,
    MAX_SESSIONS,
    on_post_compact,
    on_pre_compact,
    on_session_start,
    on_stop,
    on_tool_event,
    on_user_prompt,
)


def percentile(values: list[float], ratio: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, int(round((len(ordered) - 1) * ratio))))
    return ordered[index]


def timed(call: Callable[[], Any], samples: list[float]) -> Any:
    started = time.perf_counter()
    try:
        return call()
    finally:
        samples.append((time.perf_counter() - started) * 1000.0)


def json_cli(root: Path, *args: str, expected: set[int] | None = None) -> dict[str, Any]:
    proc = run_goal_compass(list(args), root)
    if proc.returncode not in (expected or {0}):
        raise AssertionError(
            f"goal_compass {args} returned {proc.returncode}\nSTDOUT:\n{proc.stdout}\nSTDERR:\n{proc.stderr}"
        )
    return json.loads(proc.stdout)


def event(session_id: str, phase: str, turn_id: str, **values: Any) -> dict[str, Any]:
    return {
        "session_id": session_id,
        "turn_id": turn_id,
        "hook_event_name": phase,
        **values,
    }


def run_goal_return_pressure(root: Path, *, sessions: int, cycles: int, workers: int) -> dict[str, Any]:
    runtime = root / ".agent" / "runtime" / "goal_return"
    state_path = runtime / "state.json"
    lock_path = runtime / "state.lock"
    events_path = runtime / "events.jsonl"
    north = json.loads((root / ".agent" / "north_star_goal.json").read_text(encoding="utf-8"))
    convergence = json.loads((root / ".agent" / "runtime" / "convergence_state.json").read_text(encoding="utf-8"))
    latencies: list[float] = []
    secret = "fixture-pressure-secret-abcdefghijklmnop"

    def exercise(session_index: int) -> None:
        session_id = f"pressure-{session_index:03d}"
        for cycle in range(cycles):
            turn_id = f"turn-{cycle:03d}"
            prompt = (
                f"插一句：临时检查 docs/session-{session_index:03d}-{cycle:03d}.md，"
                + (f"token={secret}" if session_index == 0 and cycle == 0 else "然后返回总目标。")
            )
            timed(
                lambda: on_user_prompt(
                    state_path,
                    lock_path,
                    events_path,
                    north,
                    convergence,
                    event(session_id, "UserPromptSubmit", turn_id, prompt=prompt),
                ),
                latencies,
            )
            timed(
                lambda: on_tool_event(
                    state_path,
                    lock_path,
                    events_path,
                    north,
                    event(session_id, "PreToolUse", turn_id, tool_use_id=f"write-{session_index}-{cycle}"),
                    paths=[f"docs/session-{session_index:03d}-{cycle:03d}.md"],
                    category="write",
                    failed=False,
                ),
                latencies,
            )
            timed(
                lambda: on_stop(
                    state_path,
                    lock_path,
                    events_path,
                    north,
                    event(
                        session_id,
                        "Stop",
                        turn_id,
                        last_assistant_message="已完成临时检查并验证通过。",
                        stop_hook_active=False,
                    ),
                ),
                latencies,
            )

    started = time.perf_counter()
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
        list(pool.map(exercise, range(sessions)))
    elapsed = time.perf_counter() - started

    state = json.loads(state_path.read_text(encoding="utf-8"))
    retained_sessions = state.get("sessions", {})
    retained_interrupts = [
        row
        for session in retained_sessions.values()
        if isinstance(session, dict)
        for row in session.get("interrupts", [])
        if isinstance(row, dict)
    ]
    open_by_session = {
        session_id: sum(1 for row in session.get("interrupts", []) if row.get("state") in {"OPEN", "CLOSE_CANDIDATE"})
        for session_id, session in retained_sessions.items()
        if isinstance(session, dict)
    }
    event_rows = [json.loads(line) for line in events_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    encoded_state = state_path.read_text(encoding="utf-8")
    encoded_events = events_path.read_text(encoding="utf-8")

    assertions = {
        "session_bound": len(retained_sessions) <= MAX_SESSIONS,
        "interrupt_bound": all(
            len(session.get("interrupts", [])) <= MAX_INTERRUPTS
            for session in retained_sessions.values()
            if isinstance(session, dict)
        ),
        "single_open_branch_per_session": all(count <= 1 for count in open_by_session.values()),
        "all_retained_branches_closed": all(row.get("state") == CLOSED for row in retained_interrupts),
        "event_count_bound": len(event_rows) <= MAX_EVENTS,
        "event_byte_bound": events_path.stat().st_size <= MAX_EVENT_BYTES,
        "state_secret_redacted": secret not in encoded_state,
        "event_secret_redacted": secret not in encoded_events,
    }

    # A deterministic replay chain runs after the concurrency burst so it is
    # easy to distinguish a real Goal Return regression from lock saturation.
    replay_session = "pressure-replay"
    replay_path = "docs/closed-branch.md"
    on_user_prompt(
        state_path,
        lock_path,
        events_path,
        north,
        convergence,
        event(replay_session, "UserPromptSubmit", "replay-open", prompt=f"临时修复 {replay_path}。"),
    )
    on_tool_event(
        state_path,
        lock_path,
        events_path,
        north,
        event(replay_session, "PreToolUse", "replay-open", tool_use_id="replay-original"),
        paths=[replay_path],
        category="write",
        failed=False,
    )
    on_stop(
        state_path,
        lock_path,
        events_path,
        north,
        event(
            replay_session,
            "Stop",
            "replay-open",
            last_assistant_message="已完成临时修复并验证通过。",
            stop_hook_active=False,
        ),
    )
    on_pre_compact(
        state_path,
        lock_path,
        events_path,
        north,
        event(replay_session, "PreCompact", "replay-compact", trigger="auto"),
    )
    on_post_compact(
        state_path,
        lock_path,
        events_path,
        north,
        event(replay_session, "PostCompact", "replay-compact", trigger="auto"),
    )
    recovery = on_session_start(
        state_path,
        lock_path,
        events_path,
        north,
        convergence,
        event(replay_session, "SessionStart", "replay-compact", source="compact"),
    )
    unrelated = on_tool_event(
        state_path,
        lock_path,
        events_path,
        north,
        event(replay_session, "PreToolUse", "unrelated", tool_use_id="unrelated"),
        paths=["src/core.py"],
        category="write",
        failed=False,
    )
    signals = [
        on_tool_event(
            state_path,
            lock_path,
            events_path,
            north,
            event(replay_session, "PreToolUse", f"replay-{index}", tool_use_id=f"replay-{index}"),
            paths=[replay_path],
            category="write",
            failed=False,
        )
        for index in range(1, 4)
    ]
    assertions.update({
        "compact_recovery_bounded": bool(recovery) and len(recovery or "") <= MAX_CONTEXT_CHARS,
        "compact_recovery_tombstones_closed_branch": "do not resume" in (recovery or ""),
        "unrelated_path_does_not_replay": unrelated is None,
        "replay_escalation_is_1_2_3": [row.get("replay_count") for row in signals if row] == [1, 2, 3],
        "judge_only_after_third_replay": bool(signals[2] and signals[2].get("needs_judge"))
        and not bool(signals[0] and signals[0].get("needs_judge")),
    })

    return {
        "status": "PASS" if all(assertions.values()) else "FAIL",
        "requested_sessions": sessions,
        "cycles_per_session": cycles,
        "workers": workers,
        "elapsed_seconds": round(elapsed, 4),
        "operations": sessions * cycles * 3,
        "retained_sessions": len(retained_sessions),
        "retained_interrupts": len(retained_interrupts),
        "retained_events": len(event_rows),
        "event_bytes": events_path.stat().st_size,
        "latency_ms": {
            "p50": round(percentile(latencies, 0.50), 3),
            "p95": round(percentile(latencies, 0.95), 3),
            "p99": round(percentile(latencies, 0.99), 3),
            "max": round(max(latencies, default=0.0), 3),
            "mean": round(statistics.fmean(latencies), 3) if latencies else 0.0,
        },
        "assertions": assertions,
    }


def run_status_pressure(root: Path, *, file_count: int) -> dict[str, Any]:
    payload_root = root / "runtime-corpus"
    payload_root.mkdir(parents=True, exist_ok=True)
    for index in range(file_count):
        branch = payload_root / f"branch-{index // 250:03d}"
        branch.mkdir(parents=True, exist_ok=True)
        (branch / f"record-{index:05d}.json").write_text("{}\n", encoding="utf-8")

    catalog = root / ".agent" / "validation_catalog.json"
    catalog_data = json.loads(catalog.read_text(encoding="utf-8"))
    for index in range(950):
        catalog_data[f"pressure_validation_{index:04d}"] = {
            "cmd": f"{{python}} -c \"print({index})\"",
            "description": "Pressure fixture that must not be reloaded once per workspace file.",
            "timeout_sec": 2,
        }
    catalog.write_text(json.dumps(catalog_data, indent=2), encoding="utf-8")

    samples: list[float] = []
    payloads: list[dict[str, Any]] = []
    for _ in range(3):
        started = time.perf_counter()
        proc = run_cmd(
            [sys.executable, str(root / ".agent" / "goal_compass.py"), "status"],
            root,
            timeout=5,
            check=True,
        )
        samples.append((time.perf_counter() - started) * 1000.0)
        payloads.append(json.loads(proc.stdout))

    compact_lengths = [len(json.dumps(payload, ensure_ascii=False)) for payload in payloads]
    assertions = {
        "cold_status_under_2_seconds": max(samples) < 2_000.0,
        "compact_status_under_2500_chars": max(compact_lengths) < 2_500,
        "status_did_not_activate_ticket": all(not payload.get("active") for payload in payloads),
        "catalog_fixture_is_large": catalog.stat().st_size >= 150 * 1024,
    }
    return {
        "status": "PASS" if all(assertions.values()) else "FAIL",
        "workspace_files": file_count,
        "validation_catalog_bytes": catalog.stat().st_size,
        "latency_ms": {
            "samples": [round(value, 3) for value in samples],
            "p95": round(percentile(samples, 0.95), 3),
            "max": round(max(samples), 3),
        },
        "compact_output_chars": max(compact_lengths),
        "assertions": assertions,
    }


def run_activation_and_boundary_regression(root: Path) -> dict[str, Any]:
    feedback = json.loads((root / ".agent" / "feedback_config.json").read_text(encoding="utf-8"))
    hook = root / ".agent" / "goal_compass_runtime" / "project_hook.py"

    def invoke(tool_name: str, tool_input: dict[str, Any]) -> str:
        proc = run_cmd(
            [sys.executable, str(hook)],
            root,
            timeout=DEFAULT_TIMEOUT,
            check=True,
            input_text=json.dumps({
                "cwd": str(root),
                "session_id": "activation-regression",
                "turn_id": tool_name,
                "hook_event_name": "PreToolUse",
                "tool_name": tool_name,
                "tool_input": tool_input,
            }),
        )
        return proc.stdout

    ordinary = invoke(
        "apply_patch",
        {"patch": "*** Begin Patch\n*** Add File: src/small_fix.py\n+x = 1\n*** End Patch"},
    )
    destructive = invoke("Bash", {"command": "git reset --hard HEAD~1"})
    control_write = invoke(
        "apply_patch",
        {"patch": "*** Begin Patch\n*** Update File: .agent/current_ticket.json\n+{}\n*** End Patch"},
    )
    assertions = {
        "ordinary_inactive_edit_is_silent": ordinary == "",
        "deterministic_destructive_git_is_denied": '"permissionDecision": "deny"' in destructive,
        "control_state_write_is_denied": '"permissionDecision": "deny"' in control_write,
        "feedback_capture_enabled": bool(feedback.get("capture_enabled")),
        "feedback_upload_disabled": not bool(feedback.get("upload_enabled")),
        "feedback_delivery_local_only": feedback.get("delivery") == "local_outbox_only",
    }
    return {
        "status": "PASS" if all(assertions.values()) else "FAIL",
        "assertions": assertions,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sessions", type=int, default=24)
    parser.add_argument("--cycles", type=int, default=40)
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--files", type=int, default=11_561)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    os.environ["GOAL_SUPERVISOR_DISABLE_LLM_JUDGE"] = "1"
    started = time.perf_counter()
    manifest = json.loads((PLUGIN_ROOT / ".codex-plugin" / "plugin.json").read_text(encoding="utf-8"))
    with tempfile.TemporaryDirectory(prefix="goal-supervisor-pressure-") as tmp:
        root = Path(tmp)
        copy_goal_compass_runtime(root, writable=True)
        json_cli(root, "init")
        json_cli(
            root,
            "goal-set",
            "--text",
            "Keep a long-running engineering project aligned while producing verified deliverables with low governance overhead.",
        )
        result = {
            "schema_version": 1,
            "scenario": "goal_supervisor_runtime_pressure",
            "plugin_version": manifest.get("version"),
            "goal_return": run_goal_return_pressure(
                root,
                sessions=max(1, args.sessions),
                cycles=max(1, args.cycles),
                workers=max(1, args.workers),
            ),
            "status_pressure": run_status_pressure(root, file_count=max(1, args.files)),
        }

    # Use a separate inactive project so a confirmed North Star cannot mask an
    # activation leak in the boundary regression.
    with tempfile.TemporaryDirectory(prefix="goal-supervisor-inactive-") as tmp:
        inactive = Path(tmp)
        copy_goal_compass_runtime(inactive, writable=True)
        json_cli(inactive, "init")
        result["activation_and_boundaries"] = run_activation_and_boundary_regression(inactive)

    sections = [result["goal_return"], result["status_pressure"], result["activation_and_boundaries"]]
    result["status"] = "PASS" if all(section["status"] == "PASS" for section in sections) else "FAIL"
    result["elapsed_seconds"] = round(time.perf_counter() - started, 4)
    encoded = json.dumps(result, indent=2, ensure_ascii=False) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(encoded, encoding="utf-8")
    print(encoded, end="")
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
