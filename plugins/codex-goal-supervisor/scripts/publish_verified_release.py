#!/usr/bin/env python3
"""Verify and publish one Codex Goal Supervisor release to every public channel."""
from __future__ import annotations

import argparse
import functools
import hashlib
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import zipfile
from pathlib import Path
from typing import Any, Sequence


PLUGIN_ROOT = Path(__file__).resolve().parents[1]
MANIFEST = PLUGIN_ROOT / ".codex-plugin" / "plugin.json"
BUILDER = PLUGIN_ROOT / "scripts" / "build_plugin_release.py"
CANONICAL_REPOSITORY = "yimengbenxin/codex-goal-supervisor"
CANONICAL_REMOTE = "https://github.com/yimengbenxin/codex-goal-supervisor.git"
MARKETPLACES = {
    "full": {
        "url": "https://github.com/yimengbenxin/codex-goal-supervisor-marketplace.git",
        "name": "goal-supervisor",
    },
    "update-only": {
        "url": "https://github.com/yimengbenxin/codex-goal-supervisor-update-only-marketplace.git",
        "name": "goal-supervisor-update-only",
    },
}
COMMAND_TIMEOUT = 120
SUITE_TIMEOUT = 240


class PublishError(RuntimeError):
    pass


def run_command(
    command: Sequence[str],
    *,
    cwd: Path = PLUGIN_ROOT,
    timeout: float = COMMAND_TIMEOUT,
    check: bool = True,
    env_overrides: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    kwargs: dict[str, Any] = {
        "cwd": cwd,
        "text": True,
        "encoding": "utf-8",
        "errors": "replace",
        "stdout": subprocess.PIPE,
        "stderr": subprocess.PIPE,
        "stdin": subprocess.DEVNULL,
        "env": {
            **os.environ,
            **(env_overrides or {}),
            "PYTHONDONTWRITEBYTECODE": "1",
            "PYTHONUTF8": "1",
        },
    }
    if os.name != "nt":
        kwargs["start_new_session"] = True
    process = subprocess.Popen(list(command), **kwargs)
    try:
        stdout, stderr = process.communicate(timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        if os.name == "nt":
            subprocess.run(
                ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=5,
                check=False,
            )
        else:
            os.killpg(process.pid, signal.SIGKILL)
        stdout, stderr = process.communicate(timeout=5)
        raise PublishError(f"Command timed out after {timeout}s: {' '.join(command)}") from exc
    result = subprocess.CompletedProcess(list(command), process.returncode, stdout, stderr)
    if check and result.returncode != 0:
        raise PublishError(
            f"Command failed ({result.returncode}): {' '.join(command)}\n"
            f"stdout:\n{stdout[-4000:]}\nstderr:\n{stderr[-4000:]}"
        )
    return result


@functools.lru_cache(maxsize=1)
def system_proxy_environment() -> dict[str, str]:
    """Bridge the active macOS proxy into CLI network commands when needed."""
    proxy_keys = ("HTTPS_PROXY", "https_proxy", "HTTP_PROXY", "http_proxy", "ALL_PROXY", "all_proxy")
    if any(os.environ.get(key) for key in proxy_keys) or sys.platform != "darwin":
        return {}
    try:
        result = subprocess.run(
            ["scutil", "--proxy"],
            text=True,
            encoding="utf-8",
            errors="replace",
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            stdin=subprocess.DEVNULL,
            timeout=3,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return {}
    values = {
        key: value.strip()
        for key, value in re.findall(r"^\s*([A-Za-z]+)\s*:\s*(.+?)\s*$", result.stdout, re.MULTILINE)
    }
    host = values.get("HTTPSProxy") or values.get("HTTPProxy")
    port = values.get("HTTPSPort") or values.get("HTTPPort")
    enabled = values.get("HTTPSEnable") == "1" or values.get("HTTPEnable") == "1"
    if not enabled or not host or not port or not port.isdigit():
        return {}
    proxy = f"http://{host}:{port}"
    return {"HTTPS_PROXY": proxy, "HTTP_PROXY": proxy, "https_proxy": proxy, "http_proxy": proxy}


def run_network_command(
    command: Sequence[str],
    *,
    cwd: Path = PLUGIN_ROOT,
    timeout: float = COMMAND_TIMEOUT,
    attempts: int = 3,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    """Retry bounded network operations without weakening verification."""
    last: subprocess.CompletedProcess[str] | None = None
    for attempt in range(attempts):
        try:
            last = run_command(
                command,
                cwd=cwd,
                timeout=timeout,
                check=False,
                env_overrides=system_proxy_environment(),
            )
        except PublishError:
            if attempt + 1 >= attempts:
                raise
            time.sleep(attempt + 1)
            continue
        if last.returncode == 0:
            return last
        if attempt + 1 < attempts:
            time.sleep(attempt + 1)
    assert last is not None
    if not check:
        return last
    raise PublishError(
        f"Network command failed after {attempts} attempts ({last.returncode}): {' '.join(command)}\n"
        f"stdout:\n{last.stdout[-4000:]}\nstderr:\n{last.stderr[-4000:]}"
    )


def manifest() -> dict[str, Any]:
    return json.loads(MANIFEST.read_text(encoding="utf-8"))


def release_identity(version: str) -> tuple[str, str, str]:
    match = re.fullmatch(r"(\d+\.\d+\.\d+)\+codex\.(\d{14})", version)
    if not match:
        raise PublishError("Version must use X.Y.Z+codex.YYYYMMDDhhmmss.")
    release, build = match.groups()
    return release, build, f"v{release}"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def tag_resolves_to_head(output: str, head: str) -> bool:
    hashes = {line.split()[0] for line in output.splitlines() if line.split()}
    return head in hashes


def require_release_source() -> dict[str, str]:
    data = manifest()
    version = str(data.get("version") or "")
    release, build, tag = release_identity(version)
    if data.get("name") != "codex-goal-supervisor":
        raise PublishError("Unexpected plugin identity.")
    branch = run_command(["git", "branch", "--show-current"]).stdout.strip()
    if branch != "main":
        raise PublishError(f"Release publishing requires main, found {branch or 'detached HEAD'}.")
    status = run_command(["git", "status", "--porcelain"]).stdout.strip()
    if status:
        raise PublishError("Release publishing requires a clean committed worktree.")
    origin = run_command(["git", "remote", "get-url", "origin"]).stdout.strip()
    if origin.rstrip("/") not in {CANONICAL_REMOTE.rstrip("/"), CANONICAL_REMOTE.removesuffix(".git")}:
        raise PublishError(f"Unexpected canonical origin: {origin}")
    notes = PLUGIN_ROOT / "docs" / f"RELEASE_NOTES_{release}.md"
    if not notes.is_file():
        raise PublishError(f"Missing release notes: {notes.relative_to(PLUGIN_ROOT)}")
    return {"version": version, "release": release, "build": build, "tag": tag, "notes": str(notes)}


def compile_source() -> None:
    roots = [
        "assets/governor-harness/.agent",
        "scripts",
        "verification/tests",
    ]
    run_command([sys.executable, "-m", "compileall", "-q", *roots], timeout=SUITE_TIMEOUT)


def run_source_verification() -> list[dict[str, Any]]:
    commands = [
        [sys.executable, "-m", "unittest", "-q", "verification.tests.test_goal_compass"],
        [sys.executable, "-m", "unittest", "discover", "-s", "verification/tests", "-q"],
        [sys.executable, "assets/governor-harness/.agent/selftest/test_goal_compass.py"],
    ]
    results = []
    for command in commands:
        result = run_command(command, timeout=SUITE_TIMEOUT)
        results.append({"command": " ".join(command), "stdout": result.stdout[-1200:], "stderr": result.stderr[-1200:]})
    return results


def build_release_archives(version: str, release: str, build: str) -> tuple[Path, dict[str, Path]]:
    release_dir = PLUGIN_ROOT / "dist" / f"releases-{release}-final-{build}"
    run_command([sys.executable, str(BUILDER), "--all-editions-dir", str(release_dir)])
    archives = {
        edition: release_dir / f"codex-goal-supervisor-{version}-{edition}.zip"
        for edition in ("offline", "update-only", "full")
    }
    for edition, archive in archives.items():
        validate_archive(archive, version, edition)
    return release_dir, archives


def validate_archive(archive: Path, version: str, edition: str) -> None:
    if not archive.is_file():
        raise PublishError(f"Missing {edition} archive: {archive}")
    with zipfile.ZipFile(archive) as bundle:
        names = bundle.namelist()
        manifest_name = "codex-goal-supervisor/.codex-plugin/plugin.json"
        if manifest_name not in names:
            raise PublishError(f"{archive.name} has no plugin manifest.")
        payload = json.loads(bundle.read(manifest_name).decode("utf-8"))
        if payload.get("version") != version or payload.get("distributionEdition") != edition:
            raise PublishError(f"{archive.name} identity or edition mismatch.")
        if any("/__pycache__/" in name or name.endswith((".pyc", ".pyo", ".DS_Store")) for name in names):
            raise PublishError(f"{archive.name} contains generated noise.")
        if any(name.startswith("codex-goal-supervisor/.agent/") for name in names):
            raise PublishError(f"{archive.name} contains checkout runtime state.")


def run_extracted_verification(full_archive: Path) -> list[dict[str, Any]]:
    with tempfile.TemporaryDirectory(prefix="goal-supervisor-release-verify-") as temporary:
        root = Path(temporary)
        with zipfile.ZipFile(full_archive) as bundle:
            bundle.extractall(root)
        plugin = root / "codex-goal-supervisor"
        commands = [
            [sys.executable, "-m", "unittest", "-q", "verification.tests.test_goal_compass"],
            [sys.executable, "-m", "unittest", "discover", "-s", "verification/tests", "-q"],
            [sys.executable, "assets/governor-harness/.agent/selftest/test_goal_compass.py"],
        ]
        results = []
        for command in commands:
            result = run_command(command, cwd=plugin, timeout=SUITE_TIMEOUT)
            results.append({"command": " ".join(command), "stdout": result.stdout[-1200:], "stderr": result.stderr[-1200:]})
        return results


def write_sha_manifest(release_dir: Path, release: str, archives: dict[str, Path]) -> Path:
    output = release_dir / f"codex-goal-supervisor-{release}-SHA256.txt"
    lines = [f"{sha256(archives[edition])}  {archives[edition].name}" for edition in ("offline", "update-only", "full")]
    output.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return output


def copy_tree_contents(source: Path, target: Path) -> None:
    for item in target.iterdir():
        if item.name == ".git":
            continue
        if item.is_dir() and not item.is_symlink():
            shutil.rmtree(item)
        else:
            item.unlink()
    for item in source.iterdir():
        destination = target / item.name
        if item.is_dir():
            shutil.copytree(item, destination)
        else:
            shutil.copy2(item, destination)


def build_marketplace_tree(edition: str, destination: Path) -> None:
    run_command([
        sys.executable,
        str(BUILDER),
        "--output",
        str(destination),
        "--marketplace-edition",
        edition,
        "--force",
    ])


def sync_marketplace(url: str, edition: str, built_tree: Path, version: str) -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix=f"goal-supervisor-publish-{edition}-") as temporary:
        checkout = Path(temporary) / "checkout"
        run_network_command(["git", "-c", "http.version=HTTP/1.1", "clone", "--quiet", url, str(checkout)], timeout=SUITE_TIMEOUT)
        copy_tree_contents(built_tree, checkout)
        run_command(["git", "add", "--all"], cwd=checkout)
        changed = run_command(["git", "diff", "--cached", "--quiet"], cwd=checkout, check=False).returncode != 0
        if changed:
            run_command([
                "git", "-c", "user.name=Codex Goal Supervisor Release",
                "-c", "user.email=release@users.noreply.github.com",
                "commit", "-m", f"release: publish Codex Goal Supervisor {version}",
            ], cwd=checkout)
            run_network_command(["git", "-c", "http.version=HTTP/1.1", "push", "origin", "HEAD:main"], cwd=checkout, timeout=SUITE_TIMEOUT)
        payload = json.loads((checkout / "plugins/codex-goal-supervisor/.codex-plugin/plugin.json").read_text(encoding="utf-8"))
        if payload.get("version") != version or payload.get("distributionEdition") != edition:
            raise PublishError(f"Published {edition} marketplace tree failed local identity verification.")
        return {"edition": edition, "changed": changed, "commit": run_command(["git", "rev-parse", "HEAD"], cwd=checkout).stdout.strip()}


def publish_github_release(identity: dict[str, str], assets: list[Path], head: str) -> dict[str, Any]:
    expected = {path.name: f"sha256:{sha256(path)}" for path in assets}

    def verify_assets(payload: dict[str, Any]) -> list[str]:
        actual = {str(row.get("name")): str(row.get("digest") or "") for row in payload.get("assets", [])}
        if set(expected) != set(actual):
            raise PublishError(f"Release {identity['tag']} has a different asset set.")
        mismatch = [name for name, digest in expected.items() if actual.get(name) != digest]
        if mismatch:
            raise PublishError(f"Release {identity['tag']} has conflicting asset digests: {', '.join(mismatch)}")
        return sorted(actual)

    existing = run_network_command(
        ["gh", "release", "view", identity["tag"], "--repo", CANONICAL_REPOSITORY, "--json", "tagName,assets,url"],
        check=False,
    )
    if existing.returncode == 0:
        payload = json.loads(existing.stdout)
        return {"created": False, "url": payload.get("url"), "assets": verify_assets(payload)}
    command = [
        "gh", "release", "create", identity["tag"],
        "--repo", CANONICAL_REPOSITORY,
        "--target", head,
        "--title", f"Codex Goal Supervisor {identity['release']}",
        "--notes-file", identity["notes"],
        *[str(path) for path in assets],
    ]
    created = run_network_command(command, timeout=SUITE_TIMEOUT).stdout.strip()
    verified = run_network_command([
        "gh", "release", "view", identity["tag"], "--repo", CANONICAL_REPOSITORY,
        "--json", "tagName,assets,url",
    ])
    payload = json.loads(verified.stdout)
    return {"created": True, "url": payload.get("url") or created, "assets": verify_assets(payload)}


def verify_remote_marketplace(url: str, edition: str, version: str) -> dict[str, str]:
    with tempfile.TemporaryDirectory(prefix=f"goal-supervisor-remote-{edition}-") as temporary:
        checkout = Path(temporary) / "checkout"
        run_network_command([
            "git", "-c", "http.version=HTTP/1.1", "clone", "--quiet", "--depth", "1", url, str(checkout),
        ], timeout=SUITE_TIMEOUT)
        payload = json.loads((checkout / "plugins/codex-goal-supervisor/.codex-plugin/plugin.json").read_text(encoding="utf-8"))
        if payload.get("version") != version or payload.get("distributionEdition") != edition:
            raise PublishError(f"Remote {edition} marketplace does not expose {version}.")
        return {"edition": edition, "version": str(payload["version"]), "commit": run_command(["git", "rev-parse", "HEAD"], cwd=checkout).stdout.strip()}


def publish(*, dry_run: bool = False) -> dict[str, Any]:
    identity = require_release_source()
    compile_source()
    source_tests = run_source_verification()
    release_dir, archives = build_release_archives(identity["version"], identity["release"], identity["build"])
    extracted_tests = run_extracted_verification(archives["full"])
    checksums = write_sha_manifest(release_dir, identity["release"], archives)
    if dry_run:
        return {
            "status": "VERIFIED_NOT_PUBLISHED",
            **identity,
            "archives": {key: str(path) for key, path in archives.items()},
            "checksums": str(checksums),
            "source_verification": source_tests,
            "extracted_verification": extracted_tests,
        }

    run_network_command(["git", "-c", "http.version=HTTP/1.1", "fetch", "origin", "main"], timeout=SUITE_TIMEOUT)
    ancestor = run_command(["git", "merge-base", "--is-ancestor", "origin/main", "HEAD"], check=False)
    if ancestor.returncode != 0:
        raise PublishError("Local main does not contain origin/main; integrate the remote before publishing.")
    run_network_command(["git", "-c", "http.version=HTTP/1.1", "push", "origin", "HEAD:main"], timeout=SUITE_TIMEOUT)
    head = run_command(["git", "rev-parse", "HEAD"]).stdout.strip()

    assets = [archives[edition] for edition in ("offline", "update-only", "full")] + [checksums]
    release = publish_github_release(identity, assets, head)
    remote_tag = run_network_command([
        "git",
        "ls-remote",
        "origin",
        f"refs/tags/{identity['tag']}",
        f"refs/tags/{identity['tag']}^{{}}",
    ]).stdout.splitlines()
    if not tag_resolves_to_head("\n".join(remote_tag), head):
        raise PublishError(f"Remote tag {identity['tag']} does not resolve to the published source commit.")

    with tempfile.TemporaryDirectory(prefix="goal-supervisor-marketplaces-") as temporary:
        marketplace_results = []
        for edition, config in MARKETPLACES.items():
            tree = Path(temporary) / edition
            build_marketplace_tree(edition, tree)
            marketplace_results.append(sync_marketplace(str(config["url"]), edition, tree, identity["version"]))
    remotes = [
        verify_remote_marketplace(str(config["url"]), edition, identity["version"])
        for edition, config in MARKETPLACES.items()
    ]
    return {
        "status": "PUBLISHED_AND_VERIFIED",
        **identity,
        "source_commit": head,
        "marketplaces": marketplace_results,
        "remote_verification": remotes,
        "github_release": release,
        "archive_sha256": {edition: sha256(path) for edition, path in archives.items()},
        "source_verification": source_tests,
        "extracted_verification": extracted_tests,
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="Run all verification and build artifacts without network writes.")
    args = parser.parse_args(argv)
    try:
        result = publish(dry_run=args.dry_run)
    except (OSError, ValueError, json.JSONDecodeError, zipfile.BadZipFile, PublishError) as exc:
        print(json.dumps({"status": "PUBLISH_FAILED", "error": str(exc)}, ensure_ascii=False, indent=2))
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
