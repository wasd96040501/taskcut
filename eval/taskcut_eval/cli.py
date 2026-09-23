"""Command line. Wiring only: every decision belongs to one of the other modules."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import subprocess

from . import arms, driver, judgebench, judgecases, mechanism, metrics, models, replay, replaycheck, report, transcript, workload

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


def _debug_file(work: Path, stem: str) -> Path:
    # Outside the results: a debug log is large and full of absolute paths.
    # What the report needs from it is summed into a sidecar.
    path = work / "debug" / f"{stem}.log"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.unlink(missing_ok=True)
    return path


def _write_judging(debug: Path, destination: Path) -> None:
    """What the judge spent, summed from the session's debug log into a sidecar
    beside the transcript. The judge's calls are in neither the transcript nor
    Claude Code's cost ledger."""
    spent = metrics.judging(debug.read_text(errors="replace") if debug.exists() else "")
    destination.write_text(json.dumps(vars(spent), indent=1) + "\n")
    print(f"judge: {spent.calls} calls, {spent.plain + spent.read + spent.write:,} tokens in, {spent.output:,} out -> {destination}")


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

    stem = f"{w.name}--{arm.name}--{model.alias}"
    plugin = driver.prepare_plugin(arm, REPO_ROOT, work / "plugins" / arm.name)
    debug = _debug_file(work, stem)
    driver.run(w, arm, space, plugin, model.alias, debug_file=debug)

    path = transcript.find(PROJECTS, space)
    results = Path(args.results)
    results.mkdir(parents=True, exist_ok=True)
    destination = results / f"{stem}.jsonl"
    destination.write_bytes(path.read_bytes())
    print(f"transcript -> {destination}")
    _write_judging(debug, results / f"{stem}.judging.json")

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
        spent = path.with_suffix("").with_suffix(".judging.json")
        if spent.exists():
            run.judging = metrics.Judging(**json.loads(spent.read_text()))
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
        "judging": vars(run.judging) if run.judging else None,
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
    stem = f"mechanism--{model.alias}"
    debug = _debug_file(work, stem)
    mechanism.drive(space, plugin, mechanism.ARM, model.alias, debug_file=debug)

    results = Path(args.results)
    results.mkdir(parents=True, exist_ok=True)
    destination = results / f"{stem}.jsonl"
    destination.write_bytes(transcript.find(PROJECTS, space).read_bytes())
    print(f"transcript -> {destination}")
    _write_judging(debug, results / f"{stem}.judging.json")

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


REPLAY = EVAL_ROOT / "replay"
#: Sets that cannot be published -- someone's own sessions. Not committed.
REPLAY_LOCAL = REPLAY / "local"


def cmd_replay_build(args) -> int:
    """A set from a transcript, and a labels file for it: `?` for every step
    still to label, the label already there for every step that has one."""
    directory = REPLAY_LOCAL if args.local else REPLAY
    directory.mkdir(parents=True, exist_ok=True)
    memory = [Path(p).read_text() for p in args.memory]
    built = replay.build(Path(args.transcript), args.name, args.source, str(Path.home()), memory)
    (directory / f"{args.name}.json").write_text(json.dumps(built, ensure_ascii=False, separators=(",", ":")) + "\n")
    marks = directory / f"{args.name}.labels"
    known = replay.read_labels(marks.read_text()) if marks.exists() else {}
    header = f"{args.name}: {args.source}\nOne line per step taskcut would judge: N moves on, S does not, E either. See eval/replay/LABELS.md."
    marks.write_text(replay.labels_template(built, header, known))
    print(f"{args.name}: {len(built['steps'])} steps, {len(built['judged'])} judged, "
          f"{sum(n not in known for n in built['judged'])} to label -> {marks}")
    return 0


def _replay_tag(ref: str) -> str:
    if ref:
        return ref.replace("/", "-")
    head = subprocess.run(["git", "-C", str(REPO_ROOT), "rev-parse", "--short", "HEAD"], capture_output=True, text=True).stdout.strip()
    dirty = subprocess.run(["git", "-C", str(REPO_ROOT), "status", "--porcelain", "--", "hooks/judge.ts"], capture_output=True, text=True).stdout.strip()
    return f"{head}{'+' if dirty else ''}"


def _score_file(path: Path, labels, sets) -> tuple[replay.Scores, dict]:
    record = json.loads(path.read_text())
    answers = replay.verdicts(record["answers"], record["model"])
    wanted = {name: marks for name, marks in labels.items() if all(f"{name}#{n}" in answers for n in marks)}
    return replay.score(sets, wanted, answers), {"record": record, "answers": answers, "labels": wanted}


