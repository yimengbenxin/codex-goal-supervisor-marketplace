from __future__ import annotations

import argparse
import json
import shutil
import sys
import tempfile
import time
import unittest
from pathlib import Path
from typing import Any

try:
    from .helpers import copy_goal_compass_runtime, run_goal_compass
except ImportError:
    from helpers import copy_goal_compass_runtime, run_goal_compass


INDUSTRIES = [
    ("aviation", "Build an aviation maintenance planning system that links aircraft findings to safe, auditable work packages."),
    ("pharma", "Build a clinical trial operations system that tracks protocol execution, evidence quality, and site-level risks."),
    ("water", "Build a municipal water operations system that forecasts demand, detects losses, and produces operator-verifiable dispatch plans."),
    ("emergency", "Build an emergency response coordination system that links incidents, resources, routes, and accountable handoffs."),
    ("insurance", "Build an insurance claims workflow that assembles evidence, detects inconsistencies, and supports explainable adjuster decisions."),
    ("hospitality", "Build a hotel revenue operations system that forecasts demand and produces auditable pricing and inventory recommendations."),
    ("transit", "Build a public transit control system that monitors service, explains disruptions, and produces operator-reviewable recovery plans."),
    ("museum", "Build a museum digital collection system that preserves provenance, rights, conservation status, and reusable public records."),
    ("semiconductor", "Build a semiconductor fab operations system that traces lots, process excursions, yield evidence, and recovery actions."),
    ("telecom", "Build a telecom network assurance system that detects faults, explains customer impact, and validates bounded remediation."),
    ("construction", "Build a construction BIM coordination system that links model clashes, field evidence, responsibility, and verified resolution."),
    ("port", "Build a port logistics control system that coordinates berths, yard capacity, customs evidence, and resilient cargo flow."),
    ("mining", "Build a mine operations planning system that connects geology, equipment, safety constraints, and auditable production plans."),
    ("waste", "Build a municipal waste operations system that plans collection, tracks contamination, and validates service outcomes."),
    ("fisheries", "Build a fisheries management system that links catch evidence, quotas, vessel activity, and explainable sustainability controls."),
    ("real_estate", "Build a property asset operations system that links inspections, leases, maintenance, and auditable investment evidence."),
]


def cli_json(root: Path, *args: str, expected: set[int] | None = None) -> dict[str, Any]:
    proc = run_goal_compass(list(args), root)
    allowed = expected or {0}
    if proc.returncode not in allowed:
        raise AssertionError(
            f"goal_compass {args} returned {proc.returncode}\nSTDOUT:\n{proc.stdout}\nSTDERR:\n{proc.stderr}"
        )
    try:
        return json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        raise AssertionError(f"Non-JSON output for {args}: {proc.stdout}") from exc


def make_ticket(
    case_id: str,
    goal: str,
    sequence: int,
    *,
    validation_id: str | None = None,
    diff_budget: int = 300,
    requested_departments: list[str] | None = None,
    draft: bool = False,
) -> dict[str, Any]:
    artifact = f"src/{case_id}/bounded_slice_{sequence:02d}.py"
    acceptance: dict[str, Any] = {
        "commands_pass": [validation_id] if validation_id else [],
        "files_exist": [] if validation_id else [artifact],
        "contains": [],
        "assertions": [],
        "files_not_changed": [],
        "max_changed_files": 6,
        "max_diff_lines": 1000,
    }
    return {
        "ticket_id": f"{case_id.upper()}-LONG-{sequence:02d}",
        "title": f"{case_id} bounded operations slice {sequence}",
        "global_goal": goal,
        "why_now": "Advance one observable end-to-end operating result without expanding the product.",
        "task_goal": f"Implement and verify bounded {case_id} operations slice {sequence}.",
        "status": "DRAFT" if draft else "PENDING",
        "acceptance_ready": not draft,
        "must_do": [f"Produce {artifact}", "Keep the result machine-checkable"],
        "must_not_do": ["Do not build an enterprise marketplace", "Do not replace the North Star with a local subsystem"],
        "anti_patterns": ["enterprise marketplace", "generic plugin platform", "full RBAC", "compliance dashboard"],
        "allowed_paths": [f"src/{case_id}/**", f"tests/{case_id}/**"],
        "forbidden_paths": [".env", ".agent/**", ".codex/**", ".git/**", "src/security/rbac/**"],
        "acceptance": acceptance,
        "validation_ids": [validation_id] if validation_id else [],
        "budget": {
            "max_minutes": 45,
            "max_tool_calls": 60,
            "max_changed_files": 6,
            "max_diff_lines": diff_budget,
        },
        "drift_signals": [
            "Starts building an enterprise marketplace",
            "Keeps expanding the same local subsystem after acceptance",
        ],
        "backlog_only": ["Enterprise marketplace", "Full RBAC", "Generic plugin platform"],
        "requested_company_departments": requested_departments or [],
        "company_ceo_confirmation": {},
    }


