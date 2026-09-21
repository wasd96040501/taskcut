#!/usr/bin/env python3
"""Turns a click checkout into nine open issues.

Each issue is a bug click really shipped and really fixed. The fixes are
reverted here -- source only, never the tests that came with them -- so the
checkout has nine real regressions, each with the regression test its original
author wrote. Four of the nine are in core.py, so the work keeps returning to
the same large file, which is where a crowded context would show.

The broken state is committed, so that a check can ask afterwards exactly what
the session changed.

Usage: click_issues.py <workspace>
"""

import pathlib
import subprocess
import sys

HERE = pathlib.Path(__file__).resolve().parent
PATCHES = HERE.parent / "fixtures" / "click"

#: Upstream commits whose source changes are reverted, in the order the issues
#: are handed out.
FIXES = [
    "399919f740", "4d3db84b25", "a3321c9ca1", "762c97eef7", "665736bc85",
    "f316d5cb3a", "047adef258", "82f377c547", "0551bf5358",
]


def run(*args, cwd):
    subprocess.run(args, cwd=cwd, check=True, stdout=subprocess.DEVNULL)


def main(root: pathlib.Path) -> None:
    exclude = root / ".git" / "info" / "exclude"
    exclude.write_text(exclude.read_text() + "\n.venv/\n*.egg-info/\n.pytest_cache/\n")

    if not (root / ".venv").exists():
        run(sys.executable, "-m", "venv", ".venv", cwd=root)
        run(".venv/bin/python", "-m", "pip", "install", "--quiet", "--disable-pip-version-check", "pytest", "-e", ".", cwd=root)

    for sha in FIXES:
        run("git", "apply", "-R", str(PATCHES / f"{sha}.patch"), cwd=root)

    run("git", "-c", "user.name=taskcut-eval", "-c", "user.email=eval@taskcut.invalid",
        "commit", "--quiet", "-am", "Nine open issues", cwd=root)


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    main(pathlib.Path(sys.argv[1]).resolve())
