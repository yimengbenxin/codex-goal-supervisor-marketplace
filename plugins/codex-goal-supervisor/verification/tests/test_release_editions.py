from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path


PLUGIN_ROOT = Path(__file__).resolve().parents[2]
BUILDER_PATH = PLUGIN_ROOT / "scripts" / "build_plugin_release.py"
SPEC = importlib.util.spec_from_file_location("goal_supervisor_release_builder", BUILDER_PATH)
assert SPEC and SPEC.loader
BUILDER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(BUILDER)


class ReleaseEditionTests(unittest.TestCase):
    def test_online_editions_build_separate_marketplaces(self) -> None:
        with tempfile.TemporaryDirectory(prefix="goal-supervisor-marketplaces-") as temporary:
            root = Path(temporary)
            for edition, expected_name in (
                ("full", "goal-supervisor"),
                ("update-only", "goal-supervisor-update-only"),
            ):
                output = root / edition
                result = BUILDER.build_edition_marketplace(output, edition)
                manifest = json.loads(
                    (output / "plugins/codex-goal-supervisor/.codex-plugin/plugin.json").read_text(encoding="utf-8")
                )
                marketplace = json.loads(
                    (output / ".agents/plugins/marketplace.json").read_text(encoding="utf-8")
                )
                readme = (output / "README.md").read_text(encoding="utf-8")
                self.assertEqual(result["marketplace_name"], expected_name)
                self.assertEqual(manifest["distributionEdition"], edition)
                self.assertEqual(marketplace["name"], expected_name)
                self.assertIn(f"official `{edition}` Codex marketplace channel", readme)
                self.assertIn("## Edition Boundary", readme)
                self.assertIn("codex plugin marketplace add", readme)
                self.assertIn("Project use remains explicit opt-in", readme)

    def test_three_editions_are_physically_distinct_and_runnable(self) -> None:
        with tempfile.TemporaryDirectory(prefix="goal-supervisor-editions-") as temporary:
            root = Path(temporary)
            result = BUILDER.build_all_editions(root / "releases")
            self.assertEqual([item["edition"] for item in result["editions"]], ["offline", "update-only", "full"])

            extracted: dict[str, Path] = {}
            for item in result["editions"]:
                edition = item["edition"]
                target = root / edition
                with zipfile.ZipFile(item["zip"]) as archive:
                    archive.extractall(target)
                plugin = target / "codex-goal-supervisor"
                extracted[edition] = plugin
                manifest = json.loads((plugin / ".codex-plugin" / "plugin.json").read_text(encoding="utf-8"))
                self.assertEqual(manifest["distributionEdition"], edition)
                subprocess.run(
                    [sys.executable, str(plugin / "assets/governor-harness/.agent/selftest/test_goal_compass.py")],
                    cwd=plugin,
                    check=True,
                    capture_output=True,
                    text=True,
                    timeout=20,
                )

            offline = extracted["offline"]
            update_only = extracted["update-only"]
            full = extracted["full"]

            for plugin in (offline, update_only):
                self.assertFalse((plugin / "server").exists())
                self.assertFalse((plugin / "verification").exists())
                self.assertFalse((plugin / "scripts/configure_feedback_client.py").exists())
                self.assertFalse((plugin / "scripts/fetch_feedback.py").exists())
                feedback = (plugin / "assets/governor-harness/.agent/goal_compass_runtime/feedback.py").read_text(encoding="utf-8")
                compass = (plugin / "assets/governor-harness/.agent/goal_compass.py").read_text(encoding="utf-8")
                installer = (plugin / "scripts/install_governor.py").read_text(encoding="utf-8")
                self.assertNotIn("urllib.request", feedback)
                self.assertNotIn("/v1/events", feedback)
                self.assertNotIn("--allow-upload", compass)
                self.assertNotIn("--allow-feedback-upload", installer)

            self.assertFalse((offline / "scripts/plugin_auto_update.py").exists())
            self.assertFalse((offline / "scripts/configure_plugin_auto_update.py").exists())
            self.assertTrue((update_only / "scripts/plugin_auto_update.py").is_file())
            self.assertTrue((update_only / "scripts/configure_plugin_auto_update.py").is_file())
            self.assertTrue((full / "server/feedback_receiver.py").is_file())
            self.assertTrue((full / "scripts/plugin_auto_update.py").is_file())


if __name__ == "__main__":
    unittest.main()
