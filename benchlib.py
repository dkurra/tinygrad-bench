"""Shared helpers for tinygrad-bench: container test runs and pytest parsing.

Used by taskgen/validate_tasks.py (task verification) and evaluation/score.py
(scoring model patches). Both run the same flow so validation results are
directly comparable to scoring results:

  fresh container (offline) -> checkout base_commit -> strip git history ->
  editable install -> apply patches -> pytest -rA on the task's test files
"""

import re
import subprocess
import tempfile
from pathlib import Path

IMAGE = "tinygrad-bench:base"

# Must match run.env_startup_command in evaluation/tinygrad.yaml so agents see
# exactly the state that validation and scoring run against.
SETUP_TEMPLATE = (
    "cd /testbed && git checkout -q {base_commit} && rm -rf .git && git init -q "
    "&& git add -A && git commit -qm 'tinygrad-bench base state' "
    "&& pip install -q -e . --no-deps --no-build-isolation"
)

PYTEST_CMD = (
    "timeout {budget} python -m pytest {files} -rA --tb=no -q "
    "--timeout 120 --continue-on-collection-errors -p no:cacheprovider"
)

_SUMMARY_RE = re.compile(r"^(PASSED|FAILED|ERROR|XPASS|XFAIL) (\S.*?)(?: - .*)?$")


def parse_pytest_summary(output: str) -> dict[str, str]:
    """Parse `pytest -rA` short-summary lines into {node_id: status}.

    XPASS counts as passed, XFAIL as failed-by-design (excluded). SKIPPED lines
    carry no node id in -rA output and are simply absent from the result.
    """
    results: dict[str, str] = {}
    for line in output.splitlines():
        m = _SUMMARY_RE.match(line.strip())
        if not m:
            continue
        status, node_id = m.group(1), m.group(2).strip()
        if "::" not in node_id:  # file-level collection error, not a single test
            continue
        results[node_id] = {"PASSED": "pass", "XPASS": "pass"}.get(status, "fail")
    return results


def passed(results: dict[str, str]) -> set[str]:
    return {k for k, v in results.items() if v == "pass"}


def run_task_container(
    base_commit: str,
    script_body: str,
    patch_files: dict[str, str] | None = None,
    timeout: int = 1800,
    image: str = IMAGE,
) -> tuple[int, str]:
    """Run setup + script_body in a fresh offline container.

    patch_files maps container-visible names to diff content; they are exposed
    read-only under /patches/.
    """
    with tempfile.TemporaryDirectory(dir=Path.home() / ".cache") as tmp:
        for name, content in (patch_files or {}).items():
            Path(tmp, name).write_text(content)
        setup = SETUP_TEMPLATE.format(base_commit=base_commit)
        cmd = [
            "docker", "run", "--rm", "--network", "none",
            "-v", f"{tmp}:/patches:ro",
            image, "bash", "-c", f"{setup} && {{ {script_body}\n}}",
        ]
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        except subprocess.TimeoutExpired as e:
            out = e.output.decode() if isinstance(e.output, bytes) else (e.output or "")
            return -1, out + "\n===TGB_TIMEOUT==="
        return proc.returncode, proc.stdout + proc.stderr


def split_sections(output: str) -> dict[str, str]:
    """Split container output on ===TGB_<NAME>=== markers."""
    sections: dict[str, str] = {}
    current = "PREAMBLE"
    for line in output.splitlines():
        m = re.match(r"^===TGB_(\w+)===$", line.strip())
        if m:
            current = m.group(1)
            sections[current] = ""
        else:
            sections[current] = sections.get(current, "") + line + "\n"
    return sections
