#!/usr/bin/env python3
"""Twelve service modules, large enough to crowd a 200k window.

This material exists to test what a probe cannot. The earlier workloads asked
the model to retrieve a fact once the work was over, which is the last thing a
crowded context breaks. Two things are planted here instead:

  a rule       set once in the opening turn and never repeated, so that
               whether it is still being applied at step twelve can be read
               off the work itself
  a reversal   a value established at step four and overridden at step ten,
               so that an answer can be wrong rather than merely absent

The modules are deliberately alike. Interference between confusable neighbours
is what a crowded context does to a model, and unrelated files would measure
retrieval again.

Usage: drift.py <directory>
"""

import json
import os
import random
import sys

VERBS = ["ingest", "shard", "lease", "digest", "quota", "cursor", "tenant", "buffer", "reap", "fence"]
OWNERS = ["ravi", "mei", "tomas", "anja", "kofi", "lena", "yusuf", "priya", "odile", "sven", "hana", "bram"]

#: Buried mid-file and never asked for during the work. Only the transcript
#: holds it, so recovering it after a cut means going back to the source --
#: which is the price of the cut, in the only currency that matters.
AUDIT_TAGS = ["cobalt", "juniper", "marlin", "quartz", "saffron", "tundra",
              "vellum", "wicket", "yarrow", "zephyr", "basalt", "cinder"]

SERVICES = 12
BLOCKS = 160

#: Every service reports the same schema version, so the rule "always quote it"
#: has one answer and compliance is a substring check rather than a lookup.
SCHEMA_VERSION = "v3.7.0"

#: The reversal. Set in one service, overridden in a later one.
SUPERSEDED_AT = 3
SUPERSEDES_AT = 9
OLD_TIMEOUT = 3000
NEW_TIMEOUT = 7500


def main(out: str) -> None:
    os.makedirs(out, exist_ok=True)
    facts = []
    for i in range(SERVICES):
        rnd = random.Random(7000 + i)
        registry = f"SVC-{1040 + i * 7:04d}"
        owner = OWNERS[i]
        retry = 11 + i * 3          # distinct, and smallest at svc_00
        lines = [
            f'"""Service svc_{i:02d} of the ingest pipeline."""',
            f"# registry: {registry}",
            "",
            f'SCHEMA_VERSION = "{SCHEMA_VERSION}"',
            f'OWNER = "{owner}"',
            f"RETRY_BUDGET = {retry}",
            "",
            "import collections",
            "import itertools",
            "",
        ]
        if i == SUPERSEDED_AT:
            lines += [f"DEFAULT_TIMEOUT_MS = {OLD_TIMEOUT}", ""]
        if i == SUPERSEDES_AT:
            lines += [
                f"# NOTE: supersedes svc_{SUPERSEDED_AT:02d}. DEFAULT_TIMEOUT_MS is "
                f"{NEW_TIMEOUT} pipeline-wide from {SCHEMA_VERSION} onward;",
                f"# the {OLD_TIMEOUT} declared there is obsolete and must not be used.",
                f"DEFAULT_TIMEOUT_MS = {NEW_TIMEOUT}",
                "",
            ]
        for j in range(BLOCKS):
            if j == BLOCKS // 2:
                lines += [f"# audit: {AUDIT_TAGS[i]}", ""]
            a, b, c = rnd.choice(VERBS), rnd.choice(VERBS), rnd.choice(VERBS)
            lines += [
                f"def {a}_{j:03d}(ctx, {b}, *, deadline=None):",
                f'    """{" ".join(rnd.choice(VERBS) for _ in range(7))}."""',
                f"    scratch = collections.deque(itertools.islice(ctx.{c}(), {j}))",
                f"    return ctx.{rnd.choice(VERBS)}(scratch, deadline=deadline)",
                "",
            ]
        with open(os.path.join(out, f"svc_{i:02d}.py"), "w") as handle:
            handle.write("\n".join(lines))
        facts.append({
            "file": f"svc_{i:02d}.py", "registry": registry, "owner": owner,
            "retry": retry, "audit": AUDIT_TAGS[i],
        })

    with open(os.path.join(out, "_facts.json"), "w") as handle:
        json.dump(
            {
                "schema_version": SCHEMA_VERSION,
                "services": facts,
                "superseded": {"at": facts[SUPERSEDED_AT]["registry"], "value": OLD_TIMEOUT},
                "supersedes": {"at": facts[SUPERSEDES_AT]["registry"], "value": NEW_TIMEOUT},
            },
            handle,
            indent=1,
        )


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    main(sys.argv[1])
