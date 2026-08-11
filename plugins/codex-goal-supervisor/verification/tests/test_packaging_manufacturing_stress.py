from __future__ import annotations

import argparse
import json
import re
import shutil
import tempfile
import time
import unittest
from pathlib import Path
from typing import Any

try:
    from .helpers import copy_goal_compass_runtime, run_goal_compass
except ImportError:
    from helpers import copy_goal_compass_runtime, run_goal_compass


PACKAGING_SECTORS = [
    {
        "id": "rigid_plastic",
        "goal": "Build a rigid plastic packaging manufacturing workflow for PET, HDPE, and PP containers with traceable material, molding, inspection, and lot-release evidence.",
        "operations": ["resin lot qualification", "preform dimension inspection", "wall thickness control", "closure torque test", "drop test", "food-contact release"],
        "future": "Add recycled resin sourcing optimization in a future bounded ticket",
        "critical": "food-contact migration limit release",
    },
    {
        "id": "flexible_film",
        "goal": "Build a flexible packaging manufacturing workflow for film, printing, lamination, curing, pouch conversion, barrier, residual-solvent, and seal evidence.",
        "operations": ["film gauge control", "print registration inspection", "lamination bond test", "curing release", "residual solvent test", "pouch seal window"],
        "future": "Add full recycled-film portfolio optimization in a future bounded ticket",
        "critical": "sterile barrier seal integrity release",
    },
    {
        "id": "corrugated",
        "goal": "Build a corrugated packaging workflow for board specification, ECT, BCT, conversion, printing, die cutting, joint strength, and shipment release.",
        "operations": ["paper incoming inspection", "ECT test", "BCT test", "print registration", "die-cut accuracy", "joint strength release"],
        "future": "Add network-wide carton optimization in a future bounded ticket",
        "critical": "dangerous goods packaging compression qualification",
    },
    {
        "id": "folding_carton",
        "goal": "Build a folding-carton manufacturing workflow for dielines, prepress, color, coating, foil, embossing, die cutting, gluing, and lot release.",
        "operations": ["dieline verification", "prepress proof", "color delta inspection", "foil registration", "die-cut accuracy", "glue seam release"],
        "future": "Add global artwork portfolio governance in a future bounded ticket",
        "critical": "pharmaceutical serialization label release",
    },
    {
        "id": "molded_fiber",
        "goal": "Build a molded-fiber packaging workflow for pulp recipe, forming, hot pressing, drying, dimensions, food contact, and lot release.",
        "operations": ["pulp recipe control", "forming weight inspection", "hot-press profile", "drying moisture test", "dimension inspection", "food-contact release"],
        "future": "Add global fiber sourcing optimization in a future bounded ticket",
        "critical": "food-contact migration limit release",
    },
    {
        "id": "textile_bags",
        "goal": "Build a textile packaging workflow for cotton, canvas, nonwoven, and woven bags with cutting, printing, sewing, strength, colorfastness, and lot evidence.",
        "operations": ["fabric weight inspection", "cutting dimension check", "print color control", "seam inspection", "handle tensile test", "colorfastness release"],
        "future": "Add global textile supplier scoring in a future bounded ticket",
        "critical": "packaging contamination control release",
    },
    {
        "id": "metal_food_can",
        "goal": "Build a metal food-can manufacturing workflow for sheet, coating, forming, body seam, double seam, corrosion, leakage, and lot release.",
        "operations": ["sheet coating inspection", "body forming control", "weld seam test", "double seam measurement", "corrosion test", "leakage release"],
        "future": "Add global metal procurement hedging in a future bounded ticket",
        "critical": "retort can double-seam integrity release",
    },
    {
        "id": "aerosol",
        "goal": "Build an aerosol packaging manufacturing workflow for can body, valve, crimp, leakage, burst pressure, and accountable batch release.",
        "operations": ["can dimension inspection", "valve incoming test", "crimp diameter control", "water-bath leak test", "pressure retention test", "burst release"],
        "future": "Add multi-plant aerosol capacity optimization in a future bounded ticket",
        "critical": "aerosol burst pressure release",
    },
    {
        "id": "glass",
        "goal": "Build a glass packaging manufacturing workflow for batch, forming, annealing, dimensions, thermal shock, internal pressure, closure fit, and lot release.",
        "operations": ["batch composition check", "forming dimension inspection", "annealing strain test", "thermal shock test", "internal pressure test", "closure fit release"],
        "future": "Add furnace network optimization in a future bounded ticket",
        "critical": "glass thermal shock and closure integrity release",
    },
    {
        "id": "aseptic_carton",
        "goal": "Build an aseptic composite-carton workflow for paper, polymer, foil, barrier, printing, lamination, sterilization, sealing, and sterile release.",
        "operations": ["paperboard qualification", "foil pinhole inspection", "lamination bond test", "print registration", "sterilization evidence", "seal integrity release"],
        "future": "Add global aseptic line scheduling in a future bounded ticket",
        "critical": "sterile barrier seal integrity release",
    },
    {
        "id": "labels_printing",
        "goal": "Build a packaging label and printing workflow for artwork, ink, adhesive, color, registration, durability, migration, traceability, and release evidence.",
        "operations": ["artwork verification", "ink batch qualification", "color delta inspection", "registration inspection", "adhesion test", "traceability release"],
        "future": "Add enterprise artwork marketplace in a future bounded ticket",
        "critical": "allergen label accuracy release",
    },
    {
        "id": "wooden_transit",
        "goal": "Build a wooden transit-packaging workflow for timber, design load, assembly, cushioning, phytosanitary evidence, and shipment release.",
        "operations": ["timber incoming inspection", "design load check", "fastener inspection", "cushioning validation", "mark verification", "shipment release"],
        "future": "Add global pallet pooling optimization in a future bounded ticket",
        "critical": "ISPM-15 phytosanitary release",
    },
    {
        "id": "protective_foam",
        "goal": "Build a protective packaging workflow for foam and honeycomb design, material density, cushioning curves, vibration, drop, and shipment release.",
        "operations": ["density inspection", "cushioning curve test", "design fit check", "vibration test", "drop test", "shipment protection release"],
        "future": "Add universal protective packaging configurator in a future bounded ticket",
        "critical": "dangerous goods packaging qualification",
    },
    {
        "id": "compostable",
        "goal": "Build a compostable packaging workflow for resin or fiber claims, converting, barrier, food contact, compostability evidence, labeling, and lot release.",
        "operations": ["material claim verification", "conversion control", "barrier test", "food-contact test", "compostability evidence", "label claim release"],
        "future": "Add global environmental-claim platform in a future bounded ticket",
        "critical": "food-contact migration limit release",
    },
]


