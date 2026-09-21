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


#: Windows as Claude Code reports them, not as the model family was once sold.
#: `sonnet` resolves to Sonnet 5, whose window is 1M: a session at 37,403 tokens
#: shows `ctx 4%` in the status line, which is 1M and not 200k (that would read
#: 19%). An earlier version of this table said 200k, and every share of the
#: window it reported was five times too high.
MODELS: dict[str, Model] = {
    "haiku": Model("haiku", 200_000, "Smallest and cheapest."),
    "sonnet": Model("sonnet", 1_000_000, "Sonnet 5, with a 1M window."),
    "opus": Model("opus", 1_000_000, "Opus 5, with a 1M window."),
}


def get(alias: str) -> Model:
    if alias in MODELS:
        return MODELS[alias]
    # An unlisted alias still runs. The window is what is unknown, so the
    # fraction is reported as unavailable rather than guessed.
    return Model(alias, 0, "unlisted; window unknown, so context is reported in tokens only")


def fraction(tokens: int, model: Model) -> float | None:
    return tokens / model.window if model.window else None
