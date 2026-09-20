# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

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
- Ledger cleanup on `session.end`, and a sweep at `session.start` for ledgers
  left behind by sessions that were killed before they could end cleanly. The
  plugin store has a hard size limit, so leftovers cannot be allowed to
  accumulate.

[Unreleased]: https://github.com/wasd96040501/taskcut/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/wasd96040501/taskcut/releases/tag/v0.1.0