def cli_json(root: Path, *args: str, expected: set[int] | None = None) -> dict[str, Any]:
    proc = run_goal_compass(list(args), root)
    if proc.returncode not in (expected or {0}):
        raise AssertionError(f"goal_compass {args} rc={proc.returncode}\n{proc.stdout}\n{proc.stderr}")
    return json.loads(proc.stdout)


def slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_")[:48]


def ticket_for(sector: dict[str, Any], sequence: int, operation: str, *, validation_id: str | None = None, diff_budget: int = 320) -> dict[str, Any]:
    artifact = f"src/{sector['id']}/{sequence:02d}_{slug(operation)}.py"
    return {
        "ticket_id": f"{sector['id'].upper()}-{sequence:02d}",
        "title": f"{sector['id']} manufacturing evidence {sequence}",
        "global_goal": sector["goal"],
        "why_now": f"Produce one machine-checkable {operation} result without expanding the manufacturing system.",
        "task_goal": f"Implement one bounded {sector['id']} {operation} result with lot traceability.",
        "status": "DRAFT",
        "acceptance_ready": False,
        "must_do": [f"Record the {operation} result", "Include lot_id and disposition"],
        "must_not_do": ["Do not build a full ERP, MES, WMS, RBAC, or supplier marketplace"],
        "anti_patterns": ["full ERP", "full MES", "WMS platform", "enterprise RBAC", "supplier marketplace"],
        "allowed_paths": [f"src/{sector['id']}/**", f"tests/{sector['id']}/**"],
        "forbidden_paths": [".agent/**", ".codex/**", ".git/**", "src/platform/**"],
        "acceptance": {
            "commands_pass": [validation_id] if validation_id else [],
            "files_exist": [] if validation_id else [artifact],
            "contains": [],
            "assertions": [],
            "files_not_changed": [],
            "max_changed_files": 6,
            "max_diff_lines": 1200,
        },
        "validation_ids": [validation_id] if validation_id else [],
        "budget": {"max_minutes": 45, "max_tool_calls": 60, "max_changed_files": 6, "max_diff_lines": diff_budget},
        "drift_signals": ["Starts building enterprise systems", "Keeps expanding after the bounded release evidence exists"],
        "backlog_only": [sector["future"], "Full ERP", "Full MES", "WMS", "Enterprise RBAC", "Supplier marketplace"],
        "requested_company_departments": [],
        "company_ceo_confirmation": {},
    }


