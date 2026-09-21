/**
 * The ledger and the keep-set rule: everything here is a pure function of plain
 * data, so none of it takes the engine interface. A hooks module may only pass
 * `$` to a function declared in the same file, never across an import, which is
 * why the code that touches the engine all lives in register.ts.
 */

import type { SessionMessage } from 'claude-code'

/** One piece of finished work: what it was, and what came of it. */
export type Entry = {
  /** The work in one line: the request, or the sub-task as the model named it. */
  task: string
  /** The model's answer for it, or the conclusion it wrote when it closed it. */
  outcome: string
  /** When the cut that recorded it happened, in milliseconds since the epoch. */
  at: number
}

/** The name the model calls taskcut's tool by. */
export const CLOSE_TOOL = 'mcp__taskcut__close_task'

/**
 * The engine's tool for loading a deferred tool's schema. The model calls it
 * before its first `close_task` after every cut, which is loading a tool, not
 * doing work.
 */
export const TOOL_SEARCH = 'ToolSearch'

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

/** The prompt that folds a run of finished work into one durable record. */
export function foldPrompt(entries: readonly Entry[]): string {
  return [
    'These are finished pieces of one long job, oldest first. Write the shortest',
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
    task: `${folded.length} earlier pieces of work, folded`,
    outcome: rolled.trim(),
    at: folded[folded.length - 1]?.at ?? 0,
  }
}

/**
 * How a ledger message begins. The ledger is a user message, so the keep-set
 * rule has to be able to tell it from a human turn: an old ledger kept as though
 * someone had typed it would sit beside the new one and say everything twice.
 */
export const LEDGER_HEADER = '[taskcut]'

/** Whether a message is the ledger an earlier cut left in place. */
export function isLedgerMessage(message: SessionMessage): boolean {
  return message.role === 'user' && message.text.startsWith(LEDGER_HEADER)
}

/**
 * The message that stands in for everything the cut dropped. It has to carry
 * state and not just findings: a ledger that lists what was learned without
 * saying the work is done reads as an open to-do list, and the model redoes it.
 */
export function renderLedger(ledger: readonly Entry[]): string {
  if (ledger.length === 0) return `${LEDGER_HEADER} Nothing earlier in this conversation has been recorded.`
  return [
    `${LEDGER_HEADER} The working context of ${ledger.length} earlier piece(s) of work was dropped from`,
    'this conversation. This is what each was and what came of it:',
    '',
    ledger.map((entry, i) => `${i + 1}. [CLOSED] ${entry.task}\n   ${entry.outcome}`).join('\n'),
    '',
    'That work is finished. Do not redo it; continue from here.',
  ].join('\n')
}

/** How much of a request the ledger names it by. The request itself is kept whole, or already gone. */
export const HEADLINE_LIMIT = 200

/** A request in one line: its first non-blank line, clipped. */
export function headline(text: string): string {
  const line = text.split('\n').find((candidate) => candidate.trim() !== '')?.trim() ?? ''
  return line.length <= HEADLINE_LIMIT ? line : `${line.slice(0, HEADLINE_LIMIT)}...`
}

/**
 * The ledger entries for everything finished since the last cut, read from the
 * transcript the cut is about to replace.
 *
 * One entry per request that got an answer. The answer is what the model said
 * after its last piece of work in that turn -- the conclusion, not the
 * narration on the way, which was about the working context being dropped.
 * Loading a tool and closing the task are not work, so a conclusion given
 * before either is still the conclusion.
 *
 * Where the model closed a sub-task with a written `outcome` (the `outcome`
 * setting), that is what it chose to carry forward, and it is kept instead.
 *
 * Every request is covered, closed or not. `close_task` is only offered once
 * the context is past the floor, so the work before that was never closed --
 * and without an entry, the first cut would erase any record of it.
 *
 * A request an earlier cut kept stands in the transcript with nothing after
 * it: its answer went with that cut, into the ledger. It yields nothing here,
 * so nothing is recorded twice.
 */
export function finishedWork(messages: readonly SessionMessage[], at: number): Entry[] {
  const entries: Entry[] = []
  let asked: string | undefined
  let conclusion: string[] = []
  let outcomes: Entry[] = []
  const notWork = new Set<string>()

  const close = () => {
    if (asked === undefined) return
    if (outcomes.length > 0) entries.push(...outcomes)
    else if (conclusion.length > 0) entries.push({ task: headline(asked), outcome: conclusion.join('\n\n'), at })
  }

  for (const message of messages) {
    if (message.role === 'user' && (message.toolResults?.length ?? 0) === 0) {
      close()
      asked = isLedgerMessage(message) ? undefined : message.text
      conclusion = []
      outcomes = []
      continue
    }
    if (message.role === 'user') {
      // The result of a piece of work: what was said before it was narration.
      if ((message.toolResults ?? []).some((result) => !notWork.has(result.tool_use_id))) conclusion = []
      continue
    }
    if (message.text.trim()) conclusion.push(message.text.trim())
    for (const use of message.toolUses) {
      if (use.tool !== CLOSE_TOOL && use.tool !== TOOL_SEARCH) continue
      notWork.add(use.tool_use_id)
      const written = typeof use.input['outcome'] === 'string' ? use.input['outcome'].trim() : ''
      if (use.tool === CLOSE_TOOL && written) {
        const named = typeof use.input['task'] === 'string' ? use.input['task'].trim() : ''
        outcomes.push({ task: named || headline(asked ?? ''), outcome: written, at })
      }
    }
  }
  close()
  return entries
}

/** What the judge answers with. */
export const FINISHED = 'finished'
export const UNFINISHED = 'unfinished'

/**
 * How much of a request and of an answer the judge reads. The end of an answer
 * is where a model says whether it is done or asks what to do next, so an
 * answer is clipped from the front.
 */
export const JUDGE_REQUEST_LIMIT = 2_000
export const JUDGE_ANSWER_LIMIT = 4_000

/**
 * What the judge is shown: the request, the answer, and the question. It
 * reads no transcript, so a turn that read a whole codebase costs the same to
 * judge as one that read nothing.
 */
export function judgeText(request: string, answer: string): string {
  const asked = request.length <= JUDGE_REQUEST_LIMIT ? request : `${request.slice(0, JUDGE_REQUEST_LIMIT)} [...]`
  const said = answer.length <= JUDGE_ANSWER_LIMIT ? answer : `[...] ${answer.slice(-JUDGE_ANSWER_LIMIT)}`
  return [
    'A person asked an assistant for something, and the assistant has just stopped and replied.',
    `Answer "${FINISHED}" if the work that was asked for is done and the reply reports it, so that`,
    'the files it read and the commands it ran are no longer needed. Answer',
    `"${UNFINISHED}" if the assistant is asking a question, waiting for a decision, reporting`,
    'partial progress, or proposing work it has not done yet.',
    '',
    '--- request ---',
    asked.trim() || '(empty)',
    '',
    '--- reply ---',
    said.trim() || '(empty)',
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
  return messages.filter(
    (message) => message.role === 'user' && (message.toolResults?.length ?? 0) === 0 && !isLedgerMessage(message),
  )
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
