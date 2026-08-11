#!/usr/bin/env python3
"""Run an installed-project stress scenario for the V2 deviation rail."""
from __future__ import annotations

import datetime as dt
import concurrent.futures
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any


PLUGIN_ROOT = Path(__file__).resolve().parents[2]
INSTALLER = PLUGIN_ROOT / "scripts" / "install_governor.py"
EMPTY_REUSE_FIXTURE = PLUGIN_ROOT / "verification" / "fixtures" / "reuse_probe_empty.json"
TIMEOUT = 10


def run(cmd: list[str], cwd: Path, *, input_text: str | None = None) -> tuple[subprocess.CompletedProcess[str], float]:
    started = time.perf_counter()
    result = subprocess.run(
        cmd,
        cwd=cwd,
        input=input_text,
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        timeout=TIMEOUT,
        env={
            **os.environ,
            "PYTHONUTF8": "1",
            "PYTHONDONTWRITEBYTECODE": "1",
            "GOAL_COMPASS_REUSE_PROBE_FIXTURE": str(EMPTY_REUSE_FIXTURE),
        },
    )
    elapsed = time.perf_counter() - started
    if result.returncode != 0:
        raise RuntimeError(f"command failed: {cmd}\nstdout={result.stdout}\nstderr={result.stderr}")
    return result, elapsed


def cli(repo: Path, *args: str) -> dict[str, Any]:
    result, _ = run([sys.executable, str(repo / ".agent" / "goal_compass.py"), *args], repo)
    return json.loads(result.stdout)


def hook_command(repo: Path, event_name: str) -> str:
    config = json.loads((repo / ".codex" / "hooks.json").read_text(encoding="utf-8"))
    return str(config["hooks"][event_name][0]["hooks"][0]["command"])


def invoke_hook(repo: Path, event: dict[str, Any]) -> tuple[str, float]:
    event = dict(event)
    event["cwd"] = str(repo)
    result, elapsed = run(
        ["/bin/sh", "-c", hook_command(repo, str(event["hook_event_name"]))],
        repo,
        input_text=json.dumps(event, ensure_ascii=False),
    )
    return result.stdout.strip(), elapsed


def patch_event(identifier: str, path: str, body: str) -> dict[str, Any]:
    return {
        "cwd": "",
        "hook_event_name": "PreToolUse",
        "tool_use_id": identifier,
        "tool_name": "apply_patch",
        "tool_input": {
            "patch": f"*** Begin Patch\n*** Add File: {path}\n+{body}\n*** End Patch",
        },
    }


def post_success(identifier: str) -> dict[str, Any]:
    return {
        "cwd": "",
        "hook_event_name": "PostToolUse",
        "tool_use_id": identifier,
        "tool_name": "Bash",
        "tool_input": {"command": "python3 -c 'pass'"},
        "tool_response": {"exit_code": 0},
    }


def classify(output: str) -> str:
    if not output:
        return "SILENT"
    payload = json.loads(output).get("hookSpecificOutput", {})
    if payload.get("permissionDecision") == "deny":
        return "DENY"
    return "WARNING" if payload.get("additionalContext") else "OTHER"


def observer(repo: Path) -> dict[str, Any]:
    return json.loads((repo / ".agent" / "runtime" / "observer_state.json").read_text(encoding="utf-8"))


