from __future__ import annotations

import json
import time
from unittest import mock

try:
    from .helpers import GOAL_COMPASS, GoalCompassRepoCase
except ImportError:
    from helpers import GOAL_COMPASS, GoalCompassRepoCase


class StatusTests(GoalCompassRepoCase):
    def test_status_reports_no_active_ticket(self) -> None:
        result = self.json_run("status")

        self.assertFalse(result["active"])
        self.assertEqual(result["axis_advisory"]["status"], "OK")
        self.assertEqual(result["backlog"]["count"], 0)
        self.assertEqual(result["mdcp"]["current_required_action"], "continue_normal_execution")
        self.assertNotIn("tool_mode", result)
        self.assertEqual(result["status"], "NEEDS_CONFIRMATION")

    def test_status_reports_goal_definition_and_preservation_policy(self) -> None:
        self.json_run(
            "goal-set",
            "--text", "Build a traceable packaging release workflow.",
            "--problem", "Release evidence is fragmented.",
            "--first-principle", "Every release maps to evidence.",
            "--action", "Connect lot tests to release results.",
            "--deliverable", "A runnable release workflow.",
            "--success-criterion", "One lot produces a reproducible result.",
        )

        result = self.json_run("status", "--verbose")

        self.assertEqual(result["north_star"]["definition"]["quality"], "STRUCTURED")
        self.assertEqual(
            result["north_star"]["preservation_policy"],
            "existing_goal_is_read_only_unless_user_explicitly_replaces_it",
        )

    def test_status_terminal_ticket_does_not_say_continue(self) -> None:
        ticket = self.read_json(".agent/tickets/examples/VIDEO-MOCK-001.json")
        ticket["status"] = "DRIFT"
        ticket["budget_used"] = {"tool_calls": 3, "changed_files": [], "diff_lines": 0}
        self.write_json(".agent/current_ticket.json", ticket)

        result = self.json_run("status", "--verbose")

        self.assertFalse(result["active"])
        self.assertEqual(result["mdcp"]["current_required_action"], "continue_normal_execution")

    def test_status_reports_active_ticket(self) -> None:
        self.start_video()

        result = self.json_run("status", "--verbose")

        self.assertTrue(result["active"])
        self.assertEqual(result["current_ticket"]["ticket_id"], "VIDEO-MOCK-001")
        company = result["mdcp"]["company_subagents"]
        self.assertFalse(company["required"])
        self.assertEqual(company["min_subagents"], 0)
        self.assertEqual(company["runtime_binding"], "not_required")
        self.assertTrue(company["runtime_execution_verified"])

    def test_status_defaults_to_compact_summary_and_verbose_keeps_details(self) -> None:
        self.start_video()

        compact = self.cli("status")
        detailed = self.cli("status", "--verbose")
        summary = json.loads(compact.stdout)
        verbose = json.loads(detailed.stdout)

        self.assertLess(len(compact.stdout.encode("utf-8")), 2200)
        self.assertNotIn("feedback", summary)
        self.assertNotIn("reuse", summary)
        self.assertNotIn("company_subagents", summary["mdcp"])
        self.assertNotIn("goal_return", summary)
        self.assertIn("feedback", verbose)
        self.assertIn("reuse", verbose)
        self.assertIn("goal_return", verbose)
        self.assertIn("company_subagents", verbose["mdcp"])

    def test_status_warns_on_repeated_local_axis(self) -> None:
        done = self.root / ".agent" / "tickets" / "done"
        done.mkdir(parents=True, exist_ok=True)
        for idx in range(4):
            ticket = self.read_json(".agent/tickets/examples/VIDEO-MOCK-001.json")
            ticket["ticket_id"] = f"QA-AXIS-{idx}"
            ticket["title"] = f"QA planned_checks schema propagation {idx}"
            ticket["task_goal"] = "Propagate planned_checks into QA report schema examples."
            self.write_json(f".agent/tickets/done/QA-AXIS-{idx}.json", ticket)

        result = self.json_run("status")

        self.assertEqual(result["axis_advisory"]["status"], "AXIS_FATIGUE_WARNING")
        self.assertIn("planned checks", result["axis_advisory"]["repeated_concepts"])

    def test_axis_fatigue_clears_after_distinct_packaging_operations(self) -> None:
        done = self.root / ".agent" / "tickets" / "done"
        done.mkdir(parents=True, exist_ok=True)
        operations = [
            "batch composition",
            "forming dimensions",
            "annealing strain",
            "thermal shock",
            "internal pressure",
            "closure fit",
        ]
        for index, operation in enumerate(operations):
            ticket = self.read_json(".agent/tickets/examples/VIDEO-MOCK-001.json")
            ticket["ticket_id"] = f"GLASS-AXIS-{index}"
            ticket["title"] = f"Glass {operation} evidence"
            ticket["task_goal"] = f"Implement one bounded glass {operation} result."
            ticket["allowed_paths"] = ["src/glass/**", "tests/glass/**"]
            self.write_json(f".agent/tickets/done/GLASS-AXIS-{index}.json", ticket)

        result = self.json_run("status")

        self.assertEqual(result["axis_advisory"]["status"], "OK")

    def test_axis_fatigue_ignores_north_star_and_quality_template_words(self) -> None:
        self.cli(
            "goal-set",
            "--text",
            "Build a bounded label quality workflow covering pressure labels, shrink sleeves, ink migration, allergens, barcode, and color controls.",
        )
        done = self.root / ".agent" / "tickets" / "done"
        done.mkdir(parents=True, exist_ok=True)
        operations = ["pressure label", "shrink sleeve", "ink migration", "allergen", "barcode", "color delta"]
        for index, operation in enumerate(operations):
            ticket = self.read_json(".agent/tickets/examples/VIDEO-MOCK-001.json")
            ticket["ticket_id"] = f"LABEL-AXIS-{index}"
            ticket["title"] = f"Label quality verification {operation}"
            ticket["task_goal"] = (
                f"Validate only the pre-seeded {operation} JSON evidence artifact for a token. "
                "This bounded ticket must not issue a real production batch decision."
            )
            ticket["allowed_paths"] = [f"src/rules/{index}_{operation.replace(' ', '_')}.json"]
            self.write_json(f".agent/tickets/done/LABEL-AXIS-{index}.json", ticket)

        result = self.json_run("status")

        self.assertEqual(result["axis_advisory"]["status"], "OK")

    def test_tool_budget_pressure_is_advisory(self) -> None:
        self.start_video()
        ticket = self.read_json(".agent/current_ticket.json")
        ticket["budget_used"]["tool_calls"] = ticket["budget"]["max_tool_calls"] + 1
        ticket["budget_used"]["budget_enforcement"] = "CONNECTED_VERIFIED"
        self.write_json(".agent/current_ticket.json", ticket)

        result = self.json_run("check", check=False)

        self.assertEqual(result["status"], "NEEDS_VALIDATION")
        self.assertEqual(result["budget_status"], "SOFT_CHANGE_PRESSURE")
        self.assertTrue(any("tool_calls" in reason for reason in result["budget_advisories"]))

    def test_axis_fatigue_does_not_block_current_ticket_close(self) -> None:
        self.goal_video()
        done = self.root / ".agent" / "tickets" / "done"
        done.mkdir(parents=True, exist_ok=True)
        for idx in range(4):
            ticket = self.read_json(".agent/tickets/examples/VIDEO-MOCK-001.json")
            ticket["ticket_id"] = f"VIDEO-AXIS-{idx}"
            ticket["title"] = f"Mock video artifact path {idx}"
            ticket["task_goal"] = f"Complete mock video artifact path {idx}."
            self.write_json(f".agent/tickets/done/VIDEO-AXIS-{idx}.json", ticket)

        ticket = self.read_json(".agent/tickets/examples/VIDEO-MOCK-001.json")
        ticket["ticket_id"] = "VIDEO-AXIS-CURRENT"
        ticket["acceptance"]["commands_pass"] = []
        ticket["validation_ids"] = []
        ticket["acceptance"]["files_exist"] = ["src/video/mock/result.ts"]
        self.write_json(".agent/tickets/pending/VIDEO-AXIS-CURRENT.json", ticket)
        self.json_run("start", ".agent/tickets/pending/VIDEO-AXIS-CURRENT.json")
        target = self.root / "src" / "video" / "mock" / "result.ts"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("export const result = 'mock artifact';\n", encoding="utf-8")

        self.complete_company_runtime()
        checked = self.json_run("check")
        closed = self.json_run("close")

        self.assertEqual(checked["status"], "PASS_READY")
        self.assertIn(
            checked["mdcp"]["layer_3_janitor_auditor"]["auditor"]["required_action"],
            {"close", "close_then_switch_axis"},
        )
        self.assertEqual(closed["status"], "PASS")

    def test_validation_failure_has_priority_over_axis_fatigue(self) -> None:
        self.install_validation("axis_failure", "import sys; sys.exit(1)")
        self.goal_video()
        done = self.root / ".agent" / "tickets" / "done"
        done.mkdir(parents=True, exist_ok=True)
        for idx in range(4):
            ticket = self.read_json(".agent/tickets/examples/VIDEO-MOCK-001.json")
            ticket["ticket_id"] = f"FAILED-AXIS-{idx}"
            self.write_json(f".agent/tickets/done/FAILED-AXIS-{idx}.json", ticket)
        ticket = self.make_validation_ticket("axis_failure")
        ticket["ticket_id"] = "AXIS-VALIDATION-FAIL"
        self.write_json(".agent/tickets/pending/AXIS-VALIDATION-FAIL.json", ticket)
        self.json_run("start", ".agent/tickets/pending/AXIS-VALIDATION-FAIL.json")

        result = self.json_run("check", "--run-validation", check=False)

        self.assertEqual(result["status"], "VALIDATION_FAILED")
        self.assertEqual(
            result["mdcp"]["layer_3_janitor_auditor"]["auditor"]["required_action"],
            "fix_validation",
        )

    def test_clean_diff_budget_overage_is_advisory(self) -> None:
        self.goal_video()
        ticket = self.read_json(".agent/tickets/examples/VIDEO-MOCK-001.json")
        ticket["budget"]["max_diff_lines"] = 1
        ticket["acceptance"]["max_diff_lines"] = 1000
        self.write_json(".agent/tickets/pending/DIFF-BUDGET.json", ticket)
        self.cli("start", ".agent/tickets/pending/DIFF-BUDGET.json")
        target = self.root / "src" / "video" / "mock" / "big.ts"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("\n".join(["export const ok = 'mock artifact';"] * 5), encoding="utf-8")

        result = self.json_run("check", check=False)

        self.assertEqual(result["status"], "NEEDS_VALIDATION")
        self.assertEqual(result["budget_status"], "SOFT_CHANGE_PRESSURE")
        self.assertTrue(any("diff_lines" in reason for reason in result["budget_advisories"]))

    def test_status_reads_cached_metadata_without_running_full_evaluation(self) -> None:
        self.start_video()
        checked = self.json_run("check")
        self.assertEqual(checked["status"], "NEEDS_VALIDATION")

        started = time.perf_counter()
        with mock.patch.object(GOAL_COMPASS, "evaluate", side_effect=AssertionError("status must not audit")):
            proc = self.cli("status")
        elapsed = time.perf_counter() - started
        result = json.loads(proc.stdout)

        self.assertLess(elapsed, 0.5)
        self.assertEqual(result["current_ticket"]["last_check"]["status"], "NEEDS_VALIDATION")
        self.assertLessEqual(len(proc.stdout.splitlines()), 30)

    def test_status_before_first_check_requests_check_without_scanning(self) -> None:
        self.start_video()

        with mock.patch.object(GOAL_COMPASS, "evaluate", side_effect=AssertionError("status must not audit")):
            result = self.json_run("status")

        self.assertEqual(result["current_ticket"]["last_check"]["status"], "ACTIVE_UNCHECKED")
        self.assertEqual(result["mdcp"]["current_required_action"], "check")