def write_ticket(root: Path, ticket: dict[str, Any]) -> Path:
    path = root / ".agent" / "tickets" / "pending" / f"{ticket['ticket_id']}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(ticket, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return path


def write_artifact(root: Path, sector: dict[str, Any], sequence: int, operation: str, lines: int = 2) -> Path:
    path = root / "src" / sector["id"] / f"{sequence:02d}_{slug(operation)}.py"
    path.parent.mkdir(parents=True, exist_ok=True)
    body = [f'"""Bounded {operation} evidence."""', f"RESULT = {{'lot_id': 'LOT-{sequence:02d}', 'disposition': 'PASS'}}"]
    while len(body) < lines:
        body.append(f"EVIDENCE_{len(body)} = 'bounded'")
    path.write_text("\n".join(body) + "\n", encoding="utf-8")
    return path


def install_catalog(root: Path) -> None:
    path = root / ".agent" / "validation_catalog.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    data["packaging_fail"] = {"cmd": "{python} -c \"import sys; sys.exit(1)\"", "description": "Deterministic packaging stress failure.", "timeout_sec": 3}
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def repair_failed_validation(root: Path) -> None:
    path = root / ".agent" / "validation_catalog.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    data["packaging_fail"]["cmd"] = "{python} -c \"import sys; sys.exit(0)\""
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def confirm_expansion(template: dict[str, Any]) -> dict[str, Any]:
    confirmed = dict(template)
    confirmed.update({
        "status": "CONFIRMED",
        "decision": "EXPAND",
        "reason": "Eight independent packaging workstreams are required for this critical release ticket.",
        "why_current_team_is_insufficient": "The base roster cannot separately own material, plant handoff, and quality evidence.",
        "expected_execution_gain": "Independent evidence owners reduce release ambiguity and prevent repeated handoff rework.",
        "coordination_cost_control": "Each department returns one bounded structured artifact in two waves and then exits.",
    })
    return confirmed


def complete_company(root: Path) -> None:
    company = cli_json(root, "company-status")["company_subagents"]
    for index, role in enumerate(company.get("missing_roles", [])):
        agent_id = f"packaging-{role}-{index}"
        cli_json(root, "company-record", "--role", role, "--agent-id", agent_id, "--status", "STARTED")
        cli_json(root, "company-record", "--role", role, "--agent-id", agent_id, "--status", "COMPLETED", "--result-hash", f"packaging-{role}-result")


