# Design

## The shape of the problem

Claude Code compacts when the context window fills. That threshold is a property
of the window, not of the work, and on a long job the two rarely coincide. The
compaction lands mid-sub-task, where every detail is still live, and summarises
it; meanwhile the detail from work that finished an hour ago is kept, because a
summariser looking at a flat transcript has no way to tell which is which.

The end of a sub-task is the one moment where "what still matters" has a clean
answer. taskcut moves the decision there.

## Why the model declares the boundary

Three things could mark a boundary:

1. **A todo transition.** Hooking `TodoWrite` and watching for an item flipping
   to `completed` needs nothing new from the model. But a todo item is a one-line
   title with no conclusion in it, so a second round trip is needed to ask what
   the sub-task established — at exactly the moment the context is about to be
   thrown away.
2. **A slash command the person types.** Reliable, and useless for a job running
   unattended for days.
3. **A tool the model calls.** The boundary and the conclusion arrive in the same
   event, because the conclusion is the argument.

The third is what taskcut does. The tool description states the consequence
plainly — *everything you did for it is dropped; only what you write here
survives* — because the quality of the cut is the quality of that text.

## Why the cut does not call a summariser

A `session.compact` hook can call `next(e)` and let core summarise, or answer
`{ messages }` of its own. taskcut answers, and never calls `next` on a boundary
cut.

The reason is that the keep-set is already known. The conclusion was written by
the model when it still had the full context, which is a better summary than one
produced later from a transcript. The human turns are worth keeping exactly as
they were said. Nothing in the keep-set benefits from being paraphrased, and
paraphrasing it would cost a model call and introduce loss.

Messages handed back with their engine `handle` stand as the engine recorded
them. Messages without one are rebuilt from `role`, `text` and their tool blocks,
which is lossy: `text` is the message's text blocks joined, and thinking blocks
are not represented at all. So the keep-set is always passed through with its
handles intact, and only the ledger message — which taskcut authors — is built.

## The keep-set rule

```
keep = [ first human turn ] + [ last N human turns ] + [ ledger ]
```

Three constraints produced it.

**Pairs must travel together.** A user message carrying `tool_result` blocks is
the answer to the assistant message that made the calls. A transcript holding one
half of that pair is rejected by the API, and the rejection surfaces at the next
model request rather than at the cut, which makes it hard to trace. Selecting
*the user turns that carry no tool_result* drops both halves of every pair
together, by construction. This is why the rule is written in terms of what a
user message carries rather than as a list of message indices.

**The standing task has to survive.** The first human turn is the only record of
what the whole job is for. It is kept whatever else goes.

**Human turns are themselves unbounded.** A job driven by a loop adds one human
turn per iteration. An early version kept all of them; across five sub-tasks the
kept set grew 2 → 4 → 5 while the ledger stayed flat, so the growth had simply
moved. Keeping the first plus the most recent `recentHumanTurns` pins it.

## The floor

The floor is not an economic threshold, and it is worth saying so plainly,
because the obvious argument for one does not survive the arithmetic. That
argument runs: a compaction invalidates the prompt cache, so the next turn
re-reads everything at full price, so a small context is not worth cutting.

Write `P` for the transcript before a cut and `K` for the kept set. A cache read
costs about a tenth of a base input token; a cache write about 1.25 of one. The
kept set opens with the first human turn, unchanged and in its original
position, so the system block, the tool definitions and that turn all still
match the cached prefix — divergence starts after it. The turn following a cut
therefore pays roughly `1.25·K` where it would have paid `0.1·P`. That is
cheaper on the very turn the cut happens whenever `K` is under about 8% of `P`,
and cheaper again on every turn after.

At the default floor the ratio is not close: a 200k window at 40% is 80k, against
a kept set of the first turn, two recent turns and a bounded ledger — roughly 3k,
under 4%. Even at 4% context fill, where a cut saves almost nothing, it costs
almost nothing: a few hundred tokens more on the next turn, repaid by the one
after. Cutting early is not expensive. It is merely pointless.

What the floor actually buys is fidelity. A cut trades the whole working context
for the ledger, which holds the conclusions the model chose to write down and
nothing else — not the file it read and did not mention, not the command whose
output shaped a decision it recorded in one line. Early in a session that is a
bad trade at any price, because what is being discarded is still small enough to
carry. The floor is the point past which carrying it stops being free.

