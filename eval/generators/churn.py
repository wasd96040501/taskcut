#!/usr/bin/env python3
"""Twelve service modules in which six pipeline-wide settings change, or do not.

Every level of this workload is the same twelve files, to the character count:
the same functions, the same header, the same seventy-two numbers in the same
places. What a level changes is what those numbers are. At `lo` the settings
are declared once, in svc_00, and every later number is a constant local to its
service. At `hi` each later service overrides three of the six settings, 33
overrides in all, so by the last file the context holds four or five obsolete
values of each. `mid` overrides one setting per service.

Three and not six: a service that overrode all six would hold every current
value itself, and the answer would always be in the file just read. With three,
half the settings in force were set files ago, behind values since replaced.

That is the one thing the literature says a long context breaks and a count of
tokens cannot see: earlier values of the same key, retrieved in place of the
current one (proactive interference, arXiv 2506.08184). The context is the
same size at every level; only the interference differs.

Each file is read with the Read tool, not `cat`. A file is about 36,000
characters; Claude Code (2.1.283) keeps a Bash output that large on disk and
puts a preview of about 2,000 characters in the context, so a `cat` never puts
the file where interference could happen, and the model goes back to the file
with a search instead -- which the first pilot of this workload did at every
step. Read returns the whole file.

After each file the model reports the six settings in force, so the answer is
graded at every step, against a value known in advance, and a wrong answer can
be told apart as stale -- an earlier value of the same setting -- or anything
else.

Usage:
  churn.py <directory> <level>      lay the files down
  churn.py --workload <level>       print the workload's JSON
"""

import json
import os
import random
import sys

VERBS = ["ingest", "shard", "lease", "digest", "quota", "cursor", "tenant", "buffer", "reap", "fence"]
OWNERS = ["ravi", "mei", "tomas", "anja", "kofi", "lena", "yusuf", "priya", "odile", "sven", "hana", "bram"]
LOCALS = ["SPILL_DEPTH", "WARM_POOL", "PAGE_SPAN", "DRAIN_WAIT", "PROBE_GAP", "LOG_RING"]

#: The settings tracked, all declared in svc_00.
KEYS = ["DEFAULT_TIMEOUT_MS", "BATCH_LIMIT", "LEASE_TTL_MS", "SHARD_COUNT", "QUOTA_BURST", "FENCE_EPOCH"]

SERVICES = 12
BLOCKS = 160
#: The block after which each of a service's six numbered lines sits: spread
#: through the file, and the same in every file and at every level.
SLOTS = [18, 44, 71, 97, 124, 150]

#: Overrides per service after svc_00, by level.
LEVELS = {"lo": 0, "mid": 1, "hi": 3}

#: Every line that carries a number is padded to this, so that a level changes
#: what a line says and never how long it is.
WIDTH = 96

BRIEFING = (
    "I am auditing the ingest pipeline before a release. We will go through its twelve services "
    "one at a time, and I will tell you which. Six settings are pipeline-wide: "
    + ", ".join(KEYS)
    + ". svc_00 declares them, and a later service may override any of them from that point on; a "
    "constant a service declares for itself changes nothing pipeline-wide. After every service, end "
    "your report with one line in exactly this form, giving the value of each setting in force once "
    "that service has been read:\n\nIN FORCE: "
    + " ".join(f"{k}=<n>" for k in KEYS)
    + "\n\nAnswer from what you have read. Use no tool but the one Read each step names: no search, "
    "no command, no second look at an earlier file. "
    "Acknowledge this and wait for the first service."
)

STEP = (
    "Sub-task {n} of {total}: read the whole of {file} with the Read tool, then report its owner and its "
    "retry budget, and end with the IN FORCE line."
)


def _line(text: str) -> str:
    if len(text) > WIDTH:
        raise ValueError(f"line longer than {WIDTH}: {text}")
    return text + " " * (WIDTH - len(text))


