"""How taskcut is configured for a run.

An arm is the independent variable. It carries the environment and the plugin
settings for one session and nothing else: it names no workload, and no metric
reads it. Adding an arm is adding an entry here.

Earlier versions compared ways of writing the ledger at a `close_task` the
model was told to call (`boundary`, `reply`, `directed`). The plugin no longer
works that way; those results stay in `results/runs.json` and
docs/measurement.md, and running them again means checking out v0.4.0.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping


@dataclass(frozen=True)
class Arm:
    name: str
    description: str
    #: Extra environment for the session. `TASKCUT` is the plugin's own switch.
    env: Mapping[str, str] = field(default_factory=dict)
    #: Overrides written into the plugin manifest's userConfig defaults. The
    #: harness loads taskcut with --plugin-dir, which takes no --config, so a
    #: setting has to be changed in a copy of the manifest.
    config: Mapping[str, object] = field(default_factory=dict)


#: The floor a cutting arm runs at. Zero would judge every turn and make the
#: mechanism easy to see, but it is not a setting anyone would use and it
#: measures taskcut at its most expensive. Thirty is a figure a real session
#: reaches, and it is below the shipped default of forty, so a benchmark run
#: reaches it without being contrived.
_REALISTIC_FLOOR = {"floorPercent": 30}


ARMS: dict[str, Arm] = {
    "off": Arm(
        name="off",
        description="Baseline. The plugin is loaded but switched off, so the transcript grows as usual.",
        env={"TASKCUT": "0"},
        config=_REALISTIC_FLOOR,
    ),
    "on": Arm(
        name="on",
        description="taskcut as shipped: past the floor, a finished turn is cut and its answer kept.",
        env={"TASKCUT": "1"},
        config=_REALISTIC_FLOOR,
    ),
    "outcome": Arm(
        name="outcome",
        description="As `on`, and past the floor the model is asked to write a conclusion with close_task.",
        env={"TASKCUT": "1"},
        config={**_REALISTIC_FLOOR, "outcome": True},
    ),
}


def get(name: str) -> Arm:
    try:
        return ARMS[name]
    except KeyError:
        raise SystemExit(f"unknown arm {name!r}; known arms: {', '.join(sorted(ARMS))}") from None
