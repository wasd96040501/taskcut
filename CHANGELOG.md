# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.7.0] - 2026-09-21

### Added

- **Compaction inside a long turn.** Past the floor, each step of the main
  conversation is judged, while the step's tools run. When one finished a piece
  of the work, taskcut ends the turn before the next request, runs the same
  compaction `/compact` runs, and submits `Continue.` -- so a list of tasks
  handed over in one message is compacted between tasks, with nobody at the
  keyboard. Interactive sessions only; a `-p` run is never interrupted.

### Changed

- The judge is asked through `$.model.complete` with rules of its own, and
  writes a sentence before its verdict. A step that ends by asking the person
  something is never a boundary.
- The default judge is `sonnet`, as auto mode's permission classifier's is:
  on the same steps, `haiku` missed four boundaries in nine where `sonnet`
  missed none.
- After a compaction that leaves the context above the floor, the next
  judgement waits until the context has grown five points more.

## [0.6.0] - 2026-09-21

### Changed

- **taskcut decides when to compact, and Claude Code decides what is kept.**
  When the judge calls a turn finished, taskcut runs `$.session.compact()`, the
  same call `/compact` makes, and the compaction is Claude Code's own: same
  transcript, same summary, recorded as a typed `/compact` is. taskcut no
  longer builds a transcript of its own, keeps no ledger and writes nothing to
  the plugin store.
- The judge reads what auto mode's permission classifier reads: every message
  you sent, every tool call except read-only lookups, and `CLAUDE.md`, with all
  tool output stripped -- plus the reply being judged.

### Removed

- The `outcome` setting and `close_task`. Asking the working model for a
  conclusion meant writing it before anything had judged the work finished,
  and Claude Code's compaction already writes one after.
- The `recentHumanTurns` and `ledgerVerbatim` settings, with the ledger they
  shaped. Two settings are left: `floorPercent` and `model`.

**Upgrading:** earlier versions kept ledgers in the plugin store, and this one
no longer sweeps them. Any left behind are safe to delete:
`rm -f ~/.claude/plugins/store/taskcut*`.

## [0.5.0] - 2026-09-21

### Changed

- **Below the floor taskcut now does nothing and costs nothing.** The working
  model no longer declares boundaries with `close_task`. A tool call ends the
  model's response, so every boundary was one more request reading the whole
  context -- about 10% of a twenty-change session, measured, paid whether or
  not anything was ever cut -- and a tool, once registered, cannot be taken
  back. Instead, once the context is past `floorPercent`, one small-model call
  at the end of each finished turn reads the request and the answer and judges
  whether that work is finished, the way auto mode's classifier judges an
  action. Below the floor no model is asked, nothing is written, and the
  working model is never told taskcut exists.
- The ledger is built at the cut, from the transcript: every request answered
  since the last cut, with the answer the model gave it. Work done before the
  floor was crossed is recorded too.
- Each judgement past the floor leaves a dim line in the transcript saying what
  was decided.
- **Settings.** `foldModel` is now `model`: the same small model judges and
  folds. `ledgerMode` is replaced by `outcome` (default off): on, past the floor
  the working model is offered `close_task` and asked for a written conclusion,
  kept in place of its answer. `directed`, measured and falsified, is gone.

### Fixed

- A ledger left by an earlier cut is no longer mistaken for a human turn and
  kept beside the new one.
- A fold that cannot reach its model no longer fails the cut.

### Added

- `make eval-mechanism`: one short real session at a low floor, asserting that
  nothing happens below the floor, that a turn ending in a question is kept, that
  a finished turn is cut, that crossing again cuts again, and that what was cut
  can be recalled.
- `issues-long`, a benchmark workload of twenty real click changes, bugs and
  features, long enough for one Sonnet 5 session to reach a floor of 30%.
- The benchmark driver waits for the transcript to record the end of a turn
  instead of for the screen to go quiet, which a model thinking for a while
  could fool.

## [0.4.0] - 2026-09-21

### Removed

- **The `.taskcut` marker file and the `activation` setting are gone.** Between
  them they answered the question `--scope` had already answered, and all three
  had to be read together to know whether anything would happen. taskcut now
  runs wherever it is installed -- `--scope user` for every session on the
  machine, `--scope project` for one repository, `--scope local` for one
  repository and only you -- and `TASKCUT=0` switches off a single session.
  That is the whole rule.

  Consent is still the plugin's own and still does not rest on
  `CLAUDE_CODE_ENABLE_FUNCTION_HOOKS`. It is the install: a session that loaded
  the plugin is one someone asked for, which an early access flag flipping
  cannot manufacture.

  **Upgrading:** a `--scope user` install that relied on `.taskcut` markers now
  runs everywhere. Either reinstall per repository with `--scope project`, or
  keep the user install and put `TASKCUT=0` in the environment where you do not
  want it.

- `scripts/install.sh` and `scripts/uninstall.sh`. Two native commands do the
  same thing, and a script that wraps them is one more thing to keep correct.

### Changed

- An unrecognised `TASKCUT` value no longer switches taskcut off. A typo that
  silently disables a plugin is the failure hardest to notice.

## [0.3.0] - 2026-09-21

### Added

- A benchmark, in `eval/`, and a `Makefile` to drive it. It is built along four
  axes that do not know about each other -- workload, arm, transcript, metric --
  so adding a workload is adding a JSON file and adding a metric is adding a
  pure function. Two workloads ship: ten generated near-identical modules, which
  isolate interference from window fill, and eight modules of Flask at ordinary
  sizes. Probes are split into facts the work asked for and facts it did not,
  because only the second kind is what a cut actually throws away.
