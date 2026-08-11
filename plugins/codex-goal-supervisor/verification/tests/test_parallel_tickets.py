from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from pathlib import Path

from verification.tests.helpers import copy_goal_compass_runtime, run_cmd, run_goal_compass


class ParallelTicketTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.template_tmp = tempfile.TemporaryDirectory()
        cls.template = Path(cls.template_tmp.name) / "main"
        copy_goal_compass_runtime(cls.template)
        init = run_goal_compass(["init"], cwd=cls.template)
        if init.returncode != 0:
            raise AssertionError(init.stdout + init.stderr)
        goal = run_goal_compass(
            ["goal-set", "--text", "Build one modular product with independently deliverable frontend and backend components."],
            cwd=cls.template,
        )
        if goal.returncode != 0:
            raise AssertionError(goal.stdout + goal.stderr)
        helper = cls(methodName="runTest")
        helper.write_contract(cls.template)
        for args in [
            ["git", "init", "-b", "main"],
            ["git", "config", "user.email", "goal-compass@example.invalid"],
            ["git", "config", "user.name", "Goal Compass Test"],
            ["git", "add", "."],
            ["git", "commit", "-m", "fixture"],
        ]:
            run_cmd(args, cwd=cls.template, timeout=8, check=True)

    @classmethod
    def tearDownClass(cls) -> None:
        cls.template_tmp.cleanup()

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp.name)
        self.main = self.base / "main"
        self.lane_a = self.base / "lane-a"
        self.lane_b = self.base / "lane-b"
        shutil.copytree(self.template, self.main)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def cli(self, cwd: Path, *args: str, check: bool = True):
        result = run_goal_compass(list(args), cwd=cwd)
        if check and result.returncode != 0:
            raise AssertionError(f"goal_compass {args} failed\nSTDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}")
        return result

    def json_cli(self, cwd: Path, *args: str, check: bool = True) -> dict:
        result = self.cli(cwd, *args, check=check)
        return json.loads(result.stdout)

    def git(self, *args: str, cwd: Path):
        return run_cmd(["git", *args], cwd=cwd, timeout=8, check=True)

    def ensure_worktrees(self) -> None:
        if not self.lane_a.exists():
            self.git("worktree", "add", "-b", "lane-a", str(self.lane_a), cwd=self.main)
        if not self.lane_b.exists():
            self.git("worktree", "add", "-b", "lane-b", str(self.lane_b), cwd=self.main)

    def write_contract(
        self,
        root: Path,
        *,
        contract_id: str = "WAVE-1",
        serial: int = 90,
        parallel: int = 40,
        coordination: int = 8,
        integration: int = 10,
    ) -> Path:
        path = root / ".agent" / "contracts" / "WAVE-1.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "contract_id": contract_id,
            "version": 1,
            "efficiency_case": {
                "estimated_serial_minutes": serial,
                "estimated_parallel_minutes": parallel,
                "coordination_minutes": coordination,
                "integration_minutes": integration,
            },
            "independence_evidence": {
                "dependency_edges": [],
                "writable_scopes_disjoint": True,
                "shared_surface": "interfaces and data contract",
            },
            "applicable_sections": [
                "language_runtime",
                "interfaces",
                "data_contracts",
                "naming_conventions",
            ],
            "language_runtime": {"language": "Python", "runtime": "project interpreter"},
            "interfaces": {"response": {"id": "string", "status": "string"}},
            "data_contracts": {"identifier": "utf-8 string"},
            "naming_conventions": {"files": "snake_case", "identifiers": "snake_case"},
            "quality_validation": {
                "checks": ["each lane hard acceptance", "one cross-lane import smoke"],
            },
            "integration_plan": {
                "owner_ticket": "INTEGRATE-WAVE-1",
                "merge_order": ["LANE-A", "LANE-B"],
                "checks": ["cross-lane import smoke"],
            },
        }
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return path

    def ticket(
        self,
        ticket_id: str,
        writable_path: str,
        *,
        mode: str = "PARALLEL",
        depends_on: list[str] | None = None,
        produces: list[str] | None = None,
        consumes: list[str] | None = None,
    ) -> dict:
        output_file = writable_path.replace("/**", "/result.txt")
        relation = {
            "mode": mode,
            "depends_on": depends_on or [],
            "produces_contracts": produces or [],
            "consumes_contracts": consumes or [],
            "rationale": "No causal dependency or shared writable path exists; the shared contract freezes integration semantics.",
        }
        return {
            "ticket_id": ticket_id,
            "title": ticket_id,
            "global_goal": "Build one modular product with independently deliverable frontend and backend components.",
            "why_now": "Deliver one independent module without delaying another independent module.",
            "task_goal": f"Implement the bounded {ticket_id} module.",
            "status": "DRAFT",
            "acceptance_ready": False,
            "must_do": [f"Create {output_file}"],
            "must_not_do": ["Do not edit the sibling lane"],
            "anti_patterns": ["shared writable ownership"],
            "allowed_paths": [writable_path],
            "writable_paths": [writable_path],
            "read_dependencies": [],
            "immutable_paths": [],
            "runtime_paths": [],
            "forbidden_paths": [".agent/**", ".codex/**", ".git/**"],
            "acceptance": {
                "commands_pass": [],
                "files_exist": [output_file],
                "contains": [],
                "assertions": [],
                "files_not_changed": [],
                "max_changed_files": 4,
                "max_diff_lines": 100,
            },
            "validation_ids": [],
            "budget": {"max_minutes": 30, "max_tool_calls": 30, "max_changed_files": 4, "max_diff_lines": 100},
            "drift_signals": ["Edits the sibling lane"],
            "backlog_only": ["Cross-lane redesign"],
            "execution_relationship": relation,
            "coordination_contract": {"path": ".agent/contracts/WAVE-1.json"} if mode == "PARALLEL" else {},
            "requested_company_departments": [],
        }

    def put_ticket(self, root: Path, ticket: dict) -> Path:
        path = root / ".agent" / "tickets" / "pending" / f"{ticket['ticket_id']}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(ticket, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return path

    def ready_start(self, root: Path, ticket: dict, *, check: bool = True) -> dict:
        path = self.put_ticket(root, ticket)
        self.cli(root, "ready", str(path.relative_to(root)))
        return self.json_cli(root, "start", str(path.relative_to(root)), check=check)

    def finish_company(self, root: Path) -> None:
        status = self.json_cli(root, "company-status")
        for index, role in enumerate(status.get("company_subagents", {}).get("missing_roles", [])):
            self.json_cli(
                root,
                "company-record",
                "--role",
                role,
                "--agent-id",
                f"test-{role}-{index}",
                "--status",
                "COMPLETED",
                "--summary",
                "bounded fixture result",
            )

    def test_disjoint_parallel_tickets_start_in_separate_worktrees(self) -> None:
        self.ensure_worktrees()
        first = self.ready_start(self.lane_a, self.ticket("LANE-A", "src/frontend/**", produces=["frontend-module"]))
        second = self.ready_start(self.lane_b, self.ticket("LANE-B", "src/backend/**", produces=["backend-module"]))
        self.assertEqual(first["status"], "ACTIVE")
        self.assertEqual(second["status"], "ACTIVE")
        self.assertEqual(second["parallel_execution"]["active_ticket_count"], 2)
        self.assertEqual(second["parallel_execution"]["efficiency"]["status"], "WORTHWHILE")

    def test_overlapping_writable_paths_are_serialized(self) -> None:
        self.ensure_worktrees()
        self.ready_start(self.lane_a, self.ticket("LANE-A", "src/shared/**"))
        result = self.ready_start(self.lane_b, self.ticket("LANE-B", "src/shared/api/**"), check=False)
        self.assertEqual(result["error"], "PARALLEL_TICKET_CONFLICT")
        self.assertTrue(any("writable scope overlaps" in reason for reason in result["conflicts"]))

    def test_dependency_edge_prevents_parallel_start(self) -> None:
        self.ensure_worktrees()
        self.ready_start(self.lane_a, self.ticket("LANE-A", "src/frontend/**", produces=["shared-api"]))
        result = self.ready_start(
            self.lane_b,
            self.ticket("LANE-B", "src/backend/**", depends_on=["LANE-A"], consumes=["shared-api"]),
            check=False,
        )
        self.assertEqual(result["error"], "PARALLEL_TICKET_CONFLICT")
        self.assertTrue(any("run serially" in reason or "depends on ACTIVE" in reason for reason in result["conflicts"]))

    def test_mismatched_coordination_contract_rejects_parallel_start(self) -> None:
        self.ensure_worktrees()
        self.ready_start(self.lane_a, self.ticket("LANE-A", "src/frontend/**"))
        self.write_contract(self.lane_b, contract_id="WAVE-OTHER")
        result = self.ready_start(self.lane_b, self.ticket("LANE-B", "src/backend/**"), check=False)
        self.assertEqual(result["error"], "PARALLEL_TICKET_CONFLICT")
        self.assertTrue(any("coordination contract differs" in reason for reason in result["conflicts"]))

    def test_parallel_contract_requires_positive_net_gain(self) -> None:
        self.write_contract(self.main, serial=50, parallel=40, coordination=8, integration=7)
        path = self.put_ticket(self.main, self.ticket("LANE-A", "src/frontend/**"))
        result = self.json_cli(self.main, "ready", str(path.relative_to(self.main)), check=False)
        self.assertFalse(result["ok"])
        self.assertTrue(any("parallel overhead exceeds expected gain" in error for error in result["errors"]))

        contract_path = self.write_contract(self.main)
        contract = json.loads(contract_path.read_text(encoding="utf-8"))
        contract["applicable_sections"] = []
        contract["independence_evidence"] = {
            "dependency_edges": [],
            "writable_scopes_disjoint": True,
            "no_shared_surface": True,
        }
        for section in ("language_runtime", "interfaces", "data_contracts", "naming_conventions"):
            contract.pop(section, None)
        contract_path.write_text(json.dumps(contract, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        light_path = self.put_ticket(self.main, self.ticket("LANE-LIGHT", "docs/independent/**"))
        light = self.json_cli(self.main, "ready", str(light_path.relative_to(self.main)))
        self.assertTrue(light["ok"])

    def test_completed_dependency_allows_serial_successor(self) -> None:
        self.ensure_worktrees()
        first = self.ticket("LANE-A", "src/frontend/**", mode="SERIAL", produces=["frontend-module"])
        self.ready_start(self.lane_a, first)
        output = self.lane_a / "src" / "frontend" / "result.txt"
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text("done\n", encoding="utf-8")
        close = self.json_cli(self.lane_a, "close")
        self.assertEqual(close["status"], "PASS")

        successor = self.ticket(
            "LANE-B",
            "src/backend/**",
            mode="SERIAL",
            depends_on=["LANE-A"],
            consumes=["frontend-module"],
        )
        result = self.ready_start(self.lane_b, successor)
        self.assertEqual(result["status"], "ACTIVE")

    def test_parallel_contract_change_is_detected(self) -> None:
        self.ready_start(self.main, self.ticket("LANE-A", "src/frontend/**"))
        self.write_contract(self.main, serial=120)
        result = self.json_cli(self.main, "check", check=False)
        self.assertEqual(result["status"], "DRIFT")
        self.assertTrue(any("coordination contract changed" in reason for reason in result["reasons"]))


if __name__ == "__main__":
    unittest.main()
