# What the benchmark has found

taskcut makes a bet: that clearing a sub-task's working context at the boundary
leaves the model in better shape than letting the transcript grow. This page
records what happened when that was checked. [eval/README.md](../eval/README.md)
describes the harness; `make eval-list` runs it.

Read the caveats first, because they bound everything below. **One run per
cell.** Model behaviour varies enough that these show the shape of a difference,
not its size, and the tool-call counts especially are small numbers. All runs
are Claude Code 2.1.278 on Sonnet. In sections 1 to 6 every cutting arm had
`floorPercent` forced to `0`, because an arm that respects the floor makes no
cuts on a run this short and measures nothing -- so the cost columns there are
the cost of cutting when cutting is not worth it, which is the case the floor
exists to avoid. Sections 7 and 8 run at a floor of 30, on real work.

Three things are measured and never collapsed into a score, because taskcut
wins some and loses others:

* **cost** -- what the session spent
* **context health** -- how much it was carrying while it worked
* **fidelity** -- whether it could still answer afterwards, and at what price
* **work** -- whether what it built holds together, for the workloads that
  build something

## The current version: taskcut decides when, Claude Code compacts

Since 0.6, taskcut changes only *when* Claude Code compacts. Past the floor a
model judges each finished turn, and on `finished` taskcut runs the same
compaction `/compact` does. Since 0.7 it also judges each step inside a turn,
and compacts between pieces of work in a turn nobody interrupts. Everything from "The runs" down measured versions up
to 0.5, which built the compacted transcript themselves and, until 0.5, had the
working model call `close_task` at every boundary. Those numbers describe a
mechanism that no longer ships; they are kept because they are what led here.

### The mechanism, end to end

`make eval-mechanism`, one real session on Sonnet 5 with the floor at 5%:

| turn | context at its end | taskcut |
| --- | --- | --- |
| `wc -l a.txt` | 38,480 | nothing: below the floor |
| read a long file, then ask which section | 67,359 | judged **unfinished** (it ended in a question); kept |
| "Section 3", answered | 67,649 | judged **finished**; compacted, 67,877 → 33,068 |
| `cat b.txt` | 33,161 | nothing: below the floor again |
| read another long file | 61,655 | judged **finished**; compacted |
| read a third | 61,908 | judged **finished**; compacted |
| list every task, no tools | 33,729 | all six results recalled, from the compacted conversation |

The working model was never asked for anything: no tool, no reminder, no
`ToolSearch`. Each compaction is recorded in the same transcript exactly as a
typed `/compact` is -- `trigger: "manual"`, the same summary, the same
preserved recent messages -- and took 21 to 25 seconds.

0.7 adds an eighth turn: one message with three tasks to do in order without
stopping -- read a long file and write its last line to a file, the same for a
second file, then count a file's lines -- and nobody stepping in. On two runs,
0.7.0 passed every check both times:

| | run 1 | run 2 |
| --- | --- | --- |
| compactions inside that one turn | 2, each after a task was reported done | 2 |
| turns taskcut carried on with `Continue.` | 2 | 2 |
| answer files correct, reply ends `ALL DONE` | yes | yes |
| the question turn (the second above) kept | yes | yes |
| step hook skipped for overrunning its budget | 0 | 0 |

In the first 0.7 draft the judgement of one step was awaited at the start of
the next, as a plain promise, and the engine skipped the hook for running past
its 10-second budget; the judgement now runs inside the step's own dispatch,
beside its tools.

### Twenty real changes, at a realistic floor

`issues-long` again -- twenty changes click shipped, bugs and features -- with
`floorPercent` 30, on Sonnet 5, each arm once:

| | off | on |
| --- | --- | --- |
| Acceptance checks | **22/22** | **22/22** |
| Cost at Sonnet list price, as recorded | $9.89 | $10.69 |
| of which changes 1–19 | $9.30 | $10.32 |
| of which change 20 | $0.54, 5 requests | $0.32, 11 requests |
| Turns judged | — | 1, `finished` |
| Compactions | 0 | 1, after change 19: 315,608 → 5,960 tokens, 80 s |
| Context carried into change 20 | 285,735 | **37,646** |

