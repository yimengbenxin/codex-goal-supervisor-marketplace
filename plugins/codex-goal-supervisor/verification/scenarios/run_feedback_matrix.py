#!/usr/bin/env python3
"""Run real-install Goal Compass scenarios derived from long-run user feedback."""
from __future__ import annotations

import argparse
import json
import sqlite3
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable


PLUGIN_ROOT = Path(__file__).resolve().parents[2]
INSTALLER = PLUGIN_ROOT / "scripts" / "install_governor.py"
DEFAULT_TIMEOUT = 12


def run(command: list[str], cwd: Path, *, check: bool = True, timeout: int = DEFAULT_TIMEOUT) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        command,
        cwd=cwd,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=timeout,
        check=False,
    )
    if check and result.returncode != 0:
        raise RuntimeError(
            f"command failed ({result.returncode}): {' '.join(command)}\n"
            f"stdout:\n{result.stdout[-3000:]}\nstderr:\n{result.stderr[-3000:]}"
        )
    return result


@dataclass
class Project:
    root: Path

    @classmethod
    def create(cls, base: Path, name: str) -> "Project":
        root = base / name
        root.mkdir(parents=True)
        run([sys.executable, str(INSTALLER), str(root), "--force"], PLUGIN_ROOT, timeout=20)
        return cls(root)

    @property
    def compass(self) -> Path:
        return self.root / ".agent" / "goal_compass.py"

    def cli(self, *args: str, check: bool = True, timeout: int = DEFAULT_TIMEOUT) -> dict[str, Any]:
        result = run([sys.executable, str(self.compass), *args], self.root, check=check, timeout=timeout)
        try:
            return json.loads(result.stdout)
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"non-JSON Goal Compass output for {args}:\n{result.stdout}\n{result.stderr}") from exc

    def write_json(self, relative: str, value: Any) -> None:
        target = self.root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    def read_json(self, relative: str) -> Any:
        return json.loads((self.root / relative).read_text(encoding="utf-8"))

    def goal(self, text: str) -> None:
        self.cli("goal-set", "--text", text)

    def git_commit(self, message: str = "baseline") -> None:
        run(["git", "init"], self.root)
        run(["git", "config", "user.email", "matrix@example.invalid"], self.root)
        run(["git", "config", "user.name", "Feedback Matrix"], self.root)
        run(["git", "add", "."], self.root)
        run(["git", "commit", "-m", message], self.root)

    def complete_company(self) -> None:
        company = self.cli("company-status").get("company_subagents", {})
        for index, role in enumerate(company.get("missing_roles", [])):
            self.cli(
                "company-record",
                "--role",
                str(role),
                "--agent-id",
                f"matrix-{role}-{index}",
                "--status",
                "COMPLETED",
                "--summary",
                f"{role} returned its bounded structured result",
            )


