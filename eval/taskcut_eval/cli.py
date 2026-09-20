"""Command line. Wiring only: every decision belongs to one of the other modules."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import arms, driver, metrics, report, transcript, workload

HERE = Path(__file__).resolve().parent
EVAL_ROOT = HERE.parent
REPO_ROOT = EVAL_ROOT.parent
WORKLOADS = EVAL_ROOT / "workloads"
GENERATORS = EVAL_ROOT / "generators"
DEFAULT_RESULTS = EVAL_ROOT / "results"
DEFAULT_WORK = Path.home() / ".cache" / "taskcut-eval"
PROJECTS = Path.home() / ".claude" / "projects"


def _workspace(work: Path, name: str, arm: str) -> Path:
    # Per arm, always: two arms sharing a directory share a transcript
    # directory, and the runs can no longer be told apart.
    return work / "workspaces" / f"{name}--{arm}"


def cmd_list(args) -> int:
    loaded = workload.load_all(WORKLOADS)
    print("workloads:")
    for name, w in loaded.items():
        print(f"  {name:<12} {len(w.files)} files, {len(w.probes)} probes  -- {w.description}")
    print("\narms:")
    for name, a in arms.ARMS.items():
        print(f"  {name:<12} {a.description}")
    return 0


def cmd_verify(args) -> int:
    work = Path(args.work)
    problems = []
    for name, w in workload.load_all(WORKLOADS).items():
        root = _workspace(work, name, "verify")
        workload.materialise(w, root, GENERATORS)
        found = workload.check_ground_truth(w, root)
        problems += found
        print(f"{name}: {len(w.probes)} probes, {len(found)} unanswerable")
    for problem in problems:
        print(f"  {problem}", file=sys.stderr)
    return 1 if problems else 0


def cmd_run(args) -> int:
    loaded = workload.load_all(WORKLOADS)
    if args.workload not in loaded:
        raise SystemExit(f"unknown workload {args.workload!r}; known: {', '.join(loaded)}")
    w = loaded[args.workload]
    arm = arms.get(args.arm)
    work = Path(args.work)

    space = workload.materialise(w, _workspace(work, w.name, arm.name), GENERATORS)
    problems = workload.check_ground_truth(w, space)
    if problems:
        raise SystemExit("workload is not answerable:\n  " + "\n  ".join(problems))

    plugin = driver.prepare_plugin(arm, REPO_ROOT, work / "plugins" / arm.name)
    driver.run(w, arm, space, plugin, args.model)

    path = transcript.find(PROJECTS, space)
    results = Path(args.results)
    results.mkdir(parents=True, exist_ok=True)
    destination = results / f"{w.name}--{arm.name}.jsonl"
    destination.write_bytes(path.read_bytes())
    print(f"transcript -> {destination}")
    return 0


def cmd_report(args) -> int:
    loaded = workload.load_all(WORKLOADS)
    results = Path(args.results)
    by_workload: dict[str, list] = {}
    for path in sorted(results.glob("*.jsonl")):
        name, _, arm = path.stem.partition("--")
        if name not in loaded:
            continue
        run = metrics.summarise(transcript.load(path), loaded[name], arm)
        by_workload.setdefault(name, []).append(run)

    if not by_workload:
        raise SystemExit(f"no results in {results}")

    chunks, summary = [], {}
    for name, runs in by_workload.items():
        runs.sort(key=lambda r: (r.arm != "off", r.arm))
        chunks.append(report.render(name, runs))
        summary[name] = {r.arm: _numbers(r) for r in runs}
    text = "\n\n".join(chunks)

    # The transcripts are large and full of absolute paths, so they stay out of
    # history. These are what a later run is compared against.
    (results / "runs.json").write_text(json.dumps(summary, indent=1, sort_keys=True) + "\n")
    if args.out:
        Path(args.out).write_text(text + "\n")
        print(f"report -> {args.out}")
    else:
        print(text)
    return 0


def _numbers(run) -> dict:
    return {
        "weighted_input": round(run.cost.weighted),
        "cache_read": run.cost.read,
        "cache_write": run.cost.write,
        "output": run.cost.output,
        "requests": run.cost.requests,
        "context_first": run.prefix[0] if run.prefix else 0,
        "context_peak": run.peak_context,
        "context_last": run.prefix[-1] if run.prefix else 0,
        "context_series": run.prefix,
        "ledger_tokens": run.ledger,
        "ledger_messages": run.ledger_messages,
        "fidelity": {
            kind: {
                "asked": f.asked,
                "correct": f.correct,
                "went_to_disk": f.to_disk,
                "tool_calls": f.tool_calls,
            }
            for kind, f in run.fidelity.items()
        },
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="taskcut_eval", description=__doc__)
    parser.add_argument("--work", default=str(DEFAULT_WORK), help="scratch directory for workspaces and plugin copies")
    parser.add_argument("--results", default=str(DEFAULT_RESULTS), help="where transcripts are collected")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("list", help="show the workloads and arms").set_defaults(func=cmd_list)
    sub.add_parser("verify", help="check every probe is answerable from the material").set_defaults(func=cmd_verify)

    run = sub.add_parser("run", help="run one workload under one arm")
    run.add_argument("--workload", required=True)
    run.add_argument("--arm", required=True)
    run.add_argument("--model", default="sonnet")
    run.set_defaults(func=cmd_run)

    rep = sub.add_parser("report", help="render the collected results")
    rep.add_argument("--out", default="")
    rep.set_defaults(func=cmd_report)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