For nineteen changes taskcut did nothing: the context was below the floor, and
not one judgement, tool call or request was added. The two arms still differ by
$1.02 over that stretch, which is what two runs of identical work differ by --
the noise is about ten percent, and it is larger than anything taskcut did.

After change 19 the context passed 30%, the judge called the turn finished,
and Claude Code compacted. Change 20 ran on 37,646 tokens instead of 285,735,
went back to the source for what it needed -- eleven requests instead of five --
and passed, for $0.32 against $0.54.

Two costs are not in the table. The compaction's own request is not recorded in
the transcript: reading 315,608 tokens and writing a 12,000-character summary
is about $0.14 if it reads from the prompt cache and about $1 if it does not,
and the transcript does not say which. The judgement is one `haiku` call of at
most about 12,000 tokens, about a cent.

What this does not show is the thing taskcut is for. At 29% of the window
Sonnet 5 got every change right with or without it, so there was no damage for
a compaction to prevent. That needs a session long enough, or a model sensitive
enough, for the baseline to start doing worse work.

## The runs

`synthetic` is ten generated modules that differ only where the probes look, so
answering means telling one apart from nine near-duplicates. `flask` is eight
modules of a real framework at ordinary sizes. Each was read one per sub-task,
then ten (or eight) probes were asked with no hint about whether to use a tool.

| workload | arm | weighted input | requests | context, first to last | ledger | correct | probes needing disk | tool calls |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| synthetic | off | 322,873 | 28 | 37,270 → 107,857 | — | 8/8 | 0/8 | 0 |
| synthetic | boundary | 433,308 | 38 | 38,102 → **44,743** | 1,860 | 8/8 | **0/8** | 0 |
| synthetic | directed | 501,844 | 46 | 37,319 → 51,513 | 3,311 | 8/8 | 6/8 | 6 |
| flask | off | **195,279** | 26 | 38,122 → 69,975 | — | 10/10 | 0/10 | 0 |
| flask | boundary | 482,953 | 41 | 37,445 → 62,792 | 5,872 | 10/10 | 5/10 | 8 |
| flask | directed | 424,574 | 47 | 38,171 → **55,313** | 3,090 | 10/10 | 10/10 | 20 |

"Weighted input" is in base-input-token equivalents: `input + 1.25 × cache
write + 0.1 × cache read`. "Context" is cache read plus cache write on the
first request of a turn -- both, because a cut invalidates the cache and most
of what a cutting arm carries arrives as a write. "Ledger" is the size the
ledger had grown to by the end.

## 1. Nothing ever lost a fact

Every arm answered every probe correctly, on both workloads. No cut, however
aggressive, produced a wrong answer. What changed was never accuracy; it was
what the answer cost.

This is worth stating plainly because it is the failure everyone expects from
compaction and it did not happen. The risk a cut carries is not that the model
is misinformed. It is that the model has to go and look again.

## 2. Context health: the ledger is the whole story

taskcut does what it claims. It also claims much less than it looks like it
claims, and the difference is the ledger.

    synthetic  off       37,270 → 45,309 → 52,221 → ... → 107,857
    synthetic  boundary  38,102 → 38,511 → 39,216 → ... →  44,743

The baseline climbs by roughly a file per sub-task and does not stop. The
cutting arm climbs by a ledger entry. Over ten sub-tasks that is 107,857
against 44,743: **59% less context** at the end, for identical answers.

On real code the same mechanism produces almost nothing:

| | ledger at the end | per entry | material per file | context saved |
| --- | --- | --- | --- | --- |
| synthetic | 1,860 | ~186 | ~6,900 | 59% |
| flask | 5,872 | ~652 | ~4,000 | 10% |

