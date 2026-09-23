# Design

## The shape of the problem

Claude Code compacts when the context window fills. That threshold is a property
of the window, not of the work, and on a long job the two rarely coincide. The
compaction lands mid-sub-task, where every detail is still live, and summarises
it; meanwhile the detail from work that finished an hour ago is kept, because a
summariser looking at a flat transcript has no way to tell which is which.

The move from one sub-task to the next is the one moment where "what still
matters" has a clean answer. taskcut moves the decision there.

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
   step of the main conversation gets one `$.model.complete` call asking
   whether the work moves on there from a finished piece to another. Below the
   floor it never runs, and the working model is never told taskcut exists.

## Moving on, not finishing

Up to 0.8 the judge was asked whether a step *finished* a piece, and the reply
a turn ended on was judged too. That compacts in two places where nothing is
gained. Hand over A, B and C in one message: when C is done, C was finished,
and the conversation was compacted -- inside the turn it was then carried on
with `Continue.` only to write the closing summary from a summary. Ask for one
thing per message: every finished turn was compacted before the person had
said a word about it, and what people say after a finished piece is as often
about that piece -- a correction, "also handle None", "commit that" -- as it
is something new.

A compaction pays for itself when the work that follows does not need the
detail of the work before. So the question is whether the work *moves on*: a
piece is finished and a different one begins. Inside a turn the step itself
says so -- "task 2 is done; now task 3". The end of a turn cannot: the work is
back with the person, and whether they move on is theirs to say, and theirs to
`/compact` before. So the end of a turn is no longer judged at all, and the
structure is otherwise 0.8's: the same steps judged, the same way of ending a
turn to compact.

The rules are, in order: a step that asks the person something, waits for
their decision or proposes work it has not done is `SAME`; a step that itself
says a piece is complete, with another piece the person asked for still to do
-- it names or starts it, or the request plainly lists more -- is `NEXT`;
anything else is `SAME`, the last piece being complete included.

Two kinds of step are not asked about at all. One with no text cannot say a
piece is complete. And after a compaction, no step is until the working model
has changed something -- a call other than a read-only lookup: nothing can have
been finished since, and the summary, which reads like a message listing the
pieces done, made the first step of the next piece look to the judge like the
move to it. In a real session the judge called that step `NEXT` and the work
was compacted twice in a row; on the same step in the benchmark it did so
three times in three.

The judge writes one sentence about the step before its verdict: asked for
the word alone, it read "task 2 is done; now task 3" as work in progress and
missed two boundaries in three. Anything but a clear `NEXT` -- no verdict, a
failed request -- keeps the context: a missed boundary waits for the next one,
and the threshold is still there.

`make eval-judge` asks the judge about 16 labelled steps, three times each,
through the same call. Against 0.8's question on the same steps:

| steps | 0.8, "finished?" | "moves on?" |
| --- | --- | --- |
| a piece done, another asked for | 18/18 | 18/18 |
| the last piece done | 0/15 | 15/15 |
| a piece in progress | 12/15 | 15/15 |

The boundaries that matter are found as often as before; the last piece, which
0.8 compacted every time, is now kept every time.

The first version of this asked `$.model.classify`, which wraps the text in a
fixed classifier prompt and treats every word of it as data. The instructions
that said what "finished" meant were data too, and a step that finished one
task and started the next was never a boundary.

## What the judge reads

The judge reads what auto mode's permission classifier reads, which decides
from a portion of the transcript rather than all of it: every message the
person sent, every tool call the assistant made except read-only lookups, and
`CLAUDE.md`, with all tool output stripped. To that it adds the step being
judged -- what the assistant just said and the calls it is making -- as the
classifier adds the pending action.

It reads all of that portion, as the classifier does. Claude Code 2.1.280's
classifier (`xLt` and `Zke` in the bundle) puts every entry of the transcript
in its request and never leaves the oldest out; when the request no longer fits
its window it gives no verdict (`transcript_too_long`) and falls back to asking
the person. 0.8's judge kept the newest 40,000 characters instead, which moved
the start of what it read with every line once the conversation passed that.
Now the conversation is read whole, and a conversation too long for the
judge's own window is a failed request: no verdict, the context kept -- the
judge's own way of falling back. Each message and each call is still clipped
on its own, and what the judge reads is a fraction of the context: no tool
output, and nothing from before the last compaction.

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

On a 1M window a floor of 35% is 350,000 tokens. Twenty real changes in one
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