def ticket(
    ticket_id: str,
    goal: str,
    task: str,
    writable: list[str],
    *,
    files_exist: list[str] | None = None,
    validation_ids: list[str] | None = None,
    read_dependencies: list[str] | None = None,
    runtime_paths: list[str] | None = None,
    quality_gates: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    validations = list(validation_ids or [])
    return {
        "ticket_id": ticket_id,
        "title": task,
        "global_goal": goal,
        "why_now": "Exercise one bounded real-project behavior.",
        "task_goal": task,
        "status": "PENDING",
        "acceptance_ready": True,
        "execution_mode": "product_edit",
        "must_do": [task],
        "must_not_do": ["Do not expand beyond this bounded behavior."],
        "anti_patterns": ["unrelated platform rewrite", "acceptance-free framework"],
        "allowed_paths": writable,
        "writable_paths": writable,
        "read_dependencies": list(read_dependencies or []),
        "immutable_paths": [],
        "runtime_paths": list(runtime_paths or []),
        "forbidden_paths": [".env", ".agent/**", ".codex/**", ".git/**"],
        "acceptance": {
            "commands_pass": validations,
            "files_exist": list(files_exist or []),
            "contains": [],
            "assertions": [],
            "files_not_changed": [],
            "max_changed_files": 8,
            "max_diff_lines": 800,
        },
        "validation_ids": validations,
        "quality_gates": list(quality_gates or []),
        "budget": {
            "max_minutes": 45,
            "max_tool_calls": 60,
            "max_changed_files": 8,
            "max_diff_lines": 800,
            "change_enforcement": "soft",
        },
        "drift_signals": ["Starts changing unrelated architecture", "Repeats work after acceptance is met"],
        "backlog_only": ["future platform", "unrelated redesign"],
        "requested_company_departments": [],
        "company_ceo_confirmation": {},
    }


def start_ticket(project: Project, value: dict[str, Any]) -> None:
    relative = f".agent/tickets/pending/{value['ticket_id']}.json"
    project.write_json(relative, value)
    project.cli("start", relative)


def scenario_runtime_sqlite(base: Path) -> dict[str, Any]:
    project = Project.create(base, "quant-runtime-sqlite")
    goal = "Operate a continuously running quantitative research service without confusing service state with code edits."
    project.goal(goal)
    output = project.root / "src" / "result.txt"
    output.parent.mkdir(parents=True)
    output.write_text("ready\n", encoding="utf-8")
    database = project.root / "var" / "runtime.sqlite"
    database.parent.mkdir(parents=True)
    with sqlite3.connect(database) as connection:
        connection.execute("create table events(id integer primary key, value text)")
        connection.execute("insert into events(value) values ('baseline')")
    value = ticket("RUNTIME-SQLITE-001", goal, "Keep the bounded output valid while the service database advances.", ["src/result.txt"], files_exist=["src/result.txt"])
    project.write_json(".agent/tickets/pending/RUNTIME-SQLITE-001.json", value)
    project.git_commit()
    project.cli("start", ".agent/tickets/pending/RUNTIME-SQLITE-001.json")
    with sqlite3.connect(database) as connection:
        connection.execute("insert into events(value) values ('runtime update')")
    checked = project.cli("check", check=False)
    passed = checked.get("status") == "IMPLEMENTATION_PASS_ENVIRONMENT_DIRTY" and checked.get("environment_status") == "DIRTY_RUNTIME_ONLY"
    return {"passed": passed, "actual": checked, "expected": "IMPLEMENTATION_PASS_ENVIRONMENT_DIRTY for service-owned SQLite churn"}


def scenario_complete_word(base: Path) -> dict[str, Any]:
    project = Project.create(base, "parser-complete-word")
    project.goal("Maintain a small document parser with focused regression tests.")
    rough = project.root / "rough.md"
    rough.write_text("Complete the missing unit test assertion for parser output. Do not build a platform or framework.\n", encoding="utf-8")
    out = ".agent/tickets/pending/PARSER-COMPLETE-001.json"
    project.cli("compile", "rough.md", "--out", out)
    compiled = project.read_json(out)
    warnings = compiled.get("lens_notes", {}).get("product", {}).get("non_goal_warning", [])
    risk = compiled.get("mdcp", {}).get("layer_1_structured_expression", {}).get("scope_sink_risk")
    passed = not any(str(value).lower() == "complete" for value in warnings) and risk != "strong"
    return {"passed": passed, "actual": {"non_goal_warning": warnings, "scope_sink_risk": risk}, "expected": "ordinary 'Complete the test' is not heavy scope"}


def scenario_negative_semantics(base: Path) -> dict[str, Any]:
    project = Project.create(base, "packaging-negative-semantics")
    goal = "Build a packaging quality dashboard for production operators."
    project.goal(goal)
    (project.root / "README.md").write_text(goal + "\n", encoding="utf-8")
    css = project.root / "src" / "quality" / "status.css"
    test = project.root / "tests" / "test_quality.py"
    css.parent.mkdir(parents=True)
    test.parent.mkdir(parents=True)
    css.write_text(".negative { color: #b42318; }\n", encoding="utf-8")
    test.write_text("def test_rejects_bad_lot():\n    assert not False\n", encoding="utf-8")
    report = project.cli("onboard-scan", check=False)
    items = {row.get("artifact"): row for row in report.get("inventory", [])}
    selected = {path: items.get(path, {}) for path in ["src/quality/status.css", "tests/test_quality.py"]}
    bad = {"NOISE_RISK", "DELETE_CANDIDATE", "QUARANTINE_CANDIDATE"}
    passed = all(row and row.get("classification") not in bad and "negative_scope" not in row.get("signals", []) for row in selected.values())
    return {"passed": passed, "actual": selected, "expected": "CSS negative state and negative assertions are not scope violations"}


def scenario_validation_cache(base: Path) -> dict[str, Any]:
    project = Project.create(base, "registry-validation-cache")
    goal = "Build a LAN registry that validates and lists reusable internal packages."
    project.goal(goal)
    output = project.root / "src" / "registry.txt"
    output.parent.mkdir(parents=True)
    output.write_text("registry ready\n", encoding="utf-8")
    catalog = project.read_json(".agent/validation_catalog.json")
    catalog["count_once"] = {
        "argv": [
            "{python}",
            "-c",
            "from pathlib import Path; p=Path('.agent/runtime/count.txt'); p.parent.mkdir(parents=True, exist_ok=True); p.write_text(str(int(p.read_text())+1) if p.exists() else '1')",
        ],
        "timeout_sec": 8,
    }
    project.write_json(".agent/validation_catalog.json", catalog)
    start_ticket(project, ticket("CACHE-001", goal, "Validate the registry result exactly once when inputs are unchanged.", ["src/registry.txt"], files_exist=["src/registry.txt"], validation_ids=["count_once"]))
    project.complete_company()
    checked = project.cli("check", "--run-validation")
    closed = project.cli("close")
    count = (project.root / ".agent" / "runtime" / "count.txt").read_text(encoding="utf-8")
    passed = checked.get("status") == "PASS_READY" and closed.get("status") == "PASS" and closed.get("validation", {}).get("cache_hit") is True and count == "1"
    return {"passed": passed, "actual": {"check": checked, "close": closed, "validation_count": count}, "expected": "close reuses unchanged passing validation"}


def scenario_upstream_evidence(base: Path) -> dict[str, Any]:
    project = Project.create(base, "medical-upstream-evidence")
    goal = "Produce a traceable medical evidence summary from a frozen source dataset."
    project.goal(goal)
    output = project.root / "src" / "summary.txt"
    source = project.root / "foundation" / "evidence.json"
    output.parent.mkdir(parents=True)
    source.parent.mkdir(parents=True)
    output.write_text("summary\n", encoding="utf-8")
    source.write_text('{"version": 1}\n', encoding="utf-8")
    start_ticket(project, ticket("UPSTREAM-001", goal, "Keep the summary tied to frozen upstream evidence.", ["src/summary.txt"], files_exist=["src/summary.txt"], read_dependencies=["foundation/evidence.json"]))
    source.write_text('{"version": 2}\n', encoding="utf-8")
    checked = project.cli("check", check=False)
    passed = checked.get("status") == "UPSTREAM_EVIDENCE_INVALID" and checked.get("suggested_action") == "supersede_or_rebaseline_upstream"
    return {"passed": passed, "actual": checked, "expected": "upstream premise invalidation is not DRIFT"}


def scenario_bilingual_request(base: Path) -> dict[str, Any]:
    project = Project.create(base, "bilingual-request-routing")
    goal = "Maintain a small parser with focused validation coverage."
    project.goal(goal)
    source = project.root / "src" / "parser.py"
    source.parent.mkdir(parents=True)
    source.write_text("def parse(value): return value\n", encoding="utf-8")
    start_ticket(project, ticket("REQUEST-001", goal, "Fix parser validation behavior.", ["src/parser.py", "tests/**"], files_exist=["src/parser.py"]))
    english = project.cli("request", "--text", "Review and fix the current parser validation behavior", check=False)
    chinese = project.cli("request", "--text", "检查并修复当前解析器验证行为", check=False)
    passed = english.get("verdict") == chinese.get("verdict") and english.get("allowed_current_change") == chinese.get("allowed_current_change")
    return {"passed": passed, "actual": {"english": english, "chinese": chinese}, "expected": "equivalent Chinese and English mutation requests route consistently"}


def scenario_quality_gate(base: Path) -> dict[str, Any]:
    project = Project.create(base, "video-artifact-quality")
    goal = "Generate a publishable product video artifact with explicit quality evidence."
    project.goal(goal)
    value = ticket(
        "QUALITY-001",
        goal,
        "Produce one video artifact that passes a declared visual quality gate.",
        ["outputs/result.mp4"],
        files_exist=["outputs/result.mp4"],
        quality_gates=[{"id": "publishable-video", "dimension": "artifact", "required": True, "evidence_types": ["artifact"]}],
    )
    start_ticket(project, value)
    output = project.root / "outputs" / "result.mp4"
    output.parent.mkdir(parents=True)
    output.write_bytes(b"not-a-real-publishable-video")
    checked = project.cli("check", check=False)
    passed = checked.get("status") == "NEEDS_QUALITY_EVIDENCE" and checked.get("quality", {}).get("artifact_quality_pass") is False
    return {"passed": passed, "actual": checked, "expected": "artifact existence alone cannot satisfy declared quality"}


def scenario_company_phase(base: Path) -> dict[str, Any]:
    project = Project.create(base, "company-phase-lifecycle")
    goal = "Deliver one bounded operational workflow with synchronized phase state."
    project.goal(goal)
    project.cli("phase-set", "--id", "MVP-1", "--goal", "Prove one bounded workflow", "--exit-criterion", "Ticket passes")
    output = project.root / "src" / "workflow.txt"
    output.parent.mkdir(parents=True)
    output.write_text("done\n", encoding="utf-8")
    value = ticket("PHASE-001", goal, "Implement and validate one bounded workflow.", ["src/workflow.txt"], files_exist=["src/workflow.txt"])
    value["program_phase_id"] = "MVP-1"
    value["phase_completion"] = {"complete_on_pass": True}
    start_ticket(project, value)
    before = project.cli("company-status").get("company_subagents", {})
    project.complete_company()
    after = project.cli("company-status").get("company_subagents", {})
    closed = project.cli("close")
    phase = project.read_json(".agent/program_phase.json")
    passed = bool(before.get("missing_roles")) and not after.get("missing_roles") and closed.get("status") == "PASS" and phase.get("status") == "COMPLETED"
    return {"passed": passed, "actual": {"before": before, "after": after, "close": closed, "phase": phase}, "expected": "one result call per role and one close synchronize phase"}


def scenario_non_git_line_delta(base: Path) -> dict[str, Any]:
    project = Project.create(base, "foundation-nongit-line-delta")
    goal = "Maintain a large foundation module through small, reviewable changes."
    project.goal(goal)
    source = project.root / "src" / "foundation.py"
    source.parent.mkdir(parents=True)
    source.write_text("".join(f"value_{index} = {index}\n" for index in range(1800)), encoding="utf-8")
    value = ticket("NON-GIT-DELTA-001", goal, "Change one foundation value without counting the whole file.", ["src/foundation.py"], files_exist=["src/foundation.py"])
    value["budget"]["max_diff_lines"] = 10
    value["acceptance"]["max_diff_lines"] = 10
    start_ticket(project, value)
    lines = source.read_text(encoding="utf-8").splitlines()
    lines[900] = "value_900 = 9999"
    source.write_text("\n".join(lines) + "\n", encoding="utf-8")
    checked = project.cli("check", check=False)
    usage = project.read_json(".agent/current_ticket.json").get("budget_used", {})
    passed = checked.get("status") not in {"BUDGET_EXCEEDED", "DIFF_BUDGET_EXCEEDED_CLEAN"} and int(usage.get("diff_lines", 9999)) <= 2
    return {"passed": passed, "actual": {"check": checked, "budget_used": usage}, "expected": "one-line non-Git edit uses a real line delta"}


def scenario_aggregate_preflight(base: Path) -> dict[str, Any]:
    project = Project.create(base, "supply-chain-aggregate-preflight")
    goal = "Build a traceable supply-chain report from frozen source inputs."
    project.goal(goal)
    catalog = project.read_json(".agent/validation_catalog.json")
    catalog["missing_supply_tool"] = {"argv": ["definitely-not-installed-supply-tool"], "timeout_sec": 8}
    project.write_json(".agent/validation_catalog.json", catalog)
    value = ticket(
        "PREFLIGHT-001",
        goal,
        "Generate one report from two required foundation inputs.",
        ["src/report.json"],
        validation_ids=["missing_supply_tool"],
        read_dependencies=["foundation/source-a.json", "foundation/source-b.json"],
    )
    value["status"] = "DRAFT"
    value["acceptance_ready"] = False
    path = ".agent/tickets/pending/PREFLIGHT-001.json"
    project.write_json(path, value)
    result = project.cli("ready", path, check=False)
    errors = "\n".join(str(row) for row in result.get("errors", []))
    passed = all(term in errors for term in ["validation executable unavailable", "foundation/source-a.json", "foundation/source-b.json"])
    return {"passed": passed, "actual": result, "expected": "one preflight exposes the whole known blocker chain"}


def scenario_compact_output(base: Path) -> dict[str, Any]:
    project = Project.create(base, "compact-supervision-output")
    goal = "Maintain a small service endpoint with low-noise supervision output."
    project.goal(goal)
    source = project.root / "src" / "endpoint.py"
    source.parent.mkdir(parents=True)
    source.write_text("def health(): return 'ok'\n", encoding="utf-8")
    start_ticket(project, ticket("COMPACT-001", goal, "Keep one health endpoint valid.", ["src/endpoint.py"], files_exist=["src/endpoint.py"]))
    compact_raw = run([sys.executable, str(project.compass), "check"], project.root, check=False)
    verbose_raw = run([sys.executable, str(project.compass), "check", "--verbose"], project.root, check=False)
    compact = json.loads(compact_raw.stdout)
    verbose = json.loads(verbose_raw.stdout)
    passed = "mdcp_audit" not in compact and "mdcp_contract" not in compact and "mdcp_audit" in verbose and len(compact_raw.stdout) < len(verbose_raw.stdout)
    return {
        "passed": passed,
        "actual": {"compact_bytes": len(compact_raw.stdout.encode()), "verbose_bytes": len(verbose_raw.stdout.encode()), "compact_keys": sorted(compact), "verbose_has_mdcp_audit": "mdcp_audit" in verbose},
        "expected": "default output is compact; verbose retains full diagnostics",
    }


def scenario_change_request_routing(base: Path) -> dict[str, Any]:
    project = Project.create(base, "packaging-change-request-routing")
    goal = "Build a packaging quality dashboard for production operators."
    project.goal(goal)
    no_ticket = project.cli("request", "--text", "Add a packaging quality filter for production operators", check=False)
    source = project.root / "src" / "lot_status.py"
    source.parent.mkdir(parents=True)
    source.write_text("STATUS = 'ready'\n", encoding="utf-8")
    start_ticket(project, ticket("LOT-STATUS-001", goal, "Fix the current lot status label.", ["src/lot_status.py"], files_exist=["src/lot_status.py"]))
    active = project.cli("request", "--text", "Add a supplier scorecard to the packaging quality dashboard", check=False)
    passed = no_ticket.get("verdict") == "PROPOSE_NEW_TICKET" and active.get("verdict") in {"SPLIT", "BACKLOG", "PROPOSE_NEW_TICKET"} and active.get("verdict") != "ACCEPT_AS_IS"
    return {"passed": passed, "actual": {"without_active_ticket": no_ticket, "with_active_ticket": active}, "expected": "new aligned work becomes a new/split/backlog ticket instead of mutating current acceptance"}


SCENARIOS: list[tuple[str, Callable[[Path], dict[str, Any]]]] = [
    ("runtime_sqlite_attribution", scenario_runtime_sqlite),
    ("complete_word_scope", scenario_complete_word),
    ("negative_semantics", scenario_negative_semantics),
    ("validation_cache", scenario_validation_cache),
    ("upstream_evidence", scenario_upstream_evidence),
    ("bilingual_request", scenario_bilingual_request),
    ("artifact_quality", scenario_quality_gate),
    ("company_phase", scenario_company_phase),
    ("non_git_line_delta", scenario_non_git_line_delta),
    ("aggregate_preflight", scenario_aggregate_preflight),
    ("compact_output", scenario_compact_output),
    ("change_request_routing", scenario_change_request_routing),
]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--json-out", type=Path)
    parser.add_argument("--keep-projects", type=Path)
    args = parser.parse_args()
    started = time.monotonic()
    temporary: tempfile.TemporaryDirectory[str] | None = None
    if args.keep_projects:
        base = args.keep_projects.resolve()
        base.mkdir(parents=True, exist_ok=True)
    else:
        temporary = tempfile.TemporaryDirectory(prefix="goal-compass-feedback-matrix-")
        base = Path(temporary.name)
    results: list[dict[str, Any]] = []
    try:
        for name, scenario in SCENARIOS:
            item_started = time.monotonic()
            try:
                detail = scenario(base)
                results.append({"scenario": name, "duration_seconds": round(time.monotonic() - item_started, 3), **detail})
            except Exception as exc:
                results.append({"scenario": name, "duration_seconds": round(time.monotonic() - item_started, 3), "passed": False, "error": f"{type(exc).__name__}: {exc}"})
    finally:
        if temporary is not None:
            temporary.cleanup()
    report = {
        "schema_version": 1,
        "plugin_version": json.loads((PLUGIN_ROOT / ".codex-plugin" / "plugin.json").read_text(encoding="utf-8")).get("version"),
        "duration_seconds": round(time.monotonic() - started, 3),
        "passed": all(item.get("passed") for item in results),
        "scenario_count": len(results),
        "results": results,
    }
    rendered = json.dumps(report, ensure_ascii=False, indent=2)
    print(rendered)
    if args.json_out:
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_text(rendered + "\n", encoding="utf-8")
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
