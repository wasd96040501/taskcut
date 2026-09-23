# Benchmarking taskcut

taskcut makes a bet: that clearing a sub-task's working context at the boundary
leaves the model in better shape than letting the transcript grow. This
directory is how that bet is checked, and it is built to make the answer
falsifiable rather than flattering.

Three things are measured, and they are not the same thing:

| | what it asks | why it is separate |
| --- | --- | --- |
| **cost** | what the session spent | a cut can save context and still cost more |
| **context health** | how much the model was carrying while it worked | the thing taskcut actually claims to change |
| **fidelity** | whether it could still answer afterwards, and at what price | the thing a cut can quietly destroy |

They are reported side by side and never collapsed into a score, because
taskcut wins some and loses others and a single number would hide that.

## Design

Four axes, none of which knows about the others:

    workload    what a session is asked to do, and what to ask it afterwards
    arm         how taskcut is configured, if it is loaded at all
    transcript  what the finished session recorded, parsed into plain records
    metric      a pure function from a transcript to a number

A run is a workload crossed with an arm. Everything downstream reads only the
transcript, so a metric never learns how the session was driven and a workload
never learns which arm it ran under. Adding a workload is adding a JSON file;
adding an arm is adding an entry to `arms.py`; adding a metric is adding a
function. None of the three requires touching the other two.

`driver.py` is the one impure module. It owns the terminal transport and
nothing else depends on how it works.

### Why a pseudo-terminal

`$.session.compact` is unavailable in a headless session: `claude -p` and the
SDK transport cannot compact, so a benchmark driven through either would
measure the plugin doing nothing at all. A pty gives the engine the interactive
surface it requires. The screen is never parsed for results -- it is read only
to notice the folder-trust prompt and to tell when a turn has gone quiet. Every
number comes from the transcript afterwards.

### Why Python

The harness needs a pseudo-terminal, and `pty` is in the Python standard
library. The equivalent in Node is a native dependency, and this repository has
none anywhere else.

## Running it

```bash
make eval-list            # the workloads and the arms
make eval-verify          # every probe is answerable from the material
make eval-mechanism       # the mechanism, end to end, in one short session
make eval-run WORKLOAD=issues-long ARM=off
make eval-run WORKLOAD=issues-long ARM=on
make eval-run WORKLOAD=sqlglot-long ARM=off
make eval-run WORKLOAD=sqlglot-long ARM=default
make eval-report
make eval-test            # the harness's own tests
```

There are three arms: `off` and `on`, both at a floor of 30%, and `default`,
taskcut exactly as installed -- a floor of 35%, judged by `sonnet` -- for a
workload long enough to pass it.

`make eval-run` materialises the workspace, bakes the arm's settings into a
copy of the plugin, drives the session, and copies the transcript into
`results/`. Raw transcripts are not committed: they are large and full of
absolute paths.

Run each pair several times. Model behaviour varies enough that one pair shows
the shape of a difference, not its size.

## The judge on its own

`make eval-judge` asks the judge about the labelled steps in
`taskcut_eval/judgecases.py` -- each with the verdict a person watching would
give -- three times each, through the same `$.model.complete` call taskcut
makes, in one headless session. The harness plugin in `eval/judge` runs with a
copy of the plugin's own `hooks/judge.ts`, so what is measured is what ships. A
change to the question is measured on the same steps before and after; it
costs a few cents a step and about half a minute.

## The mechanism check

A benchmark run at a realistic floor crosses it once, if at all, so it cannot
show that the mechanism behaves every time. `make eval-mechanism` drives one
short session with the floor at 5%: two messages of four tasks each, handed
over with nobody stepping in and reading files large enough to cross the floor
in each, and a question between them. It asserts from the transcript:

* below the floor, nothing -- no judgement, no tool, no reminder;
* in each long turn, a finished task with another to follow is compacted
  inside the turn, none skipped, and the work carries on with `Continue.`;
* the last task is not compacted, and no turn ends in a compaction;
* nothing is compacted below the floor, and crossing again compacts again;
* what was compacted can still be recalled, value for value;
* every task is done;
* the working model is never asked for anything.

It exits non-zero if any fails. The assertions were also run against a 0.4.0
transcript, where the ones that should fail do.

## Workloads

The first two ask the model to read and then to recall. The last two ask it to
do something, and grade what it produced.

**`synthetic`** -- ten generated modules that differ only where the probes
look. Answering a question about one of them means telling it apart from nine
near-duplicates. This is interference, which is what a crowded context actually
does to a model, and it appears long before the window is full. It controls for
everything else: same length, same vocabulary, same shape.

**`flask`** -- eight modules of a real web framework, one per sub-task. Ordinary
code at ordinary sizes, where a conclusion written at a boundary cannot possibly
hold everything the file contained.

