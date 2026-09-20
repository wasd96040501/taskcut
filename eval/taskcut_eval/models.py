"""The third axis: which model does the work.

Resistance to a crowded context is a property of the model, not of the plugin,
so a result from one model says nothing about another. A model is named by the
alias `--model` accepts, and carries the one number a context measurement needs
that the transcript does not record: how big its window is.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Model:
    #: The alias passed to `claude --model`.
    alias: str
    #: Context window in tokens. Absolute token counts mean different things on
    #: different windows: 100k is half of one model's context and a tenth of
    #: another's, and dilution tracks the fraction, not the count.
    window: int
    description: str


MODELS: dict[str, Model] = {
    "haiku": Model("haiku", 200_000, "Smallest and cheapest; the most likely to show an effect if there is one."),
    "sonnet": Model("sonnet", 200_000, "The middle of the range."),
    "opus": Model("opus", 200_000, "The strongest; the hardest case for any claim that context hurts."),
}


def get(alias: str) -> Model:
    if alias in MODELS:
        return MODELS[alias]
    # An unlisted alias still runs. The window is what is unknown, so the
    # fraction is reported as unavailable rather than guessed.
    return Model(alias, 0, "unlisted; window unknown, so context is reported in tokens only")


def fraction(tokens: int, model: Model) -> float | None:
    return tokens / model.window if model.window else None
