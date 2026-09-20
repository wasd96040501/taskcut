# Measuring taskcut

taskcut is a bet: that flattening the transcript at sub-task boundaries costs
less, over a long run, than letting it grow. A bet is worth measuring, and the
measurement is not the obvious one. This page describes how to run it, what the
numbers mean, and what the first run found.

## What not to measure

Tokens saved. Cutting is trivially good at saving tokens — the limit case, a
cut that keeps nothing, saves all of them and is useless. The quantity that
matters is the cost of finishing the work, and the failure mode that matters is
the model redoing a sub-task it already closed.

## Where the numbers are

Every session writes a transcript to
`~/.claude/projects/<slugified-cwd>/<session-id>.jsonl`. Each assistant record
carries the usage block the API returned:

```json
"usage":{"input_tokens":2,"cache_creation_input_tokens":11968,
         "cache_read_input_tokens":26791,"output_tokens":88}
```

This is the only honest source. The status line rounds, and adding the three
input counters together bills cached tokens at full price, which overstates a
long session by four or five times.

`scripts/measure.py` reads one or two transcripts and prints a per-request
table plus a weighted total in base-input-token equivalents, using the
published cache multipliers — a cache write costs about 1.25 of a base input
token, a cache read about 0.1:

```
weighted = input_tokens + 1.25 * cache_creation + 0.1 * cache_read
```

It deduplicates by request id first, because a streamed assistant message is
recorded several times and every copy carries the same usage block.

## Running an A/B

`TASKCUT=1` and `TASKCUT=0` switch the plugin on and off without changing
anything else on the machine, which makes a clean pair of arms.

1. Pick a task with several genuine sub-tasks, from a fixed starting commit.
2. Run it in a terminal session with `TASKCUT=1`, asking the model to call
   `close_task` at each boundary.
3. Run the same task, in a different directory so it gets its own transcript,
   with `TASKCUT=0` and no mention of `close_task` — that is what a session
   without the plugin actually looks like.
4. `scripts/measure.py <on>.jsonl <off>.jsonl`.

Run each arm several times. Model behaviour varies enough that a single pair
tells you the shape of the difference, not its size.

## What to read off it

| Signal | Where | What it says |
| --- | --- | --- |
| Weighted input per completed task | `measure.py` total | The headline. The denominator has to be *completed*, not turns spent. |
| `cache_read` trend | the per-request table | Baseline climbs every turn; a cutting arm resets at each boundary. This is the whole mechanism, visible directly. |
| `cache_creation` after a cut | first request following a ledger message | What the cut costs. It is larger than the kept set looks, because the per-session preamble is re-cached in full every time. |
| Engine auto-compactions | summary records in the transcript | taskcut aims to drive these to zero. |
| Rework | repeated `(tool, principal argument)` pairs after a cut | The failure that undoes every saving. A closed sub-task being read or run again is the signal. |
| `close_task` density | `boundaries` count | Too dense and the model is amnesiac; too sparse and the plugin is inert. |

## First run

Four sub-tasks, each reading a 661-line file and reporting one fact from it.
One arm with `floorPercent` forced to `0` so that every boundary cut; one
baseline with the plugin off. Claude Code 2.1.278, Opus 5 (1M context).

| | cut at every boundary | baseline |
| --- | --- | --- |
| Weighted input | **210,408** | **121,602** |
| `cache_read` | 695,211 | 510,920 |
| `cache_creation` | 112,682 | 56,394 |
| Output | 3,552 | 1,086 |
| Requests | 17 | 9 |
| Peak context | 5% | 8% |

The cutting arm cost **1.73×** the baseline. That is the right answer for that
workload, and it is the case the floor exists to avoid: context fill never
passed 8%, and the default floor of 40 would have made no cut at all.

Three things the run established:

**What survives a cut is the system block and the tool definitions, and nothing
else.** `cache_read` on the first request after a cut was 26,791 — the identical
figure after all four cuts. The kept set beyond that breakpoint is written
again in full.

**The kept set is bigger than it looks.** `cache_creation` on that request ran
11,968 → 14,720 across the four cuts. The first human turn, two recent turns and
the ledger are a small part of it; most of it is the preamble the engine puts in
front of every conversation, which is re-cached on every cut. The ledger itself
accounts for the growth of roughly 500–900 a cut.

**The lines cross around the fourteenth sub-task.** Per sub-task the cutting arm
cost 49,358 and did not grow; the baseline cost 28,368 and grew by about 2,200
each time, as its `cache_read` climbed 26,791 → 36,690 → 49,451 → 60,609 →
71,867 → 83,050. Flat beats climbing, but not immediately.

## A cost the run exposed

`close_task` is a registered tool, and in this build the model has to spend a
`ToolSearch` round-trip to load its schema before it can call it. It did so at
every one of the four boundaries, not just the first: the cut discards the
assistant message that carried the schema, so the next boundary has to fetch it
again. One extra request per sub-task, caused by taskcut and paid for by
taskcut. This is a property of the current deferred-tool mechanism rather than
of the design, but it is real and it is on the wrong side of the ledger.
