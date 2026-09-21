#!/usr/bin/env python3
"""Turns a click checkout into a set of open issues.

Each issue is a change click really shipped -- a bug fix or a feature -- and is
reverted here, source only, never the tests that came with it. The checkout is
left with real regressions and real missing features, each with the tests its
original author wrote.

Which changes, and in what order they are reverted, is named by an order file
beside the patches. Reverting has to go newest first: a later change can build
on an earlier one, and peeling them off in any other order does not apply.

The broken state is committed, so that a check can ask afterwards exactly what
the session changed.

Usage: click_issues.py <workspace> <order file>
"""

import pathlib
import subprocess
import sys

HERE = pathlib.Path(__file__).resolve().parent
PATCHES = HERE.parent / "fixtures" / "click"


def run(*args, cwd):
    subprocess.run(args, cwd=cwd, check=True, stdout=subprocess.DEVNULL)


def main(root: pathlib.Path, order: str) -> None:
    shas = [line.strip() for line in (PATCHES / order).read_text().splitlines() if line.strip()]

    exclude = root / ".git" / "info" / "exclude"
    exclude.write_text(exclude.read_text() + "\n.venv/\n*.egg-info/\n.pytest_cache/\n")

    if not (root / ".venv").exists():
        run(sys.executable, "-m", "venv", ".venv", cwd=root)
        run(".venv/bin/python", "-m", "pip", "install", "--quiet", "--disable-pip-version-check",
            "pytest", "-e", ".", cwd=root)

    for sha in shas:
        run("git", "apply", "-R", str(PATCHES / f"{sha}.patch"), cwd=root)

    run("git", "-c", "user.name=taskcut-eval", "-c", "user.email=eval@taskcut.invalid",
        "commit", "--quiet", "-am", f"{len(shas)} open issues", cwd=root)


if __name__ == "__main__":
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    main(pathlib.Path(sys.argv[1]).resolve(), sys.argv[2])