A cut replaces the working context with the ledger, so the saving is the
difference between them. The synthetic modules are 140 near-identical functions
and one planted fact: there is almost nothing to say about one, so the entry is
tiny and the cut is nearly free. A Flask module has a great deal to say, the
entry says it, and the cut buys 10%.

**Whether taskcut helps is not a property of taskcut. It is a property of how
compressible the work is.** Nothing in the design changes that, and a run whose
sub-tasks each produce a page of genuine findings will see the ledger grow into
the problem the cuts were meant to solve.

## 3. The working model hoards, and the hoarding is load-bearing

`close_task` tells the model that only what it writes will survive. It answers
by writing down everything it noticed, including what nobody asked for:

> The last function defined in mod00.py is `flush_pending(ctx)`. […] Other
> things in the file: it imports `collections` and `itertools`; it defines the
> constant `RETRY_BUDGET = 4011` between `handler_061` and `tenant_062`; and it
> has a stray comment `# owner: ravi` between `tenant_093` and `buffer_094`.

`RETRY_BUDGET` and the owner comment were never asked for during the work. They
are two of the three incidental probes. The boundary arm answered them from the
ledger without touching the disk, because the model had defensively written them
down against exactly that possibility.

That instinct is the reason the synthetic boundary arm needed zero disk trips
while holding 59% less context. It is also why its entries are larger than a
conclusion needs to be. The two are the same behaviour.

## 4. Directed extraction: smaller ledger, more re-reading

`ledgerMode: directed` throws away the working model's conclusion and has the
fold model write the entry from the transcript being dropped. The hypothesis was
that a writer who sees the work and knows the job would keep less and keep
better.

It keeps less. It does not keep better.

| flask | ledger | context at the end | probes needing disk | tool calls |
| --- | --- | --- | --- | --- |
| boundary | 5,872 | 62,792 (−10%) | 5/10 | 8 |
| directed | 3,090 (−47%) | 55,313 (−21%) | **10/10** | **20** |

The ledger halves and the context saving doubles. Every probe then goes back to
disk -- including all five **headline** facts, the ones the model was explicitly
asked for while it worked. A smaller record bought more looking, and the
accounting came out worse: 47 requests against 41, and 20 tool calls against 8.

On the synthetic workload it loses on every axis at once: a *larger* ledger
(3,311 against 1,860) because a small model given latitude fills it with
`## Summary for Continuation` and `## Next Steps` headings, and six disk trips
where the boundary arm needed none.

Two things were ruled out as explanations.

**It is not the prompt being too prescriptive.** The extractor's prompt states
the situation and stops -- no list of what to keep or drop -- deliberately, so
that the model's own judgement is what is being tested rather than a checklist.

**It is not the misaimed standing task**, though that was a real bug found here
and fixed. The first version told the extractor that the first human turn *was*
the standing task; in a session that opens by asking for the first step it is
that step, and the extractor duly wrote entries saying "The standing task is
complete - no further action needed" and "Immediate Task: Sub-task 1. Action
required: run `cat mod00.py`" -- an instruction to redo a sub-task the same
ledger had marked closed. That is fixed, the extractor is now told it cannot
know which it has, and re-running changed the outcome very little: flask went
from 10 disk trips to 10, synthetic from 8 to 6.

What is left is structural. Asked to write what a continuation needs, a model
writes a summary: fluent, well organised, and about the work rather than made of
it. Constants, paths and identifiers are exactly what a summary drops, and they
are exactly what the next question asks for. The working model's inventory reads
worse and holds more.

`directed` ships, defaulting off, because a smaller ledger is a real trade for
someone whose binding constraint is context and whose files are cheap to re-read.
On this evidence that is a narrow case.

## 5. On work, rather than on recall

Everything above asks the model to read and then answer. That is the easiest
thing it does, and scoring 100% at it says less than it looks like it says. The
`build` workload asks for work instead: ten steps constructing a package, with
a public contract changed at step seven -- `event_ts` becomes `occurred_at`,
everywhere -- and three rules set once in an opening briefing and never
repeated. Nothing the model says afterwards counts. The grade is ten assertions
run against what it produced.