def write_ticket(root: Path, ticket: dict[str, Any]) -> Path:
    target = root / ".agent" / "tickets" / "pending" / f"{ticket['ticket_id']}.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(ticket, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return target


def write_artifact(root: Path, case_id: str, sequence: int, lines: int = 2) -> Path:
    target = root / "src" / case_id / f"bounded_slice_{sequence:02d}.py"
    target.parent.mkdir(parents=True, exist_ok=True)
    body = [
        f'"""Bounded {case_id} operating result {sequence}."""',
        f"RESULT_{sequence} = 'verified {case_id} slice'",
    ]
    while len(body) < lines:
        body.append(f"EVIDENCE_{len(body)} = 'bounded' ")
    target.write_text("\n".join(body) + "\n", encoding="utf-8")
    return target


def install_catalog(root: Path) -> None:
    path = root / ".agent" / "validation_catalog.json"
    catalog = json.loads(path.read_text(encoding="utf-8"))
    catalog["long_run_fail"] = {
        "cmd": "{python} -c \"import sys; sys.exit(1)\"",
        "description": "Long-run benchmark deterministic failure.",
        "timeout_sec": 3,
    }
    path.write_text(json.dumps(catalog, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def repair_failed_validation(root: Path) -> None:
    path = root / ".agent" / "validation_catalog.json"
    catalog = json.loads(path.read_text(encoding="utf-8"))
    catalog["long_run_fail"]["cmd"] = "{python} -c \"import sys; sys.exit(0)\""
    path.write_text(json.dumps(catalog, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def confirm_expansion(template: dict[str, Any]) -> dict[str, Any]:
    confirmed = dict(template)
    confirmed.update({
        "status": "CONFIRMED",
        "decision": "EXPAND",
        "reason": "Seven independent workstreams are required for this bounded integration ticket.",
        "why_current_team_is_insufficient": "The first four departments cannot own architecture, evidence, and audit deliverables simultaneously.",
        "expected_execution_gain": "Distinct owners reduce integration ambiguity and prevent repeated cross-role rework.",
        "coordination_cost_control": "Each department returns one structured output in bounded waves and exits after handoff.",
    })
    return confirmed


def complete_company(root: Path) -> None:
    company = cli_json(root, "company-status")["company_subagents"]
    for index, role in enumerate(company.get("missing_roles", [])):
        agent_id = f"stress-{role}-{index}"
        cli_json(root, "company-record", "--role", role, "--agent-id", agent_id, "--status", "STARTED")
        cli_json(root, "company-record", "--role", role, "--agent-id", agent_id, "--status", "COMPLETED", "--result-hash", f"stress-{role}-result")


def run_industry(case_id: str, goal: str) -> dict[str, Any]:
    started = time.monotonic()
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        copy_goal_compass_runtime(root)
        cli_json(root, "init")
        cli_json(root, "goal-set", "--text", goal)
        (root / "GOAL.md").write_text(f"# North Star\n{goal}\n", encoding="utf-8")
        install_catalog(root)

        heavy_verdicts: list[str] = []
        default_company_sizes: list[int] = []
        pass_count = 0

        for sequence in range(1, 5):
            path = write_ticket(root, make_ticket(case_id, goal, sequence))
            start = cli_json(root, "start", str(path.relative_to(root)))
            company = start["company_subagents"]
            default_company_sizes.append(int(company["min_subagents"]))
            if company["ceo_confirmation"]["status"] != "NOT_REQUIRED":
                raise AssertionError(f"automatic 0-4 roster unexpectedly requires CEO confirmation: {company}")
            if sequence == 1:
                routed = cli_json(root, "request", "--text", f"Build a full enterprise marketplace platform for {case_id} now")
                heavy_verdicts.append(str(routed["verdict"]))
                if routed["verdict"] == "ACCEPT_AS_IS" or routed.get("allowed_current_change"):
                    raise AssertionError(f"heavy request escaped gate for {case_id}: {routed}")
            write_artifact(root, case_id, sequence)
            checked = cli_json(root, "check")
            if checked["status"] != "PASS_READY":
                raise AssertionError(f"normal ticket not pass-ready for {case_id}: {checked}")
            prune = cli_json(root, "prune-check", expected={0, 1})
            if prune["status"] == "ARTIFACT_SPRAWL":
                raise AssertionError(f"core artifact misclassified for {case_id}: {prune}")
            closed = cli_json(root, "close")
            if closed["status"] != "PASS":
                raise AssertionError(f"normal ticket failed to close for {case_id}: {closed}")
            pass_count += 1

        axis = cli_json(root, "status")["axis_advisory"]
        if axis["status"] != "AXIS_FATIGUE_WARNING":
            raise AssertionError(f"same-axis fatigue not detected for {case_id}: {axis}")

        expanded = make_ticket(
            case_id,
            goal,
            5,
            requested_departments=["strategy", "business", "product", "engineering", "architecture", "qa", "auditor"],
            draft=True,
        )
        expanded_path = write_ticket(root, expanded)
        blocked = cli_json(root, "ready", str(expanded_path.relative_to(root)), expected={2})
        ceo = blocked["company_subagents"]["ceo_confirmation"]
        if ceo["status"] != "KEEP_CURRENT" or not ceo["confirmation_template"]:
            raise AssertionError(f"expanded company was not gated for {case_id}: {blocked}")
        expanded["company_ceo_confirmation"] = confirm_expansion(ceo["confirmation_template"])
        write_ticket(root, expanded)
        ready = cli_json(root, "ready", str(expanded_path.relative_to(root)))
        if ready["company_subagents"]["min_subagents"] != 7:
            raise AssertionError(f"expanded company count changed for {case_id}: {ready}")
        cli_json(root, "start", str(expanded_path.relative_to(root)))
        complete_company(root)
        write_artifact(root, case_id, 5)
        if cli_json(root, "close")["status"] != "PASS":
            raise AssertionError(f"CEO-confirmed ticket failed for {case_id}")
        pass_count += 1

        failing = make_ticket(case_id, goal, 6, validation_id="long_run_fail")
        failing_path = write_ticket(root, failing)
        cli_json(root, "start", str(failing_path.relative_to(root)))
        failed_check = cli_json(root, "check", "--run-validation")
        if failed_check["status"] != "VALIDATION_FAILED":
            raise AssertionError(f"validation failure was misrouted for {case_id}: {failed_check}")
        failed_close = cli_json(root, "close", expected={1})
        if failed_close["status"] != "NOT_CERTIFIED" or failed_close.get("ticket_status") != "ACTIVE":
            raise AssertionError(f"failed validation passed close for {case_id}: {failed_close}")
        repair_failed_validation(root)
        recovery = cli_json(root, "close")
        if recovery["status"] != "PASS":
            raise AssertionError(f"in-place validation recovery failed for {case_id}: {recovery}")
        pass_count += 1

        budget_path = write_ticket(root, make_ticket(case_id, goal, 8, diff_budget=1))
        cli_json(root, "start", str(budget_path.relative_to(root)))
        write_artifact(root, case_id, 8, lines=8)
        budget = cli_json(root, "check")
        if budget.get("budget_status") != "SOFT_CHANGE_PRESSURE":
            raise AssertionError(f"clean diff budget signal failed for {case_id}: {budget}")
        cli_json(root, "abort", "--reason", "long-run benchmark budget boundary", expected={1})

        noise = root / "src" / "security" / "rbac" / f"{case_id}_provider_marketplace.py"
        noise.parent.mkdir(parents=True, exist_ok=True)
        noise.write_text(
            f"Full enterprise RBAC provider marketplace compliance framework. {goal}\n",
            encoding="utf-8",
        )
        scan = cli_json(root, "onboard-scan", "--verbose", expected={0, 1})
        inventory = {row["artifact"]: row for row in scan["inventory"]}
        noise_path = noise.relative_to(root).as_posix()
        if inventory[noise_path]["classification"] == "PROTECTED":
            raise AssertionError(f"disguised long-run noise was protected for {case_id}: {inventory[noise_path]}")
        cli_json(root, "prune-plan", expected={0, 1})
        applied = cli_json(root, "prune-apply", "--confirm", expected={0, 1})
        if applied.get("deleted") or applied.get("moved") or not noise.exists():
            raise AssertionError(f"Janitor changed product files for {case_id}: {applied}")

        detected = cli_json(root, "goal-detect")
        if detected["project_detected_goal"] != goal:
            raise AssertionError(f"North Star changed after long run for {case_id}: {detected}")

        return {
            "industry": case_id,
            "elapsed_seconds": round(time.monotonic() - started, 4),
            "tickets_started": 8,
            "tickets_passed": pass_count,
            "validation_failures_blocked": 1,
            "budget_overruns_blocked": 1,
            "axis_fatigue_status": axis["status"],
            "heavy_request_verdicts": heavy_verdicts,
            "default_company_sizes": default_company_sizes,
            "expanded_company_size": 7,
            "janitor_deleted": False,
            "north_star_preserved": True,
        }


def run_stress(industry_cases: list[tuple[str, str]] | None = None) -> dict[str, Any]:
    started = time.monotonic()
    results = [run_industry(case_id, goal) for case_id, goal in (industry_cases or INDUSTRIES)]
    return {
        "status": "PASS",
        "industry_count": len(results),
        "ticket_count": sum(row["tickets_started"] for row in results),
        "elapsed_seconds": round(time.monotonic() - started, 4),
        "results": results,
    }


class LongRunIndustryStressTests(unittest.TestCase):
    def test_representative_industries_survive_full_ticket_lifecycle(self) -> None:
        # Keep the default verification suite fast. The standalone main() below
        # runs all 16 industries and writes the durable long-run report.
        report = run_stress(INDUSTRIES[:1])

        self.assertEqual(report["status"], "PASS")
        self.assertEqual(report["industry_count"], 1)
        self.assertEqual(report["ticket_count"], 8)
        self.assertTrue(all(row["axis_fatigue_status"] == "AXIS_FATIGUE_WARNING" for row in report["results"]))
        self.assertTrue(all(all(1 <= size <= 4 for size in row["default_company_sizes"]) for row in report["results"]))
        self.assertTrue(all(row["expanded_company_size"] == 7 for row in report["results"]))
        self.assertTrue(all(row["north_star_preserved"] for row in report["results"]))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out")
    args = parser.parse_args()
    report = run_stress()
    payload = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if args.out:
        Path(args.out).write_text(payload, encoding="utf-8")
    print(payload, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