def cmd_replay(args) -> int:
    """The judge over every labelled step of every set, `--repeats` times each."""
    sets, labels, paths = replay.load_sets([REPLAY, REPLAY_LOCAL], args.set)
    work = Path(args.work)
    judge = REPO_ROOT / "hooks" / "judge.ts"
    if args.ref:
        judge = judgebench.judge_at(REPO_ROOT, args.ref, work / "judges" / f"{args.ref.replace('/', '-')}.ts")
    plugin = judgebench.prepare(EVAL_ROOT / "judge", judge, work / "plugins" / "judgebench")
    order = list(sets)
    items = replay.cases(sets, labels, order)
    print(f"{len(items)} steps from {len(sets)} sets, {args.repeats} times each, judged by {args.model} with hooks/judge.ts at {args.ref or 'the working tree'}")
    answers = judgebench.ask(items, plugin, work / "replay", args.model, args.repeats, args.concurrency,
                             sets=[paths[name] for name in order], timeout=6 * 3600)

    results = Path(args.results)
    results.mkdir(parents=True, exist_ok=True)
    tag = f"replay--{_replay_tag(args.ref)}--{args.model}"
    # What is committed: the verdicts and what each call cost. The judge's
    # sentences go beside them, uncommitted, for reading the misses.
    compact = [{k: a[k] for k in ("id", "run", "verdict", "usage", "ms", "attempts") if k in a} for a in answers]
    (results / f"{tag}.json").write_text(json.dumps(
        {"judge": args.ref or _replay_tag(""), "model": args.model, "repeats": args.repeats, "sets": order, "answers": compact},
        indent=0) + "\n")
    with (results / f"{tag}.texts.jsonl").open("w") as out:
        for a in answers:
            out.write(json.dumps({"id": a["id"], "run": a["run"], "text": a["text"]}, ensure_ascii=False) + "\n")
    print(f"verdicts -> {results / f'{tag}.json'}")
    return _replay_report(results / f"{tag}.json", sets, labels)


def _replay_report(path: Path, sets, labels) -> int:
    scores, data = _score_file(path, labels, sets)
    caught, false = replay.units(data["labels"], data["answers"])
    past = replay.stretch(sets, data["answers"], "sqlglot-long--off", 350_000) if "sqlglot-long--off" in sets else None
    print(replay.render(path.stem, scores, replay.interval(caught), replay.interval(false), past))
    return 0


def cmd_replay_report(args) -> int:
    sets, labels, _ = replay.load_sets([REPLAY, REPLAY_LOCAL], args.set)
    for path in args.runs:
        _replay_report(Path(path), sets, labels)
        print()
    return 0


def cmd_replay_compare(args) -> int:
    """Two runs over the same steps: the difference in each rate, B minus A,
    with a bootstrap interval over the boundaries and steps both were asked."""
    sets, labels, _ = replay.load_sets([REPLAY, REPLAY_LOCAL], args.set)
    a_scores, a = _score_file(Path(args.a), labels, sets)
    b_scores, b = _score_file(Path(args.b), labels, sets)
    shared = {name: marks for name, marks in a["labels"].items() if name in b["labels"]}
    ca, fa = replay.units(shared, a["answers"])
    cb, fb = replay.units(shared, b["answers"])
    # Units are compared on the repeats both have.
    k = min(len(ca[0]) if ca else 0, len(cb[0]) if cb else 0) or min(a_scores.repeats, b_scores.repeats)
    trim = lambda units: [u[:k] for u in units]  # noqa: E731
    print(f"B minus A over {len(ca)} boundaries and {len(fa)} steps that are not one, {k} repeats each")
    print(f"  A: {args.a}\n  B: {args.b}")
    for name, (x, y) in {"boundaries caught": (ca, cb), "false NEXT": (fa, fb)}.items():
        d, lo, hi = replay.paired(trim(x), trim(y))
        print(f"  {name:<18} {d:+.1%}   95% {lo:+.1%} to {hi:+.1%}")
    print(f"  $ per judgement    {a_scores.per_judgement:.5f} -> {b_scores.per_judgement:.5f}"
          f"   ({b_scores.per_judgement / a_scores.per_judgement:.2f}x)")
    return 0


