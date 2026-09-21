# Design

## The shape of the problem

Claude Code compacts when the context window fills. That threshold is a property
of the window, not of the work, and on a long job the two rarely coincide. The
compaction lands mid-sub-task, where every detail is still live, and summarises
it; meanwhile the detail from work that finished an hour ago is kept, because a
summariser looking at a flat transcript has no way to tell which is which.

The end of a sub-task is the one moment where "what still matters" has a clean
answer. taskcut moves the decision there.

## taskcut decides when, and nothing else

A compaction has two halves: *when* it happens, and *what* it keeps. Claude
Code already has an answer to the second -- the prompt behind `/compact` and
automatic compaction, tuned for exactly this, which keeps every message you
sent, the files and decisions that matter, and what was in progress. What it
does not have is a trigger tied to the work: it compacts when you type
`/compact`, or when the window fills.

taskcut adds that trigger and nothing else. When it decides a sub-task is
finished it calls `$.session.compact()` with no arguments -- the same call
`/compact` makes -- and the compaction that follows is Claude Code's own. It
writes to the same transcript and keeps what Claude Code keeps, and the
transcript records it exactly as it records a typed `/compact`, down to
`trigger: "manual"`.

Inside a turn that is still true, with one step added in front: Claude Code
compacts only between turns, so taskcut ends the turn first and starts the next
one with `Continue.` -- see [Inside a turn](#inside-a-turn).

Versions up to 0.5 built the compacted transcript themselves: the human turns,
kept verbatim, and a ledger of what each sub-task had established, with no
summariser called. It measured well on context size, and it was the wrong
split. To write a ledger entry the plugin had to get a conclusion from
somewhere, and every way of getting one was worse than the engine's: asking the
working model for it at `close_task` meant writing it before anyone had decided
the work was finished, and a small model writing it from the dropped
transcript (`directed`) halved the ledger and doubled the re-reading. The
lessons it left -- keep tool pairs together, key the store by session, mark
finished work finished -- are in the history, and none of them is taskcut's
problem any more.

## Who decides that a sub-task is finished

Four things could mark the end of a sub-task:

1. **A todo transition.** Hooking `TaskUpdate` for an item flipping to
   `completed` needs nothing new from the model, but works only for a model that
   keeps a task list, and whether it keeps one is up to the model from one job
   to the next. taskcut does not rely on it.
2. **A slash command the person types.** That is `/compact`, which already
   exists.
3. **A tool the working model calls.** What versions up to 0.5 did, with
   `close_task`. It has two costs that do not go away. A tool call ends the
   model's response, so every boundary is one more request that reads the whole
   context again -- about ten percent of a twenty-change session, measured, paid
   below the floor as much as above it. And a tool cannot be unregistered: once
   the model has been told about it, it is there for the rest of the session.
4. **A judge.** What taskcut does. Once the context is past the floor, each
   step of the main conversation, and the reply each turn ends on, gets one
   `$.model.complete` call asking whether it reports a piece of the work
   complete. Below the floor it never runs, and the working model is never told
   taskcut exists.

The question is asked as three rules in order. A step that ends by asking the
person something, waiting for their decision or proposing work it has not done
is `WORKING` -- even when asking is exactly what the person told it to do,
since their answer carries the same piece on. A step that says a piece is
complete is `DONE`, whether or not it has already started the next piece. Anything
else is `WORKING`. The judge writes one sentence about the step before its
verdict: asked for the word alone, it read "task 2 is done; now task 3" as work
in progress and missed two boundaries in three. Anything but a clear `DONE` --
no verdict, a failed request -- keeps the context: a missed boundary waits for
the next one, and the threshold is still there.

The first version of this asked `$.model.classify`, which wraps the text in a
fixed classifier prompt and treats every word of it as data. The instructions
that said what "finished" meant were data too, and a step that finished one
task and started the next was never a boundary.

## What the judge reads

The judge reads what auto mode's permission classifier reads, which decides
from a portion of the transcript rather than all of it: every message the
person sent, every tool call the assistant made except read-only lookups, and
`CLAUDE.md`, with all tool output stripped. To that it adds the step being
judged -- what the assistant just said, and the calls it is making or the fact
that it stopped -- as the classifier adds the pending action.

Reading the whole transcript would cost a full-price read of everything past
the floor on every judged turn, since the judge shares no cache with the
session, and would add nothing to the question it answers. Each piece is
clipped, and when the conversation runs long its oldest lines are left out:
whether the latest request is done lives at the end.

The default model is `sonnet`, as the permission classifier's is. On twelve
steps of one long turn -- three boundaries among them -- judged three times
each, `sonnet` was right 36 times out of 36 and `haiku` 32, every miss a
boundary it did not see. On forty steps sampled from inside twenty real
changes, none of them a boundary, `sonnet` called none of them one. A judgement
costs a few cents and runs only past the floor.

## The floor

A compaction invalidates the prompt cache past the tool definitions, so the next
turn re-reads at full price what it would otherwise have read cached; it also
costs the summarising call itself. Below the floor that costs more than it
saves. The measurement in [measurement.md](measurement.md) puts numbers on it
for versions that wrote their own ledger: what survived a cut was the system
block and the tool definitions, 26,791 tokens, the same after each of four
consecutive cuts, and everything past that was written to the cache again.

This sets the direction of the error. A floor set too high wastes context the
session could have shed; set too low it spends real money compacting a
transcript that was not a problem yet. The default leans high.

`floorPercent` gates on `$.session.usage()`, whose `context.percent` is the same
figure the status line shows, read off the last response for nothing. Below the
floor nothing runs at all.

On a 1M window a floor of 40% is 400,000 tokens. Twenty real changes in one
Sonnet 5 session reached 29%. taskcut is for sessions that genuinely get that
long.

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

`$.session.compact` rejects while a turn is running. At the end of a turn, both
the judgement and the compaction happen in `turn.complete`, after `next(e)` has
settled the turn. Only a main-loop turn that ended with `reason: 'answer'` is
judged: a subagent's run is not the person's conversation, and an interrupted or
failed turn stopped in the middle of its work, which is the transcript that
explains what went wrong.

## Inside a turn

The job taskcut is for is the one nobody watches: a list of tasks handed over
in one message and worked through in a single turn that runs for hours. A
trigger at the end of a turn never fires there, and Claude Code's own
threshold is the only compaction the turn gets -- in the middle of whatever
task happens to be running when the window fills.

So taskcut judges each step. `turn.step` wraps every model request of the main
loop; once the response is in, the hook judges it while the engine runs the
step's tools, and the next request waits for both. The judgement is a `$` call
made inside the step's own dispatch, which matters: a hook's 10-second budget
counts only its own code, and stops while one of its `$` calls is in flight. An
earlier version started the judgement in one step and awaited it in the next,
where it was a plain promise; the budget ran out and the engine skipped the
hook.

When a step is judged to have finished a piece, the next dispatch of the hook
does what a person watching would do with Esc, `/compact` and "continue":

1. `$.turn.abort` ends the turn before the request goes out. Every tool result
   of the finished step is already in, and no interruption marker is written.
2. In `turn.complete`, `$.session.compact()` compacts -- the same call, the same
   summary, the same kept messages as at the end of a turn.
3. `$.prompt.submit({ text: 'Continue.' })` starts the next turn. The summary
   Claude Code writes already tells the model to pick up where it left off.

The turn becomes two, and the transcript shows `Continue.` as a message from the
taskcut plugin. That is the whole difference from a compaction at the end of a
turn.

Two other ways were tried and do not work. Lowering
`CLAUDE_CODE_AUTO_COMPACT_WINDOW` with `$.env.set` at a boundary, to make Claude
Code's own threshold fire on the next request, changes nothing: the engine does
not read it again. And `$.session.compact()` itself cannot run inside a turn.

A turn is only ended in an interactive session. A `-p` run would end with it,
and could not compact anyway. A compaction that leaves the context above the
floor -- a very large `CLAUDE.md`, a large kept tail -- would otherwise have the
next finished piece compacted again at once, so the next judgement then waits
until the context has grown five points past what the compaction left.

Two other candidates were tried. `classic.Stop` never reached the hooks module.
Deferring the call with `$.clock.after(0, ...)` was unnecessary: in an
interactive session the straight call from `turn.complete` succeeds.

A failure there is caught and logged rather than thrown. A plugin that cannot
compact should not be able to take the turn down with it.

## The one structural rule in the source

A hooks module may pass `$` only to a function declared at the top level of the
same file. The loader refuses anything else, before a session loads it:

```
$ is passed to "judge", imported from "./judge": $ is followed only into a
function declared in this same file, never across an import
```

This is what lets `claude plugin validate` print the complete list of what a
plugin calls, including through helpers — `$.model.complete (via judge)`.
The file layout follows from it: everything touching the engine is in
`register.ts`, and everything that is a function of plain data is beside it,
where it can be read on its own.
