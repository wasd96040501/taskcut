#!/usr/bin/env python3
"""Turns a click checkout into a set of open issues.

Each issue is a change click really shipped -- a bug fix or a feature -- and is
reverted here, source only, never the tests that came with it. The checkout is
left with real regressions and real missing features, each with the tests its
original author wrote.

Which changes, and in what order they are reverted, is named by an order file
beside the patches. Reverting has to go newest first: a later change can build
on an earlier one, and peeling them off in any other order does not apply.

The broken state is committed and tagged `eval-start`, so that a check can ask
afterwards exactly what the session changed -- even of a session told to commit
its work as it goes, which moves HEAD.

A workload that hands every issue over in one message names its own file as a
third argument, and its issues are written to ISSUES.md, in its order.

Usage: click_issues.py <workspace> <order file> [workload file]
"""

import json
import pathlib
import subprocess
import sys

HERE = pathlib.Path(__file__).resolve().parent
PATCHES = HERE.parent / "fixtures" / "click"
WORKLOADS = HERE.parent / "workloads"


def run(*args, cwd):
    subprocess.run(args, cwd=cwd, check=True, stdout=subprocess.DEVNULL)


def issues_markdown(issues: list[str]) -> str:
    parts = [f"# Open issues\n\n{len(issues)} issues, to be worked through in order.\n"]
    parts += [f"## Issue {n}\n\n{text.strip()}\n" for n, text in enumerate(issues, 1)]
    return "\n".join(parts)


def main(root: pathlib.Path, order: str, workload: str = "") -> None:
    shas = [line.strip() for line in (PATCHES / order).read_text().splitlines() if line.strip()]

    exclude = root / ".git" / "info" / "exclude"
    exclude.write_text(exclude.read_text() + "\n.venv/\n*.egg-info/\n.pytest_cache/\n")

    if not (root / ".venv").exists():
        run(sys.executable, "-m", "venv", ".venv", cwd=root)
        run(".venv/bin/python", "-m", "pip", "install", "--quiet", "--disable-pip-version-check",
            "pytest", "-e", ".", cwd=root)

    for sha in shas:
        run("git", "apply", "-R", str(PATCHES / f"{sha}.patch"), cwd=root)

    if workload:
        issues = json.loads((WORKLOADS / workload).read_text())["files"]
        (root / "ISSUES.md").write_text(issues_markdown(issues))

    run("git", "add", "-A", cwd=root)
    run("git", "-c", "user.name=taskcut-eval", "-c", "user.email=eval@taskcut.invalid",
        "commit", "--quiet", "-m", f"{len(shas)} open issues", cwd=root)
    run("git", "tag", "eval-start", cwd=root)


if __name__ == "__main__":
    if len(sys.argv) not in (3, 4):
        sys.exit(__doc__)
    main(pathlib.Path(sys.argv[1]).resolve(), *sys.argv[2:])
