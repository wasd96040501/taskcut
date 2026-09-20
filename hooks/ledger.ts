/**
 * The ledger and the keep-set rule: everything here is a pure function of plain
 * data, so none of it takes the engine interface. A hooks module may only pass
 * `$` to a function declared in the same file, never across an import, which is
 * why the code that touches the engine all lives in register.ts.
 */

import type { SessionMessage } from 'claude-code'

/** One finished sub-task, as the model closed it. */
export type Entry = {
  /** The sub-task in one line, as the model named it. */
  task: string
  /** What the model wrote down to carry forward; the only thing that survives the cut. */
  outcome: string
  /** When it was closed, in milliseconds since the epoch. */
  at: number
}

/**
 * Which entries to fold and which to keep verbatim, or null when the ledger is
 * still short enough to leave alone. The oldest are folded so that the entries
 * a next step is most likely to need stay in the model's own words.
 */
export function planFold(ledger: readonly Entry[], verbatim: number): { fold: Entry[]; keep: Entry[] } | null {
  if (ledger.length <= verbatim) return null
  const boundary = ledger.length - Math.floor(verbatim / 2)
  return { fold: ledger.slice(0, boundary), keep: ledger.slice(boundary) }
}

/** The prompt that folds a run of finished sub-tasks into one durable record. */
export function foldPrompt(entries: readonly Entry[]): string {
  return [
    'These are finished sub-tasks of one long job, oldest first. Write the shortest',
    'record a worker resuming this job would still need: decisions that still bind,',
    'paths, names, numbers, and anything later work must not contradict. Drop',
    'everything a later entry superseded. No preamble.',
    '',
    entries.map((entry, i) => `${i + 1}. ${entry.task}\n   ${entry.outcome}`).join('\n'),
  ].join('\n')
}

/** The entry a fold collapses a run of entries into. */
export function foldedEntry(folded: readonly Entry[], rolled: string): Entry {
  return {
    task: `${folded.length} earlier sub-tasks, folded`,
    outcome: rolled.trim(),
    at: folded[folded.length - 1]?.at ?? 0,
  }
}

/**
 * The message that stands in for everything the cut dropped. It has to carry
 * state and not just findings: a ledger that lists what was learned without
 * saying the work is done reads as an open to-do list, and the model redoes it.
 */
export function renderLedger(ledger: readonly Entry[]): string {
  if (ledger.length === 0) return 'No sub-tasks have been closed yet.'
  return [
    `The working context of ${ledger.length} closed sub-task(s) was dropped from this`,
    'conversation. This is what they established:',
    '',
    ledger.map((entry, i) => `${i + 1}. [CLOSED] ${entry.task}\n   ${entry.outcome}`).join('\n'),
    '',
    'Those sub-tasks are finished. Do not redo them; continue from here.',
  ].join('\n')
}

/** How long a ledger left behind by a session that never ended cleanly is kept. */
export const STALE_LEDGER_MS = 7 * 24 * 60 * 60 * 1000

/** The store key prefix every ledger is written under. */
export const LEDGER_PREFIX = 'ledger:'

/**
 * Which stored ledgers to drop. `session.end` removes a ledger when a session
 * exits cleanly, but a session that is killed never reaches it, and the plugin
 * store has a hard size limit: without a sweep, a machine that loses sessions
 * abruptly accumulates ledgers until writes start failing. The current session's
 * own key is never swept, however old its newest entry is.
 */
export function staleLedgerKeys(
  entriesByKey: ReadonlyMap<string, readonly Entry[]>,
  currentKey: string,
  now: number,
): string[] {
  const stale: string[] = []
  for (const [key, entries] of entriesByKey) {
    if (key === currentKey || !key.startsWith(LEDGER_PREFIX)) continue
    const newest = entries.reduce((max, entry) => Math.max(max, entry.at), 0)
    if (now - newest > STALE_LEDGER_MS) stale.push(key)
  }
  return stale
}

/**
 * A user message that carries tool_result blocks is the answer to the assistant
 * message that made the calls. Dropping one half of that pair leaves a
 * conversation the API refuses, so the keep-set is defined in terms of the user
 * turns that carry no tool_result: taking those alone drops both halves of every
 * pair together.
 */
export function humanTurnsOf(messages: readonly SessionMessage[]): SessionMessage[] {
  return messages.filter((message) => message.role === 'user' && (message.toolResults?.length ?? 0) === 0)
}

/**
 * Human turns are themselves unbounded: a job that runs for days adds one per
 * iteration, so keeping every one of them only moves the growth. The turn that
 * set the standing task is kept because nothing else records the goal; of the
 * rest, only the most recent few, because the ledger records the others.
 */
export function boundedHumanTurns(messages: readonly SessionMessage[], recent: number): SessionMessage[] {
  const turns = humanTurnsOf(messages)
  if (turns.length <= recent + 1) return turns
  return [turns[0]!, ...turns.slice(-recent)]
}