**`drift`** -- twelve crowded, confusable service modules read end to end. Three
rules are set once in an opening briefing and never repeated, and a value
established at step four is overridden at step ten. It exists because the first
two workloads scored every arm at 100%: retrieval is the last thing a crowded
context breaks, and a probe asked after the work cannot see a rule that stopped
being applied during it.

**`build`** -- ten steps constructing a package. A public contract changes at
step seven, and three rules run through the whole job. Nothing is asked of the
model afterwards that matters: the grade is whether the package imports, parses
the fixture, aggregates it correctly, passes its own tests and runs from the
command line.

**`issues`** -- nine bugs click really shipped and really fixed, reverted
source-only at a pinned commit so each still has the regression test its
original author wrote. Handed out one at a time as a symptom plus the failing
tests, never the fix. Four are in `core.py`, so the work keeps returning to the
same large file. Graded by the tests: each issue's own, the whole suite for
regressions, and `git diff` to confirm no test was touched. This is the one
that looks like real work -- exploration, dead ends, re-running the suite --
and so the one whose context actually fills with what taskcut exists to clear.

**`issues-long`** -- the same, twenty changes long: the nine bugs above and
eleven larger ones, bugs and features handed out alternately, five in the words
of their upstream issue. Seven land in `core.py`. Twenty real changes are what
it takes for one session on Sonnet 5 to reach 30% of its 1M window, which is the
lowest floor anyone would run -- so this is the workload where a cutting arm at
a realistic setting cuts at all. About forty minutes and $10 to $12 an arm.

**`sqlglot-long`** -- thirty-six changes sqlglot shipped, reverted source-only
at a pinned commit: eleven in the optimizer, four in the parser, one each in
the executor, lineage, expressions, the generator and transforms, and sixteen
in dialects; twenty-nine bugs and seven features. Unlike
every workload above, it is handed over in **one message**: ISSUES.md lists
them, and the model is told to work through all of them in order without
stopping to ask. That is the job taskcut is for, and the one a trigger at the
end of a turn never sees. If the model stops early anyway, the harness sends
the same nudge under every arm and counts it. sqlglot's parser alone is ten
thousand lines, so the work reads a lot, and one Sonnet 5 session goes past
half its 1M window. Graded per issue by the test cases that issue broke --
several sqlglot tests hold cases broken by different issues -- with a helper
that lives outside the workspace; plus the whole suite and `git diff`.

Every change was kept only after checking, in the state the session gets, that
its cases fail and that its own fix alone removes them without adding any; with
all thirty-six real fixes put back, every check passes. Two changes only apply
on top of an older one's; both stay separate issues, and the cases that need
both belong to the later.

**`click-zh`** -- the twenty click changes of `issues-long`, handed over in
**one message, in Chinese**, the way the job taskcut is for is given in real
use: keep a task list, fix the issues in the order ISSUES.md lists them, and
commit after each one. It exists because every boundary the judge had been
measured on came from `sqlglot-long` -- one repository, one prompt, one way of
saying "Issue 12 done; now 13" -- and from sessions that never kept a task list
or committed, where real ones do both: a commit is the most common thing a step
does between one piece and the next, and it is wrapping up, not moving on.
Graded by the same per-issue tests and the whole suite. Because the session
commits as it goes, `git diff HEAD` no longer shows what it changed, so the
workspace's broken state is tagged `eval-start` and the checks diff against
that; one more check asks that the work was committed, a commit per issue at
least. Verified both ways: in the broken state every issue check fails, with
the twenty real fixes committed one by one every check passes, and a test
edited and committed fails `tests_untouched`.

**`audit`** -- five steps researching a real Flask checkout, then five building
a standard-library tool that finds configuration key reads, run against that
same checkout. The answer is exact and computable -- 30 keys, 42 reads, under a
counting rule the briefing fixes -- so the tool either agrees with the source or
it does not. The output format changes at step nine, invalidating what step
seven built.

## The judge, replayed over real sessions

`make eval-judge` asks the judge about sixteen steps written for it. `make
eval-replay` asks it about every step real sessions took that taskcut would
have judged, as the session looked at that moment -- so a change to what the
judge reads or is asked is measured on the work it will actually see, and
priced:

```bash
make eval-replay MODEL=sonnet                 # the working tree's hooks/judge.ts
make eval-replay MODEL=sonnet REF=main        # the judge as it was on main
make eval-replay-compare A=eval/results/replay--main--sonnet.json B=eval/results/replay--<sha>--sonnet.json
```

A **set** (`replay/<set>.json`) is one session's transcript turned into what
`$.session.messages()` held before each step, with the step, and nothing of
any tool's output; its **labels** (`replay/<set>.labels`) say, for every step
taskcut would judge, whether the work moves on there: `N`, `S`, or `E` for
either. [replay/LABELS.md](replay/LABELS.md) says how to label, and `make
eval-replay-sheet SET=…` prints a set's steps with what a labeller needs to
see. A set that is someone's own session goes in `replay/local/`, which is not
committed; it is read the same way when it is there.