| | off | boundary |
| --- | --- | --- |
| Acceptance checks | **10/10** | **10/10** |
| Weighted input | 282,552 | 573,747 |
| Requests | 38 | 54 |
| Context, first to last | 38,337 → 82,155 | 38,381 → 59,475 |
| Peak, as a share of the 1M window | 8.2% | 5.9% |
| Ledger | — | 6,978 |

Both packages import, parse the fixture, aggregate exactly the four hundred
good lines, pass their own tests and run from the command line. Both applied
the step-seven rename completely. Both kept all three briefing rules: a
docstring on every module, no bare exception raised anywhere, and exactly one
definition of the shared record type. The work is indistinguishable. taskcut
carried 28% less context to do it and spent 2.03× as much.

`audit` is the same shape and larger: five steps reading a real Flask checkout
to work out how configuration keys are used, then five building a
standard-library tool that finds them, run against that same checkout. The
answer is exact -- 26 keys and 38 reads, under a counting rule the briefing
fixes -- so the tool either agrees with the source or it does not. The output
format changes at step nine, invalidating what step seven built.

| | off | boundary |
| --- | --- | --- |
| Acceptance checks | **9/9** | **9/9** |
| Weighted input | 467,723 | 1,007,906 |
| Peak context | 128,133 | 76,749 |
| Peak, as a share of the 1M window | **12.8%** | 7.7% |
| Ledger | — | 12,081 |

This is the most context any run here has carried, and the result is the same:
both tools scan correctly, both emit the JSON step nine demanded, both deleted
the module step nine superseded, neither imported Flask, neither touched the
checkout. taskcut halved the peak context and spent 2.16× as much to do it.

### Two corrections, both the same mistake

Each of these failed correct work, and each was mine.

The `build` integration check failed both arms identically at 401 lines instead
of 400, with an unexpected `NOTALEVEL` bucket. Both arms were right: the
briefing gives level checking to `validate` and tells `parse_line` only to
reject a malformed line.

The `audit` scan check expected 30 keys. Both arms found 26, and both were
right: the briefing spells the rule `config["KEY"]`, with double quotes, and
the four missing keys are single-quoted in the Flask source.

In both cases the expected answer had been computed by a reference
implementation written alongside the brief rather than derived from the
brief's literal text, and in both cases the reference had quietly taken a
different reading. **An acceptance check should be derived from the
specification, not from a second implementation of it** -- otherwise it tests
agreement between two of the author's opinions, and grades the model against
the one that was not written down.

## 6. What has not been shown

Five workloads, two of which produce something that is graded by running it.
Peak context from 44,743 to 128,133 tokens, at most 12.8% of the 1M window. Ten
interdependent steps, a public contract reversed mid-way, three standing rules
never repeated after the briefing.

**Not one measurement found the baseline doing worse work.** Every probe
answered correctly by both arms on the recall workloads; every acceptance
check passed by both arms on the build workloads; every standing rule still
being applied at the last step by both arms; the superseded value correctly
replaced by both arms. Effort per sub-task in the baseline is flat: over ten
sub-tasks it ran 2 requests, 1 tool call and about 140 output tokens each
time, with no drift at all.

The premise taskcut rests on -- that a crowded context degrades the work -- has
not been demonstrated here, at these sizes, on this model. What has been
demonstrated is the mechanism: context stops climbing, by 10% to 59% depending
entirely on how compressible the work is, and it costs 1.34× to 2.47× to do
that.

Two honest explanations, and only one experiment separates them.

**Either the effect needs a fuller window.** 12.8% is the most this reached.
Reports of context degradation concentrate well above that, and the engine's
own auto-compaction fires higher still. The comparison that has not been run
is one long enough for the *baseline* to hit auto-compaction: at that point it
loses its transcript to a summariser, which is the thing taskcut replaces with
a deterministic cut. Every run here stopped short of the only point where
taskcut's central claim is testable.

