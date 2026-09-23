# Where the labellers disagreed

Every set was labelled three times, independently and blind: once by the
author of the labels as first committed (`first`), and once each by two
annotators (`A`, `B`: Claude Sonnet 5, each given only LABELS.md and the
sheets `make eval-replay-sheet` prints, never another's labels). Cohen's
kappa over the 257 steps: first/A 0.87, first/B 0.89, A/B 0.91.

A step on which they did not all agree takes the label two of the three
gave; where all three differ, E -- a step people disagree about is what E is
for. 10 labels changed. The steps, with the annotators' reasons:

| step | first | A | B | now | the step |
| --- | --- | --- | --- | --- | --- |
| click-zh--on#51 | E | S | N | E | Issue 13 is committed. Now issue 14: I'm reading `echo_via_pager`. — A: continues reading echo_via_pager for issue 14, already begun; B: Issue 13 committed, starting Issue 14 |
| sqlglot-long--default#14 | E | S | E | E | Issue 1 done (the long lines are pre-existing). Let me set up a regression-check script that diffs the full-s… — A: issue 1 done; building a regression-check tool, not yet issue 2; B: Issue 1 done, building/running regression-check checkpoint |
| sqlglot-long--default#65 | E | S | E | E | Part (a) passes. Now parts (b)/(c). Let me look at how `Dot` is annotated and `meta_get`'s cost, since the an… — A: implementing part (a) of issue 8, moving to parts (b)/(c); B: Issue 8 part (a) passes, moving to parts (b)/(c) of same issue |
| sqlglot-long--default#73 | E | S | E | E | All Issue 8 tests pass. Running the full-suite regression check now. — A: issue 8 tests pass; running full-suite regression check; B: Issue 8 tests pass, running full-suite regression checkpoint |
| sqlglot-long--default#109 | E | S | E | E | Issue 13 passes. Quick check whether that moved the mystery `test_tpcds` failure: — A: issue 13 passes; checking the tpcds mystery failure; B: Issue 13 passes, checkpointing the tpcds mystery failure |
| sqlglot-long--default#146 | S | S | N | S | Most cases are fixed; the two `NOT p // 'x'` cases still lose their parentheses somewhere. Let me trace where. — A: debugging remaining issue 20 cases; B: Issue 19 done, on to Issue 20 |
| sqlglot-long--default#150 | N | N | S | N | Issue 20's cases are all fixed (the one remaining `test_simplify` failure is Issue 27's). Now Issue 21 (`push… — A: issue 20 done, starts issue 21 (pushdown_projections); compacts here; B: fixing literal-paren unwrapping gap, still Issue 20 |
| sqlglot-long--default#163 | E | S | S | **S** | I'm on Issue 22. `replace_aliases` swaps in the aliased expression bare, so I'll wrap operator expressions in… — A: implementing the fix for issue 22; B: implementing alias-paren wrapping, mid Issue 22 work |
| sqlglot-long--default#176 | E | E | S | E | Both target tests pass. I'll run the full-suite regression check, since this changes where CUBE, ROLLUP and G… — A: full-suite regression check for issues 23/32, before issue 24; B: Issues 23/32 pass, running full-suite regression check |
| sqlglot-long--default#177 | E | S | S | **S** | No new failures against baseline, and both Issue 23/32 tests no longer appear in the remaining list. I'll che… — A: further checking (line lengths) after the checkpoint; B: still checking added line lengths after Issues 23/32 |
| sqlglot-long--default#196 | E | S | E | E | I'm on Issue 26. I'll look at exactly which `test_scope` assertion and which canonicalize fixture fail, then … — A: continuing issue 26 investigation; B: first sampled step of Issue 26 after silent transition |
| sqlglot-long--off#25 | E | S | S | **S** | Oracle test passes. I'll tweak the helper to print only failures that weren't in the baseline, so regressions… — A: running full suite after issue 2's fix, checking regressions; B: Oracle test passes, tweaking helper before continuing |
| sqlglot-long--off#67 | E | S | E | E | Part A passes (Redshift inherits from Postgres). Now part B: preserving the case of dot parts into semi-struc… — A: implementing part B of issue 8, same piece; B: Issue 8 part A passes, moving to part B of same issue |
| sqlglot-long--off#81 | N | E | E | **E** | Issues 9 and 10 are done. I'll run the full suite as a checkpoint before Issue 11 (pipe syntax `__tmp` CTEs). — A: full-suite checkpoint after issues 9-10, before issue 11; B: Issues 9-10 done, full-suite checkpoint before Issue 11 |
| sqlglot-long--off#82 | E | N | N | **N** | No regressions from Issues 1–10. Issue 11: pipe syntax CTE collisions. — A: checkpoint clean, starts issue 11 (pipe syntax CTEs); B: checkpoint clean, on to Issue 11 |
| sqlglot-long--off#122 | E | S | S | **S** | Both pass now. To avoid misreading tail output again, I'll build a checker that runs each issue's exact liste… — A: building a per-issue test checker, still verifying issue 15; B: regression fixed, building per-issue test checker |
| dev-1bb1d249#44 | N | S | S | **S** | (an unpublished session) |
| dev-1bb1d249#67 | E | S | S | **S** | (an unpublished session) |
| dev-1bb1d249#104 | E | S | S | **S** | (an unpublished session) |
| dev-1bb1d249#108 | E | S | N | E | (an unpublished session) |
| dev-1bb1d249#189 | E | S | S | **S** | (an unpublished session) |
