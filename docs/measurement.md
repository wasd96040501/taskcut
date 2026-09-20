# What the benchmark has found

taskcut makes a bet: that clearing a sub-task's working context at the boundary
leaves the model in better shape than letting the transcript grow. This page
records what happened when that was checked. [eval/README.md](../eval/README.md)
describes the harness; `make eval-list` runs it.

Read the caveats first, because they bound everything below. **One run per
cell.** Model behaviour varies enough that these show the shape of a difference,
not its size, and the tool-call counts especially are small numbers. All runs
are Claude Code 2.1.278 on Sonnet. Every cutting arm had `floorPercent` forced
to `0`, because an arm that respects the floor makes no cuts on a run this short
and measures nothing -- so the cost columns are the cost of cutting when cutting
is not worth it, which is the case the floor exists to avoid.

Three things are measured and never collapsed into a score, because taskcut
wins some and loses others:

* **cost** -- what the session spent
* **context health** -- how much it was carrying while it worked
* **fidelity** -- whether it could still answer afterwards, and at what price
* **work** -- whether what it built holds together, for the workloads that
  build something

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
| Peak, as a share of the window | 41% | 30% |
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
| Peak, as a share of the window | **64%** | 38% |
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
Peak context from 44,743 to 128,133 tokens, up to 64% of the window. Ten
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

**Either the effect needs a fuller window.** 64% is the most this reached.
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

## 7. What a cut costs

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

## 8. Two costs that are not in the table

**A boundary costs an extra round-trip.** `close_task` is a registered tool and
the model spends a `ToolSearch` call loading its schema before each use -- at
every boundary, not just the first, because the cut discards the message that
carried it. One extra request per sub-task, caused by taskcut and paid for by
taskcut.

**The model keeps closing tasks after the work is over.** After eight sub-tasks
of being asked to call `close_task`, the flask boundary arm went on calling it
during the probe phase, so cuts kept happening once there was nothing left to
cut. This is what produced 17 ledger messages for 9 closed sub-tasks.

## Reproducing

```bash
make eval-run WORKLOAD=flask ARM=off
make eval-run WORKLOAD=flask ARM=boundary
make eval-run WORKLOAD=flask ARM=directed
make eval-report
```

`eval/results/runs.json` holds the numbers above in machine-readable form.
Transcripts are not committed: they are large and full of absolute paths.
