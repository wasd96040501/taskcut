# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

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

[Unreleased]: https://github.com/wasd96040501/taskcut/compare/v0.2.0...HEAD
[0.2.0]: https://github.com/wasd96040501/taskcut/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/wasd96040501/taskcut/releases/tag/v0.1.0
