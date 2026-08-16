from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import os
import signal
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any


PLUGIN_ROOT = Path(__file__).resolve().parents[2]
HARNESS_ROOT = PLUGIN_ROOT / "assets" / "governor-harness"
SCRIPT = HARNESS_ROOT / ".agent" / "goal_compass.py"
RUNTIME_PACKAGE = HARNESS_ROOT / ".agent" / "goal_compass_runtime"
INSTALLER = PLUGIN_ROOT / "scripts" / "install_governor.py"
FIXTURE_TICKETS = PLUGIN_ROOT / "verification" / "fixtures" / "tickets"
EMPTY_REUSE_FIXTURE = PLUGIN_ROOT / "verification" / "fixtures" / "reuse_probe_empty.json"

# Verification must never depend on public network availability. Individual
# reuse-probe tests temporarily replace this deterministic empty search result.
os.environ.setdefault("GOAL_COMPASS_REUSE_PROBE_FIXTURE", str(EMPTY_REUSE_FIXTURE))
# Detailed Goal tests validate the route contract in process. They do not start
# one detached dashboard per fixture; roadmap server tests opt in explicitly.
os.environ.setdefault("GOAL_SUPERVISOR_DISABLE_ROADMAP_SERVER", "1")
# The suite imports the product CLI in-process and may inherit the developer's
# live Codex task id. Native Goal synchronization is covered with an isolated
# fake app-server; ordinary fixtures must never mutate the task running tests.
os.environ.setdefault("GOAL_SUPERVISOR_NATIVE_GOAL_BRIDGE", "disabled")

DEFAULT_TIMEOUT = 8
LONG_TIMEOUT = 20


def _load_goal_compass_module():
    agent_root = str(SCRIPT.parent)
    if agent_root not in sys.path:
        sys.path.insert(0, agent_root)
    spec = importlib.util.spec_from_file_location("goal_compass_under_test", SCRIPT)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to import {SCRIPT}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


GOAL_COMPASS = _load_goal_compass_module()


def _link_or_copy(source: Path, target: Path, writable: bool) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    if not writable:
        try:
            os.link(source, target)
            return
        except OSError:
            pass
    shutil.copy2(source, target)


def copy_goal_compass_runtime(root: Path, *, writable: bool = False) -> None:
    agent = root / ".agent"
    agent.mkdir(parents=True, exist_ok=True)
    _link_or_copy(SCRIPT, agent / "goal_compass.py", writable)
    runtime_target = agent / "goal_compass_runtime"
    runtime_target.mkdir(parents=True, exist_ok=True)
    for pattern in ("*.py", "*.html"):
        for source in RUNTIME_PACKAGE.glob(pattern):
            _link_or_copy(source, runtime_target / source.name, writable)