This also sets the direction of the error. Too high a floor wastes context; too
low a floor loses work. The default leans high.

`floorPercent` gates on `$.session.usage()`, whose `context.percent` is the same
figure the status line shows. Below the floor the conclusion is still recorded —
the ledger is the durable artefact — and the transcript is left alone. The cut
happens at the first boundary after the window has actually filled.

## The ledger

The ledger survives every cut, which makes it the one thing that grows without
bound. Past `ledgerVerbatim` entries the oldest are folded into a single entry by
one `$.model.complete` call on a small model. Recent entries stay in the model's
own words, because those are the ones the next step is most likely to need.

Two details are load-bearing:

* **It is keyed by session id.** The plugin store is shared by every session on
  the machine. An early version used a bare `ledger` key; two test runs shared
  it, and a model was told a sub-task was finished that its session had never
  done. It re-ran the work and wrote *"this re-run matches the previously closed
  sub-task B result exactly"* — a quiet, expensive failure.
* **Entries carry state, not just findings.** The rendering marks each entry
  `[CLOSED]` and ends with *"Those sub-tasks are finished. Do not redo them."*
  Without that, a ledger that lists what was learned reads as an open to-do list.
  An early version omitted it and the model reported the closed sub-task as
  outstanding.

### Cleaning up after a session

`session.end` deletes the session's ledger, which covers a session that exits
cleanly. A session that is killed never reaches that hook — driving Claude Code
over a pty and closing the pty leaves the ledger behind, which is how this was
found — and the plugin store has a hard size limit, so leftovers cannot simply
accumulate. `session.start` therefore sweeps ledgers whose newest entry is more
than a week old. The current session's own key is never swept, however old its
newest entry is.

## What is left to the engine

The engine's own threshold compaction stays in place. A sub-task can be too large
to reach a boundary, and when that happens the right behaviour is the existing
one: core summarises. taskcut hooks `session.compact` on `trigger: 'auto'` only
to pass the ledger down as `instructions`, so the summariser is not asked to
re-derive what is already settled.

## Where taskcut can run

`$.session.compact` is refused in a headless session. The same probe plugin,
started four ways, reports:

| How the binary was started | `surface` | `isInteractive` | `$.session.compact` |
| --- | --- | --- | --- |
| `claude -p` | `null` | `false` | refused |
| `--input-format stream-json` over pipes (the SDK transport) | `null` | `false` | refused |
| a terminal, on a pty | `terminal` | `true` | works |
| `claude --bg` | `terminal` | `true` | works |

The refusal is explicit:

```
$.session.compact: not available in a headless (-p / SDK) session yet:
compaction here runs inside a turn (a /compact prompt); catch it and carry on
```

The second row is worth stating outright, because a bidirectional stream-json
session over pipes looks interactive from the outside — it is persistent, it
takes many turns, it is not `-p` — and the engine still classifies it as the SDK
transport. Anything driving Claude Code that way cannot compact.

`claude --bg` is the useful row: a detached session still counts as interactive,
so an unattended job does not need a terminal held open for it.

## Where the compaction is triggered from

`$.session.compact` rejects while a turn is running, so the call cannot be made
from the `close_task` handler. The handler sets a flag; `turn.complete` reads it.

Two other candidates were tried. `classic.Stop` never reached the hooks module.
Deferring the call with `$.clock.after(0, ...)` was unnecessary: in an
interactive session the straight call from `turn.complete` succeeds.

A failure there is caught and logged rather than thrown. A plugin that cannot
compact should not be able to take the turn down with it.

## The one structural rule in the source

A hooks module may pass `$` only to a function declared at the top level of the
same file. The loader refuses anything else, before a session loads it:

```
$ is passed to "readLedger", imported from "./ledger": $ is followed only into a
function declared in this same file, never across an import
```

This is what lets `claude plugin validate` print the complete list of what a
plugin calls, including through helpers — `$.model.complete (via foldLedger)`.
The file layout follows from it: everything touching the engine is in
`register.ts`, and everything that is a function of plain data is beside it,
where it can be read on its own.
