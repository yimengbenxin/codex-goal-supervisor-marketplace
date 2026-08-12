from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock


PLUGIN_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = PLUGIN_ROOT / "scripts" / "publish_verified_release.py"
SPEC = importlib.util.spec_from_file_location("goal_supervisor_release_publish", SCRIPT)
assert SPEC and SPEC.loader
PUBLISHER = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = PUBLISHER
SPEC.loader.exec_module(PUBLISHER)


class ReleasePublishTests(unittest.TestCase):
    def test_release_identity_requires_timestamped_semver(self) -> None:
        self.assertEqual(
            PUBLISHER.release_identity("2.4.5+codex.20260812150000"),
            ("2.4.5", "20260812150000", "v2.4.5"),
        )
        with self.assertRaises(PUBLISHER.PublishError):
            PUBLISHER.release_identity("2.4.5")

    def test_remote_tag_can_resolve_through_annotated_tag(self) -> None:
        output = (
            "tag-object\trefs/tags/v2.4.5\n"
            "source-head\trefs/tags/v2.4.5^{}\n"
        )
        self.assertTrue(PUBLISHER.tag_resolves_to_head(output, "source-head"))
        self.assertFalse(PUBLISHER.tag_resolves_to_head(output, "other-head"))

    def test_network_command_retries_transient_failure(self) -> None:
        failed = subprocess.CompletedProcess([], 128, "", "HTTP2 framing error")
        passed = subprocess.CompletedProcess([], 0, "ok", "")
        with mock.patch.object(PUBLISHER, "run_command", side_effect=[failed, passed]) as command, mock.patch.object(PUBLISHER.time, "sleep"):
            result = PUBLISHER.run_network_command(["git", "fetch"], attempts=2)
        self.assertEqual(result.stdout, "ok")
        self.assertEqual(command.call_count, 2)

    def test_network_query_can_return_expected_not_found(self) -> None:
        missing = subprocess.CompletedProcess([], 1, "", "release not found")
        with mock.patch.object(PUBLISHER, "run_command", return_value=missing), mock.patch.object(PUBLISHER.time, "sleep"):
            result = PUBLISHER.run_network_command(["gh", "release", "view"], attempts=2, check=False)
        self.assertEqual(result.returncode, 1)

    def test_macos_system_proxy_is_used_only_without_explicit_proxy_env(self) -> None:
        payload = "HTTPEnable : 1\nHTTPProxy : 127.0.0.1\nHTTPPort : 7897\n"
        completed = subprocess.CompletedProcess([], 0, payload, "")
        PUBLISHER.system_proxy_environment.cache_clear()
        with mock.patch.object(PUBLISHER.sys, "platform", "darwin"), mock.patch.dict(PUBLISHER.os.environ, {}, clear=True), mock.patch.object(PUBLISHER.subprocess, "run", return_value=completed):
            self.assertEqual(
                PUBLISHER.system_proxy_environment()["HTTPS_PROXY"],
                "http://127.0.0.1:7897",
            )
        PUBLISHER.system_proxy_environment.cache_clear()
        with mock.patch.object(PUBLISHER.sys, "platform", "darwin"), mock.patch.dict(PUBLISHER.os.environ, {"HTTPS_PROXY": "http://explicit:8080"}, clear=True):
            self.assertEqual(PUBLISHER.system_proxy_environment(), {})
        PUBLISHER.system_proxy_environment.cache_clear()

    def make_archive(self, path: Path, *, version: str, edition: str) -> None:
        manifest = {
            "name": "codex-goal-supervisor",
            "version": version,
            "distributionEdition": edition,
        }
        with zipfile.ZipFile(path, "w") as bundle:
            bundle.writestr(
                "codex-goal-supervisor/.codex-plugin/plugin.json",
                json.dumps(manifest),
            )
            bundle.writestr("codex-goal-supervisor/README.md", "release\n")

    def test_archive_validation_binds_version_and_edition(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            archive = Path(temporary) / "release.zip"
            self.make_archive(archive, version="2.4.5+codex.20260812150000", edition="offline")
            PUBLISHER.validate_archive(archive, "2.4.5+codex.20260812150000", "offline")
            with self.assertRaises(PUBLISHER.PublishError):
                PUBLISHER.validate_archive(archive, "2.4.5+codex.20260812150000", "full")

    def test_copy_tree_contents_preserves_git_and_removes_stale_files(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source"
            target = root / "target"
            source.mkdir()
            target.mkdir()
            (source / "new.txt").write_text("new\n", encoding="utf-8")
            (target / "old.txt").write_text("old\n", encoding="utf-8")
            (target / ".git").mkdir()
            (target / ".git/config").write_text("git\n", encoding="utf-8")
            PUBLISHER.copy_tree_contents(source, target)
            self.assertFalse((target / "old.txt").exists())
            self.assertEqual((target / "new.txt").read_text(encoding="utf-8"), "new\n")
            self.assertTrue((target / ".git/config").is_file())

    def test_sync_marketplace_is_idempotent_with_local_bare_remote(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            remote = root / "remote.git"
            seed = root / "seed"
            built = root / "built"
            subprocess.run(["git", "init", "--bare", str(remote)], check=True, capture_output=True, timeout=10)
            subprocess.run(["git", "clone", str(remote), str(seed)], check=True, capture_output=True, timeout=10)
            subprocess.run(["git", "config", "user.name", "Release Test"], cwd=seed, check=True, timeout=10)
            subprocess.run(["git", "config", "user.email", "release-test@example.invalid"], cwd=seed, check=True, timeout=10)
            (seed / "README.md").write_text("seed\n", encoding="utf-8")
            subprocess.run(["git", "add", "."], cwd=seed, check=True, timeout=10)
            subprocess.run(["git", "commit", "-m", "seed"], cwd=seed, check=True, capture_output=True, timeout=10)
            subprocess.run(["git", "branch", "-M", "main"], cwd=seed, check=True, timeout=10)
            subprocess.run(["git", "push", "origin", "main"], cwd=seed, check=True, capture_output=True, timeout=10)
            subprocess.run(["git", "symbolic-ref", "HEAD", "refs/heads/main"], cwd=remote, check=True, timeout=10)
            plugin = built / "plugins/codex-goal-supervisor/.codex-plugin"
            plugin.mkdir(parents=True)
            plugin.joinpath("plugin.json").write_text(json.dumps({
                "name": "codex-goal-supervisor",
                "version": "2.4.5+codex.20260812150000",
                "distributionEdition": "full",
            }), encoding="utf-8")
            built.joinpath("README.md").write_text("marketplace\n", encoding="utf-8")

            first = PUBLISHER.sync_marketplace(str(remote), "full", built, "2.4.5+codex.20260812150000")
            second = PUBLISHER.sync_marketplace(str(remote), "full", built, "2.4.5+codex.20260812150000")
            self.assertTrue(first["changed"])
            self.assertFalse(second["changed"])

    def test_publish_refuses_dirty_source_before_expensive_verification(self) -> None:
        with mock.patch.object(PUBLISHER, "require_release_source", side_effect=PUBLISHER.PublishError("dirty")), mock.patch.object(PUBLISHER, "compile_source") as compile_source:
            with self.assertRaises(PUBLISHER.PublishError):
                PUBLISHER.publish(dry_run=True)
        compile_source.assert_not_called()

    def test_existing_release_requires_exact_asset_digests(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            asset = Path(temporary) / "release.zip"
            asset.write_bytes(b"verified release")
            identity = {"tag": "v2.4.5", "release": "2.4.5", "notes": "notes.md"}
            good = json.dumps({
                "url": "https://example.invalid/release",
                "assets": [{"name": asset.name, "digest": f"sha256:{PUBLISHER.sha256(asset)}"}],
            })
            with mock.patch.object(
                PUBLISHER,
                "run_command",
                return_value=subprocess.CompletedProcess([], 0, good, ""),
            ):
                result = PUBLISHER.publish_github_release(identity, [asset], "abc")
            self.assertFalse(result["created"])

            bad = json.dumps({
                "url": "https://example.invalid/release",
                "assets": [{"name": asset.name, "digest": "sha256:deadbeef"}],
            })
            with mock.patch.object(
                PUBLISHER,
                "run_command",
                return_value=subprocess.CompletedProcess([], 0, bad, ""),
            ), self.assertRaises(PUBLISHER.PublishError):
                PUBLISHER.publish_github_release(identity, [asset], "abc")


if __name__ == "__main__":
    unittest.main()