def cmd_replay_sheet(args) -> int:
    sets, labels, _ = replay.load_sets([REPLAY, REPLAY_LOCAL], [args.set]) if not args.unlabelled else ({}, {}, {})
    if args.unlabelled:
        path = next(p for p in (REPLAY / f"{args.set}.json", REPLAY_LOCAL / f"{args.set}.json") if p.exists())
        sets = {args.set: json.loads(path.read_text())}
        marks = path.with_suffix(".labels")
        labels = {args.set: replay.read_labels(marks.read_text()) if marks.exists() else {}}
    print(replay.sheet(sets[args.set], {} if args.blind else labels[args.set]))
    return 0


def cmd_replay_check(args) -> int:
    """One real session with the recorder beside taskcut: does the replay
    build the prompts the judge is given live?"""
    work = Path(args.work)
    model = models.get(args.model)
    space = _workspace(work, "replaycheck", mechanism.ARM.name, model.alias)
    judge = REPO_ROOT / "hooks" / "judge.ts"
    recorder = work / "plugins" / "replaycheck"
    debug = work / "debug" / "replaycheck.log"
    if not args.again:
        space = mechanism.materialise(space)
        taskcut = driver.prepare_plugin(mechanism.ARM, REPO_ROOT, work / "plugins" / "replaycheck-taskcut")
        replaycheck.prepare(judge, recorder)
        debug = _debug_file(work, "replaycheck")
        replaycheck.drive(space, [taskcut, recorder], model.alias, debug_file=debug)

    records = json.loads((recorder / "records.json").read_text())
    rebuilt = replay.parse(transcript.find(PROJECTS, space).read_text().splitlines())
    outcome = replaycheck.compare(records, rebuilt, judge)
    print(f"{outcome.matched}/{outcome.steps} steps: the replay built the prompt the judge was given live; the session had {outcome.kinds}")
    for problem in outcome.mismatches:
        print(f"  {problem}")
    judged_live = metrics.judging(debug.read_text(errors="replace") if debug.exists() else "")
    print(f"taskcut judged {judged_live.calls} step(s) past the floor and compacted {rebuilt and len(rebuilt['segments']) - 1} time(s)")
    return 0 if outcome.passed else 1


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

    build = sub.add_parser("replay-build", help="turn a transcript into a replay set and a labels file")
    build.add_argument("--transcript", required=True)
    build.add_argument("--name", required=True)
    build.add_argument("--source", required=True, help="one line: where the session came from, and on what")
    build.add_argument("--memory", action="append", default=[], help="a CLAUDE.md the session had loaded, for judges that read it")
    build.add_argument("--local", action="store_true", help="a session that cannot be published: eval/replay/local, not committed")
    build.set_defaults(func=cmd_replay_build)

    rp = sub.add_parser("replay", help="ask the judge about every labelled step of real sessions")
    rp.add_argument("--model", default="sonnet")
    rp.add_argument("--ref", default="", help="measure hooks/judge.ts as it was at this commit, not the working tree's")
    rp.add_argument("--repeats", type=int, default=3)
    rp.add_argument("--concurrency", type=int, default=6)
    rp.add_argument("--set", action="append", default=[], help="only this set (repeatable)")
    rp.set_defaults(func=cmd_replay)

    rr = sub.add_parser("replay-report", help="score recorded replay runs against the current labels")
    rr.add_argument("runs", nargs="+")
    rr.add_argument("--set", action="append", default=[])
    rr.set_defaults(func=cmd_replay_report)

    rc = sub.add_parser("replay-compare", help="two replay runs over the same steps: B minus A")
    rc.add_argument("a")
    rc.add_argument("b")
    rc.add_argument("--set", action="append", default=[])
    rc.set_defaults(func=cmd_replay_compare)

    sh = sub.add_parser("replay-sheet", help="a set's judged steps, for labelling or checking labels")
    sh.add_argument("--set", required=True)
    sh.add_argument("--unlabelled", action="store_true", help="a set whose labels are not all there yet")
    sh.add_argument("--blind", action="store_true", help="leave the labels out, for labelling it again independently")
    sh.set_defaults(func=cmd_replay_sheet)

    ck = sub.add_parser("replay-check", help="check the replay against a live session's judge prompts")
    ck.add_argument("--model", default="sonnet")
    ck.add_argument("--again", action="store_true", help="compare the last check's session again, without running one")
    ck.set_defaults(func=cmd_replay_check)

    rep = sub.add_parser("report", help="render the collected results")
    rep.add_argument("--out", default="")
    rep.set_defaults(func=cmd_report)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