**Or the effect needs a longer run than a benchmark can afford.** The job
taskcut was written for runs for days. Twelve sub-tasks is not a scale model of
that; it is a different thing that finishes before the problem starts.

Until one of those is run, the honest summary is that taskcut reliably does
what it says to the context and has not yet been shown to buy anything with it.

### A correction to every share of the window above

`sonnet` resolves to Sonnet 5, whose window is 1M, not 200k. The harness had
the old figure, and every "share of the window" it reported was five times too
high: the `audit` run described as reaching 64% reached 12.8%. The token counts
were always right; only the denominator was wrong. The evidence is the status
line itself -- a session at 37,403 tokens reads `ctx 4%`, which is 1M, where
200k would read 19%.

It does not change what was measured, but it changes what it means. Every run
here sat between 4% and 16% of the window. None came near the regime where
anyone reports a crowded context degrading work, so "no measurement found the
baseline doing worse" is a statement about a tenth of the window, not about the
window.

## 7. At a realistic floor, on real bugs

Everything above forced `floorPercent` to 0, which cuts at every boundary and is
not a setting anyone would run. `issues` is the first workload at a realistic
floor, 30, on real work: nine bugs click shipped and fixed, reverted source-only
at a pinned commit so each keeps its original regression test, handed out as a
symptom and the failing tests.

| | off | boundary | reply |
| --- | --- | --- | --- |
| Acceptance checks | **11/11** | **11/11** | **11/11** |
| Cost at Sonnet list price | $3.31 | $2.90 | $3.14 |
| Requests | 60 | 63 | 67 |
| Peak context | 155,702 | 133,059 | 136,939 |
| Peak, as a share of the 1M window | 15.6% | 13.3% | 13.7% |
| `close_task` calls | — | 9 | 9 |
| **Cuts** | — | **0** | **0** |

Every arm fixed all nine bugs, broke nothing and touched no test. And no arm
cut: the model closed every sub-task, but a 30% floor on a 1M window is 300,000
tokens, and nine real debugging sessions with repeated test runs peaked at
155,702. taskcut, correctly, did nothing.

That is the most consequential measurement here, and it is not about whether
cutting helps. **At its shipped default of 40% on a 1M window, taskcut does not
act until a session holds 400,000 tokens.** A floor expressed as a share of the
window was calibrated when windows were 200k; at five times the window it means
five times the context before anything happens.

It also turned the run into an A/A/A comparison, which is useful in its own
right. Three runs of identical work cost $3.31, $2.90 and $3.14 -- about ±7% --
so a single run cannot resolve a difference in cost smaller than roughly ten
percent. Over nine short changes, calling `close_task` without cutting cost
nothing measurable: the two arms that called it nine times were the two
cheapest. Over twenty it does -- see the next section.

## 8. Twenty real changes: the floor, reached once

