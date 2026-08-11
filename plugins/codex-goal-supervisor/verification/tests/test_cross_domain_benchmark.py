from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from pathlib import Path

try:
    from .helpers import copy_goal_compass_runtime, run_goal_compass
except ImportError:
    from helpers import copy_goal_compass_runtime, run_goal_compass


CASES = [
    ("quant", "Build a multi-market quantitative trading control system with research, portfolio decisions, execution, risk controls, and reproducible backtests.", "src/trading/portfolio.py"),
    ("video", "Build an AI video production system that turns prompts into traceable video artifacts and creator-visible results.", "src/video/pipeline.py"),
    ("geometry", "Build a product geometry operating system for dieline parsing, structured GLB modeling, texture alignment, and professional quality validation.", "src/geometry/pipeline.py"),
    ("healthcare", "Build a hospital bed-capacity planning tool that forecasts demand, coordinates transfers, and produces auditable daily plans.", "src/capacity/planner.py"),
    ("legal", "Build a legal matter intelligence service that preserves privilege boundaries and links evidence to human-reviewable claims.", "src/matters/timeline.py"),
    ("education", "Build an adaptive learning workflow that diagnoses skill gaps, assigns bounded practice, and gives teachers evidence-backed progress views.", "src/learning/diagnostics.py"),
    ("supply-chain", "Build a supply-chain control tower that detects shortages, explains constraints, and recommends operator-reviewable recovery plans.", "src/supply/recovery.py"),
    ("robotics", "Build a warehouse robotics orchestration system with safe task planning, simulation validation, fleet telemetry, and operator takeover.", "src/robotics/orchestrator.py"),
    ("knowledge", "Build an enterprise knowledge service that ingests trusted sources, preserves citations, answers questions, and exposes freshness gaps.", "src/knowledge/retrieval.py"),
    ("game", "Build a cooperative game backend with deterministic sessions, player progression, matchmaking, and replayable acceptance scenarios.", "src/game/session.py"),
    ("science", "Build a scientific computing pipeline that runs reproducible simulations, tracks parameters, validates numerical stability, and publishes datasets.", "src/science/simulation.py"),
    ("privacy", "Build a privacy-preserving data collaboration service with consent-aware ingestion, lineage, minimization, and auditable exports.", "src/privacy/lineage.py"),
    ("design", "Build a design production system that turns briefs into constrained assets, keeps brand rules, and records visual QA evidence.", "src/design/production.py"),
    ("iot", "Build an industrial IoT maintenance system that ingests sensor signals, predicts failures, and produces technician-verifiable work orders.", "src/iot/maintenance.py"),
    ("risk", "Build a financial risk monitoring service that reconciles exposures, explains limit breaches, and preserves regulator-ready evidence.", "src/risk/exposure.py"),
    ("content", "Build a content operations platform that plans, produces, reviews, publishes, and measures reusable editorial assets.", "src/content/workflow.py"),
    ("agriculture", "Build a precision agriculture assistant that combines field observations, weather, and crop models into explainable action plans.", "src/agriculture/advice.py"),
    ("energy", "Build a distributed energy operations system that forecasts load, schedules flexible assets, and validates grid-safe dispatch plans.", "src/energy/dispatch.py"),
]


class CrossDomainBenchmarkTests(unittest.TestCase):
    def test_eighteen_large_goals_preserve_core_and_do_not_protect_disguised_noise(self) -> None:
        predictions = 0
        for case_id, goal, core_path in CASES:
            with self.subTest(domain=case_id), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                copy_goal_compass_runtime(root)
                self.assertEqual(run_goal_compass(["init"], root).returncode, 0)
                self.assertEqual(run_goal_compass(["goal-set", "--text", goal], root).returncode, 0)
                (root / "GOAL.md").write_text(f"# North Star\n{goal}\n", encoding="utf-8")

                core = root / core_path
                core.parent.mkdir(parents=True)
                core.write_text(f"Current acceptance implementation for {case_id}.\n", encoding="utf-8")
                copied = root / "archive" / "copied-goal.md"
                copied.parent.mkdir(parents=True)
                copied.write_text(goal + "\n", encoding="utf-8")
                noise = root / "src" / "security" / "rbac" / "provider_marketplace.py"
                noise.parent.mkdir(parents=True)
                noise.write_text(f"Full RBAC provider marketplace compliance framework. {goal}\n", encoding="utf-8")

                ticket = {
                    "ticket_id": f"{case_id.upper()}-001",
                    "title": f"{case_id} bounded slice",
                    "global_goal": goal,
                    "why_now": "Advance one end-to-end product slice.",
                    "task_goal": f"Implement the current {case_id} acceptance path.",
                    "status": "ACTIVE",
                    "acceptance_ready": True,
                    "must_do": [f"Implement {core_path}"],
                    "must_not_do": ["Do not build a full RBAC provider marketplace"],
                    "anti_patterns": ["RBAC", "provider marketplace", "compliance framework"],
                    "allowed_paths": [core_path, "tests/**"],
                    "forbidden_paths": [".agent/**", ".codex/**"],
                    "acceptance": {
                        "commands_pass": [],
                        "files_exist": [core_path],
                        "contains": [],
                        "assertions": [],
                        "files_not_changed": [".agent/**"],
                        "max_changed_files": 4,
                        "max_diff_lines": 300,
                    },
                    "validation_ids": [],
                    "budget": {"max_minutes": 45, "max_tool_calls": 40, "max_changed_files": 4, "max_diff_lines": 300},
                    "drift_signals": ["Starts building a generic enterprise platform"],
                    "backlog_only": ["Full RBAC", "provider marketplace", "compliance framework"],
                    "budget_used": {"tool_calls": 0, "changed_files": [], "diff_lines": 0},
                }
                (root / ".agent" / "current_ticket.json").write_text(
                    json.dumps(ticket, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8",
                )

                detected_proc = run_goal_compass(["goal-detect"], root)
                self.assertEqual(detected_proc.returncode, 0)
                detected = json.loads(detected_proc.stdout)
                self.assertEqual(detected["project_detected_goal"], goal)

                scan_proc = run_goal_compass(["onboard-scan", "--verbose"], root)
                self.assertEqual(scan_proc.returncode, 0)
                inventory = {row["artifact"]: row for row in json.loads(scan_proc.stdout)["inventory"]}
                self.assertEqual(inventory[core_path]["classification"], "PROTECTED")
                self.assertEqual(inventory["archive/copied-goal.md"]["classification"], "REVIEW_REQUIRED", inventory["archive/copied-goal.md"])
                self.assertNotEqual(inventory["src/security/rbac/provider_marketplace.py"]["classification"], "PROTECTED")
                self.assertIn(
                    inventory["src/security/rbac/provider_marketplace.py"]["classification"],
                    {"QUARANTINE_CANDIDATE", "REVIEW_REQUIRED", "BACKLOG_CANDIDATE"},
                )
                predictions += 3

        self.assertEqual(predictions, 54)


if __name__ == "__main__":
    unittest.main()
