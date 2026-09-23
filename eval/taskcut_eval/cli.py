"""Command line. Wiring only: every decision belongs to one of the other modules."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import arms, driver, judgebench, judgecases, mechanism, metrics, models, report, transcript, workload

HERE = Path(__file__).resolve().parent
EVAL_ROOT = HERE.parent
REPO_ROOT = EVAL_ROOT.parent
WORKLOADS = EVAL_ROOT / "workloads"
GENERATORS = EVAL_ROOT / "generators"
DEFAULT_RESULTS = EVAL_ROOT / "results"
DEFAULT_WORK = Path.home() / ".cache" / "taskcut-eval"
PROJECTS = transcript.PROJECTS


def _workspace(work: Path, name: str, arm: str, model: str) -> Path:
    # Per arm and per model, always: two runs sharing a directory share a
    # transcript directory, and can no longer be told apart afterwards.
    return work / "workspaces" / f"{name}--{arm}--{model}"


def cmd_list(args) -> int:
    loaded = workload.load_all(WORKLOADS)
    print("workloads:")
    for name, w in loaded.items():
        print(f"  {name:<12} {len(w.files)} files, {len(w.probes)} probes  -- {w.description}")
    print("\narms:")
    for name, a in arms.ARMS.items():
        print(f"  {name:<12} {a.description}")
    print("\nmodels:")
    for name, m in models.MODELS.items():
        print(f"  {name:<12} window {m.window:,} -- {m.description}")
    return 0


def cmd_verify(args) -> int:
    work = Path(args.work)
    problems = []
    for name, w in workload.load_all(WORKLOADS).items():
        root = _workspace(work, name, "verify", "none")
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

    model = models.get(args.model)
    space = workload.materialise(w, _workspace(work, w.name, arm.name, model.alias), GENERATORS)
    problems = workload.check_ground_truth(w, space)
    if problems:
        raise SystemExit("workload is not answerable:\n  " + "\n  ".join(problems))

    plugin = driver.prepare_plugin(arm, REPO_ROOT, work / "plugins" / arm.name)
    driver.run(w, arm, space, plugin, model.alias)

    path = transcript.find(PROJECTS, space)
    results = Path(args.results)
    results.mkdir(parents=True, exist_ok=True)
    stem = f"{w.name}--{arm.name}--{model.alias}"
    destination = results / f"{stem}.jsonl"
    destination.write_bytes(path.read_bytes())
    print(f"transcript -> {destination}")

    # While the workspace is still as the session left it. A check is the only
    # honest grade for a task that produced something, and it cannot be
    # recovered from the transcript afterwards.
    if w.checks:
        # A check may need a helper the session must not see; it lives with the
        # fixtures, outside the workspace, and is found through this variable.
        verdicts = metrics.run_checks(w, space, env={"EVAL_FIXTURES": str(EVAL_ROOT / "fixtures")})
        (results / f"{stem}.checks.json").write_text(
            json.dumps([vars(v) for v in verdicts], indent=1) + "\n"
        )
        for v in verdicts:
            print(f"  {'PASS' if v.passed else 'FAIL'}  {v.id}: {v.description}")
    return 0


def cmd_report(args) -> int:
    loaded = workload.load_all(WORKLOADS)
    results = Path(args.results)
    # A run is identified by all three axes. Grouping by workload and model
    # keeps the comparison within a group like for like: an arm is only
    # comparable to another arm the same model ran.
    grouped: dict[tuple[str, str], list] = {}
    for path in sorted(results.glob("*.jsonl")):
        parts = path.stem.split("--")
        if len(parts) != 3:
            print(f"skipping {path.name}: expected workload--arm--model", file=sys.stderr)
            continue
        name, arm, model = parts
        if name not in loaded:
            continue
        run = metrics.summarise(transcript.load(path), loaded[name], arm)
        sidecar = path.with_suffix("").with_suffix(".checks.json")
        if sidecar.exists():
            run.checks.extend(metrics.CheckResult(**v) for v in json.loads(sidecar.read_text()))
        grouped.setdefault((name, model), []).append(run)

    if not grouped:
        raise SystemExit(f"no results in {results}")

    chunks, summary = [], {}
    for (name, model), runs in sorted(grouped.items()):
        runs.sort(key=lambda r: (r.arm != "off", r.arm))
        chunks.append(report.render(f"{name} on {model}", runs, models.get(model)))
        summary.setdefault(name, {})[model] = {r.arm: _numbers(r) for r in runs}
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
        "cuts": run.cuts,
        "nudges": run.nudges,
        "continued": run.continued,
        "request_context_peak": run.peak_request,
        "request_context_mean": round(run.mean_request),
        "elapsed_seconds": round(run.elapsed),
        "checks": {c.id: c.passed for c in run.checks},
        "drift": {
            d.id: {"held": d.held, "steps": d.steps, "first_lapse": d.first_lapse,
                   "per_step": list(d.per_step)}
            for d in run.drift
        },
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


def cmd_mechanism(args) -> int:
    """One short real session at a low floor, and every property it must show."""
    work = Path(args.work)
    model = models.get(args.model)
    space = mechanism.materialise(_workspace(work, "mechanism", mechanism.ARM.name, model.alias))
    plugin = driver.prepare_plugin(mechanism.ARM, REPO_ROOT, work / "plugins" / mechanism.ARM.name)
    mechanism.drive(space, plugin, mechanism.ARM, model.alias)

    results = Path(args.results)
    results.mkdir(parents=True, exist_ok=True)
    stem = f"mechanism--{model.alias}"
    destination = results / f"{stem}.jsonl"
    destination.write_bytes(transcript.find(PROJECTS, space).read_bytes())
    print(f"transcript -> {destination}")

    verdicts = mechanism.check(destination, model.window, space)
    (results / f"{stem}.checks.json").write_text(json.dumps([vars(v) for v in verdicts], indent=1) + "\n")
    for v in verdicts:
        print(f"  {'PASS' if v.passed else 'FAIL'}  {v.name}: {v.detail}")
    return 0 if all(v.passed for v in verdicts) else 1


def cmd_judge(args) -> int:
    """The judge alone, over the labelled steps, a few times each."""
    work = Path(args.work)
    cases = [c for c in judgecases.CASES if not args.case or c.id in args.case]
    plugin = judgebench.prepare(EVAL_ROOT / "judge", REPO_ROOT / "hooks" / "judge.ts", work / "plugins" / "judgebench")
    answers = judgebench.ask(cases, plugin, work / "judge", args.model, args.repeats)
    scored = judgebench.score(cases, answers)

    results = Path(args.results)
    results.mkdir(parents=True, exist_ok=True)
    destination = results / f"judge--{args.model}.json"
    destination.write_text(json.dumps([vars(s) for s in scored], indent=1) + "\n")
    print(f"verdicts -> {destination}")
    for line in judgebench.summary(scored):
        print(line)
    return 0 if all(s.right == len(s.verdicts) for s in scored) else 1


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
    run.add_argument("--model", default="sonnet", help=f"one of {', '.join(models.MODELS)}, or any --model alias")
    run.set_defaults(func=cmd_run)

    mech = sub.add_parser("mechanism", help="check the mechanism end to end in one short real session")
    mech.add_argument("--model", default="sonnet", help=f"one of {', '.join(models.MODELS)}, or any --model alias")
    mech.set_defaults(func=cmd_mechanism)

    judge = sub.add_parser("judge", help="ask the judge about the labelled steps, a few times each")
    judge.add_argument("--model", default="sonnet", help="the judge's model, as the plugin's `model` setting takes it")
    judge.add_argument("--repeats", type=int, default=3)
    judge.add_argument("--case", action="append", default=[], help="only this case id (repeatable)")
    judge.set_defaults(func=cmd_judge)

    rep = sub.add_parser("report", help="render the collected results")
    rep.add_argument("--out", default="")
    rep.set_defaults(func=cmd_report)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