def plan(level: str) -> list[list[tuple[str, int, bool]]]:
    """For each service, its six numbered lines in order: (name, value, overrides?)."""
    overrides = LEVELS[level]
    pool = random.Random(4242).sample(range(1000, 10000), SERVICES * len(SLOTS))
    services = []
    for i in range(SERVICES):
        values = pool[i * len(SLOTS):(i + 1) * len(SLOTS)]
        if i == 0:
            services.append([(k, v, True) for k, v in zip(KEYS, values)])
            continue
        # Which settings this service overrides, and in which of its lines:
        # drawn once per service, so `mid` and `hi` agree on what they share.
        rnd = random.Random(9100 + i)
        keys = rnd.sample(KEYS, len(KEYS))[:overrides]
        slots = sorted(rnd.sample(range(len(SLOTS)), len(SLOTS))[:overrides])
        lines = [(f"SVC{i:02d}_{LOCALS[s]}", values[s], False) for s in range(len(SLOTS))]
        for key, s in zip(keys, slots):
            lines[s] = (key, values[s], True)
        services.append(lines)
    return services


def render(i: int, lines: list[tuple[str, int, bool]]) -> str:
    rnd = random.Random(7000 + i)
    out = [
        f'"""Service svc_{i:02d} of the ingest pipeline."""',
        f"# registry: SVC-{1040 + i * 7:04d}",
        "",
        f'OWNER = "{OWNERS[i]}"',
        f"RETRY_BUDGET = {11 + i * 3}",
        "",
        "import collections",
        "import itertools",
        "",
    ]
    for j in range(BLOCKS):
        if j in SLOTS:
            name, value, pipeline = lines[SLOTS.index(j)]
            if i == 0:
                note = "pipeline-wide; a later service may override it"
            elif pipeline:
                note = "overrides the pipeline-wide value from here on"
            else:
                note = "local to this service; pipeline unchanged"
            out += [_line(f"{name} = {value}  # {note}"), ""]
        a, b, c = rnd.choice(VERBS), rnd.choice(VERBS), rnd.choice(VERBS)
        out += [
            f"def {a}_{j:03d}(ctx, {b}, *, deadline=None):",
            f'    """{" ".join(rnd.choice(VERBS) for _ in range(7))}."""',
            f"    scratch = collections.deque(itertools.islice(ctx.{c}(), {j}))",
            f"    return ctx.{rnd.choice(VERBS)}(scratch, deadline=deadline)",
            "",
        ]
    return "\n".join(out)


def tracked(level: str) -> list[dict]:
    """After each service: every setting's value in force, and the values it had before."""
    history = {k: [] for k in KEYS}
    steps = []
    for lines in plan(level):
        for name, value, pipeline in lines:
            if pipeline:
                history[name].append(str(value))
        steps.append({k: {"current": h[-1], "stale": h[:-1]} for k, h in history.items()})
    return steps


def workload(level: str) -> dict:
    files = [f"svc_{i:02d}.py" for i in range(SERVICES)]
    final = tracked(level)[-1]
    overrides = sum(len(v["stale"]) for v in final.values())
    return {
        "name": f"churn-{level}",
        "description": (
            f"Twelve service modules, identical in length at every level, in which six pipeline-wide "
            f"settings are overridden {overrides} times in all. The settings in force are graded after "
            f"every file."
        ),
        "source": {"kind": "generated", "generator": f"churn.py {level}"},
        "files": files,
        "briefing": BRIEFING,
        "step_template": STEP,
        "tracked": {"pattern": r"\b{key}\s*[=:]\s*(\d+)", "steps": tracked(level)},
        "probes": [
            {
                "id": f"F{n}",
                "kind": "superseded" if value["stale"] else "headline",
                "question": f"State the pipeline-wide {key} in force now. Answer with the number alone and nothing else.",
                "expect": [value["current"]],
                "reject": value["stale"],
            }
            for n, (key, value) in enumerate(final.items(), 1)
        ],
    }


def main(out: str, level: str) -> None:
    os.makedirs(out, exist_ok=True)
    for i, lines in enumerate(plan(level)):
        with open(os.path.join(out, f"svc_{i:02d}.py"), "w") as handle:
            handle.write(render(i, lines))


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "--workload":
        print(json.dumps(workload(sys.argv[2]), indent=1))
    elif len(sys.argv) == 3 and sys.argv[2] in LEVELS:
        main(sys.argv[1], sys.argv[2])
    else:
        sys.exit(__doc__)
