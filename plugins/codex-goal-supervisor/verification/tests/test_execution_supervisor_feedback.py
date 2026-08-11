from __future__ import annotations

import contextlib
import tempfile
from pathlib import Path

try:
    from .helpers import GOAL_COMPASS, GoalCompassRepoCase, run_cmd
except ImportError:
    from helpers import GOAL_COMPASS, GoalCompassRepoCase, run_cmd


class ExecutionSupervisorFeedbackTests(GoalCompassRepoCase):
    def simple_file_ticket(self, ticket_id: str, path: str = "src/result.txt") -> dict:
        ticket = self.read_json(".agent/tickets/examples/VIDEO-MOCK-001.json")
        ticket["ticket_id"] = ticket_id
        ticket["status"] = "PENDING"
        ticket["acceptance_ready"] = True
        ticket["allowed_paths"] = [path]
        ticket.pop("writable_paths", None)
        ticket["acceptance"] = {
            "commands_pass": [],
            "files_exist": [path],
            "contains": [],
            "assertions": [],
            "files_not_changed": [],
            "max_changed_files": 5,
            "max_diff_lines": 300,
        }
        ticket["validation_ids"] = []
        ticket["budget"] = {"max_minutes": 30, "max_tool_calls": 40, "max_changed_files": 5, "max_diff_lines": 300}
        return ticket

    def test_validation_pass_is_reused_by_close_when_inputs_do_not_change(self) -> None:
        self.goal_video()
        catalog = self.read_json(".agent/validation_catalog.json")
        catalog["count_once"] = {
            "argv": [
                "{python}",
                "-c",
                "from pathlib import Path; p=Path('.agent/runtime/validation-count.txt'); p.parent.mkdir(parents=True, exist_ok=True); p.write_text(str(int(p.read_text())+1) if p.exists() else '1')",
            ],
            "timeout_sec": 8,
        }
        self.write_json(".agent/validation_catalog.json", catalog)
        ticket = self.make_validation_ticket("count_once")
        ticket["ticket_id"] = "VALIDATION-CACHE-001"
        self.write_json(".agent/tickets/pending/VALIDATION-CACHE-001.json", ticket)
        self.json_run("start", ".agent/tickets/pending/VALIDATION-CACHE-001.json")
        self.complete_company_runtime()

        checked = self.json_run("check", "--run-validation")
        closed = self.json_run("close")

        self.assertEqual(checked["status"], "PASS_READY")
        self.assertEqual(closed["status"], "PASS")
        self.assertTrue(closed["validation"]["cache_hit"])
        self.assertEqual((self.root / ".agent/runtime/validation-count.txt").read_text(), "1")

    def test_completed_company_receipt_auto_records_started_and_survives_start(self) -> None:
        self.goal_video()
        ticket = self.read_json(".agent/tickets/examples/VIDEO-MOCK-001.json")
        ticket["ticket_id"] = "PRESTART-COMPANY-001"
        ticket["requested_company_departments"] = ["product"]
        path = ".agent/tickets/pending/PRESTART-COMPANY-001.json"
        self.write_json(path, ticket)
        self.json_run("ready", path)
        ticket = self.read_json(path)
        policy = ticket["mdcp"]["layer_2_company_subagents"]
        role = policy["required_subagents"][0]["role"]

        recorded = self.json_run(
            "company-record", "--ticket", path, "--role", role, "--agent-id", "planning-agent",
            "--status", "COMPLETED", "--summary", "bounded planning result",
        )
        self.assertIsNotNone(recorded["auto_started_receipt"])
        pending = self.read_json(path)
        self.assertEqual([row["status"] for row in pending["company_runtime"]["receipts"]], ["STARTED", "COMPLETED"])

        self.json_run("start", path)
        company = self.json_run("company-status")["company_subagents"]
        self.assertEqual(company["role_status"][role]["status"], "COMPLETED")

    def test_non_git_small_edit_uses_real_line_delta(self) -> None:
        self.goal_video()
        path = self.root / "src/big.py"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("".join(f"value_{index} = {index}\n" for index in range(900)), encoding="utf-8")
        ticket = self.simple_file_ticket("NON-GIT-DIFF-001", "src/big.py")
        ticket["budget"]["max_diff_lines"] = 10
        ticket["acceptance"]["max_diff_lines"] = 10
        self.write_json(".agent/tickets/pending/NON-GIT-DIFF-001.json", ticket)
        self.json_run("start", ".agent/tickets/pending/NON-GIT-DIFF-001.json")

        lines = path.read_text(encoding="utf-8").splitlines()
        lines[450] = "value_450 = 999"
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        result = self.json_run("check")

        self.assertNotIn(result["status"], {"BUDGET_EXCEEDED", "DIFF_BUDGET_EXCEEDED_CLEAN"})
        self.assertLessEqual(self.read_json(".agent/current_ticket.json")["budget_used"]["diff_lines"], 2)

    def test_runtime_sqlite_change_is_environment_not_product_drift(self) -> None:
        self.goal_video()
        target = self.root / "src/result.txt"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("ready\n", encoding="utf-8")
        ticket = self.simple_file_ticket("RUNTIME-STATE-001")
        ticket["runtime_paths"] = ["data/**"]
        self.write_json(".agent/tickets/pending/RUNTIME-STATE-001.json", ticket)
        self.json_run("start", ".agent/tickets/pending/RUNTIME-STATE-001.json")
        runtime = self.root / "data/runtime.sqlite"
        runtime.parent.mkdir(parents=True, exist_ok=True)
        runtime.touch()

        result = self.json_run("check")

        self.assertEqual(result["status"], "IMPLEMENTATION_PASS_ENVIRONMENT_DIRTY")
        self.assertEqual(result["environment_status"], "DIRTY_RUNTIME_ONLY")
        self.assertNotIn("data/runtime.sqlite", self.read_json(".agent/current_ticket.json")["budget_used"]["changed_files"])

    def test_nonempty_sqlite_churn_is_runtime_without_explicit_runtime_path(self) -> None:
        import sqlite3

        self.goal_video()
        target = self.root / "src/result.txt"
        database = self.root / "var/runtime.sqlite"
        target.parent.mkdir(parents=True, exist_ok=True)
        database.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("ready\n", encoding="utf-8")
        with contextlib.closing(sqlite3.connect(database)) as connection:
            with connection:
                connection.execute("create table events(id integer primary key, value text)")
                connection.execute("insert into events(value) values ('baseline')")
        ticket = self.simple_file_ticket("IMPLICIT-RUNTIME-SQLITE-001")
        self.write_json(".agent/tickets/pending/IMPLICIT-RUNTIME-SQLITE-001.json", ticket)
        self.commit_paths(".")
        self.json_run("start", ".agent/tickets/pending/IMPLICIT-RUNTIME-SQLITE-001.json")
        with contextlib.closing(sqlite3.connect(database)) as connection:
            with connection:
                connection.execute("insert into events(value) values ('runtime update')")

        result = self.json_run("check")
        usage = self.read_json(".agent/current_ticket.json")["budget_used"]

        self.assertEqual(result["status"], "IMPLEMENTATION_PASS_ENVIRONMENT_DIRTY")
        self.assertEqual(usage["runtime_changes"], ["var/runtime.sqlite"])
        self.assertNotIn("var/runtime.sqlite", usage["changed_files"])

    def test_explicit_writable_database_remains_product_scope(self) -> None:
        self.goal_video()
        ticket = self.simple_file_ticket("WRITABLE-DATABASE-001", "fixtures/result.db")
        self.write_json(".agent/tickets/pending/WRITABLE-DATABASE-001.json", ticket)
        self.json_run("start", ".agent/tickets/pending/WRITABLE-DATABASE-001.json")
        target = self.root / "fixtures/result.db"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b"fixture database artifact")

        result = self.json_run("check")
        usage = self.read_json(".agent/current_ticket.json")["budget_used"]

        self.assertEqual(result["status"], "PASS_READY")
        self.assertIn("fixtures/result.db", usage["changed_files"])
        self.assertNotIn("fixtures/result.db", usage["runtime_changes"])

    def test_git_runtime_diff_does_not_count_product_lines(self) -> None:
        self.goal_video()
        target = self.root / "src/result.txt"
        runtime = self.root / "data/runtime.sqlite"
        target.parent.mkdir(parents=True, exist_ok=True)
        runtime.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("ready\n", encoding="utf-8")
        runtime.write_text("runtime-v1\n", encoding="utf-8")
        ticket = self.simple_file_ticket("GIT-RUNTIME-STATE-001")
        ticket["runtime_paths"] = ["data/**"]
        self.write_json(".agent/tickets/pending/GIT-RUNTIME-STATE-001.json", ticket)
        run_cmd(["git", "init"], cwd=self.root, check=True)
        run_cmd(["git", "config", "user.email", "goal-compass@example.invalid"], cwd=self.root, check=True)
        run_cmd(["git", "config", "user.name", "Goal Compass Test"], cwd=self.root, check=True)
        run_cmd(["git", "add", "."], cwd=self.root, check=True)
        run_cmd(["git", "commit", "-m", "baseline"], cwd=self.root, check=True)
        self.json_run("start", ".agent/tickets/pending/GIT-RUNTIME-STATE-001.json")
        runtime.write_text("runtime-v2\nextra-runtime-row\n", encoding="utf-8")

        result = self.json_run("check")
        usage = self.read_json(".agent/current_ticket.json")["budget_used"]

        self.assertEqual(result["status"], "IMPLEMENTATION_PASS_ENVIRONMENT_DIRTY")
        self.assertEqual(usage["diff_lines"], 0)
        self.assertEqual(usage["runtime_changes"], ["data/runtime.sqlite"])

    def test_read_dependency_change_is_upstream_evidence_invalid(self) -> None:
        self.goal_video()
        target = self.root / "src/result.txt"
        dependency = self.root / "foundation/input.json"
        target.parent.mkdir(parents=True, exist_ok=True)
        dependency.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("ready\n", encoding="utf-8")
        dependency.write_text('{"version": 1}\n', encoding="utf-8")
        ticket = self.simple_file_ticket("UPSTREAM-INVALID-001")
        ticket["read_dependencies"] = ["foundation/input.json"]
        self.write_json(".agent/tickets/pending/UPSTREAM-INVALID-001.json", ticket)
        self.json_run("start", ".agent/tickets/pending/UPSTREAM-INVALID-001.json")
        dependency.write_text('{"version": 2}\n', encoding="utf-8")

        result = self.json_run("check", check=False)

        self.assertEqual(result["status"], "UPSTREAM_EVIDENCE_INVALID")
        self.assertEqual(result["suggested_action"], "supersede_or_rebaseline_upstream")

    def test_compiled_change_budget_is_soft_but_scope_remains_bounded(self) -> None:
        self.goal_video()
        (self.root / "rough.md").write_text("Implement one small output file for the current product result.\n", encoding="utf-8")
        path = ".agent/tickets/pending/SOFT-BUDGET-001.json"
        self.json_run("compile", "rough.md", "--out", path)
        ticket = self.read_json(path)
        ticket["ticket_id"] = "SOFT-BUDGET-001"
        ticket["global_goal"] = "Build an AI automatic video generation system."
        ticket["allowed_paths"] = ["src/result.txt"]
        ticket["writable_paths"] = ["src/result.txt"]
        ticket["acceptance"]["files_exist"] = ["src/result.txt"]
        ticket["budget"]["max_diff_lines"] = 20
        ticket["acceptance"]["max_diff_lines"] = 20
        self.write_json(path, ticket)
        self.json_run("ready", path)
        self.json_run("start", path)
        target = self.root / "src/result.txt"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("\n".join(f"line {index}" for index in range(220)) + "\n", encoding="utf-8")

        result = self.json_run("check")

        self.assertEqual(result["status"], "PASS_READY")
        self.assertEqual(result["budget_status"], "SOFT_CHANGE_PRESSURE")
        self.assertTrue(result["budget_advisories"])

    def test_artifact_quality_gate_requires_explicit_evidence(self) -> None:
        self.goal_video()
        ticket = self.simple_file_ticket("QUALITY-GATE-001", "outputs/result.mp4")
        ticket["quality_gates"] = [{
            "id": "publishable-video",
            "dimension": "artifact",
            "required": True,
            "evidence_types": ["artifact"],
        }]
        self.write_json(".agent/tickets/pending/QUALITY-GATE-001.json", ticket)
        self.json_run("start", ".agent/tickets/pending/QUALITY-GATE-001.json")
        output = self.root / "outputs/result.mp4"
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(b"mock-video")

        blocked = self.json_run("check", check=False)
        self.assertEqual(blocked["status"], "NEEDS_QUALITY_EVIDENCE")
        self.assertFalse(blocked["quality"]["artifact_quality_pass"])

        self.json_run(
            "evidence-add", "--type", "artifact", "--source", "artifact-quality-check",
            "--summary", "Visual and encoding checks passed", "--path", "outputs/result.mp4",
            "--acceptance-id", "publishable-video",
        )
        passed = self.json_run("check")
        self.assertEqual(passed["status"], "PASS_READY")
        self.assertTrue(passed["quality"]["artifact_quality_pass"])

    def test_request_operation_is_bilingual_and_mutation_aware(self) -> None:
        self.goal_video()

        english = self.json_run("request", "--text", "Inspect the current validation status without changes")
        chinese = self.json_run("request", "--text", "只读核查当前验收状态，不要修改")

        self.assertEqual(english["verdict"], "ACCEPT_READ_ONLY")
        self.assertEqual(chinese["verdict"], "ACCEPT_READ_ONLY")

    def test_equivalent_bilingual_mutation_requests_route_the_same(self) -> None:
        self.goal_video()
        ticket = self.simple_file_ticket("BILINGUAL-MUTATION-001", "src/parser.py")
        ticket["task_goal"] = "Fix parser validation behavior."
        ticket["must_do"] = ["Fix parser validation behavior."]
        self.write_json(".agent/tickets/pending/BILINGUAL-MUTATION-001.json", ticket)
        self.json_run("start", ".agent/tickets/pending/BILINGUAL-MUTATION-001.json")

        english = self.json_run("request", "--text", "Review and fix the current parser validation behavior")
        chinese = self.json_run("request", "--text", "检查并修复当前解析器验证行为")

        self.assertEqual(english["verdict"], "ACCEPT_AS_IS")
        self.assertEqual(chinese["verdict"], english["verdict"])
        self.assertEqual(chinese["allowed_current_change"], english["allowed_current_change"])

    def test_phase_can_complete_once_with_passing_ticket(self) -> None:
        self.goal_video()
        self.json_run("phase-set", "--id", "MVP-1", "--goal", "Prove one bounded output", "--exit-criterion", "Ticket passes")
        ticket = self.simple_file_ticket("PHASE-CLOSE-001")
        ticket["program_phase_id"] = "MVP-1"
        ticket["phase_completion"] = {"complete_on_pass": True}
        self.write_json(".agent/tickets/pending/PHASE-CLOSE-001.json", ticket)
        self.json_run("start", ".agent/tickets/pending/PHASE-CLOSE-001.json")
        target = self.root / "src/result.txt"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("done\n", encoding="utf-8")
        self.complete_company_runtime()

        closed = self.json_run("close")

        self.assertEqual(closed["status"], "PASS")
        self.assertEqual(closed["program_phase"]["status"], "COMPLETED")
        self.assertEqual(self.read_json(".agent/program_phase.json")["completed_by_ticket_id"], "PHASE-CLOSE-001")

    def test_default_check_is_compact_and_verbose_retains_full_diagnostics(self) -> None:
        self.start_video()

        compact = self.json_run("check")
        verbose = self.json_run("check", "--verbose")

        self.assertNotIn("mdcp_audit", compact)
        self.assertNotIn("mdcp_contract", compact)
        self.assertIn("mdcp_audit", verbose)
        self.assertIn("mdcp_contract", verbose)

    def test_runtime_checkpoint_is_visible_without_granting_kill_authority(self) -> None:
        self.start_video()

        self.json_run(
            "evidence-add", "--type", "runtime", "--source", "long-render",
            "--summary", "render checkpoint", "--owner", "VIDEO-MOCK-001", "--pid", "1234",
            "--port", "8188", "--checkpoint-id", "prompt-42", "--resume-command", "resume --id prompt-42",
            "--resource", "gpu:0", "--resource", "port:8188",
        )
        checkpoint = self.json_run("status", "--verbose")["current_ticket"]["runtime_checkpoint"]

        self.assertEqual(checkpoint["checkpoint_id"], "prompt-42")
        self.assertEqual(checkpoint["resources"], ["gpu:0", "port:8188"])
        self.assertEqual(checkpoint["authority"], "evidence_only_no_cross_task_kill_authority")

    def test_ready_preflight_reports_all_missing_inputs(self) -> None:
        self.goal_video()
        catalog = self.read_json(".agent/validation_catalog.json")
        catalog["missing_tool"] = {"argv": ["definitely-not-installed-goal-compass-tool"], "timeout_sec": 8}
        self.write_json(".agent/validation_catalog.json", catalog)
        ticket = self.make_validation_ticket("missing_tool")
        ticket["ticket_id"] = "PREFLIGHT-ALL-001"
        ticket["status"] = "DRAFT"
        ticket["acceptance_ready"] = False
        ticket["read_dependencies"] = ["foundation/one.json", "foundation/two.json"]
        self.write_json(".agent/tickets/pending/PREFLIGHT-ALL-001.json", ticket)

        result = self.json_run("ready", ".agent/tickets/pending/PREFLIGHT-ALL-001.json", check=False)
        errors = "\n".join(result["errors"])

        self.assertIn("validation executable unavailable", errors)
        self.assertIn("foundation/one.json", errors)
        self.assertIn("foundation/two.json", errors)

    def test_ready_resolves_existing_external_read_dependency(self) -> None:
        self.goal_video()
        with tempfile.TemporaryDirectory(prefix="goal-supervisor-external-read-", dir=self.root.parent) as external_dir:
            dependency = Path(external_dir) / "utility_api.pyi"
            dependency.write_text("def exported_api() -> None: ...\n", encoding="utf-8")
            ticket = self.read_json(".agent/tickets/examples/VIDEO-MOCK-001.json")
            ticket["ticket_id"] = "EXTERNAL-READ-001"
            ticket["read_dependencies"] = [str(dependency)]
            path = ".agent/tickets/pending/EXTERNAL-READ-001.json"
            self.write_json(path, ticket)

            ready = self.json_run("ready", path)

        self.assertTrue(ready["ok"])
        self.assertEqual(ready["preflight"]["status"], "READY")

    def test_windows_external_dependency_token_restores_drive_path(self) -> None:
        restored = GOAL_COMPASS.filesystem_path(
            "__outside_repo__/I:/sheji ruanjian/CLO Standalone OnlineAuth/ApiStubFiles/utility_api.pyi"
        )
        self.assertEqual(
            str(restored).replace("\\", "/"),
            "I:/sheji ruanjian/CLO Standalone OnlineAuth/ApiStubFiles/utility_api.pyi",
        )

    def test_ready_allows_existing_immutable_acceptance_evidence(self) -> None:
        self.goal_video()
        evidence = self.root / "deliveries" / "evidence" / "receipt.json"
        evidence.parent.mkdir(parents=True, exist_ok=True)
        evidence.write_text('{"status":"verified"}\n', encoding="utf-8")
        ticket = self.simple_file_ticket("IMMUTABLE-EVIDENCE-001")
        ticket["acceptance"]["files_exist"] = ["deliveries/evidence/receipt.json"]
        ticket["acceptance"]["files_not_changed"] = ["deliveries/evidence/receipt.json"]
        ticket["immutable_paths"] = ["deliveries/evidence/receipt.json"]
        path = ".agent/tickets/pending/IMMUTABLE-EVIDENCE-001.json"
        self.write_json(path, ticket)

        ready = self.json_run("ready", path)

        self.assertTrue(ready["ok"])
        self.assertEqual(ready["preflight"]["status"], "READY")

    def test_company_receipts_invalidate_only_changed_role_contract(self) -> None:
        self.goal_video()
        ticket = self.read_json(".agent/tickets/examples/VIDEO-MOCK-001.json")
        ticket["ticket_id"] = "ROLE-DELTA-001"
        ticket["requested_company_departments"] = [
            {"name": "engineering", "acceptance_criteria": ["Implementation result is machine-checkable."]},
            {"name": "qa", "acceptance_criteria": ["Validation evidence names the tested behavior."]},
        ]
        path = ".agent/tickets/pending/ROLE-DELTA-001.json"
        self.write_json(path, ticket)
        self.json_run("ready", path)
        for role in ["engineering", "qa"]:
            self.json_run(
                "company-record", "--ticket", path, "--role", role,
                "--agent-id", f"agent-{role}", "--status", "COMPLETED",
                "--summary", f"{role} result",
            )

        changed = self.read_json(path)
        changed["requested_company_departments"][1]["acceptance_criteria"] = [
            "Validation evidence names the tested behavior and its failure mode."
        ]
        self.write_json(path, changed)
        refreshed = self.json_run("ready", path)

        company = refreshed["company_subagents"]
        self.assertEqual(company["role_status"]["engineering"]["status"], "COMPLETED")
        self.assertEqual(company["role_status"]["qa"]["status"], "NOT_STARTED")
        self.assertEqual(company["invalidated_roles"], ["qa"])
        self.assertEqual(company["preserved_roles"], ["engineering"])

    def test_company_failure_receipt_preserves_failure_semantics(self) -> None:
        self.goal_video()
        ticket = self.read_json(".agent/tickets/examples/VIDEO-MOCK-001.json")
        ticket["ticket_id"] = "ROLE-FAILURE-CLASS-001"
        ticket["requested_company_departments"] = ["qa"]
        path = ".agent/tickets/pending/ROLE-FAILURE-CLASS-001.json"
        self.write_json(path, ticket)
        self.json_run("ready", path)
        role = self.read_json(path)["mdcp"]["layer_2_company_subagents"]["required_subagents"][0]["role"]

        self.json_run(
            "company-record", "--ticket", path, "--role", role,
            "--agent-id", "agent-runtime-failure", "--status", "FAILED",
            "--failure-class", "RUNTIME_FAILURE", "--summary", "worker process was interrupted",
        )
        company = self.json_run("ready", path)["company_subagents"]

        self.assertEqual(company["role_status"][role]["status"], "RUNTIME_FAILURE")
        self.assertEqual(company["role_status"][role]["latest_failure_class"], "RUNTIME_FAILURE")
        self.assertEqual(company["role_status"][role]["recommended_action"], "retry_role_runtime")

    def test_untracked_cad_binary_does_not_consume_text_diff_lines(self) -> None:
        self.goal_video()
        ticket = self.simple_file_ticket("CAD-BINARY-BUDGET-001", "cad/parts/body.SLDPRT")
        ticket["budget"]["max_diff_lines"] = 5
        ticket["acceptance"]["max_diff_lines"] = 5
        self.write_json(".agent/tickets/pending/CAD-BINARY-BUDGET-001.json", ticket)
        self.json_run("start", ".agent/tickets/pending/CAD-BINARY-BUDGET-001.json")
        part = self.root / "cad" / "parts" / "body.SLDPRT"
        part.parent.mkdir(parents=True, exist_ok=True)
        part.write_bytes((b"\x00CAD-PART\n" * 2000) + b"END")

        result = self.json_run("check")
        usage = self.read_json(".agent/current_ticket.json")["budget_used"]

        self.assertNotIn(result["status"], {"BUDGET_EXCEEDED", "DIFF_BUDGET_EXCEEDED_CLEAN"})
        self.assertEqual(usage["diff_lines"], 0)
        self.assertEqual(usage["binary_artifacts_changed"], ["cad/parts/body.SLDPRT"])

    def test_active_execution_contract_freezes_writable_scope(self) -> None:
        self.goal_video()
        ticket = self.simple_file_ticket("FULL-CONTRACT-FREEZE-001")
        self.write_json(".agent/tickets/pending/FULL-CONTRACT-FREEZE-001.json", ticket)
        self.json_run("start", ".agent/tickets/pending/FULL-CONTRACT-FREEZE-001.json")
        active = self.read_json(".agent/current_ticket.json")
        active["allowed_paths"] = ["src/**"]
        active["writable_paths"] = ["src/**"]
        self.write_json(".agent/current_ticket.json", active)

        result = self.json_run("check", check=False)

        self.assertEqual(result["status"], "FAIL")
        self.assertTrue(any("execution contract changed" in reason for reason in result["reasons"]))

    def test_active_execution_contract_witnesses_source_ticket_bytes(self) -> None:
        self.goal_video()
        ticket = self.simple_file_ticket("SOURCE-WITNESS-001")
        path = ".agent/tickets/pending/SOURCE-WITNESS-001.json"
        self.write_json(path, ticket)
        self.json_run("start", path)
        source = self.read_json(path)
        source["why_now"] = "mutated after activation"
        self.write_json(path, source)

        result = self.json_run("check", check=False)

        self.assertEqual(result["status"], "FAIL")
        self.assertTrue(any("source ticket bytes changed" in reason for reason in result["reasons"]))


if __name__ == "__main__":
    import unittest

    unittest.main()
