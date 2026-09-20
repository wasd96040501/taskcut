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

/**
 * How much of a dropped transcript the directed extractor is shown. A tool
 * result can be an entire file, and the extractor is paid for by the token, so
 * the transcript is trimmed rather than sent whole. Trimming loses the tail of
 * a long result, which is the trade the mode makes: a cheaper reader that saw
 * most of the work, against an expensive one that saw all of it.
 */
export const DIRECTED_RESULT_LIMIT = 20_000
export const DIRECTED_TOTAL_LIMIT = 120_000

/** The messages a cut is about to drop: everything the keep-set rule did not take. */
export function droppedMessages(
  all: readonly SessionMessage[],
  kept: readonly SessionMessage[],
): SessionMessage[] {
  const keptSet = new Set<SessionMessage>(kept)
  return all.filter((message) => !keptSet.has(message))
}

/**
 * The standing task: the first human turn, which is the only record of what the
 * whole job is for. A directed extraction is directed at this and nothing else.
 */
export function standingTask(messages: readonly SessionMessage[]): string {
  return humanTurnsOf(messages)[0]?.text?.trim() ?? ''
}

function clip(text: string, limit: number): string {
  return text.length <= limit ? text : `${text.slice(0, limit)}\n[... ${text.length - limit} characters omitted]`
}

/** A dropped transcript as plain text, for a model that was not in the conversation. */
export function renderDropped(messages: readonly SessionMessage[]): string {
  const parts: string[] = []
  for (const message of messages) {
    if (message.text?.trim()) parts.push(`${message.role}: ${message.text.trim()}`)
    for (const use of message.toolUses ?? []) {
      const result = typeof use.text === 'string' ? use.text : ''
      parts.push(`${message.role} ran ${use.tool}:\n${clip(result, DIRECTED_RESULT_LIMIT)}`)
    }
    for (const result of message.toolResults ?? []) {
      if (result.text) parts.push(clip(result.text, DIRECTED_RESULT_LIMIT))
    }
  }
  return clip(parts.join('\n\n'), DIRECTED_TOTAL_LIMIT)
}

/**
 * The prompt that writes a ledger entry from the work itself rather than from
 * the working model's own account of it.
 *
 * The difference is what the writer knows. A model closing its own sub-task is
 * told that nothing else will survive, and answers that by writing down
 * everything it noticed, which is a poor conclusion and a large one. This
 * writer is not under that pressure and has something the other did not: the
 * standing task, against which most of what happened is irrelevant.
 *
 * It says what the situation is and stops. A list of rules about what to keep
 * and what to drop would decide in advance the very thing the mode exists to
 * test -- whether a model given the job and the work can judge for itself what
 * matters -- and a writer following a checklist produces an inventory, which is
 * the failure the mode is meant to avoid.
 */
export function directedPrompt(task: string, subTask: string, dropped: string): string {
  return [
    'A long job is in progress. This is the standing task, in the words of the',
    'person who set it:',
    '',
    task || '(the standing task was not recorded)',
    '',
    `A sub-task of it has just finished: ${subTask}`,
    '',
    'Below is everything that happened while it was worked on. It is about to be',
    'deleted. Write what someone continuing the standing task will need.',
    '',
    '--- transcript ---',
    dropped,
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
  // `slice(-0)` is `slice(0)`, which is the whole array, so a bound of zero has
  // to be spelled out rather than fall out of the arithmetic.
  const tail = recent > 0 ? turns.slice(-recent) : []
  return [turns[0]!, ...tail]
}
