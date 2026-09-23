# Labelling a replay set

Each `<set>.labels` file has one line per step taskcut would judge in that
session: the step's number, its label, and how the step starts.

    16   N  Issue 3 is done: the lineage walks both PIVOTs. Issue 4: Oracle ...

A label says what is **true** of the step, read with everything the session
shows -- the requests, what came before, the step's own words and calls, what
came after -- not what the judge could tell from what it is given. A judge
that cannot see enough to get a step right should score badly on it.

## The labels

**N -- the work moves on here.** At this step a piece of work the person asked
for is finished, and the assistant turns to another piece they asked for. A
piece is one thing in their request: one issue in a list, one task, one fix,
one question -- or a clearly separate phase of a single task ("the parser is
done; now the docs"). The N is the step where the move is made: typically "N
is done / passes; now N+1", or the first step of N+1 when the one before it
closed N.

**S -- it does not.** Everything else, and in particular:

- work inside a piece: reading, editing, running tests, a failed attempt;
- a piece that passes but is still being checked or tidied ("tests pass; let me
  also run the full suite");
- the last piece asked for finishing, and anything after it: a final check, a
  summary, a commit, a push -- nothing follows it yet;
- a status recap of pieces finished earlier;
- a step that asks the person something, or proposes work not yet asked for.

**E -- either is defensible.** Left out of both rates. Use it sparingly, for:

- a checkpoint between two pieces: "Issue 22 done. Full-suite checkpoint:"
  followed by "Clean. Issue 23:" -- the move is spread over two steps, and a
  compaction at either is right. The N goes on the step that starts the next
  piece, the E on the checkpoint before it;
- a setup phase ending (a baseline taken, then "Starting with issue 1"), where
  the setup is not a piece the person asked for but is a phase of its own;
- part A to part B of one piece, when the request does not say whether they
  are one piece or two;
- the first piece after the work silently changed subject.

A boundary is scored as a window -- the N and the E steps directly before it
-- and it is caught when the judge says NEXT at any step of the window, as live
the first NEXT compacts.

## Commits, task lists and wrap-ups

A commit after a piece is part of that piece: "Issue 4 passes. Committing."
is S. The step after it that starts issue 5 is N -- or, when one step both
commits issue 4 and starts issue 5, that step is N.

A task-list update is not a boundary on its own: "marking task 3 complete" is
S unless the same step moves on to task 4.

## How to label a new set

    make eval-replay-build TRANSCRIPT=… NAME=… SOURCE="…"   # the set, with a `?` per step
    make eval-replay-sheet SET=…                             # every judged step, with its context

Replace every `?`. `make eval-replay` refuses a set with a `?` left, a judged
step without a label, or a label on a step taskcut would not judge.

## How the labels were checked

Labels from one person are an opinion. Every set was also labelled blind, from
the same sheet and this page, by two independent annotators, and the three
compared: agreement is reported as Cohen's kappa in docs/measurement.md, and
every step the three did not all agree on was read again and settled, with
the reason, in `disagreements.md` beside this page.