def save_observer(repo: Path, state: dict[str, Any]) -> None:
    (repo / ".agent" / "runtime" / "observer_state.json").write_text(
        json.dumps(state, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def incident_row(repo: Path, policy: str) -> tuple[str, dict[str, Any]]:
    incidents = observer(repo).get("deviation_incidents", {})
    for identifier, row in incidents.items():
        if row.get("policy") == policy:
            return identifier, row
    raise AssertionError(f"incident not found for {policy}")


def backdate_confirmation(repo: Path, identifier: str) -> None:
    state = observer(repo)
    state["deviation_incidents"][identifier]["last_confirmation_at"] = (
        dt.datetime.now(dt.timezone.utc) - dt.timedelta(minutes=31)
    ).isoformat()
    save_observer(repo, state)


def main() -> int:
    stages: list[dict[str, Any]] = []
    with tempfile.TemporaryDirectory(prefix="goal-supervisor-v2-rail-") as raw:
        repo = Path(raw) / "product"
        repo.mkdir()
        (repo / "README.md").write_text("Private internal Agent Registry.\n", encoding="utf-8")
        run([
            sys.executable, str(INSTALLER), str(repo), "--force",
            "--feedback-context", "enterprise", "--deny-feedback-upload",
        ], PLUGIN_ROOT)
        cli(
            repo,
            "goal-set", "--text", "Build a private internal Agent Registry.",
            "--non-goal", "Do not build a provider marketplace before MVP",
            "--non-goal", "enterprise RBAC platform",
        )

        aligned, elapsed = invoke_hook(repo, patch_event("aligned-0", "src/core/registry.py", "private registry"))
        stages.append({"stage": "aligned_baseline", "decision": classify(aligned), "seconds": elapsed})

        first, elapsed = invoke_hook(repo, patch_event(
            "deviation-1", "src/providers/provider_marketplace/index.py", "provider marketplace",
        ))
        identifier, row = incident_row(repo, "Do not build a provider marketplace before MVP")
        stages.append({
            "stage": "first_deviation", "decision": classify(first), "strike": row["strike_count"],
            "status": row["status"], "seconds": elapsed,
        })

        for index in range(12):
            invoke_hook(repo, post_success(f"unrelated-success-{index}"))
        _, row = incident_row(repo, "Do not build a provider marketplace before MVP")
        stages.append({
            "stage": "unrelated_successes", "decision": "NO_CLEAR", "strike": row["strike_count"],
            "status": row["status"],
        })

        ambiguous, elapsed = invoke_hook(repo, patch_event(
            "ambiguous-sibling", "src/features/routes.py", "add route",
        ))
        _, row = incident_row(repo, "Do not build a provider marketplace before MVP")
        stages.append({
            "stage": "ambiguous_sibling_without_evidence", "decision": classify(ambiguous),
            "strike": row["strike_count"], "seconds": elapsed,
        })

        backdate_confirmation(repo, identifier)
        second, elapsed = invoke_hook(repo, patch_event(
            "deviation-2", "src/providers/provider_marketplace/catalog.py", "add catalog route",
        ))
        _, row = incident_row(repo, "Do not build a provider marketplace before MVP")
        stages.append({
            "stage": "thirty_minute_recheck", "decision": classify(second), "strike": row["strike_count"],
            "status": row["status"], "seconds": elapsed,
        })

        backdate_confirmation(repo, identifier)
        third, elapsed = invoke_hook(repo, patch_event(
            "deviation-3", "src/providers/provider_marketplace/download.py", "add download route",
        ))
        _, row = incident_row(repo, "Do not build a provider marketplace before MVP")
        stages.append({
            "stage": "third_confirmation", "decision": classify(third), "strike": row["strike_count"],
            "status": row["status"], "seconds": elapsed,
        })

        unrelated, elapsed = invoke_hook(repo, patch_event("aligned-1", "src/core/search.py", "private search"))
        wrong, wrong_elapsed = invoke_hook(repo, patch_event(
            "deviation-4", "src/providers/provider_marketplace/more.py", "provider marketplace",
        ))
        read, read_elapsed = invoke_hook(repo, {
            "cwd": str(repo), "hook_event_name": "PreToolUse", "tool_use_id": "read-1",
            "tool_name": "Read", "tool_input": {"path": "README.md"},
        })
        stages.append({
            "stage": "targeted_rail", "aligned_write": classify(unrelated),
            "wrong_direction": classify(wrong), "read": classify(read),
            "max_seconds": max(elapsed, wrong_elapsed, read_elapsed),
        })

        opened = cli(
            repo, "deviation-correct", "--incident", identifier,
            "--reason", "remove provider marketplace and restore private registry",
        )
        correction, elapsed = invoke_hook(repo, patch_event(
            "correction-1", "src/providers/provider_marketplace/download.py", "restore private registry path",
        ))
        corrected = cli(
            repo, "deviation-corrected", "--incident", identifier,
            "--evidence", "provider marketplace removed; private registry validation passed",
        )
        stages.append({
            "stage": "correction_lane", "opened": opened["status"],
            "correction_write": classify(correction), "corrected": corrected["status"], "seconds": elapsed,
        })

        recurrence, elapsed = invoke_hook(repo, patch_event(
            "recurrence-1", "src/providers/provider_marketplace/return.py", "provider marketplace",
        ))
        _, row = incident_row(repo, "Do not build a provider marketplace before MVP")
        stages.append({
            "stage": "recurrence_inside_week", "decision": classify(recurrence),
            "strike": row["strike_count"], "status": row["status"], "seconds": elapsed,
        })

        cli(repo, "deviation-correct", "--incident", identifier, "--reason", "remove recurrence")
        cli(repo, "deviation-corrected", "--incident", identifier, "--evidence", "recurrence removed")
        before_week, _ = invoke_hook(repo, patch_event("clean-day-1", "src/core/day1.py", "aligned work"))
        _, before_row = incident_row(repo, "Do not build a provider marketplace before MVP")
        state = observer(repo)
        clean = state["deviation_incidents"][identifier]["clean_window"]
        clean["started_at"] = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=8)).isoformat()
        today = dt.datetime.now(dt.timezone.utc).date()
        clean["active_days"] = [(today - dt.timedelta(days=2)).isoformat(), (today - dt.timedelta(days=1)).isoformat()]
        save_observer(repo, state)
        after_week, elapsed = invoke_hook(repo, patch_event("clean-day-3", "src/core/day3.py", "aligned work"))
        _, after_row = incident_row(repo, "Do not build a provider marketplace before MVP")
        stages.append({
            "stage": "seven_day_clear", "before": before_row["status"], "before_decision": classify(before_week),
            "after": after_row["status"], "strike": after_row["strike_count"],
            "after_decision": classify(after_week), "seconds": elapsed,
        })

        bilingual_events = []
        for index in range(3):
            output, elapsed = invoke_hook(repo, patch_event(
                f"bilingual-deviation-{index}", f"src/security/access_{index}.py", "企业级权限平台",
            ))
            bilingual_events.append({"decision": classify(output), "seconds": elapsed})
        stages.append({"stage": "cross_language_boundary", "events": bilingual_events})

        before_concurrency = int(observer(repo).get("post_events", 0) or 0)
        with concurrent.futures.ThreadPoolExecutor(max_workers=16) as pool:
            futures = [
                pool.submit(invoke_hook, repo, post_success(f"concurrent-post-{index}"))
                for index in range(48)
            ]
            concurrent_results = [future.result() for future in futures]
        invoke_hook(repo, post_success("concurrent-recovery"))
        concurrent_state = observer(repo)
        pending_dir = repo / ".agent" / "runtime" / "observer_pending"
        stages.append({
            "stage": "concurrent_observer_events",
            "recorded": int(concurrent_state.get("post_events", 0) or 0) - before_concurrency,
            "pending": len(list(pending_dir.glob("*.json"))) if pending_dir.exists() else 0,
            "fallback_recovered": int(concurrent_state.get("fallback_events_recovered", 0) or 0),
            "max_seconds": max(elapsed for _, elapsed in concurrent_results),
        })

        before_fallback = int(concurrent_state.get("post_events", 0) or 0)
        observer_lock = repo / ".agent" / "runtime" / "observer_state.lock"
        observer_lock.write_text(
            json.dumps({"pid": os.getpid(), "created_at": time.time(), "nonce": "forced-stress-lock"}),
            encoding="utf-8",
        )
        try:
            with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
                futures = [
                    pool.submit(invoke_hook, repo, post_success(f"fallback-post-{index}"))
                    for index in range(8)
                ]
                fallback_results = [future.result() for future in futures]
        finally:
            observer_lock.unlink(missing_ok=True)
        invoke_hook(repo, post_success("fallback-recovery"))
        fallback_state = observer(repo)
        stages.append({
            "stage": "forced_lock_fallback",
            "recorded": int(fallback_state.get("post_events", 0) or 0) - before_fallback,
            "pending": len(list(pending_dir.glob("*.json"))) if pending_dir.exists() else 0,
            "fallback_recovered": int(fallback_state.get("fallback_events_recovered", 0) or 0),
            "max_seconds": max(elapsed for _, elapsed in fallback_results),
        })

        active_ticket = {
            "status": "ACTIVE", "ticket_id": "STRESS-ACTIVE", "run_id": "stress-active-run",
            "task_goal": "Implement the private registry core", "must_do": ["private registry core"],
            "must_not_do": ["generic plugin framework"], "anti_patterns": [], "drift_signals": [],
            "allowed_paths": ["src/**"], "writable_paths": ["src/**"], "forbidden_paths": [],
            "read_dependencies": [], "immutable_paths": [], "runtime_paths": [], "budget": {},
            "budget_used": {}, "acceptance": {}, "validation_ids": [],
        }
        (repo / ".agent" / "current_ticket.json").write_text(
            json.dumps(active_ticket, ensure_ascii=False, indent=2) + "\n", encoding="utf-8",
        )
        active_outputs = []
        for index in range(3):
            output, elapsed = invoke_hook(repo, patch_event(
                f"active-deviation-{index}", f"src/plugin_framework/{index}.py", "generic plugin framework",
            ))
            active_outputs.append({"decision": classify(output), "seconds": elapsed})
        stages.append({"stage": "active_ticket_full_hook", "events": active_outputs})

        expected = {
            "aligned_baseline": "SILENT",
            "first_deviation": "WARNING",
            "unrelated_successes": "NO_CLEAR",
            "thirty_minute_recheck": "WARNING",
            "third_confirmation": "DENY",
            "recurrence_inside_week": "DENY",
        }
        for row in stages:
            if row["stage"] in expected and row["decision"] != expected[row["stage"]]:
                raise AssertionError(f"unexpected stage result: {row}")
        targeted = next(row for row in stages if row["stage"] == "targeted_rail")
        if targeted["aligned_write"] != "SILENT" or targeted["wrong_direction"] != "DENY" or targeted["read"] != "SILENT":
            raise AssertionError(f"rail was not targeted: {targeted}")
        clean_stage = next(row for row in stages if row["stage"] == "seven_day_clear")
        if clean_stage["before"] != "CORRECTED_MONITORING" or clean_stage["after"] != "CLEARED_AFTER_7D":
            raise AssertionError(f"clean window semantics failed: {clean_stage}")
        ambiguous_stage = next(row for row in stages if row["stage"] == "ambiguous_sibling_without_evidence")
        if ambiguous_stage["decision"] != "SILENT" or ambiguous_stage["strike"] != 1:
            raise AssertionError(f"ambiguous sibling was over-classified: {ambiguous_stage}")
        bilingual_stage = next(row for row in stages if row["stage"] == "cross_language_boundary")
        if [row["decision"] for row in bilingual_stage["events"]] != ["WARNING", "WARNING", "DENY"]:
            raise AssertionError(f"cross-language boundary failed: {bilingual_stage}")
        concurrency_stage = next(row for row in stages if row["stage"] == "concurrent_observer_events")
        if concurrency_stage["recorded"] != 49 or concurrency_stage["pending"] != 0:
            raise AssertionError(f"observer concurrency lost events: {concurrency_stage}")
        fallback_stage = next(row for row in stages if row["stage"] == "forced_lock_fallback")
        if fallback_stage["recorded"] != 9 or fallback_stage["pending"] != 0 or fallback_stage["fallback_recovered"] < 8:
            raise AssertionError(f"observer fallback lost events: {fallback_stage}")
        active_stage = next(row for row in stages if row["stage"] == "active_ticket_full_hook")
        if [row["decision"] for row in active_stage["events"]] != ["WARNING", "WARNING", "DENY"]:
            raise AssertionError(f"full hook parity failed: {active_stage}")

        print(json.dumps({
            "ok": True,
            "plugin_version": json.loads((PLUGIN_ROOT / ".codex-plugin" / "plugin.json").read_text(encoding="utf-8"))["version"],
            "stages": stages,
            "max_hook_seconds": max(
                float(value)
                for row in stages
                for key, value in row.items()
                if key.endswith("seconds") and isinstance(value, (int, float))
            ),
        }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
