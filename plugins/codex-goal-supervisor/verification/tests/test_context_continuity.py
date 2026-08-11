from __future__ import annotations

import json

try:
    from .helpers import GoalCompassRepoCase
except ImportError:
    from helpers import GoalCompassRepoCase

from goal_compass_runtime.context_continuity import (
    LARGE_OUTPUT_BYTES,
    LARGE_READ_FILES,
    compact_status,
    record_read,
    recovery_context,
    seal_before_compact,
    subagent_context,
)


class ContextContinuityTests(GoalCompassRepoCase):
    def setUp(self) -> None:
        super().setUp()
        runtime = self.root / ".agent" / "runtime"
        self.state = runtime / "context_continuity.json"
        self.lock = runtime / "context_continuity.lock"
        self.capsule = runtime / "context" / "index.json"

    def read_event(self, path: str, index: int = 0, response: str = "ok") -> dict:
        return {
            "session_id": "session-context",
            "turn_id": "turn-context",
            "hook_event_name": "PostToolUse",
            "tool_use_id": f"read-{index}",
            "tool_name": "read_file",
            "tool_input": {"path": path},
            "tool_response": {"content": response},
        }

    def record(self, event: dict) -> str | None:
        return record_read(self.root, self.state, self.lock, self.capsule, event)

    def test_small_read_phase_is_silent(self) -> None:
        target = self.root / "src" / "small.py"
        target.parent.mkdir(parents=True)
        target.write_text("VALUE = 1\n", encoding="utf-8")

        message = self.record(self.read_event("src/small.py"))

        self.assertIsNone(message)
        self.assertFalse(self.capsule.exists())

    def test_large_read_phase_records_local_subagent_recommendation_without_injection(self) -> None:
        secret = "SOURCE_TEXT_MUST_NOT_ENTER_CAPSULE"
        for index in range(LARGE_READ_FILES):
            target = self.root / "legacy" / f"part_{index % 2}" / f"module_{index:02d}.py"
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(f"{secret}_{index}\n", encoding="utf-8")
            output = self.record(self.read_event(target.relative_to(self.root).as_posix(), index=index))

        self.assertIsNone(output)
        capsule_text = self.capsule.read_text(encoding="utf-8")
        self.assertNotIn(secret, capsule_text)
        directory_capsules = sorted((self.capsule.parent / "by-directory").rglob("_context.json"))
        self.assertEqual(len(directory_capsules), 2)
        self.assertNotIn(secret, directory_capsules[0].read_text(encoding="utf-8"))
        state = json.loads(self.state.read_text(encoding="utf-8"))
        self.assertTrue(state["checkpoint_due"])
        self.assertTrue(state["subagent_recommended"])

        compact = self.json_run("status")
        verbose = self.json_run("status", "--verbose")
        self.assertNotIn("context_continuity", compact)
        self.assertEqual(verbose["context_continuity"]["status"], "CHECKPOINT_DUE")
        self.assertEqual(
            verbose["context_continuity"]["recommended_action"],
            "checkpoint_findings_and_partition_independent_read_only_slices",
        )
        self.assertFalse(verbose["context_continuity"]["proactive_injection"])
        self.assertFalse(verbose["context_continuity"]["llm_assistance"])

    def test_compaction_recovers_mechanical_capsule_before_any_visible_summary(self) -> None:
        target = self.root / "docs" / "history.md"
        target.parent.mkdir(parents=True)
        target.write_text("private historical detail\n", encoding="utf-8")
        self.record(self.read_event("docs/history.md"))
        compact_event = {
            "session_id": "session-context",
            "turn_id": "turn-context",
            "hook_event_name": "PreCompact",
            "trigger": "auto",
        }

        seal_before_compact(self.root, self.state, self.lock, self.capsule, compact_event)
        message = recovery_context(
            self.root,
            self.state,
            self.lock,
            self.capsule,
            {
                "session_id": "session-context",
                "hook_event_name": "SessionStart",
                "source": "compact",
            },
        )

        self.assertIn("context/index.json", message or "")
        self.assertIn("mechanical read ledger", message or "")
        self.assertIn("do not blindly reread", message or "")
        self.assertNotIn("private historical detail", self.capsule.read_text(encoding="utf-8"))

    def test_context_records_are_hierarchical_and_loaded_on_demand(self) -> None:
        for index, directory in enumerate(("src/api", "src/ui", "docs/history")):
            target = self.root / directory / f"item_{index}.txt"
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(f"item {index}\n", encoding="utf-8")
            self.record(self.read_event(target.relative_to(self.root).as_posix(), index=index))
        seal_before_compact(
            self.root,
            self.state,
            self.lock,
            self.capsule,
            {"session_id": "session-context", "hook_event_name": "PreCompact", "trigger": "auto"},
        )

        index = json.loads(self.capsule.read_text(encoding="utf-8"))

        self.assertNotIn("files", index)
        self.assertEqual([row["directory"] for row in index["directory_index"]], ["docs/history", "src/api", "src/ui"])
        for row in index["directory_index"]:
            capsule = self.root / row["capsule"]
            self.assertTrue(capsule.is_file())
            self.assertEqual(json.loads(capsule.read_text(encoding="utf-8"))["directory"], row["directory"])

    def test_context_note_records_explicit_conclusions_by_directory(self) -> None:
        secret = "SOURCE_BODY_MUST_STAY_OUT_OF_CHECKPOINT"
        target = self.root / "src" / "api" / "schema.py"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(f"{secret}\n", encoding="utf-8")
        self.record(self.read_event("src/api/schema.py"))

        result = self.json_run(
            "context-note",
            "--directory", "src/api",
            "--fact", "The request schema is validated before persistence.",
            "--interface", "create_job(request) returns a persisted job id.",
            "--dependency", "src/api depends on src/storage.",
            "--open-question", "Retry ownership remains unconfirmed.",
            "--next-action", "Inspect src/workers retry handling.",
            "--evidence", "src/api/schema.py",
        )

        self.assertEqual(result["status"], "RECORDED")
        self.assertFalse(result["source_text_stored"])
        self.assertFalse(result["hidden_reasoning_stored"])
        directory_capsule = self.root / result["capsule"]
        payload = json.loads(directory_capsule.read_text(encoding="utf-8"))
        semantic = payload["semantic_checkpoint"]
        self.assertEqual(semantic["confirmed_facts"], ["The request schema is validated before persistence."])
        self.assertEqual(semantic["key_interfaces"], ["create_job(request) returns a persisted job id."])
        self.assertEqual(semantic["evidence"][0]["path"], "src/api/schema.py")
        self.assertNotIn(secret, directory_capsule.read_text(encoding="utf-8"))
        index = json.loads(self.capsule.read_text(encoding="utf-8"))
        entry = next(row for row in index["directory_index"] if row["directory"] == "src/api")
        self.assertTrue(entry["semantic_checkpoint_present"])
        verbose = self.json_run("status", "--verbose")
        self.assertEqual(verbose["context_continuity"]["semantic_directory_count"], 1)

    def test_context_note_rejects_paths_outside_project(self) -> None:
        result = self.json_run(
            "context-note",
            "--directory", str(self.root.parent),
            "--fact", "This must not be recorded.",
            check=False,
        )

        self.assertEqual(result["status"], "FAIL")
        self.assertIn("inside the project", result["reason"])

    def test_subagent_guidance_is_conditional_on_large_read_phase(self) -> None:
        self.assertIsNone(subagent_context(self.root, self.state, self.capsule))
        for index in range(LARGE_READ_FILES):
            target = self.root / "archive" / f"slice_{index % 2}" / f"part_{index}.txt"
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(str(index), encoding="utf-8")
            self.record(self.read_event(target.relative_to(self.root).as_posix(), index=index))

        message = subagent_context(self.root, self.state, self.capsule)

        self.assertIn("stay read-only", message or "")
        self.assertIn("assigned module/archive slice", message or "")

    def test_tiny_grep_queries_do_not_create_a_false_large_read(self) -> None:
        target = self.root / "src" / "small.py"
        target.parent.mkdir(parents=True)
        target.write_text("VALUE = 1\n", encoding="utf-8")
        for index in range(3):
            self.record({
                "session_id": "session-context",
                "hook_event_name": "PostToolUse",
                "tool_name": "exec_command",
                "tool_input": {"cmd": "rg VALUE src/small.py"},
                "tool_response": {"output": "src/small.py:VALUE = 1\n"},
            })

        state = json.loads(self.state.read_text(encoding="utf-8"))
        self.assertFalse(state["checkpoint_due"])
        self.assertEqual(state["broad_read_calls"], 0)

    def test_partial_read_of_large_file_uses_observed_output_not_source_size(self) -> None:
        target = self.root / "archive" / "large.log"
        target.parent.mkdir(parents=True)
        target.write_bytes(b"x" * (4 * 1024 * 1024))

        self.record({
            "session_id": "session-context",
            "hook_event_name": "PostToolUse",
            "tool_name": "read_file",
            "tool_input": {"path": "archive/large.log", "offset": 0, "limit": 20},
            "tool_response": {"content": "x" * 20},
        })

        state = json.loads(self.state.read_text(encoding="utf-8"))
        self.assertGreater(state["unique_file_bytes"], LARGE_OUTPUT_BYTES)
        self.assertFalse(state["checkpoint_due"])
        self.assertEqual(state["bounded_read_calls"], 1)
        self.assertEqual(state["reader_kinds"], ["builtin"])

    def test_large_unbounded_output_recommends_symbol_or_paged_reading(self) -> None:
        target = self.root / "docs" / "history.md"
        target.parent.mkdir(parents=True)
        target.write_text("history\n", encoding="utf-8")

        self.record(self.read_event("docs/history.md", response="x" * LARGE_OUTPUT_BYTES))

        summary = compact_status(self.root, self.state, self.capsule)
        self.assertEqual(summary["unbounded_large_output_calls"], 1)
        self.assertEqual(summary["recommended_action"], "switch_to_symbol_or_paged_reads_then_checkpoint")

    def test_single_coupled_directory_does_not_recommend_subagents(self) -> None:
        for index in range(LARGE_READ_FILES):
            target = self.root / "src" / "coupled" / f"module_{index}.py"
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(f"VALUE = {index}\n", encoding="utf-8")
            self.record(self.read_event(target.relative_to(self.root).as_posix(), index=index))

        state = json.loads(self.state.read_text(encoding="utf-8"))
        self.assertTrue(state["checkpoint_due"])
        self.assertFalse(state["subagent_recommended"])
        summary = compact_status(self.root, self.state, self.capsule)
        self.assertEqual(summary["recommended_action"], "checkpoint_findings_and_continue_bounded_reading")

    def test_serena_and_fastctx_reads_are_observed_without_installing_them(self) -> None:
        target = self.root / "src" / "service.py"
        target.parent.mkdir(parents=True)
        target.write_text("def run():\n    return 1\n", encoding="utf-8")
        events = (
            {
                "session_id": "session-context",
                "hook_event_name": "PostToolUse",
                "tool_name": "mcp__serena__find_symbol",
                "tool_input": {"relative_path": "src/service.py", "name_path_pattern": "run"},
                "tool_response": {"content": "run"},
            },
            {
                "session_id": "session-context",
                "hook_event_name": "PostToolUse",
                "tool_name": "mcp__fastctx__read_text",
                "tool_input": {"path": "src/service.py", "offset": 0, "limit": 20},
                "tool_response": {"content": "def run"},
            },
        )
        for event in events:
            self.record(event)

        state = json.loads(self.state.read_text(encoding="utf-8"))
        self.assertEqual(state["reader_kinds"], ["serena", "fastctx"])
        self.assertEqual(state["bounded_read_calls"], 2)
        self.assertFalse(state["checkpoint_due"])

    def test_changed_checkpoint_evidence_is_reported_stale(self) -> None:
        target = self.root / "src" / "api" / "schema.py"
        target.parent.mkdir(parents=True)
        target.write_text("SCHEMA = 1\n", encoding="utf-8")
        self.record(self.read_event("src/api/schema.py"))
        self.json_run(
            "context-note",
            "--directory", "src/api",
            "--fact", "Schema version one is active.",
            "--evidence", "src/api/schema.py",
        )
        target.write_text("SCHEMA = 2 and changed\n", encoding="utf-8")

        summary = compact_status(self.root, self.state, self.capsule)

        self.assertEqual(summary["semantic_directory_count"], 0)
        self.assertEqual(summary["stale_directories"], ["src/api"])

    def test_read_only_subagent_filter_avoids_polluting_implementation_agents(self) -> None:
        for index in range(LARGE_READ_FILES):
            target = self.root / f"area_{index % 2}" / f"item_{index}.txt"
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(str(index), encoding="utf-8")
            self.record(self.read_event(target.relative_to(self.root).as_posix(), index=index))

        read_message = subagent_context(
            self.root,
            self.state,
            self.capsule,
            {"task": "Inspect and summarize the assigned archive slice."},
        )
        implementation_message = subagent_context(
            self.root,
            self.state,
            self.capsule,
            {"task": "Implement and edit the API service."},
        )

        self.assertIn("stay read-only", read_message or "")
        self.assertIsNone(implementation_message)


if __name__ == "__main__":
    import unittest

    unittest.main()