`$.session.compact` rejects while a turn is running, so taskcut ends the turn
first and compacts from `turn.complete`, after `next(e)` has settled it -- see
[Inside a turn](#inside-a-turn). A subagent's steps are never judged: its run
is not the person's conversation.

## When a compaction can summarise

On Claude Code 2.1.280 a compaction summarises only when the last request the
main loop sent ended on tool results. When it ended on the person's own words --
a turn's first request, or a turn they asked and Claude answered without a
tool -- the summary instruction reaches the model as part of those words: it
answers them, and says the rest looks like an instruction smuggled into their
message. The "summary" that replaces the conversation is that answer.

Three one-message sessions, then a compaction, isolate it:

| the request before | compacted from | summary |
| --- | --- | --- |
| a question, answered without a tool | `turn.complete`, as 0.8 did at a turn's end | `4` -- the answer to the question |
| a question, answered without a tool | a plugin, before the next message went in | the answer, and a note that the rest "looks injected" |
| tool results | a plugin, before the next message went in | a summary |

and `/compact` typed by hand after a turn answered without a tool, with no
plugin loaded, gives the same answer in place of a summary. It is not taskcut's
to fix, but taskcut does not make it: it records whether the request each step
sent ended on tool results -- every step's but a turn's first -- and ends a
turn only after one that did. 0.8 was exposed to it at every turn answered
without a tool, since it judged the end of every turn; its mechanism check never
compacted one, and did not show it.

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

When a step is judged to move the work on, the next dispatch of the hook does
what a person watching would do with Esc, `/compact` and "continue":

1. `$.turn.abort` ends the turn before the request goes out. Every tool result
   of the step is already in, and no interruption marker is written.
2. In `turn.complete`, `$.session.compact()` compacts -- the same call, the same
   summary, the same kept messages as `/compact`.
3. `$.prompt.submit({ text: 'Continue.' })` starts the next turn. The summary
   Claude Code writes already tells the model to pick up where it left off.

The turn becomes two, and the transcript shows `Continue.` as a message from the
taskcut plugin. That is the whole difference from a `/compact` typed between
turns.

Two other ways were tried and do not work. Lowering
`CLAUDE_CODE_AUTO_COMPACT_WINDOW` with `$.env.set` at a boundary, to make Claude
Code's own threshold fire on the next request, changes nothing: the engine does
not read it again. And `$.session.compact()` itself cannot run inside a turn.

A turn is only ended in an interactive session. A `-p` run would end with it,
and could not compact anyway. A compaction that leaves the context above the
floor -- a very large `CLAUDE.md`, a large kept tail -- would otherwise have the
next piece compacted again at once, so the next judgement then waits until the
context has grown five points past what the compaction left.

Two other candidates were tried. `classic.Stop` never reached the hooks module.
Deferring the call with `$.clock.after(0, ...)` was unnecessary: in an
interactive session the straight call from `turn.complete` succeeds.

A failure there is caught and logged rather than thrown. A plugin that cannot
compact should not be able to take the turn down with it.

## The judge's prompt cache

The judge's calls are not served from a prompt cache, and on Claude Code
2.1.280 nothing a plugin puts in its prompt can change that. `$.model.complete`
(`YTe` in the bundle) sends a system block and one user message holding the
prompt as a single string, with no `cache_control` anywhere in the request, and
the API caches only up to a breakpoint. The usage it resolves is the API's own,
copied field for field -- the same mapping `$.model.fork` reports its cache
reads through -- so two identical 30,000-token prompts sent one after the other
reporting `cache_creation_input_tokens: 0` and `cache_read_input_tokens: 0` is
the request going uncached, not the count going missing.

The permission classifier is cached because it builds its own request (`Zke`,
`iRr`): a breakpoint after its rules, one after `CLAUDE.md`, one after the last
block of the transcript and one after the action. It splits the transcript
into a block of its own at every call it has classified before, so the action
it judged last time is now a whole block of the transcript, and the next
request is served from the cache up to it; its second stage changes only what
follows the action, and is served whole.

A plugin could build that request itself, with `$.session.authorize()` and
`$.http.fetch`, but only by copying what the engine does to send one -- the
credential's beta header, the identity block a subscription requires, the base
URL, the model id -- which is the engine's to change. So the judge uses
`$.model.complete`, and its prompt is built the way the classifier's is, ready
for a call that caches: the rules, `CLAUDE.md`, the whole conversation oldest
first, and the step last. `$.session.messages()` only ever adds to what the
judge reads -- between two steps the one field that changes on an earlier
message is a call's `result`, which the judge never reads -- so each
judgement's prompt begins with everything the one before it read ahead of its
step.

`$.model.fork`, the one call that is served from a cache, reads the main
thread's whole transcript with the main model: past a floor of 35% on a 1M
window that is 350,000 tokens a judgement at the cache-read price, several
times what the judge's own prompt costs uncached, and it puts every tool output
back in front of the judge.

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
