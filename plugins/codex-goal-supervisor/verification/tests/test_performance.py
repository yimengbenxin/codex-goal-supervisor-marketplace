from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import os
import time

try:
    from .helpers import GOAL_COMPASS, HARNESS_ROOT, LONG_TIMEOUT, PLUGIN_ROOT, GoalCompassRepoCase, pushd, run_cmd
except ImportError:
    from helpers import GOAL_COMPASS, HARNESS_ROOT, LONG_TIMEOUT, PLUGIN_ROOT, GoalCompassRepoCase, pushd, run_cmd


class PerformanceTests(GoalCompassRepoCase):
    def _start_nongit_file_ticket(self, ticket_id: str, path: str, required_text: str) -> None:
        self.cli("goal-set", "--text", "Build one bounded local artifact with machine-checkable content.")
        ticket = self.read_json(".agent/tickets/examples/VIDEO-MOCK-001.json")
        ticket.update({
            "ticket_id": ticket_id,
            "global_goal": "Build one bounded local artifact with machine-checkable content.",
            "task_goal": f"Update only {path}.",
            "must_do": [f"Update {path}"],
            "allowed_paths": [path],
            "forbidden_paths": [".agent/**", ".codex/**", ".git/**"],
            "acceptance": {
                "commands_pass": [], "files_exist": [path],
                "contains": [{"file": path, "text": required_text}], "assertions": [],
                "files_not_changed": [], "max_changed_files": 2, "max_diff_lines": 30,
            },
            "validation_ids": [],
            "budget": {"max_minutes": 10, "max_tool_calls": 10, "max_changed_files": 2, "max_diff_lines": 30},
            "drift_signals": ["Changes any unrelated artifact"],
            "backlog_only": ["Additional artifacts"],
        })
        self.write_json(f".agent/tickets/pending/{ticket_id}.json", ticket)
        self.cli("start", f".agent/tickets/pending/{ticket_id}.json")

    def test_nongit_hash_detects_same_size_same_mtime_change(self) -> None:
        path = self.root / "scripts" / "audit.py"
        path.parent.mkdir(parents=True)
        path.write_text("aaaa\n", encoding="utf-8")
        original = path.stat()
        self._start_nongit_file_ticket("HASH-TRACK-001", "scripts/audit.py", "bbbb")
        path.write_text("bbbb\n", encoding="utf-8")
        os.utime(path, ns=(original.st_atime_ns, original.st_mtime_ns))

        result = self.json_run("check")
        current = self.read_json(".agent/current_ticket.json")

        self.assertEqual(result["status"], "PASS_READY")
        self.assertIn("scripts/audit.py", current["budget_used"]["changed_files"])

    def test_nested_runtime_caches_do_not_count_as_product_changes(self) -> None:
        path = self.root / "src" / "app.py"
        path.parent.mkdir(parents=True)
        path.write_text("before\n", encoding="utf-8")
        self._start_nongit_file_ticket("CACHE-TRACK-001", "src/app.py", "after")
        cache = self.root / "src" / "pkg" / "__pycache__" / "module.pyc"
        cache.parent.mkdir(parents=True)
        cache.write_bytes(b"runtime cache")
        path.write_text("after\n", encoding="utf-8")

        self.json_run("check")
        changed = self.read_json(".agent/current_ticket.json")["budget_used"]["changed_files"]

        self.assertEqual(changed, ["src/app.py"])

    def test_sqlite_wal_is_reported_as_volatile_not_product_drift(self) -> None:
        path = self.root / "src" / "app.py"
        path.parent.mkdir(parents=True)
        path.write_text("before\n", encoding="utf-8")
        self._start_nongit_file_ticket("VOLATILE-TRACK-001", "src/app.py", "after")
        wal = self.root / "data" / "state.sqlite-wal"
        wal.parent.mkdir(parents=True)
        wal.write_bytes(b"volatile runtime state")
        path.write_text("after\n", encoding="utf-8")

        result = self.json_run("check")
        usage = self.read_json(".agent/current_ticket.json")["budget_used"]

        self.assertEqual(result["status"], "PASS_READY")
        self.assertNotIn("data/state.sqlite-wal", usage["changed_files"])
        self.assertIn("data/state.sqlite-wal", usage["volatile_runtime_changes"])

    def test_init_compacts_inactive_legacy_baseline_without_losing_ticket(self) -> None:
        ticket = self.read_json(".agent/tickets/examples/VIDEO-MOCK-001.json")
        ticket["status"] = "DRIFT"
        ticket["budget_used"] = {
            "tool_calls": 12,
            "changed_files": ["scripts/a.py"],
            "diff_lines": 5,
            "baseline_snapshot": {f"data/runtime-{idx}.json": {"size": idx, "mtime_ns": idx} for idx in range(500)},
        }
        self.write_json(".agent/current_ticket.json", ticket)

        self.cli("init")
        current = self.read_json(".agent/current_ticket.json")
        archived = self.read_json(".agent/tickets/failed/VIDEO-MOCK-001.json")

        self.assertEqual(current["status"], "NONE")
        self.assertEqual(archived["budget_used"]["tool_calls"], 12)
        self.assertNotIn("baseline_snapshot", archived["budget_used"])
        self.assertEqual(self.read_json(".agent/last_ticket.json")["ticket_id"], "VIDEO-MOCK-001")

    def test_nongit_tracking_skips_runtime_vendor_trees_and_keeps_product_changes(self) -> None:
        for prefix in [
            ".venv-tradingagents/lib/python/site-packages",
            "data/processed",
            "logs",
            "outputs/handoff/staging/archive",
            "external_research/source_cache/vendor",
        ]:
            folder = self.root / prefix
            folder.mkdir(parents=True, exist_ok=True)
            for idx in range(30):
                (folder / f"runtime-{idx}.json").write_text("{}\n", encoding="utf-8")
        script = self.root / "scripts" / "audit.py"
        script.parent.mkdir(parents=True, exist_ok=True)
        script.write_text("print('before')\n", encoding="utf-8")
        self.cli("goal-set", "--text", "Build a quantitative trading audit tool with stable model routing.")
        ticket = self.read_json(".agent/tickets/examples/VIDEO-MOCK-001.json")
        ticket.update({
            "ticket_id": "NONGIT-RUNTIME-001",
            "global_goal": "Build a quantitative trading audit tool with stable model routing.",
            "task_goal": "Update scripts/audit.py and verify it exists.",
            "must_do": ["Update scripts/audit.py"],
            "must_not_do": ["Do not modify runtime market data"],
            "anti_patterns": ["runtime market data rewrite"],
            "allowed_paths": ["scripts/audit.py"],
            "forbidden_paths": [".agent/**", ".codex/**", "data/broker_gateway/**"],
            "acceptance": {
                "commands_pass": [],
                "files_exist": ["scripts/audit.py"],
                "contains": [{"file": "scripts/audit.py", "text": "after"}],
                "assertions": [],
                "files_not_changed": [],
                "max_changed_files": 2,
                "max_diff_lines": 20,
            },
            "validation_ids": [],
            "budget": {"max_minutes": 30, "max_tool_calls": 20, "max_changed_files": 2, "max_diff_lines": 20},
            "drift_signals": ["Starts changing runtime data"],
            "backlog_only": ["Runtime data migration"],
        })
        self.write_json(".agent/tickets/pending/NONGIT-RUNTIME-001.json", ticket)
        self.cli("start", ".agent/tickets/pending/NONGIT-RUNTIME-001.json")
        current = self.read_json(".agent/current_ticket.json")
        with pushd(self.root):
            baseline = GOAL_COMPASS.load_baseline(current)
        self.assertIn("baseline_ref", current["budget_used"])
        self.assertLess(len(baseline), 80)
        self.assertFalse(any(path.startswith(("data/", "logs/", ".venv-tradingagents/", "outputs/handoff/")) for path in baseline))

        (self.root / "data" / "processed" / "runtime-new.json").write_text("{\"live\": true}\n", encoding="utf-8")
        broker = self.root / "data" / "broker_gateway" / "paper-state.json"
        broker.parent.mkdir(parents=True, exist_ok=True)
        broker.write_text("{\"background\": true}\n", encoding="utf-8")
        (self.root / "logs" / "cycle.log").write_text("tick\n", encoding="utf-8")
        script.write_text("print('after')\n", encoding="utf-8")
        result = self.json_run("check")
        current = self.read_json(".agent/current_ticket.json")

        self.assertEqual(result["status"], "PASS_READY")
        self.assertEqual(current["budget_used"]["changed_files"], ["scripts/audit.py"])
        self.assertLess((self.root / ".agent" / "current_ticket.json").stat().st_size, 120_000)

    def test_nongit_exact_allowed_path_tracks_unexpected_sibling_in_ignored_root(self) -> None:
        self.cli("goal-set", "--text", "Build one bounded cosmetics packaging evidence artifact.")
        ticket = self.read_json(".agent/tickets/examples/VIDEO-MOCK-001.json")
        ticket.update({
            "ticket_id": "NONGIT-ARTIFACT-SIBLING-001",
            "global_goal": "Build one bounded cosmetics packaging evidence artifact.",
            "task_goal": "Create only artifacts/COS-098.json.",
            "must_do": ["Create artifacts/COS-098.json"],
            "must_not_do": ["Do not create sibling artifacts"],
            "anti_patterns": ["unapproved sibling artifact"],
            "allowed_paths": ["artifacts/COS-098.json"],
            "forbidden_paths": [".agent/**", ".codex/**", ".git/**"],
            "acceptance": {
                "commands_pass": [],
                "files_exist": ["artifacts/COS-098.json"],
                "contains": [],
                "assertions": [],
                "files_not_changed": [],
                "max_changed_files": 5,
                "max_diff_lines": 100,
            },
            "validation_ids": [],
            "budget": {"max_minutes": 30, "max_tool_calls": 20, "max_changed_files": 5, "max_diff_lines": 100},
            "drift_signals": ["Creates any artifact outside the exact allowed file"],
            "backlog_only": ["Additional cosmetics artifacts"],
        })
        self.write_json(".agent/tickets/pending/NONGIT-ARTIFACT-SIBLING-001.json", ticket)
        self.cli("start", ".agent/tickets/pending/NONGIT-ARTIFACT-SIBLING-001.json")
        artifacts = self.root / "artifacts"
        artifacts.mkdir(parents=True, exist_ok=True)
        (artifacts / "COS-098.json").write_text("{}\n", encoding="utf-8")
        (artifacts / "COS-098-unallowed.json").write_text("{}\n", encoding="utf-8")

        result = self.json_run("check", check=False)
        current = self.read_json(".agent/current_ticket.json")

        self.assertEqual(result["status"], "PASS_READY")
        self.assertEqual(result["budget_status"], "SOFT_CHANGE_PRESSURE")
        self.assertTrue(any("COS-098-unallowed.json" in reason for reason in result["budget_advisories"]))
        self.assertIn("artifacts/COS-098-unallowed.json", current["budget_used"]["changed_files"])

    def test_nongit_sparse_runtime_contract_does_not_expand_to_entire_data_tree(self) -> None:
        protected = self.root / "data" / "processed" / "protected-state.json"
        protected.parent.mkdir(parents=True, exist_ok=True)
        protected.write_text('{"version": 1}\n', encoding="utf-8")
        realtime = self.root / "data" / "processed" / "realtime_execution" / "current.json"
        realtime.parent.mkdir(parents=True, exist_ok=True)
        realtime.write_text('{"sequence": 1}\n', encoding="utf-8")
        for branch in range(20):
            folder = self.root / "data" / "processed" / f"unrelated-{branch:02d}"
            folder.mkdir(parents=True, exist_ok=True)
            for idx in range(50):
                (folder / f"runtime-{idx:02d}.json").write_text("{}\n", encoding="utf-8")

        self.cli("goal-set", "--text", "Protect one runtime state while releasing a bounded sidecar.")
        self.install_validation("sparse_runtime_contract_test", "import sys; sys.exit(0)")
        ticket = self.read_json(".agent/tickets/examples/VIDEO-MOCK-001.json")
        ticket.update({
            "ticket_id": "NONGIT-SPARSE-DATA-001",
            "global_goal": "Protect one runtime state while releasing a bounded sidecar.",
            "task_goal": "Observe one protected data file and one realtime publication branch.",
            "must_do": ["Read the protected state without modifying it"],
            "execution_mode": "read_only",
            "allowed_paths": [],
            "read_dependencies": [],
            "immutable_paths": ["data/processed/protected-state.json"],
            "runtime_paths": ["data/processed/realtime_execution/**"],
            "forbidden_paths": [".agent/**", ".codex/**", ".git/**"],
            "acceptance": {
                "commands_pass": ["sparse_runtime_contract_test"], "files_exist": [], "contains": [], "assertions": [],
                "files_not_changed": ["data/processed/protected-state.json"],
                "max_changed_files": 0, "max_diff_lines": 0,
            },
            "validation_ids": ["sparse_runtime_contract_test"],
            "budget": {"max_minutes": 10, "max_tool_calls": 10, "max_changed_files": 0, "max_diff_lines": 0},
            "drift_signals": ["Changes protected state"],
            "backlog_only": ["Unrelated runtime files"],
        })
        self.write_json(".agent/tickets/pending/NONGIT-SPARSE-DATA-001.json", ticket)

        started = time.perf_counter()
        self.cli("start", ".agent/tickets/pending/NONGIT-SPARSE-DATA-001.json")
        start_elapsed = time.perf_counter() - started
        current = self.read_json(".agent/current_ticket.json")
        with pushd(self.root):
            baseline = GOAL_COMPASS.load_baseline(current)

        self.assertLess(start_elapsed, 5.0)
        self.assertIn("data/processed/protected-state.json", baseline)
        self.assertIn("data/processed/realtime_execution/current.json", baseline)
        self.assertFalse(any("unrelated-" in path for path in baseline))
        self.assertLess(len(baseline), 80)

        status_started = time.perf_counter()
        result = self.json_run("status")
        status_elapsed = time.perf_counter() - status_started
        self.assertLess(status_elapsed, 5.0)
        self.assertTrue(result["active"])

        (self.root / "data" / "processed" / "unrelated-00" / "runtime-00.json").write_text(
            '{"background": true}\n', encoding="utf-8"
        )
        protected.write_text('{"version": 2}\n', encoding="utf-8")
        check = self.json_run("check", check=False)
        current = self.read_json(".agent/current_ticket.json")

        self.assertEqual(check["status"], "DRIFT")
        self.assertIn("data/processed/protected-state.json", current["budget_used"]["immutable_changes"])
        observed = [
            *current["budget_used"]["changed_files"],
            *current["budget_used"]["immutable_changes"],
            *current["budget_used"]["runtime_changes"],
        ]
        self.assertFalse(any("unrelated-" in path for path in observed))


    def test_status_is_compact_and_omits_baseline_snapshot(self) -> None:
        self.start_video()

        result = self.json_run("status")
        encoded = json.dumps(result, ensure_ascii=False)

        self.assertNotIn("baseline_snapshot", encoded)
        self.assertLess(len(encoded), 2_500)

    def _commit_all(self, message: str) -> None:
        run_cmd(["git", "add", "."], cwd=self.root, timeout=8, check=True)
        proc = run_cmd(
            ["git", "-c", "user.email=test@example.com", "-c", "user.name=Test", "commit", "-m", message],
            cwd=self.root,
            timeout=8,
            check=False,
        )
        if proc.returncode != 0 and "nothing to commit" not in (proc.stdout + proc.stderr):
            self.fail(f"git commit failed\nSTDOUT:\n{proc.stdout}\nSTDERR:\n{proc.stderr}")

    def _start_low_diff_budget_ticket_after_committed_ready_state(self) -> None:
        run_cmd(["git", "init"], cwd=self.root, timeout=8, check=True)
        self._commit_all("initial goal compass install")
        self.goal_video()
        self.install_validation("mock_video_pipeline_test", "import sys; sys.exit(0)")
        ticket = self.read_json(".agent/tickets/examples/VIDEO-MOCK-001.json")
        ticket["ticket_id"] = "STATE-BUDGET-001"
        ticket["status"] = "DRAFT"
        ticket["acceptance_ready"] = False
        ticket["budget"]["max_diff_lines"] = 1
        ticket["acceptance"]["max_diff_lines"] = 1
        self.write_json(".agent/tickets/pending/STATE-BUDGET-001.json", ticket)
        self.cli("ready", ".agent/tickets/pending/STATE-BUDGET-001.json")
        self._commit_all("ready ticket state")
        self.cli("start", ".agent/tickets/pending/STATE-BUDGET-001.json")

    def test_installed_agent_files_do_not_count_against_product_ticket_budget(self) -> None:
        run_cmd(["git", "init"], cwd=self.root, timeout=8, check=True)
        self.goal_video()
        self.cli("start", ".agent/tickets/examples/VIDEO-MOCK-001.json")
        result = self.json_run("check")
        self.assertNotEqual(result["status"], "BUDGET_EXCEEDED")
        self.assertNotEqual(result["status"], "DRIFT")
        self.assertFalse(any("outside allowed_paths" in r for r in result["reasons"]))
        self.assertFalse(any("forbidden_paths" in r for r in result["reasons"]))

    def test_current_ticket_state_does_not_count_against_diff_budget(self) -> None:
        self._start_low_diff_budget_ticket_after_committed_ready_state()

        result = self.json_run("check")
        current = self.read_json(".agent/current_ticket.json")

        self.assertEqual(result["status"], "NEEDS_VALIDATION")
        self.assertNotEqual(result["status"], "DIFF_BUDGET_EXCEEDED_CLEAN")
        self.assertNotEqual(result["status"], "BUDGET_EXCEEDED")
        self.assertFalse(any(".agent/current_ticket.json" in reason for reason in result["reasons"]))
        self.assertEqual(current["budget_used"]["diff_lines"], 0)
        self.assertNotIn(".agent/current_ticket.json", current["budget_used"]["changed_files"])

    def test_staged_agent_state_does_not_count_against_diff_budget(self) -> None:
        self._start_low_diff_budget_ticket_after_committed_ready_state()
        run_cmd(["git", "add", ".agent/current_ticket.json"], cwd=self.root, timeout=8, check=True)

        result = self.json_run("check")
        current = self.read_json(".agent/current_ticket.json")

        self.assertEqual(result["status"], "NEEDS_VALIDATION")
        self.assertNotEqual(result["status"], "DIFF_BUDGET_EXCEEDED_CLEAN")
        self.assertNotEqual(result["status"], "BUDGET_EXCEEDED")
        self.assertFalse(any(".agent/current_ticket.json" in reason for reason in result["reasons"]))
        self.assertEqual(current["budget_used"]["diff_lines"], 0)
        self.assertNotIn(".agent/current_ticket.json", current["budget_used"]["changed_files"])

    def test_legacy_wall_clock_elapsed_does_not_explode_resumed_ticket(self) -> None:
        self.goal_video()
        self.cli("start", ".agent/tickets/examples/VIDEO-MOCK-001.json")
        current_path = self.root / ".agent" / "current_ticket.json"
        ticket = json.loads(current_path.read_text(encoding="utf-8"))
        ticket["budget_used"]["started_at"] = "2026-07-03T00:00:00+00:00"
        ticket["budget_used"]["elapsed_minutes"] = 480
        ticket["budget_used"].pop("last_metered_at", None)
        current_path.write_text(json.dumps(ticket, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

        result = self.json_run("check")

        self.assertNotEqual(result["status"], "BUDGET_EXCEEDED")
        self.assertFalse(any("elapsed_minutes" in r for r in result["reasons"]))

    def test_prune_plan_finishes_under_timeout(self) -> None:
        self.start_video()
        for i in range(12):
            target = self.root / "src" / "video" / "mock" / f"file{i}.ts"
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(f"export const item{i} = 'mock video artifact';\n", encoding="utf-8")
        started = time.perf_counter()
        proc = self.cli("prune-plan")
        elapsed = time.perf_counter() - started
        self.assertEqual(proc.returncode, 0)
        self.assertLess(elapsed, 5.0)

    def test_selftest_finishes_under_timeout(self) -> None:
        started = time.perf_counter()
        path = HARNESS_ROOT / ".agent" / "selftest" / "test_goal_compass.py"
        spec = importlib.util.spec_from_file_location("goal_compass_selftest_under_verification", path)
        self.assertIsNotNone(spec)
        self.assertIsNotNone(spec.loader)
        module = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        spec.loader.exec_module(module)
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            code = int(module.main())
        elapsed = time.perf_counter() - started
        self.assertEqual(code, 0, stdout.getvalue())
        self.assertLess(elapsed, 20.0)
