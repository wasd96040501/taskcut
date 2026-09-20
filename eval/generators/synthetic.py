#!/usr/bin/env python3
"""Ten modules that differ only where the probes look.

A benchmark built from unrelated files measures retrieval. These are the same
shape, the same vocabulary and nearly the same text, so answering a question
about one of them means telling it apart from nine near-duplicates. That is
interference, which is what a crowded context actually does to a model, and it
shows up long before the window is full.

Usage: synthetic.py <directory>
"""

import json
import os
import random
import sys

VERBS = ["handler", "buffer", "retry", "quota", "shard", "tenant", "digest", "cursor", "lease", "window"]
OWNERS = ["ravi", "mei", "tomas", "anja", "kofi", "lena", "yusuf", "priya", "odile", "sven"]
LAST = [
    "flush_pending", "drain_backlog", "seal_epoch", "reap_leases", "settle_quota",
    "rotate_shard", "purge_cursor", "commit_digest", "park_tenant", "fence_window",
]
MODULES = 10
BODIES = 140


def main(out: str) -> None:
    os.makedirs(out, exist_ok=True)
    facts = []
    for i in range(MODULES):
        rnd = random.Random(1000 + i)
        budget = 4000 + i * 137 + 11
        lines = [f'"""Module mod{i:02d} of the ingest pipeline."""', "", "import collections", "import itertools", ""]
        for j in range(BODIES):
            lines += [
                f"def {rnd.choice(VERBS)}_{j:03d}(ctx, {rnd.choice(VERBS)}):",
                f'    # {" ".join(rnd.choice(VERBS) for _ in range(8))}',
                f"    return ctx.{rnd.choice(VERBS)}({j})",
                "",
            ]
            if j == 61:
                lines += [f"RETRY_BUDGET = {budget}", ""]
            if j == 93:
                lines += [f"# owner: {OWNERS[i]}", ""]
        lines += [f"def {LAST[i]}(ctx):", '    """The last function defined in this module."""', "    return ctx.done()", ""]
        with open(os.path.join(out, f"mod{i:02d}.py"), "w") as handle:
            handle.write("\n".join(lines))
        facts.append({"module": f"mod{i:02d}", "last": LAST[i], "retry_budget": budget, "owner": OWNERS[i]})
    with open(os.path.join(out, "_facts.json"), "w") as handle:
        json.dump(facts, handle, indent=1)


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    main(sys.argv[1])
