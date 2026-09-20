#!/usr/bin/env python3
"""The starting point for a build workload: a log file and nothing else.

The material a build task works on is the material it produces. All this lays
down is the input the finished package has to handle and a README stating the
job, so that a session which loses the thread has somewhere to look -- exactly
as a real repository would.

Usage: build.py <directory>
"""

import os
import random
import sys

LEVELS = ["DEBUG", "INFO", "WARN", "ERROR"]
SERVICES = ["ingest", "shard", "lease", "digest", "quota"]
MESSAGES = [
    "accepted batch", "deferred retry", "lease expired", "quota exceeded",
    "shard rebalanced", "cursor advanced", "digest committed", "tenant parked",
]
LINES = 400


def main(out: str) -> None:
    os.makedirs(out, exist_ok=True)
    os.makedirs(os.path.join(out, "fixtures"), exist_ok=True)
    rnd = random.Random(31337)
    lines = []
    for i in range(LINES):
        stamp = f"2024-03-{1 + i % 28:02d}T{i % 24:02d}:{i % 60:02d}:{(i * 7) % 60:02d}Z"
        lines.append(f"{stamp} {rnd.choice(LEVELS)} {rnd.choice(SERVICES)}: {rnd.choice(MESSAGES)}")
    # Three lines the parser has to reject, so that error handling is exercised
    # rather than merely written.
    lines.insert(40, "2024-03-05T01:02:03Z NOTALEVEL ingest: unknown level")
    lines.insert(120, "this line has no timestamp at all")
    lines.insert(300, "2024-03-09T04:05:06Z INFO missing-colon and message")
    with open(os.path.join(out, "fixtures", "events.log"), "w") as handle:
        handle.write("\n".join(lines) + "\n")

    with open(os.path.join(out, "README.md"), "w") as handle:
        handle.write(
            "# pipeline\n\n"
            "A package that reads event logs, validates them and summarises them.\n"
            "Standard library only.\n\n"
            "Input lines look like:\n\n"
            "    2024-03-01T00:00:00Z INFO ingest: accepted batch\n\n"
            "Some lines are malformed and must be rejected, not crashed on.\n"
        )


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    main(sys.argv[1])
