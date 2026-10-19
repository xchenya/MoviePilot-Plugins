"""Run every V3 Python regression suite in an isolated process.

The shared gate invokes this entry point with the MoviePilot environment.
Suites intentionally use independent offline adapters; isolation prevents a
plugin's app-module doubles and repeated test_plugin.py names affecting others.
Frontend interaction checks remain in each plugin's dedicated workflow.
"""
import os
from pathlib import Path
import subprocess
import sys

root = Path(__file__).resolve().parents[1]
suites = sorted(path for path in (root / "tests/v3").iterdir()
                if path.is_dir() and list(path.glob("test_*.py")))
if not suites:
    raise SystemExit("No V3 test suites found")
failed = []
for suite in suites:
    env = dict(os.environ)
    if suite.name == "dian115sign":
        env["DIAN115_OFFLINE_TEST"] = "1"
    print(f"Running {suite.name}", flush=True)
    result = subprocess.run([sys.executable, "-m", "pytest", "-q", str(suite)],
                            cwd=root, env=env, check=False)
    if result.returncode:
        failed.append(suite.name)
if failed:
    raise SystemExit("Failed suites: " + ", ".join(failed))
