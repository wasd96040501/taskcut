"""Numbers derived from a transcript. Every function here is pure.

Three questions are asked of a run, and they are not the same question:

    cost            what the session spent
    context health  how much it was carrying while it worked
    fidelity        whether it could still answer afterwards, and at what price

taskcut can win one and lose another, so they are reported side by side and
never collapsed into a score.
"""

from __future__ import annotations

from dataclasses import dataclass
from statistics import mean

from .transcript import Transcript, Turn
from .workload import Probe, Workload

#: Published cache multipliers, in base-input-token equivalents. A cache write
#: costs about 1.25 of a base input token and a cache read about 0.1, so adding
#: the three input counters together overstates a long session several times
#: over. Every cost here is weighted.
CACHE_WRITE_MULTIPLIER = 1.25
CACHE_READ_MULTIPLIER = 0.1


@dataclass(frozen=True)
class Cost:
    requests: int
    read: int
    write: int
    plain: int
    output: int

    @property
    def weighted(self) -> float:
        """Input cost in base-input-token equivalents."""
        return self.plain + CACHE_WRITE_MULTIPLIER * self.write + CACHE_READ_MULTIPLIER * self.read

    @property
    def naive(self) -> int:
        """The sum people usually quote. Kept only to show how wrong it is."""
        return self.plain + self.write + self.read


def cost(transcript: Transcript) -> Cost:
    requests = transcript.requests
    return Cost(
        requests=len(requests),
        read=sum(r.read for r in requests),
        write=sum(r.write for r in requests),
        plain=sum(r.plain for r in requests),
        output=sum(r.output for r in requests),
    )


def prefix_series(transcript: Transcript) -> list[int]:
    """What the model carried into each turn, turn by turn.

    The first request of a turn sends the whole conversation so far, so its
    input is the size of the context the model is working in. It has to be read
    plus write, not read alone: a cut invalidates the cache past the tool
    definitions, so most of what an arm that cuts carries arrives as a cache
    write. Counting only the read makes a cutting arm look emptier than it is.
    """
    return [turn.requests[0].read + turn.requests[0].write for turn in transcript.turns if turn.requests]


@dataclass(frozen=True)
class ProbeResult:
    id: str
    kind: str
    matched: int
    expected: int
    tools: int
    answer: str

    @property
    def correct(self) -> bool:
        return self.expected > 0 and self.matched == self.expected

    @property
    def went_to_disk(self) -> bool:
        """The model could not answer from context and had to go back to the source."""
        return self.tools > 0


def probe_results(transcript: Transcript, workload: Workload) -> list[ProbeResult]:
    out = []
    for probe in workload.probes:
        turn = transcript.turn_for(probe.question)
        if turn is None:
            out.append(ProbeResult(probe.id, probe.kind, 0, len(probe.expect), 0, "(not asked)"))
            continue
        matched, expected = probe.grade(turn.answer)
        out.append(ProbeResult(probe.id, probe.kind, matched, expected, len(turn.tools), turn.answer))
    return out


@dataclass(frozen=True)
class Fidelity:
    kind: str
    asked: int
    correct: int
    to_disk: int
    tool_calls: int

    @property
    def accuracy(self) -> float:
        return self.correct / self.asked if self.asked else 0.0

    @property
    def reread_rate(self) -> float:
        return self.to_disk / self.asked if self.asked else 0.0


def fidelity(results: list[ProbeResult]) -> dict[str, Fidelity]:
    """Accuracy and re-read rate, split by whether the fact was ever asked for.

    Splitting matters. A conclusion written at a boundary carries the headline
    fact by construction, so an arm that cuts should hold accuracy there for
    free. The incidental facts are the ones a cut actually throws away, and the
    honest question is what recovering them costs.
    """
    out: dict[str, Fidelity] = {}
    for kind in sorted({r.kind for r in results}):
        group = [r for r in results if r.kind == kind]
        out[kind] = Fidelity(
            kind=kind,
            asked=len(group),
            correct=sum(1 for r in group if r.correct),
            to_disk=sum(1 for r in group if r.went_to_disk),
            tool_calls=sum(r.tools for r in group),
        )
    return out


@dataclass(frozen=True)
class Run:
    """Everything one workload-and-arm pair produced."""

    workload: str
    arm: str
    cost: Cost
    prefix: list[int]
    probes: list[ProbeResult]

    @property
    def fidelity(self) -> dict[str, Fidelity]:
        return fidelity(self.probes)

    @property
    def peak_context(self) -> int:
        return max(self.prefix) if self.prefix else 0

    @property
    def mean_context(self) -> float:
        return mean(self.prefix) if self.prefix else 0.0


def summarise(transcript: Transcript, workload: Workload, arm: str) -> Run:
    return Run(
        workload=workload.name,
        arm=arm,
        cost=cost(transcript),
        prefix=prefix_series(transcript),
        probes=probe_results(transcript, workload),
    )