`issues` never came near the floor, so `issues-long` makes the session longer
rather than the floor lower: twenty changes click shipped -- the nine bugs above
and eleven larger ones -- handed out alternately as bug reports and feature
requests. Five are handed out in the words of their upstream issue (#3802,
#2869, #2819, #3136, #3700), and seven land in `core.py`. Same pin, same
grading: each change's own tests, the whole suite, and no test touched. Sonnet
5, `floorPercent` 30.

| | off | boundary | reply |
| --- | --- | --- | --- |
| Acceptance checks | **22/22** | **22/22** | **22/22** |
| Cost at Sonnet list price | $10.37 | $11.50 | $11.01 |
| Requests | 143 | 165 | 160 |
| Wall clock | 44 min | 37 min | 37 min |
| Context carried into the last change | 294,690 | 292,546 | **40,294** |
| Peak, as a share of the 1M window | 29.5% | 29.3% | 27.2% |
| `close_task` calls | — | 20 | 20 |
| **Cuts** | — | 1, after the last change | **1, before the last change** |

Twenty changes and forty minutes of uninterrupted work end a session just under
300,000 tokens. Both cutting arms crossed the floor inside a final turn -- at
303,164 and 301,827 tokens -- and cut in 12 and 23 milliseconds, down to 11,173
and 7,903. Where the crossing fell was luck. `reply` crossed at the end of
change 19 and did change 20 carrying 40,294 tokens; `boundary` crossed at the
end of change 20, with nothing left to do.

Change 20 is the only work in this document done after a cut at a realistic
floor. It passed, and it cost $0.26, against $0.64 and $0.74 in the two arms
that carried 290,000 tokens into it. That is one sample: it shows a cut at 30%
does not break the next change, and nothing about how often.

**Closing a task costs a round-trip, and over twenty it shows.** A tool call
ends the model's response, so every `close_task` takes one more request to
finish the turn, and that request reads the whole context again from the cache.
In `boundary`, which never cut before the work was over, the twenty requests
after `close_task` read 3,645,518 cached tokens -- $1.09. The whole difference
from `off` was $1.13. So at a floor the session never reaches, taskcut costs
about ten percent and does nothing for it. In `reply` the one cut won back
about $0.40 of that.

Nothing here was diluted. At 29% of the window every arm fixed every change,
broke nothing and touched no test, so there was no damage for a cut to prevent.
**At the shipped default of 40%, none of these sessions would have cut at
all.**

## 9. What a cut costs

A compaction invalidates the prompt cache past the tool definitions. Measured
over four consecutive cuts, `cache_read_input_tokens` on the first request after
a cut was **26,791 every time** -- what survives is the system block and the
tool definitions, and nothing else.

Everything past that is written again, and the kept set is bigger than the
keep-set rule suggests: `cache_creation_input_tokens` on the same request ran
11,968 → 14,720. The first human turn, two recent turns and the ledger are a
small part of it; most is the preamble the engine puts in front of every
conversation, re-cached on every cut.

Writing a token costs about 1.25 of a base input token and reading a cached one
about 0.1. So the turn after a cut pays `0.1·S + 1.25·(K−S)` where it would have
paid `0.1·P`. With S = 26,791 and K−S ≈ 12,000 that is 17,639 against 5,074:
three and a half times more, repaid at `0.1·(P−K)` per turn afterwards.

End to end at `floorPercent=0`, cutting cost **1.34×** the baseline on synthetic
and **2.47×** on flask. Both are the correct answer for runs whose context never
passed 8% of the window. Per sub-task the earlier four-sub-task run measured the
cutting arm flat at 49,358 against a baseline of 28,368 growing by about 2,200,
which crosses near the fourteenth sub-task.

**taskcut is a bet on the run being long. The floor is what keeps the bet off
the table when it is not.**

## 10. Two costs that are not in the table

**A cut costs a second round-trip.** Every `close_task` already costs one
request (section 8). On top of that the tool is deferred, so the model spends a
`ToolSearch` call loading its schema before using it -- once per session, and
again after every cut, because the cut discards the message that carried it.
Where the cut was forced at every boundary that meant one more request per
sub-task; in `issues-long`, which cut once, it was one or two in the whole run.

**The model keeps closing tasks after the work is over.** After eight sub-tasks
of being asked to call `close_task`, the flask boundary arm went on calling it
during the probe phase, so cuts kept happening once there was nothing left to
cut. This is what produced 17 ledger messages for 9 closed sub-tasks.

## Reproducing

```bash
make eval-mechanism
make eval-run WORKLOAD=issues-long ARM=off MODEL=sonnet
make eval-run WORKLOAD=issues-long ARM=on MODEL=sonnet
make eval-report
```

The mechanism check is a few minutes and about a dollar. Each `issues-long` arm
is about forty minutes and $10 to $11; they can run at once. Reproducing the
sections for earlier versions means checking out the tag they measured.

`eval/results/runs.json` holds the numbers above in machine-readable form.
Transcripts are not committed: they are large and full of absolute paths.