def run_sector(sector: dict[str, Any]) -> dict[str, Any]:
    started = time.monotonic()
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        copy_goal_compass_runtime(root)
        cli_json(root, "init")
        cli_json(root, "goal-set", "--text", sector["goal"])
        (root / "GOAL.md").write_text("# North Star Goal\n\n" + sector["goal"] + "\n", encoding="utf-8")
        install_catalog(root)

        pass_count = 0
        request_counts = {"core": 0, "future": 0, "heavy": 0, "acceptance": 0}
        default_sizes: list[int] = []

        for sequence, operation in enumerate(sector["operations"], 1):
            ticket = ticket_for(sector, sequence, operation)
            path = write_ticket(root, ticket)
            ready = cli_json(root, "ready", str(path.relative_to(root)))
            if not ready["ok"]:
                raise AssertionError(f"ready failed for {sector['id']} {operation}: {ready}")
            start = cli_json(root, "start", str(path.relative_to(root)))
            company = start["company_subagents"]
            default_sizes.append(int(company["min_subagents"]))
            if company["min_subagents"] != 4 or company["ceo_confirmation"]["status"] != "NOT_REQUIRED":
                raise AssertionError(f"default company mismatch: {company}")

            if sequence <= 3:
                requests = {
                    "core": f"Record the current {operation} result with lot_id",
                    "future": sector["future"],
                    "heavy": f"Build a full ERP MES WMS RBAC supplier marketplace now for {operation}",
                    "acceptance": f"Complete the {operation} acceptance assertion",
                }
                for kind, text in requests.items():
                    routed = cli_json(root, "request", "--text", text, expected={0, 1})
                    if kind in {"core", "acceptance"}:
                        if routed["verdict"] != "ACCEPT_AS_IS" or not routed["allowed_current_change"]:
                            raise AssertionError(f"current request rejected for {sector['id']}: {routed}")
                    else:
                        if routed["verdict"] == "ACCEPT_AS_IS" or routed["allowed_current_change"]:
                            raise AssertionError(f"future/heavy request escaped for {sector['id']}: {routed}")
                    request_counts[kind] += 1

            write_artifact(root, sector, sequence, operation)
            checked = cli_json(root, "check")
            if checked["status"] != "PASS_READY":
                raise AssertionError(f"ticket not pass ready: {checked}")
            prune = cli_json(root, "prune-check", expected={0, 1})
            if prune["status"] == "ARTIFACT_SPRAWL":
                raise AssertionError(f"core packaging artifact marked shit mountain: {prune}")
            if cli_json(root, "close")["status"] != "PASS":
                raise AssertionError(f"close failed for {sector['id']} {operation}")
            pass_count += 1

        axis = cli_json(root, "status")["axis_advisory"]
        if axis["status"] != "OK":
            raise AssertionError(f"distinct packaging operations falsely triggered axis fatigue for {sector['id']}: {axis}")

        expanded = ticket_for(sector, 7, sector["critical"])
        expanded["company_escalation_evidence"] = ["max insufficient after two prior failures"]
        expanded["requested_company_departments"] = [
            "strategy", "business", "product", "engineering", "qa",
            "materials",
            {"name": "operations", "responsibility": "Check the bounded plant handoff.", "workspace_access": "read_only"},
            "quality",
        ]
        expanded_path = write_ticket(root, expanded)
        blocked = cli_json(root, "ready", str(expanded_path.relative_to(root)), expected={2})
        policy = blocked["company_subagents"]
        strategy_effort = policy["strategy_effort"]
        if policy["min_subagents"] != 8 or policy["ceo_confirmation"]["status"] != "KEEP_CURRENT":
            raise AssertionError(f"CEO gate missing: {policy}")
        if policy["complexity_tier"] != "T3_CRITICAL" or strategy_effort != "max":
            raise AssertionError(f"packaging consequence routing failed: {policy}")

        expanded["company_ceo_confirmation"] = confirm_expansion(policy["ceo_confirmation"]["confirmation_template"])
        expanded["requested_company_departments"][6]["workspace_access"] = "allowed_paths_writer"
        write_ticket(root, expanded)
        invalidated = cli_json(root, "ready", str(expanded_path.relative_to(root)), expected={2})
        if invalidated["company_subagents"]["ceo_confirmation"]["status"] != "PENDING":
            raise AssertionError("CEO confirmation survived workspace authority change")
        expanded["company_ceo_confirmation"] = confirm_expansion(invalidated["company_subagents"]["ceo_confirmation"]["confirmation_template"])
        write_ticket(root, expanded)
        cli_json(root, "ready", str(expanded_path.relative_to(root)))
        cli_json(root, "start", str(expanded_path.relative_to(root)))
        complete_company(root)
        write_artifact(root, sector, 7, sector["critical"])
        if cli_json(root, "close")["status"] != "PASS":
            raise AssertionError("CEO-expanded packaging ticket failed")
        pass_count += 1

        failing = ticket_for(sector, 8, "deterministic validation failure", validation_id="packaging_fail")
        failing_path = write_ticket(root, failing)
        cli_json(root, "ready", str(failing_path.relative_to(root)))
        cli_json(root, "start", str(failing_path.relative_to(root)))
        failed = cli_json(root, "check", "--run-validation")
        if failed["status"] != "VALIDATION_FAILED":
            raise AssertionError(f"validation failure escaped: {failed}")
        failed_close = cli_json(root, "close", expected={1})
        if failed_close["status"] != "NOT_CERTIFIED" or failed_close.get("ticket_status") != "ACTIVE":
            raise AssertionError("validation failure passed close")
        repair_failed_validation(root)
        if cli_json(root, "close")["status"] != "PASS":
            raise AssertionError("in-place validation recovery failed")
        pass_count += 1

        budget = ticket_for(sector, 10, "clean budget overrun", diff_budget=1)
        budget_path = write_ticket(root, budget)
        cli_json(root, "ready", str(budget_path.relative_to(root)))
        cli_json(root, "start", str(budget_path.relative_to(root)))
        write_artifact(root, sector, 10, "clean budget overrun", lines=10)
        budget_result = cli_json(root, "check")
        if budget_result.get("budget_status") != "SOFT_CHANGE_PRESSURE":
            raise AssertionError(f"budget status mismatch: {budget_result}")
        cli_json(root, "abort", "--reason", "packaging stress budget boundary", expected={1})

        noise = root / "src" / "platform" / f"{sector['id']}_supplier_marketplace.py"
        noise.parent.mkdir(parents=True, exist_ok=True)
        noise.write_text(f"Full ERP MES WMS RBAC supplier marketplace. {sector['goal']}\n", encoding="utf-8")
        scan = cli_json(root, "onboard-scan", "--verbose", expected={0, 1})
        inventory = {row["artifact"]: row for row in scan["inventory"]}
        noise_key = noise.relative_to(root).as_posix()
        if inventory[noise_key]["classification"] == "PROTECTED":
            raise AssertionError(f"packaging platform noise protected: {inventory[noise_key]}")
        cli_json(root, "prune-plan", expected={0, 1})
        applied = cli_json(root, "prune-apply", "--confirm", expected={0, 1})
        if applied.get("deleted") or applied.get("moved") or not noise.exists():
            raise AssertionError(f"Janitor changed packaging files: {applied}")

        detected = cli_json(root, "goal-detect")
        if detected["project_detected_goal"] != sector["goal"]:
            raise AssertionError(f"North Star changed: {detected}")

        return {
            "sector": sector["id"],
            "elapsed_seconds": round(time.monotonic() - started, 4),
            "tickets_started": len(sector["operations"]) + 4,
            "tickets_passed": pass_count,
            "validation_failures_blocked": 1,
            "budget_overruns_blocked": 1,
            "request_counts": request_counts,
            "default_company_sizes": default_sizes,
            "expanded_company_size": 8,
            "strategy_effort": strategy_effort,
            "axis_fatigue": axis["status"],
            "janitor_non_destructive": True,
            "north_star_preserved": True,
        }


def run_stress(sectors: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    started = time.monotonic()
    rows = [run_sector(sector) for sector in (sectors or PACKAGING_SECTORS)]
    return {
        "status": "PASS",
        "sector_count": len(rows),
        "ticket_count": sum(row["tickets_started"] for row in rows),
        "request_count": sum(sum(row["request_counts"].values()) for row in rows),
        "elapsed_seconds": round(time.monotonic() - started, 4),
        "results": rows,
    }


class PackagingManufacturingStressTests(unittest.TestCase):
    def test_representative_packaging_sectors_survive_long_run(self) -> None:
        representative = dict(PACKAGING_SECTORS[0])
        representative["operations"] = representative["operations"][:3]
        report = run_stress([representative])

        self.assertEqual(report["status"], "PASS")
        self.assertEqual(report["sector_count"], 1)
        self.assertEqual(report["ticket_count"], 7)
        self.assertTrue(all(row["default_company_sizes"] == [4, 4, 4] for row in report["results"]))
        self.assertTrue(all(row["expanded_company_size"] == 8 for row in report["results"]))
        self.assertTrue(all(row["strategy_effort"] == "max" for row in report["results"]))


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
