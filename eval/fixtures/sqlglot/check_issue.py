#!/usr/bin/env python3
"""Whether one issue is solved in a finished workspace: none of the test cases
it broke fails any more.

A test method can hold cases broken by different issues, so a whole test id is
too coarse to grade one issue by. issues.json records, per test, the cases
each issue broke -- a subtest's label, or "(test)" for the test as a whole --
and this passes when none of them is failing. It runs in the workspace, and
lives outside it, where the session never sees it.

Usage: check_issue.py <issue number, from 1>
"""

import json
import pathlib
import re
import subprocess
import sys

HERE = pathlib.Path(__file__).resolve().parent


def same(label: str) -> str:
    """A subtest's label, as it compares. pytest-xdist reports a keyword
    argument as the repr of its repr, a plain run as its repr, so quoting and
    escaping are left out of the comparison."""
    return re.sub(r"[\\'\"\s]", "", label)


def failing(ids: list[str]) -> dict[str, set[str]]:
    done = subprocess.run([".venv/bin/python", "-m", "pytest", "-q", "-rfE", "-p", "no:cacheprovider", *ids],
                          capture_output=True, text=True)
    if done.returncode not in (0, 1):
        # Collection failed or pytest could not run: nothing can be said passed.
        return {i: {"(test)"} for i in ids}
    out: dict[str, set[str]] = {}
    for line in done.stdout.splitlines():
        if m := re.match(r"^(FAILED|ERROR) (tests/\S+)", line):
            out.setdefault(m.group(2), set()).add("(test)")
        elif m := re.match(r"^SUBFAILED(.*) (tests/\S+)$", line):
            out.setdefault(m.group(2), set()).add(same(m.group(1)))
    return out


def main(number: int) -> int:
    issue = json.loads((HERE / "issues.json").read_text())[number - 1]
    now = failing(sorted(issue["cases"]))
    still = [f"{test} {case}" for test, cases in issue["cases"].items() for case in cases
             if same(case) in now.get(test, set()) or (case == "(test)" and "(test)" in now.get(test, set()))]
    for s in still:
        print("still failing:", s)
    return 1 if still else 0


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    sys.exit(main(int(sys.argv[1])))