The run reports, with a 95% bootstrap interval where it is a rate:

* **boundaries caught** -- an N step and the E steps just before it are one
  window, caught if the judge says NEXT anywhere in it, as live the first NEXT
  compacts;
* **false NEXT** -- S steps called NEXT: a compaction in the middle of a piece;
* **hard SAME** -- S steps that say a piece passes or is done, got right;
* **same every repeat**, **unanswered**, and what it cost: list price per
  judgement, and for the judged steps of `sqlglot-long--off` past 35% of the
  window, the stretch a shipped floor would actually judge.

`replay-compare` pairs two runs step by step and gives the difference of each
rate with an interval over the same boundaries and steps, which is what "not
worse" has to rest on.

### Whether the replay is what the judge sees

Every number above is about a prompt rebuilt from a transcript. `make
eval-replay-check` checks that it is the prompt a live session builds: one
real session -- a request, a long turn kept on a task list and compacted twice
by taskcut, the `Continue.` it submits, a question after -- with a recorder
plugin (`replaycheck/`) beside taskcut that writes, at every step, the judge's
prompt as taskcut builds it from what the engine holds. The transcript is
then replayed and every step's prompt compared, character for character.

It is not a formality. Its first run matched 2 steps of 18: the engine holds a
response a block at a time and already holds the step, and its tools' results
when they have run, when the step is judged -- so taskcut's judge had been
reading every step twice -- and after a compaction the engine keeps the latest
messages whole after the summary, which the replay had dropped. Both are
fixed, and it matches every step.

### The harness's own tests

`make eval-test` runs, for the replay: the parser against a transcript written
to hold every case (a response split over records, a compaction and its
preserved messages, a plugin's prompt, a sub-agent, a message nobody sent);
which steps are judged, against register.ts's rule; the scorer against judges
whose answers are known -- one always right, one always SAME, one always NEXT,
one that changes its mind between repeats -- which must score exactly what they
must; the intervals; the replay check against records it must accept and
records it must reject; and, for the committed sets, that their labels cover
exactly the steps taskcut judges and that they hold no home directory. Where
Python mirrors the plugin (the read-only tools, the debug line's format), a
test runs the plugin's own TypeScript under node and compares.

## Checks

A probe asks the model what it remembers, which is the easiest thing it does. A
**check** is a shell assertion run against the finished workspace: exit zero
passes, and it asks the work whether it holds together. Checks run once, right
after the session while the workspace is still as the session left it, and
their verdicts are stored beside the transcript so every later report reads a
record rather than re-running anything.

Every check ships verified in both directions -- against a reference
implementation that should pass it, and against a deliberately broken one that
should fail it. This is not ceremony. Writing those controls is what found that
`build` passed a version in which a module redefined the shared record type,
and that `audit` had put its tests in `tests/`, which in a Flask checkout is
Flask's own suite. A check nobody has watched fail is not evidence.

## Probes

Every probe is asked after the work is finished, and the prompt says nothing
about whether to use a tool: whether the model goes back to the source **is** the
measurement.

Probes come in two kinds, and the split is the point:

* **`headline`** -- the fact was asked for during the work, so any reasonable
  conclusion carries it. An arm that cuts should hold accuracy here for free.
* **`incidental`** -- the fact was in the material and was never mentioned. Only
  the transcript held it. This is what a cut actually throws away, and the
  honest question is what recovering it costs.

`make eval-verify` refuses a probe whose answer is not in the material, because
such a probe grades every arm as wrong and silently removes itself from the
comparison.

## Reading the output

`weighted input` is in base-input-token equivalents: a cache write costs about
1.25 of a base input token and a cache read about 0.1. Adding the three input
counters together -- the number people usually quote -- bills cached tokens at
full price and overstates a long session several times over. Both are printed.

The `judge` columns are taskcut's own calls, in the same units for the judge's
model. They are in neither the transcript nor Claude Code's cost ledger, so the
harness runs every session with `--debug-file`, sums the record at the end of
each judgement line (`[judge sonnet: in=… cache_read=… cache_write=… out=…
ms=…]`) and keeps the sums in `results/<run>.judging.json`, beside the
transcript. A `-` there is a run recorded before taskcut logged them, not a
run that made none. The debug log itself stays in the scratch directory: it is
large and full of absolute paths.

`context carried into each turn` is `cache_read + cache_write` on the first
request of a turn. It has to be both: a cut invalidates the cache past the tool
definitions, so most of what an arm that cuts carries arrives as a write, and
counting the read alone makes it look emptier than it is.

`went to disk` is the count of probes the model could not answer without
running a tool. For an arm that cuts, this is the price of the cut, stated in
the only currency that matters.

## What has been found so far

See [../docs/measurement.md](../docs/measurement.md).
