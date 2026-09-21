# Design

## The shape of the problem

Claude Code compacts when the context window fills. That threshold is a property
of the window, not of the work, and on a long job the two rarely coincide. The
compaction lands mid-sub-task, where every detail is still live, and summarises
it; meanwhile the detail from work that finished an hour ago is kept, because a
summariser looking at a flat transcript has no way to tell which is which.

The end of a sub-task is the one moment where "what still matters" has a clean
answer. taskcut moves the decision there.

## Who decides that a sub-task is finished

Four things could mark a boundary:

1. **A todo transition.** Hooking `TodoWrite` and watching for an item flipping
   to `completed` needs nothing new from the model, but only works for a model
   that keeps a todo list, and a one-line title says nothing about what the
   sub-task established.
2. **A slash command the person types.** Reliable, and useless for a job running
   unattended for days.
3. **A tool the working model calls.** What versions up to 0.4 did: the model
   called `close_task` and the argument was the conclusion. It has two costs
   that do not go away. A tool call ends the model's response, so every
   boundary is one more request that reads the whole context again -- measured
   at about ten percent of a twenty-change session, paid below the floor as
   much as above it. And a tool cannot be unregistered, so once the model has
   been told about it, it is there for the rest of the session.
4. **A judge at the end of the turn.** What taskcut does. Once the context is
   past the floor, at the end of each turn the model finished, one
   `$.model.classify` call on a small model reads the request and the answer
   and says `finished` or `unfinished` -- the same shape as auto mode's
   permission classifier, reading a few thousand characters rather than the
   transcript. Below the floor it never runs, and the working model is never
   told taskcut exists, so there is nothing for a cut to leave behind.

The judge decides only whether to cut. A reply that asks a question, waits for
a decision or reports partial progress is `unfinished`, and the context is kept.
Anything but a clear `finished` -- an unrecognised label, a failed request --
keeps it too: a missed cut waits for the next turn, while a wrong one costs
re-reading.

What a cut keeps of the work is the answer the model gave for each request,
which it wrote while it still had the full context. The `outcome` setting asks
for more: past the floor it offers the working model the old `close_task`, whose
argument is a conclusion written for the purpose, kept in place of the answer.
That brings back the round-trip and the tool that stays, which is why it is off
by default.

## Why the cut does not call a summariser

A `session.compact` hook can call `next(e)` and let core summarise, or answer
`{ messages }` of its own. taskcut answers, and never calls `next` on a boundary
cut.

The reason is that the keep-set is already known. The answers were written by
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

A compaction invalidates the prompt cache prefix, so the next turn re-reads at
full price what it would otherwise have read cached. Below the floor that costs
more than it saves. The measurement in
[measurement.md](measurement.md) puts numbers on every part of that sentence.

What survives a cut is the system block and the tool definitions, and nothing
else: `cache_read_input_tokens` on the first request after a cut was 26,791 —
the same figure after each of four consecutive cuts. Everything past that
breakpoint is written again. Write `S` for what survives, `K` for the kept set
and `P` for the transcript before the cut. A cache write costs about 1.25 of a
base input token and a cache read about 0.1, so the turn after a cut pays
`0.1·S + 1.25·(K−S)` where it would have paid `0.1·P`, and it is repaid at
`0.1·(P−K)` per turn after that.

`K−S` is larger than the keep-set rule suggests, because the kept set also
carries the preamble the engine puts in front of every conversation, and that is
re-cached in full on every cut. Measured at 11,968 → 14,720 across the four
cuts, against a ledger contributing only 500–900 of the growth. With `S` =
26,791 and `K−S` ≈ 12,000 the turn after a cut cost 17,639 where it would have
cost 5,074: three and a half times more, repaid over about eleven requests.

End to end on that workload — four sub-tasks, context never past 8% — cutting at
every boundary cost 1.73× the baseline. Per sub-task the cutting arm was flat at
49,358 while the baseline was 28,368 and growing by about 2,200 each time, so
the lines cross near the fourteenth sub-task. taskcut is a bet on the run being
longer than that, and the floor is what keeps the bet off the table when it is
not.

This sets the direction of the error, too. A floor set too high wastes context
the session could have shed; set too low it spends real money flattening a
transcript that was not a problem yet. The default leans high.

`floorPercent` gates on `$.session.usage()`, whose `context.percent` is the same
figure the status line shows, read off the last response for nothing. Below the
floor nothing runs at all -- no judge, no ledger write. Nothing is lost by
waiting: the ledger is built at the cut, from the transcript being replaced, and
records every request answered since the last one.

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
  `[CLOSED]` and ends with *"That work is finished. Do not redo it."*
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

The engine's own threshold compaction stays in place. A single turn can be too
large to end below the limit, and when that happens the right behaviour is the
existing one: core summarises. taskcut hooks `session.compact` on `trigger: 'auto'` only
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

`$.session.compact` rejects while a turn is running, so both the judgement and
the cut happen in `turn.complete`, after `next(e)` has settled the turn. Only a
main-loop turn that ended with `reason: 'answer'` is judged: a subagent's run is
not the person's conversation, and an interrupted or failed turn stopped in the
middle of its work, which is the transcript that explains what went wrong.

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
