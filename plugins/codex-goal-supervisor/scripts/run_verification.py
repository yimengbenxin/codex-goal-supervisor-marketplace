#!/usr/bin/env python3
"""Run every verification module in bounded parallel subprocesses."""
from __future__ import annotations

import argparse
import concurrent.futures
import os
import re
import signal
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path


PLUGIN_ROOT = Path(__file__).resolve().parents[1]
TEST_ROOT = PLUGIN_ROOT / "verification" / "tests"
DEFAULT_WORKERS = min(6, max(1, os.cpu_count() or 1))
DEFAULT_MODULE_TIMEOUT = 120.0


@dataclass(frozen=True)
class ModuleResult:
    module: str
    returncode: int
    elapsed: float
    stdout: str
    stderr: str
    test_count: int


def verification_modules() -> list[str]:
    modules = []
    for path in sorted(TEST_ROOT.glob("test_*.py")):
        if path.name == "test_goal_compass.py":
            continue
        modules.append(f"verification.tests.{path.stem}")
    if not modules:
        raise RuntimeError("No verification modules found.")
    return modules


def _kill_process_tree(process: subprocess.Popen[str]) -> None:
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


def run_module(module: str, timeout: float) -> ModuleResult:
    command = [sys.executable, "-m", "unittest", "-q", module]
    kwargs = {
        "cwd": PLUGIN_ROOT,
        "text": True,
        "encoding": "utf-8",
        "errors": "replace",
        "stdout": subprocess.PIPE,
        "stderr": subprocess.PIPE,
        "stdin": subprocess.DEVNULL,
        "env": {
            **os.environ,
            "PYTHONDONTWRITEBYTECODE": "1",
            "PYTHONUTF8": "1",
        },
    }
    if os.name != "nt":
        kwargs["start_new_session"] = True
    started = time.perf_counter()
    process = subprocess.Popen(command, **kwargs)
    try:
        stdout, stderr = process.communicate(timeout=timeout)
        returncode = process.returncode
    except subprocess.TimeoutExpired:
        _kill_process_tree(process)
        try:
            stdout, stderr = process.communicate(timeout=5)
        except subprocess.TimeoutExpired:
            stdout, stderr = "", "<process did not flush after termination>"
        returncode = 124
        stderr = f"Module timed out after {timeout:.0f}s.\n{stderr}"
    elapsed = time.perf_counter() - started
    match = re.search(r"Ran\s+(\d+)\s+tests?", f"{stdout}\n{stderr}")
    return ModuleResult(module, returncode, elapsed, stdout, stderr, int(match.group(1)) if match else 0)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workers", type=int, default=DEFAULT_WORKERS)
    parser.add_argument("--module-timeout", type=float, default=DEFAULT_MODULE_TIMEOUT)
    args = parser.parse_args(argv)
    if args.workers < 1 or args.module_timeout <= 0:
        parser.error("workers and module-timeout must be positive")

    modules = verification_modules()
    started = time.perf_counter()
    with concurrent.futures.ThreadPoolExecutor(max_workers=min(args.workers, len(modules))) as executor:
        futures = {executor.submit(run_module, module, args.module_timeout): module for module in modules}
        results = [future.result() for future in concurrent.futures.as_completed(futures)]
    results.sort(key=lambda item: item.module)

    failures = [result for result in results if result.returncode != 0]
    for result in failures:
        print(f"FAIL {result.module} ({result.elapsed:.3f}s)", file=sys.stderr)
        if result.stdout:
            print(result.stdout[-4000:], file=sys.stderr)
        if result.stderr:
            print(result.stderr[-4000:], file=sys.stderr)
    elapsed = time.perf_counter() - started
    total_tests = sum(result.test_count for result in results)
    slowest = sorted(results, key=lambda item: item.elapsed, reverse=True)[:5]
    print(f"Ran {total_tests} tests across {len(results)} modules in {elapsed:.3f}s")
    print("Slowest modules: " + ", ".join(f"{item.module.rsplit('.', 1)[-1]}={item.elapsed:.3f}s" for item in slowest))
    print("FAILED" if failures else "OK")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