def install_product_test_fixtures(root: Path) -> None:
    target = root / ".agent" / "tickets" / "examples"
    target.mkdir(parents=True, exist_ok=True)
    for source in FIXTURE_TICKETS.glob("*.json"):
        shutil.copy2(source, target / source.name)
    catalog_path = root / ".agent" / "validation_catalog.json"
    catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
    catalog.update({
        "mock_video_pipeline_test": {
            "cmd": "{python} -c \"import sys; sys.exit(0)\"",
            "description": "Verification-only fixture.",
            "timeout_sec": DEFAULT_TIMEOUT,
        },
        "routing_mvp_test": {
            "cmd": "{python} -c \"import sys; sys.exit(0)\"",
            "description": "Verification-only fixture.",
            "timeout_sec": DEFAULT_TIMEOUT,
        },
        "permission_guard_test": {
            "cmd": "{python} -c \"import sys; sys.exit(0)\"",
            "description": "Verification-only fixture.",
            "timeout_sec": DEFAULT_TIMEOUT,
        },
    })
    catalog_path.write_text(json.dumps(catalog, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


@contextlib.contextmanager
def pushd(path: Path):
    old = Path.cwd()
    os.chdir(path)
    try:
        yield
    finally:
        os.chdir(old)


def run_goal_compass(args: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    """Run goal_compass.py in-process so the suite is fast and deterministic.

    The product CLI is still exercised through its argparse/main entrypoint; this
    avoids a fresh Python interpreter for every assertion, which made the full
    verification suite slow and flaky in CI-like sandboxes.
    """
    stdout = io.StringIO()
    stderr = io.StringIO()
    code = 0
    with pushd(cwd), contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
        try:
            code = int(GOAL_COMPASS.main(args))
        except SystemExit as exc:
            code = int(exc.code or 0) if isinstance(exc.code, int) else 1
        except Exception as exc:  # preserve CLI-style failure diagnostics
            code = 1
            print(f"{type(exc).__name__}: {exc}", file=stderr)
    return subprocess.CompletedProcess([sys.executable, ".agent/goal_compass.py", *args], code, stdout.getvalue(), stderr.getvalue())


def run_cmd(
    cmd: list[str] | str,
    cwd: Path,
    timeout: float = DEFAULT_TIMEOUT,
    check: bool = False,
    input_text: str | None = None,
    shell: bool = False,
) -> subprocess.CompletedProcess[str]:
    popen_kwargs: dict[str, Any] = {
        "cwd": cwd,
        "text": True,
        "encoding": "utf-8",
        "errors": "replace",
        "stdout": subprocess.PIPE,
        "stderr": subprocess.PIPE,
        "env": {**os.environ, "PYTHONDONTWRITEBYTECODE": "1", "PYTHONUTF8": "1"},
        "shell": shell,
    }
    if input_text is not None:
        popen_kwargs["stdin"] = subprocess.PIPE
    else:
        # Test subprocesses must never inherit the suite runner's TTY. An
        # inherited terminal can turn an otherwise non-interactive installer
        # into a prompt that waits forever during the full suite.
        popen_kwargs["stdin"] = subprocess.DEVNULL
    if os.name != "nt":
        popen_kwargs["start_new_session"] = True
    proc = subprocess.Popen(cmd, **popen_kwargs)
    try:
        stdout, stderr = proc.communicate(input=input_text, timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        if os.name == "nt":
            subprocess.run(
                ["taskkill", "/PID", str(proc.pid), "/T", "/F"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=3,
                check=False,
            )
        else:
            os.killpg(proc.pid, signal.SIGKILL)
        try:
            stdout, stderr = proc.communicate(timeout=2)
        except subprocess.TimeoutExpired:
            stdout, stderr = "", "<process did not flush after SIGKILL>"
        raise AssertionError(
            f"Command timed out after {timeout}s: {cmd}\nCWD: {cwd}\nSTDOUT:\n{stdout[-2000:]}\nSTDERR:\n{stderr[-2000:]}"
        ) from exc
    result = subprocess.CompletedProcess(cmd, proc.returncode, stdout, stderr)
    if check and result.returncode != 0:
        raise AssertionError(f"{cmd} failed\nCWD: {cwd}\nSTDOUT:\n{stdout[-2000:]}\nSTDERR:\n{stderr[-2000:]}")
    return result


class GoalCompassRepoCase(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self._old_feedback_global_config = os.environ.get("GOAL_COMPASS_FEEDBACK_GLOBAL_CONFIG")
        self._old_disable_default_feedback_endpoint = os.environ.get("GOAL_COMPASS_FEEDBACK_DISABLE_DEFAULT_ENDPOINT")
        self._old_disable_llm_judge = os.environ.get("GOAL_SUPERVISOR_DISABLE_LLM_JUDGE")
        os.environ["GOAL_COMPASS_FEEDBACK_GLOBAL_CONFIG"] = str(self.root / "no-global-feedback-config.json")
        os.environ["GOAL_COMPASS_FEEDBACK_DISABLE_DEFAULT_ENDPOINT"] = "1"
        os.environ["GOAL_SUPERVISOR_DISABLE_LLM_JUDGE"] = "1"
        copy_goal_compass_runtime(self.root)
        self.cli("init")
        install_product_test_fixtures(self.root)

    def tearDown(self) -> None:
        if self._old_feedback_global_config is None:
            os.environ.pop("GOAL_COMPASS_FEEDBACK_GLOBAL_CONFIG", None)
        else:
            os.environ["GOAL_COMPASS_FEEDBACK_GLOBAL_CONFIG"] = self._old_feedback_global_config
        if self._old_disable_default_feedback_endpoint is None:
            os.environ.pop("GOAL_COMPASS_FEEDBACK_DISABLE_DEFAULT_ENDPOINT", None)
        else:
            os.environ["GOAL_COMPASS_FEEDBACK_DISABLE_DEFAULT_ENDPOINT"] = self._old_disable_default_feedback_endpoint
        if self._old_disable_llm_judge is None:
            os.environ.pop("GOAL_SUPERVISOR_DISABLE_LLM_JUDGE", None)
        else:
            os.environ["GOAL_SUPERVISOR_DISABLE_LLM_JUDGE"] = self._old_disable_llm_judge
        self.tmp.cleanup()

    def cli(self, *args: str, check: bool = True, timeout: float = DEFAULT_TIMEOUT) -> subprocess.CompletedProcess[str]:
        # timeout kept for API compatibility; in-process calls are bounded by the
        # command logic and the outer test runner.
        result = run_goal_compass(list(args), cwd=self.root)
        if check and result.returncode != 0:
            raise AssertionError(f"goal_compass {args} failed\nSTDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}")
        return result

    def json_run(self, *args: str, check: bool = True, timeout: float = DEFAULT_TIMEOUT) -> dict[str, Any]:
        result = self.cli(*args, check=check, timeout=timeout)
        try:
            return json.loads(result.stdout)
        except json.JSONDecodeError as exc:
            raise AssertionError(f"Non-JSON stdout for {args}:\n{result.stdout}\nSTDERR:\n{result.stderr}") from exc

    def read_json(self, path: str) -> dict[str, Any]:
        return json.loads((self.root / path).read_text(encoding="utf-8"))

    def write_json(self, path: str, data: dict[str, Any]) -> None:
        target = self.root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    def goal_video(self) -> None:
        self.cli("goal-set", "--text", "Build an AI automatic video generation system.")

    def start_video(self) -> None:
        self.goal_video()
        self.cli("start", ".agent/tickets/examples/VIDEO-MOCK-001.json")

    def start_permission(self) -> None:
        self.goal_video()
        self.cli("start", ".agent/tickets/examples/PERMISSION-GUARD-001.json")

    def complete_company_runtime(self) -> None:
        status = self.json_run("company-status")
        for index, role in enumerate(status.get("company_subagents", {}).get("missing_roles", [])):
            agent_id = f"test-{role}-{index}"
            self.json_run("company-record", "--role", role, "--agent-id", agent_id, "--status", "STARTED")
            self.json_run(
                "company-record", "--role", role, "--agent-id", agent_id, "--status", "COMPLETED",
                "--result-hash", f"fixture-{role}-result", "--summary", "verification fixture result",
            )

    def goal_agent_registry(self) -> None:
        self.cli(
            "goal-set",
            "--text",
            "Build a LAN Agent Registry / Skill Hub MVP for uploading, scanning, classifying, searching, downloading, and reusing Agent packages.",
        )

    def start_agent_registry(self) -> None:
        self.goal_agent_registry()
        ticket = {
            "ticket_id": "AGENT-REGISTRY-MVP",
            "title": "LAN Agent Registry / Skill Hub MVP",
            "global_goal": "Build a LAN Agent Registry / Skill Hub MVP.",
            "why_now": "Prove the upload to scan to registry listing and download loop.",
            "task_goal": "Implement the local Agent Registry MVP with upload, scan/sanitize, SQLite, list/search/detail/download, and version ledger.",
            "status": "PENDING",
            "acceptance_ready": True,
            "must_do": [
                "Upload zip Agent packages and validate agent.yaml plus README.md",
                "Scan secrets and support sanitize_mode off preview force with second scan",
                "Store packages in SQLite and local storage",
                "Show internal marketplace list, detail, filters, download, and version ledger",
            ],
            "must_not_do": ["Do not build an Agent Runner", "Do not build a public marketplace"],
            "anti_patterns": ["Agent Runner", "public marketplace", "remote execution platform", "organization RBAC"],
            "allowed_paths": ["app/**", "tests/**", "scripts/**", "README.md", "requirements.txt", "design-qa.md", "work/**", "storage/**"],
            "forbidden_paths": [".env", ".agent/**", ".codex/**", ".git/**"],
            "acceptance": {
                "commands_pass": [],
                "files_exist": ["app/static/index.html", "requirements.txt", "design-qa.md"],
                "contains": [{"file": "app/static/index.html", "text": "Skill Hub"}],
                "assertions": [],
                "files_not_changed": [".agent/**", ".codex/**"],
                "max_changed_files": 80,
                "max_diff_lines": 8000,
            },
            "validation_ids": [],
            "budget": {"max_minutes": 240, "max_tool_calls": 220, "max_changed_files": 80, "max_diff_lines": 8000},
            "drift_signals": ["Starts building Agent Runner", "Starts building public marketplace"],
            "backlog_only": ["Agent Runner", "public sharing marketplace", "organization RBAC", "cloud deployment"],
        }
        self.write_json(".agent/tickets/pending/AGENT-REGISTRY-MVP.json", ticket)
        self.cli("start", ".agent/tickets/pending/AGENT-REGISTRY-MVP.json")

    def make_validation_ticket(self, command_id: str = "ok_validation") -> dict[str, Any]:
        ticket = self.read_json(".agent/tickets/examples/VIDEO-MOCK-001.json")
        ticket["ticket_id"] = f"VALIDATION-{command_id.upper().replace('_', '-')}"
        ticket["status"] = "PENDING"
        ticket["acceptance_ready"] = True
        ticket["acceptance"] = {
            "commands_pass": [command_id],
            "files_exist": [],
            "contains": [],
            "assertions": [],
            "files_not_changed": [],
            "max_changed_files": 5,
            "max_diff_lines": 300,
        }
        ticket["validation_ids"] = [command_id]
        return ticket

    def install_validation(self, command_id: str, code: str) -> None:
        catalog = self.read_json(".agent/validation_catalog.json")
        cmd = f"{{python}} -c {json.dumps(code)}"
        catalog[command_id] = {
            "cmd": cmd,
            "description": "test validation",
            "timeout_sec": DEFAULT_TIMEOUT,
        }
        self.write_json(".agent/validation_catalog.json", catalog)

    def commit_paths(self, *paths: str) -> None:
        run_cmd(["git", "init"], cwd=self.root, timeout=DEFAULT_TIMEOUT, check=True)
        run_cmd(["git", "add", *paths], cwd=self.root, timeout=DEFAULT_TIMEOUT, check=True)
        run_cmd(
            ["git", "-c", "user.email=test@example.com", "-c", "user.name=Test", "commit", "-m", "fixture"],
            cwd=self.root,
            timeout=DEFAULT_TIMEOUT,
            check=True,
        )


class MinimalPluginFixtureCase(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp.name)
        self.plugin = self.base / "plugin"
        self.repo = self.base / "repo"
        self.repo.mkdir()
        (self.repo / "README.md").write_text("User README\n", encoding="utf-8")
        (self.repo / "AGENTS.md").write_text("User AGENTS\n", encoding="utf-8")
        (self.repo / "tests").mkdir()
        (self.repo / "tests" / "existing_test.py").write_text("print('existing')\n", encoding="utf-8")
        (self.repo / "src").mkdir()
        (self.repo / "src" / "app.py").write_text("print('app')\n", encoding="utf-8")
        self.make_plugin_fixture()

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def make_plugin_fixture(self) -> None:
        (self.plugin / "scripts").mkdir(parents=True)
        shutil.copy2(INSTALLER, self.plugin / "scripts" / "install_governor.py")
        shutil.copy2(PLUGIN_ROOT / "scripts" / "verified_asset.py", self.plugin / "scripts" / "verified_asset.py")
        assets = self.plugin / "assets" / "governor-harness"
        copy_goal_compass_runtime(assets)
        for rel in [
            ".agent/north_star_goal.json",
            ".agent/current_ticket.json",
            ".agent/backlog.jsonl",
            ".agent/validation_catalog.json",
            ".agent/prune_plan.json",
            ".agent/request_decisions.jsonl",
            ".agent/quarantine_manifest.jsonl",
            ".codex/hooks.json",
        ]:
            src = HARNESS_ROOT / rel
            dst = assets / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            if src.exists():
                shutil.copy2(src, dst)
            else:
                dst.write_text("{}\n", encoding="utf-8")
        for rel in [".agent/lenses", ".agent/protocols", ".agent/docs", ".agent/selftest"]:
            src = HARNESS_ROOT / rel
            dst = assets / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            if src.exists():
                shutil.copytree(src, dst, dirs_exist_ok=True)
        for rel in [
            "README.md",
            "README.zh.md",
            "AGENTS.md",
            "tests/test_goal_compass.py",
            "legacy/governor.py",
            ".agent/legacy/governor.py",
            ".agent/board_events.jsonl",
            ".agent/reverse_signal.jsonl",
            ".agent/signed_ledger.json",
        ]:
            target = assets / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text("should not install\n", encoding="utf-8")