- `ledgerMode`. Under the default, `outcome`, a ledger entry is the conclusion
  the working model wrote at `close_task`. Under `directed` that is discarded
  and `foldModel` writes the entry from the transcript being dropped. What each
  one costs is measured in [docs/measurement.md](docs/measurement.md); the
  default is the default for a reason.

### Fixed

- The pending-boundary flag is read and cleared before anything that can throw.
  A turn that failed after `close_task` had run left it set, and the next turn
  to complete inherited a cut it had not earned -- discarding the transcript
  that explained the failure.
- The directed extractor is no longer told that the first human turn is the
  standing task. In a session that opens by asking for the first step it is that
  step, and a benchmark run produced a ledger entry instructing the model to
  redo a sub-task the same ledger had marked closed.

### Changed

- The floor's justification in the documentation is now the measured one. It had
  been corrected to a fidelity argument on the strength of arithmetic that
  assumed a kept set of about 3k tokens; the measurement says the kept set
  carries a per-session preamble of 12k-15k that is re-cached on every cut, so
  the original prompt-cache argument was right after all.
- Settings are documented as `--config KEY=VALUE` at install time and `/plugin`
  from a session. The documentation had named `/config`, which is a different
  command and does not configure a plugin.
- The README no longer claims the cut keeps every human turn. It keeps the
  first and the most recent `recentHumanTurns`; the rest are dropped, because
  human turns are unbounded on a long run.


## [0.2.0] - 2026-09-20

### Changed

- **taskcut now decides for itself whether it runs, and defaults to inert.**
  Activation was previously left to `CLAUDE_CODE_ENABLE_FUNCTION_HOOKS`, which
  is an early-access flag: when function hooks graduate, that flag defaults to
  on or disappears, and every installation that had relied on it would have
  become active in every session on an unrelated Claude Code release. A session
  is now active only when `activation` is `always`, a `.taskcut` marker sits at
  the project root, or `TASKCUT=1` is set; `TASKCUT=0` outranks all of them. The
  state before `session.start` runs is inert, so a missed hook fails closed.
- Installation goes through Claude Code's own plugin mechanism. The repository
  ships `.claude-plugin/marketplace.json`, so adopting it is
  `claude plugin marketplace add wasd96040501/taskcut` followed by
  `claude plugin install taskcut@taskcut --scope project`, with
  `claude plugin update` and `--config KEY=VALUE` working as they do for any
  plugin. `scripts/install.sh` now drives the same mechanism from a local path,
  for a private or air-gapped checkout, instead of copying files into the skills
  directory.

### Removed

- `scripts/bootstrap.sh`. It existed to fetch an installer through the GitHub
  CLI's credentials, on the assumption that a private repository could not be
  reached by name. `claude plugin marketplace add <owner>/<repo>` clones with the
  user's git credentials and works on a private repository unchanged, so the
  workaround was solving a problem that does not exist.

### Added

- A unit test suite for the pure modules, run by `scripts/test.sh` and in CI.
  Node 22.18+ runs the TypeScript sources directly, so it needs no build step
  and no dependencies.
- `docs/compatibility.md`: what taskcut depends on, what a Claude Code upgrade
  can break, and what the public surface is for semantic versioning.
- `.github/CODEOWNERS`.

### Fixed

- `recentHumanTurns: 0` kept the entire transcript and duplicated the first turn,
  because `slice(-0)` is `slice(0)`. Found by the new tests.
- A blank or null value in settings read as a deliberate `0`, because
  `Number(null)`, `Number('')` and `Number([])` are all `0`. A setting now has to
  actually spell a number to be used. Found by the new tests.
- A `session.compact` raised by another plugin was answered as though it were
  taskcut's own boundary cut, replacing that plugin's transcript. The hook now
  passes through anything but its own dispatch.

## [0.1.0] - 2026-09-20

### Added

- `close_task`, the tool the model calls to declare a sub-task finished and
  record the conclusion that will survive the cut.
- A deterministic `session.compact` hook: the transcript is replaced by the human
  turns, kept verbatim by their engine handles, plus one ledger message. No
  summariser call is made.
- A per-session ledger in the plugin store, keyed by session id so that two jobs
  running on one machine cannot read each other's conclusions.
- A context-fill floor (`floorPercent`, default 40) so that a cut is only made
  once the window has filled enough to be worth the prompt cache it costs.
- A bound on the human turns kept (`recentHumanTurns`, default 2, beside the
  turn that set the standing task), so the keep-set does not grow without limit
  on a long run.
- Ledger folding (`ledgerVerbatim`, default 12; `foldModel`, default `haiku`),
  so the ledger itself does not become the growth the cuts were meant to stop.
- Pass-through of the engine's own threshold compaction, with the ledger handed
  to the summariser as instructions, as the safety net for a sub-task too large
  to reach a boundary.
- `scripts/install.sh --opt-in`, which installs taskcut switched off for every
  session so that repositories enable it individually, and a "Controlling where
  it runs" section documenting both switches.
- Ledger cleanup on `session.end`, and a sweep at `session.start` for ledgers
  left behind by sessions that were killed before they could end cleanly. The
  plugin store has a hard size limit, so leftovers cannot be allowed to
  accumulate.

[Unreleased]: https://github.com/wasd96040501/taskcut/compare/v0.4.0...HEAD
[0.4.0]: https://github.com/wasd96040501/taskcut/compare/v0.3.0...v0.4.0
[0.3.0]: https://github.com/wasd96040501/taskcut/compare/v0.2.0...v0.3.0
[0.2.0]: https://github.com/wasd96040501/taskcut/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/wasd96040501/taskcut/releases/tag/v0.1.0
