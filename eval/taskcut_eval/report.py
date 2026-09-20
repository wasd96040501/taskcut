"""Rendering. Pure functions from runs to text; no run is read from disk here."""

from __future__ import annotations

from .metrics import Run
from .workload import KIND_HEADLINE, KIND_INCIDENTAL


def _row(cells: list[str], widths: list[int]) -> str:
    return "| " + " | ".join(c.ljust(w) for c, w in zip(cells, widths)) + " |"


def table(header: list[str], rows: list[list[str]]) -> str:
    widths = [max(len(header[i]), *(len(r[i]) for r in rows)) if rows else len(header[i]) for i in range(len(header))]
    out = [_row(header, widths), "| " + " | ".join("-" * w for w in widths) + " |"]
    out += [_row(r, widths) for r in rows]
    return "\n".join(out)


def cost_table(runs: list[Run]) -> str:
    rows = []
    for run in runs:
        c = run.cost
        rows.append([
            run.arm,
            f"{c.weighted:,.0f}",
            f"{c.read:,}",
            f"{c.write:,}",
            f"{c.output:,}",
            str(c.requests),
        ])
    return table(["arm", "weighted input", "cache read", "cache write", "output", "requests"], rows)


def context_table(runs: list[Run]) -> str:
    rows = []
    for run in runs:
        rows.append([
            run.arm,
            f"{run.prefix[0]:,}" if run.prefix else "-",
            f"{run.peak_context:,}",
            f"{run.mean_context:,.0f}",
            f"{run.prefix[-1]:,}" if run.prefix else "-",
            f"{run.ledger:,}" if run.ledger else "-",
        ])
    return table(["arm", "first turn", "peak", "mean", "last turn", "ledger"], rows)


def fidelity_table(runs: list[Run]) -> str:
    rows = []
    for run in runs:
        for kind in (KIND_HEADLINE, KIND_INCIDENTAL):
            f = run.fidelity.get(kind)
            if f is None:
                continue
            rows.append([
                run.arm,
                kind,
                f"{f.correct}/{f.asked}",
                f"{f.accuracy:.0%}",
                f"{f.to_disk}/{f.asked}",
                str(f.tool_calls),
            ])
    return table(["arm", "fact", "correct", "accuracy", "went to disk", "tool calls"], rows)


def probe_detail(run: Run) -> str:
    rows = []
    for p in run.probes:
        rows.append([
            p.id,
            p.kind,
            f"{p.matched}/{p.expected}",
            str(p.tools),
            " ".join(p.answer.split())[:60] or "(empty)",
        ])
    return table(["probe", "fact", "matched", "tools", "answer"], rows)


def render(workload_name: str, runs: list[Run]) -> str:
    out = [f"# {workload_name}", ""]
    out += ["## Cost", "", cost_table(runs), ""]
    out += ["## Context carried into each turn", "",
            "The first request of a turn sends the whole conversation, so its input",
            "(cache read plus cache write) is the context the model is working in.", "", context_table(runs), ""]
    for run in runs:
        out += [f"    {run.arm}: " + " -> ".join(f"{v:,}" for v in run.prefix)]
    out += ["", "## Fidelity after the work", "",
            f"`{KIND_HEADLINE}` facts were asked for during the work, so a conclusion",
            f"written at a boundary should carry them. `{KIND_INCIDENTAL}` facts were in",
            "the material but never mentioned, so only the transcript held them.",
            "", fidelity_table(runs), ""]
    for run in runs:
        out += [f"### {run.arm}", "", probe_detail(run), ""]
    return "\n".join(out)
