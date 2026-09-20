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
make eval-run WORKLOAD=flask ARM=off
make eval-run WORKLOAD=flask ARM=boundary
make eval-report
make eval-test            # the harness's own tests
```

`make eval-run` materialises the workspace, bakes the arm's settings into a
copy of the plugin, drives the session, and copies the transcript into
`results/`. Raw transcripts are not committed: they are large and full of
absolute paths.

Run each pair several times. Model behaviour varies enough that one pair shows
the shape of a difference, not its size.

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

**`audit`** -- five steps researching a real Flask checkout, then five building
a standard-library tool that finds configuration key reads, run against that
same checkout. The answer is exact and computable -- 30 keys, 42 reads, under a
counting rule the briefing fixes -- so the tool either agrees with the source or
it does not. The output format changes at step nine, invalidating what step
seven built.

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

`context carried into each turn` is `cache_read + cache_write` on the first
request of a turn. It has to be both: a cut invalidates the cache past the tool
definitions, so most of what an arm that cuts carries arrives as a write, and
counting the read alone makes it look emptier than it is.

`went to disk` is the count of probes the model could not answer without
running a tool. For an arm that cuts, this is the price of the cut, stated in
the only currency that matters.

## What has been found so far

See [../docs/measurement.md](../docs/measurement.md).
