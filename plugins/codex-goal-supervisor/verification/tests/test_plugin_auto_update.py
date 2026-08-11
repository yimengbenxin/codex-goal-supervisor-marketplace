from __future__ import annotations

import importlib.util
import io
import json
import os
import plistlib
import sys
import tempfile
import time
import unittest
import zipfile
from pathlib import Path
from unittest import mock


PLUGIN_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = PLUGIN_ROOT / "scripts"


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))
UPDATER = load_module("plugin_auto_update", SCRIPTS / "plugin_auto_update.py")
CONFIGURE = load_module("configure_plugin_auto_update_test", SCRIPTS / "configure_plugin_auto_update.py")
BUILDER = load_module("build_plugin_release_test", SCRIPTS / "build_plugin_release.py")
INSTALLER_MODULE = load_module("install_governor_test", SCRIPTS / "install_governor.py")


class PluginAutoUpdateTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="goal-supervisor-updater-test-")
        self.root = Path(self.temp.name)
        self.old_home = os.environ.get("CODEX_HOME")
        self.old_updater = os.environ.get("GOAL_SUPERVISOR_UPDATER_HOME")
        os.environ["CODEX_HOME"] = str(self.root / "codex")
        os.environ["GOAL_SUPERVISOR_UPDATER_HOME"] = str(self.root / "updater")
        self.codex = self.root / "codex-bin"
        self.codex.write_text("fixture\n", encoding="utf-8")

    def tearDown(self) -> None:
        if self.old_home is None:
            os.environ.pop("CODEX_HOME", None)
        else:
            os.environ["CODEX_HOME"] = self.old_home
        if self.old_updater is None:
            os.environ.pop("GOAL_SUPERVISOR_UPDATER_HOME", None)
        else:
            os.environ["GOAL_SUPERVISOR_UPDATER_HOME"] = self.old_updater
        self.temp.cleanup()

    def config(self) -> dict:
        return {
            "enabled": True,
            "plugin_name": "codex-goal-supervisor",
            "marketplace_name": "goal-supervisor",
            "interval_hours": 24,
            "codex_cli": str(self.codex),
            "stable_script": str(self.root / "updater" / "plugin_auto_update.py"),
        }

    @staticmethod
    def listing(version: str) -> dict:
        return {
            "installed": [{
                "name": "codex-goal-supervisor",
                "marketplaceName": "goal-supervisor",
                "version": version,
            }],
            "available": [],
        }

    def make_install(self, version: str, edition: str = "full") -> Path:
        path = self.root / "codex" / "plugins" / "cache" / "goal-supervisor" / "codex-goal-supervisor" / version
        manifest = path / ".codex-plugin" / "plugin.json"
        manifest.parent.mkdir(parents=True)
        manifest.write_text(json.dumps({
            "name": "codex-goal-supervisor",
            "version": version,
            "distributionEdition": edition,
        }) + "\n", encoding="utf-8")
        scripts = path / "scripts"
        scripts.mkdir()
        scripts.joinpath("plugin_auto_update.py").write_text("# refreshed updater\n", encoding="utf-8")
        return path

    def test_version_order_uses_release_and_codex_build(self) -> None:
        self.assertEqual(UPDATER.compare_versions("2.2.1+codex.20260809170000", "2.2.1+codex.20260809180000"), 1)
        self.assertEqual(UPDATER.compare_versions("2.2.2+codex.20260809180000", "2.2.1+codex.20260809190000"), -1)
        self.assertEqual(UPDATER.compare_versions("2.2.1+codex.20260809180000", "2.2.1+codex.20260809180000"), 0)

    def test_newer_marketplace_version_installs_to_versioned_cache(self) -> None:
        current = "2.2.1+codex.20260809170000"
        candidate = "2.3.0+codex.20260809180000"
        installed_path = self.make_install(candidate)
        responses = [
            self.listing(current),
            {"selectedMarketplaces": ["goal-supervisor"], "upgradedRoots": ["fixture"], "errors": []},
            self.listing(candidate),
            {
                "name": "codex-goal-supervisor",
                "marketplaceName": "goal-supervisor",
                "version": candidate,
                "installedPath": str(installed_path),
            },
        ]
        with mock.patch.object(UPDATER, "run_codex_json", side_effect=responses):
            code, result = UPDATER.update_once(self.config(), force=True)
        self.assertEqual(code, 0)
        self.assertEqual(result["status"], "UPDATED")
        self.assertTrue(result["restart_required"])
        self.assertEqual(result["installed_after"], candidate)
        self.assertEqual((self.root / "updater" / "plugin_auto_update.py").read_text(), "# refreshed updater\n")

    def test_same_version_does_not_reinstall(self) -> None:
        version = "2.3.0+codex.20260809180000"
        responses = [
            self.listing(version),
            {"selectedMarketplaces": ["goal-supervisor"], "upgradedRoots": ["fixture"], "errors": []},
            self.listing(version),
        ]
        with mock.patch.object(UPDATER, "run_codex_json", side_effect=responses) as runner:
            code, result = UPDATER.update_once(self.config(), force=True)
        self.assertEqual(code, 0)
        self.assertEqual(result["status"], "UP_TO_DATE")
        self.assertEqual(runner.call_count, 3)

    def test_remote_downgrade_is_refused(self) -> None:
        responses = [
            self.listing("2.3.0+codex.20260809180000"),
            {"selectedMarketplaces": ["goal-supervisor"], "upgradedRoots": ["fixture"], "errors": []},
            self.listing("2.2.9+codex.20260809190000"),
        ]
        with mock.patch.object(UPDATER, "run_codex_json", side_effect=responses) as runner:
            code, result = UPDATER.update_once(self.config(), force=True)
        self.assertEqual(code, 0)
        self.assertEqual(result["status"], "REMOTE_VERSION_OLDER")
        self.assertEqual(runner.call_count, 3)

    def test_interval_skip_has_no_network_or_codex_call(self) -> None:
        UPDATER.atomic_write_json(UPDATER.state_path(), {
            "status": "UP_TO_DATE",
            "last_successful_check_at": UPDATER.iso_time(),
        })
        with mock.patch.object(UPDATER, "run_codex_json") as runner:
            code, result = UPDATER.update_once(self.config())
        self.assertEqual(code, 0)
        self.assertEqual(result["status"], "NOT_DUE")
        runner.assert_not_called()

    def test_scheduled_cli_bypasses_ad_hoc_interval_guard(self) -> None:
        args = UPDATER.parser().parse_args(["--scheduled"])
        self.assertTrue(args.scheduled)
        self.assertFalse(args.force)

    def test_existing_lock_returns_immediately(self) -> None:
        UPDATER.lock_path().parent.mkdir(parents=True)
        UPDATER.lock_path().write_text("123\n", encoding="utf-8")
        started = time.monotonic()
        with mock.patch.object(UPDATER, "run_codex_json") as runner:
            code, result = UPDATER.update_once(self.config(), force=True)
        self.assertLess(time.monotonic() - started, 0.5)
        self.assertEqual(code, 0)
        self.assertEqual(result["status"], "ALREADY_RUNNING")
        runner.assert_not_called()

    @unittest.skipIf(os.name == "nt", "POSIX process-group assertion")
    def test_timeout_terminates_the_process_group(self) -> None:
        command = [
            sys.executable,
            "-c",
            "import subprocess,sys,time; subprocess.Popen([sys.executable,'-c','import time; time.sleep(30)']); time.sleep(30)",
        ]
        started = time.monotonic()
        with self.assertRaises(UPDATER.UpdateError):
            UPDATER.run_process(command, timeout=1)
        self.assertLess(time.monotonic() - started, 4)

    def test_process_environment_uses_system_proxy_when_environment_is_unset(self) -> None:
        with (
            mock.patch.dict(os.environ, {}, clear=True),
            mock.patch.object(
                UPDATER.urllib.request,
                "getproxies",
                return_value={"http": "http://127.0.0.1:7897", "https": "http://127.0.0.1:7897"},
            ),
        ):
            environment = UPDATER.process_environment()
        self.assertEqual(environment["HTTP_PROXY"], "http://127.0.0.1:7897")
        self.assertEqual(environment["HTTPS_PROXY"], "http://127.0.0.1:7897")

    def test_process_environment_keeps_explicit_proxy(self) -> None:
        with (
            mock.patch.dict(os.environ, {"HTTPS_PROXY": "https://explicit.example:8443"}, clear=True),
            mock.patch.object(
                UPDATER.urllib.request,
                "getproxies",
                return_value={"https": "http://system.example:8080"},
            ),
        ):
            environment = UPDATER.process_environment()
        self.assertEqual(environment["HTTPS_PROXY"], "https://explicit.example:8443")

    def test_marketplace_requires_https(self) -> None:
        CONFIGURE.require_safe_url("https://updates.example/goal-supervisor.git")
        with self.assertRaises(UPDATER.UpdateError):
            CONFIGURE.require_safe_url("http://updates.example/goal-supervisor.git")

    def test_update_only_uses_its_own_marketplace_channel(self) -> None:
        full_name, full_url = CONFIGURE.marketplace_defaults("full")
        update_name, update_url = CONFIGURE.marketplace_defaults("update-only")
        self.assertEqual(full_name, "goal-supervisor")
        self.assertEqual(update_name, "goal-supervisor-update-only")
        self.assertNotEqual(full_url, update_url)
        self.assertIn("codex-goal-supervisor-marketplace.git", full_url)
        self.assertIn("codex-goal-supervisor-update-only-marketplace.git", update_url)

    def test_updater_refuses_cross_edition_install(self) -> None:
        version = "2.3.7+codex.20260812000000"
        installed = self.make_install(version, "full")
        with self.assertRaises(UPDATER.UpdateError):
            UPDATER.verify_install(
                str(installed),
                "codex-goal-supervisor",
                version,
                "goal-supervisor",
                "update-only",
            )

    def test_macos_schedule_is_background_and_daily(self) -> None:
        payload = CONFIGURE.mac_launch_agent_payload("/usr/bin/python3", Path("/tmp/updater.py"), 9, 30, 24)
        encoded = plistlib.dumps(payload)
        decoded = plistlib.loads(encoded)
        self.assertEqual(decoded["ProcessType"], "Background")
        self.assertTrue(decoded["LowPriorityIO"])
        self.assertEqual(decoded["StartCalendarInterval"], {"Hour": 9, "Minute": 30})
        self.assertEqual(decoded["ProgramArguments"][-1], "--scheduled")
        self.assertNotIn("CODEX_CLI_PATH", decoded["EnvironmentVariables"])
        self.assertNotIn("KeepAlive", decoded)

        configured = CONFIGURE.mac_launch_agent_payload(
            "/usr/bin/python3", Path("/tmp/updater.py"), 9, 30, 24, str(self.codex)
        )
        self.assertEqual(configured["EnvironmentVariables"]["CODEX_CLI_PATH"], str(self.codex))

    def test_windows_schedule_uses_task_scheduler_without_shell(self) -> None:
        command = CONFIGURE.windows_task_command(r"C:\Python\python.exe", Path(r"C:\Updater\plugin_auto_update.py"), 9, 30)
        self.assertEqual(command[0], "schtasks")
        self.assertIn("DAILY", command)
        task_name = CONFIGURE.WINDOWS_TASK_NAME
        self.assertIn(task_name, command)
        self.assertNotIn("cmd", [value.lower() for value in command])
        self.assertIn("plugin_auto_update.py", command[-1])
        self.assertIn("--scheduled", command[-1])
        self.assertTrue(task_name)

    def test_marketplace_manifest_points_to_canonical_plugin_root(self) -> None:
        marketplace = json.loads((PLUGIN_ROOT / "server" / "goal-supervisor-marketplace.json").read_text(encoding="utf-8"))
        self.assertEqual(marketplace["name"], "goal-supervisor")
        self.assertEqual(marketplace["plugins"][0]["name"], "codex-goal-supervisor")
        self.assertEqual(marketplace["plugins"][0]["source"]["path"], "./plugins/codex-goal-supervisor")

    def test_marketplace_nginx_supports_read_only_smart_http(self) -> None:
        config = (PLUGIN_ROOT / "server" / "nginx-goal-supervisor-marketplace-location.conf").read_text(
            encoding="utf-8"
        )
        self.assertIn("git-http-backend", config)
        self.assertIn("GIT_PROJECT_ROOT /var/www/goal-supervisor-marketplace", config)
        self.assertIn("PATH_INFO $uri", config)
        self.assertIn("git-upload-pack", config)
        self.assertIn("git-receive-pack", config)
        self.assertRegex(config, r"location = /goal-supervisor-marketplace\.git/git-receive-pack \{\s*return 403;")
        self.assertIn("/goal-supervisor-assets/", config)
        self.assertIn("limit_except GET HEAD", config)
        self.assertIn("alias /var/www/goal-supervisor-assets/$asset", config)

    def test_release_builder_excludes_checkout_runtime_state(self) -> None:
        output = self.root / "marketplace"
        archive = self.root / "goal-supervisor.zip"
        role_pack = self.root / "agency-agents.zip"
        harness = self.root / "governor-harness.zip"
        result = BUILDER.build(output, archive, role_pack, harness)
        plugin = output / "plugins" / "codex-goal-supervisor"
        self.assertEqual(result["status"], "BUILT")
        self.assertTrue(archive.is_file())
        self.assertTrue(role_pack.is_file())
        self.assertTrue(harness.is_file())
        self.assertFalse((plugin / ".agent").exists())
        self.assertFalse((plugin / ".codex").exists())
        self.assertFalse(any(plugin.rglob("*.pyc")))
        self.assertTrue((plugin / "scripts" / "plugin_auto_update.py").is_file())
        self.assertTrue((plugin / "assets" / "role-packs" / "agency-agents.remote.json").is_file())
        self.assertTrue((plugin / "assets" / "governor-harness.remote.json").is_file())
        self.assertFalse((plugin / "assets" / "governor-harness").exists())
        self.assertFalse((plugin / "assets" / "role-packs" / "agency-agents" / "roles").exists())
        self.assertFalse((plugin / "verification").exists())
        self.assertFalse((plugin / "server").exists())
        self.assertFalse((plugin / "docs").exists())

        compact = self.root / "marketplace-plugin.zip"
        BUILDER.write_zip(plugin, compact)
        self.assertLess(compact.stat().st_size, 150_000)
        with zipfile.ZipFile(archive) as bundle:
            names = set(bundle.namelist())
        self.assertIn(
            "codex-goal-supervisor/assets/role-packs/agency-agents/roles/specialized/supply-chain-strategist.md",
            names,
        )
        self.assertIn("codex-goal-supervisor/verification/tests/test_plugin_auto_update.py", names)

        class Response(io.BytesIO):
            def __init__(self, payload: bytes):
                super().__init__(payload)
                self.headers = {"Content-Length": str(len(payload))}

            def __enter__(self):
                return self

            def __exit__(self, *_):
                self.close()

        runtime_descriptor = plugin / "assets" / "governor-harness.remote.json"
        env = {
            "CODEX_HOME": str(self.root / "runtime-codex"),
            "GOAL_SUPERVISOR_ASSET_CACHE": str(self.root / "runtime-cache"),
        }
        with (
            mock.patch.object(INSTALLER_MODULE, "HARNESS_ROOT", self.root / "not-bundled"),
            mock.patch.object(INSTALLER_MODULE, "HARNESS_DESCRIPTOR", runtime_descriptor),
            mock.patch.dict(os.environ, env, clear=False),
            mock.patch.object(
                INSTALLER_MODULE.verified_asset.urllib.request,
                "urlopen",
                return_value=Response(harness.read_bytes()),
            ),
        ):
            resolved = INSTALLER_MODULE.resolve_harness_root()
        self.assertTrue((resolved / ".agent" / "goal_compass.py").is_file())
        self.assertTrue((resolved / ".codex" / "hooks.json").is_file())


if __name__ == "__main__":
    unittest.main()
