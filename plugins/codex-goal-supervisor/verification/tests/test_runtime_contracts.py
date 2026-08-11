from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest import mock

try:
    from .helpers import GOAL_COMPASS, GoalCompassRepoCase, pushd, run_cmd
except ImportError:
    from helpers import GOAL_COMPASS, GoalCompassRepoCase, pushd, run_cmd


class RuntimeContractTests(GoalCompassRepoCase):
    def test_post_hook_records_state_without_running_full_evaluation(self) -> None:
        self.start_video()
        event = {
            "hook_event_name": "PostToolUse",
            "tool_use_id": "lightweight-hook",
            "tool_name": "apply_patch",
            "tool_input": {"patch": "*** Begin Patch\n*** Add File: src/video/mock/light.ts\n+x\n*** End Patch"},
        }

        with pushd(self.root), mock.patch.object(GOAL_COMPASS, "evaluate", side_effect=AssertionError("hook must stay lightweight")):
            pre_event = dict(event)
            pre_event["hook_event_name"] = "PreToolUse"
            self.assertEqual(GOAL_COMPASS.hook_pre(pre_event), 0)
            self.assertEqual(GOAL_COMPASS.hook_post(event), 0)

        status = self.json_run("status", "--verbose")
        self.assertEqual(status["hook"]["status"], "CONNECTED_VERIFIED")
        self.assertEqual(status["current_ticket"]["budget_used"]["tool_calls"], 1)

    def _start_file_ticket(self, ticket_id: str = "RUNTIME-CONTRACT-001", *, require_company: bool = False) -> Path:
        self.goal_video()
        ticket = self.read_json(".agent/tickets/examples/VIDEO-MOCK-001.json")
        ticket["ticket_id"] = ticket_id
        ticket["acceptance"]["commands_pass"] = []
        ticket["validation_ids"] = []
        ticket["acceptance"]["files_exist"] = ["src/video/mock/result.ts"]
        if require_company:
            ticket["requested_company_departments"] = ["engineering"]
        path = f".agent/tickets/pending/{ticket_id}.json"
        self.write_json(path, ticket)
        self.json_run("start", path)
        target = self.root / "src" / "video" / "mock" / "result.ts"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("export const result = 'mock artifact';\n", encoding="utf-8")
        return target

    def _post_hook(self, event_id: str, tool: str, tool_input: dict | None = None) -> None:
        event = {
            "hook_event_name": "PostToolUse",
            "tool_use_id": event_id,
            "tool_name": tool,
            "tool_input": tool_input or {},
        }
        proc = run_cmd(
            [sys.executable, ".agent/goal_compass.py", "hook"],
            cwd=self.root,
            input_text=json.dumps(event),
            check=True,
        )
        self.assertEqual(proc.returncode, 0)

    def test_terminal_ticket_is_archived_and_no_longer_scopes_requests(self) -> None:
        self._start_file_ticket()
        self.complete_company_runtime()

        closed = self.json_run("close")
        request = self.json_run("request", "--text", "Add one AI video generation mock artifact assertion")

        self.assertEqual(closed["status"], "PASS")
        self.assertEqual(self.read_json(".agent/current_ticket.json")["status"], "NONE")
        self.assertEqual(self.read_json(".agent/last_ticket.json")["ticket_id"], "RUNTIME-CONTRACT-001")
        self.assertFalse((self.root / ".agent/tickets/pending/RUNTIME-CONTRACT-001.json").exists())
        self.assertTrue((self.root / ".agent/tickets/done/RUNTIME-CONTRACT-001.json").exists())
        self.assertIsNone(request["active_ticket"])
        self.assertEqual(request["verdict"], "PROPOSE_NEW_TICKET")

    def test_terminal_history_is_immutable_and_ticket_id_cannot_restart(self) -> None:
        self._start_file_ticket("IMMUTABLE-001")
        self.complete_company_runtime()
        self.json_run("close")
        ticket = self.read_json(".agent/tickets/examples/VIDEO-MOCK-001.json")
        ticket["ticket_id"] = "IMMUTABLE-001"
        self.write_json(".agent/tickets/pending/IMMUTABLE-001.json", ticket)

        result = self.json_run("start", ".agent/tickets/pending/IMMUTABLE-001.json", check=False)

        self.assertFalse(result["ok"])
        self.assertIn("already exists", result["error"])

    def test_hook_health_is_unknown_until_post_event_then_counts_once(self) -> None:
        self.start_video()
        before = self.json_run("status", "--verbose")
        self.assertEqual(before["hook"]["status"], "DISCONNECTED")
        self.assertIsNone(before["current_ticket"]["budget_used"]["tool_calls"])

        self._post_hook("read-1", "Read", {"path": "README.md"})
        self._post_hook("write-1", "apply_patch", {"patch": "*** Begin Patch\n*** End Patch"})
        self._post_hook("agent-1", "spawn_agent", {"role": "qa"})
        self._post_hook("agent-1", "spawn_agent", {"role": "qa"})

        after = self.json_run("status", "--verbose")
        doctor = self.json_run("doctor")
        usage = after["current_ticket"]["budget_used"]
        self.assertEqual(after["hook"]["status"], "CONNECTED_VERIFIED")
        self.assertEqual(doctor["hook"]["status"], "CONNECTED_VERIFIED")
        self.assertEqual(usage["tool_calls"], 3)
        self.assertEqual(usage["tool_calls_by_type"]["read"], 1)
        self.assertEqual(usage["tool_calls_by_type"]["write"], 1)
        self.assertEqual(usage["tool_calls_by_type"]["agent"], 1)

    def test_connected_hook_tool_budget_is_advisory(self) -> None:
        self.goal_video()
        ticket = self.read_json(".agent/tickets/examples/VIDEO-MOCK-001.json")
        ticket["ticket_id"] = "HOOK-BUDGET-001"
        ticket["budget"]["max_tool_calls"] = 1
        self.write_json(".agent/tickets/pending/HOOK-BUDGET-001.json", ticket)
        self.json_run("start", ".agent/tickets/pending/HOOK-BUDGET-001.json")
        self._post_hook("call-1", "Read", {"path": "README.md"})
        self._post_hook("call-2", "Read", {"path": "GOAL.md"})

        result = self.json_run("check", check=False)

        self.assertEqual(result["status"], "NEEDS_VALIDATION")
        self.assertTrue(any("tool_calls 2 > 1" in reason for reason in result["budget_advisories"]))

    def test_company_receipts_are_optional_but_preserve_failure_retry(self) -> None:
        self._start_file_ticket("COMPANY-RECEIPTS-001", require_company=True)
        company_before = self.json_run("company-status")["company_subagents"]
        self.assertFalse(company_before["required"])
        self.assertTrue(company_before["recommended"])
        roles = company_before["required_roles"]
        first = roles[0]
        self.json_run("company-record", "--role", first, "--agent-id", "failed-agent", "--status", "STARTED")
        self.json_run("company-record", "--role", first, "--agent-id", "failed-agent", "--status", "FAILED", "--summary", "model route unavailable")
        self.json_run("company-record", "--role", first, "--agent-id", "fallback-agent", "--status", "STARTED")
        self.json_run("company-record", "--role", first, "--agent-id", "fallback-agent", "--status", "COMPLETED", "--result-hash", "fallback-result")
        for role in roles[1:]:
            self.json_run("company-record", "--role", role, "--agent-id", f"agent-{role}", "--status", "COMPLETED", "--result-hash", f"result-{role}")

        company = self.json_run("company-status")["company_subagents"]
        closed = self.json_run("close")
        archived = self.read_json(".agent/tickets/done/COMPANY-RECEIPTS-001.json")
        self.assertTrue(company["runtime_execution_verified"])
        self.assertEqual(company["role_status"][first]["failed_attempts"], 1)
        self.assertEqual(closed["status"], "PASS")
        self.assertTrue(any(row["status"] == "FAILED" for row in archived["company_runtime"]["receipts"]))

    def test_evidence_is_hashed_and_archived_with_ticket(self) -> None:
        target = self._start_file_ticket("EVIDENCE-001")
        added = self.json_run(
            "evidence-add", "--type", "browser", "--source", "manual-browser-check",
            "--summary", "Rendered result was visible", "--path", str(target.relative_to(self.root)),
        )
        self.complete_company_runtime()
        self.json_run("close")
        archived = self.read_json(".agent/tickets/done/EVIDENCE-001.json")
        self.assertTrue(added["evidence"]["sha256"])
        self.assertEqual(archived["evidence"][0]["type"], "browser")

    def test_validation_lifecycle_always_runs_teardown(self) -> None:
        self.goal_video()
        flag = "src/video/mock/service.flag"
        commands = {
            "service_setup": "from pathlib import Path; Path('src/video/mock').mkdir(parents=True, exist_ok=True); Path('src/video/mock/service.flag').write_text('up')",
            "service_health": "from pathlib import Path; import sys; sys.exit(0 if Path('src/video/mock/service.flag').exists() else 1)",
            "service_fail": "import sys; sys.exit(1)",
            "service_teardown": "from pathlib import Path; p=Path('src/video/mock/service.flag'); p.unlink() if p.exists() else None",
        }
        for command_id, code in commands.items():
            self.install_validation(command_id, code)
        ticket = self.make_validation_ticket("service_fail")
        ticket["ticket_id"] = "SERVICE-LIFECYCLE-001"
        ticket["validation_lifecycle"] = {"setup": ["service_setup"], "healthcheck": ["service_health"], "teardown": ["service_teardown"]}
        self.write_json(".agent/tickets/pending/SERVICE-LIFECYCLE-001.json", ticket)
        self.json_run("start", ".agent/tickets/pending/SERVICE-LIFECYCLE-001.json")
        self.complete_company_runtime()

        closed = self.json_run("close", check=False)

        self.assertEqual(closed["status"], "NOT_CERTIFIED")
        self.assertEqual(closed["ticket_status"], "ACTIVE")
        self.assertFalse((self.root / flag).exists())

    def test_program_phase_is_separate_request_provenance(self) -> None:
        self.goal_video()
        self.json_run("phase-set", "--id", "MVP-1", "--goal", "Prove prompt to mock artifact", "--exit-criterion", "Mock artifact test passes")

        request = self.json_run("request", "--text", "Audit the existing repository status only")

        self.assertEqual(request["verdict"], "ACCEPT_READ_ONLY")
        self.assertEqual(request["program_phase"]["phase_id"], "MVP-1")
        self.assertEqual(request["provenance"]["program_phase_id"], "MVP-1")

    def test_prune_scope_is_explicit_without_active_ticket(self) -> None:
        self.goal_video()
        noise = self.root / "src" / "security" / "rbac" / "full.ts"
        noise.parent.mkdir(parents=True, exist_ok=True)
        noise.write_text("Full enterprise RBAC marketplace platform.\n", encoding="utf-8")

        current = self.json_run("prune-check")
        full = self.json_run("prune-plan", "--scope", "full-repo", check=False)

        self.assertEqual(current["status"], "NOT_APPLICABLE")
        self.assertEqual(full["scope"], "full-repo")
        self.assertTrue(any(row["target"] == "src/security/rbac/full.ts" for row in full["items"]))
