#!/usr/bin/env python3
"""Turns a sqlglot checkout into a list of open issues, written to ISSUES.md.

Each issue is a change sqlglot really shipped -- a bug fix or a feature -- and
is reverted here, source only, never the tests that came with it. The checkout
is left with real regressions and real missing features, each with the tests
its original author wrote, and ISSUES.md describes them the way a bug report
would, naming the tests that fail.

The order file lists the changes newest first, which is the only order their
reversals apply in: a later change can build on an earlier one. ISSUES.md lists
them in the order of issues.json, which interleaves the kinds of work.

The broken state is committed, so that a check can ask afterwards exactly what
the session changed.

Usage: sqlglot_issues.py <workspace> <order file>
"""

import json
import os
import pathlib
import subprocess
import sys

HERE = pathlib.Path(__file__).resolve().parent
FIXTURES = HERE.parent / "fixtures" / "sqlglot"

#: setuptools_scm reads the version off git history, and the workspace is a
#: single commit with no tags.
VERSION = {"SETUPTOOLS_SCM_PRETEND_VERSION": "30.18.0"}


def run(*args, cwd, env=None):
    subprocess.run(args, cwd=cwd, check=True, stdout=subprocess.DEVNULL, env={**os.environ, **(env or {})})


def issues_markdown(issues: list[dict]) -> str:
    parts = [f"# Open issues\n\n{len(issues)} issues, to be worked through in order.\n"]
    for n, issue in enumerate(issues, 1):
        failing = "\n".join(f"    {t}" for t in issue["failing"])
        parts.append(f"## Issue {n}: {issue['title']}\n\n{issue['body'].strip()}\n\nFailing:\n\n{failing}\n")
    return "\n".join(parts)


def main(root: pathlib.Path, order: str) -> None:
    shas = [line.strip() for line in (FIXTURES / order).read_text().splitlines() if line.strip()]
    issues = json.loads((FIXTURES / "issues.json").read_text())

    exclude = root / ".git" / "info" / "exclude"
    exclude.write_text(exclude.read_text() + "\n.venv/\n*.egg-info/\n.pytest_cache/\n")

    if not (root / ".venv").exists():
        run(sys.executable, "-m", "venv", ".venv", cwd=root)
        run(".venv/bin/python", "-m", "pip", "install", "--quiet", "--disable-pip-version-check",
            "pytest", "pytest-xdist", "duckdb", "pandas", "python-dateutil", "pytz", "typing_extensions",
            "-e", ".", cwd=root, env=VERSION)

    for sha in shas:
        run("git", "apply", "-R", str(FIXTURES / f"{sha}.patch"), cwd=root)

    (root / "ISSUES.md").write_text(issues_markdown([i for i in issues if i["sha"] in shas]))

    run("git", "add", "-A", cwd=root)
    run("git", "-c", "user.name=taskcut-eval", "-c", "user.email=eval@taskcut.invalid",
        "commit", "--quiet", "-m", f"{len(shas)} open issues", cwd=root)


if __name__ == "__main__":
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    main(pathlib.Path(sys.argv[1]).resolve(), sys.argv[2])
