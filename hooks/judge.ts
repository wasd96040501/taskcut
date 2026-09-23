/**
 * What the judge reads, and how its answer is read back, as pure functions of
 * plain data. A hooks module may only pass `$` to a function declared in the
 * same file, never across an import, which is why the code that fetches these
 * inputs lives in register.ts.
 *
 * The inputs follow auto mode's permission classifier, which decides from a
 * portion of the transcript rather than all of it: the person's messages, the
 * assistant's tool calls other than read-only lookups, and CLAUDE.md, with every
 * tool result stripped. To that the judge adds the one thing it is judging --
 * the step the assistant is taking -- as the classifier adds the pending action.
 *
 * Like the classifier, the judge reads the whole of that portion, never a
 * window of it, and in the same order every time: CLAUDE.md, then the
 * conversation oldest first, then the step. Each judgement's prompt therefore
 * begins with the whole of the one before it, which is the prefix a prompt
 * cache can serve. (`$.model.complete` marks no cache point as of 2.1.280; the
 * classifier builds its own request and marks one after the transcript.)
 */

import type { SessionMessage } from 'claude-code'

/**
 * The two answers the judge gives, as it writes them: the work moves on from a
 * finished piece to another, or it stays where it is.
 */
export const NEXT = 'NEXT'
export const SAME = 'SAME'

/**
 * Lookups that change nothing. The permission classifier leaves out "tool
 * calls other than read-only lookups such as file reads and searches"; what
 * the assistant read says nothing about whether a piece of work is done.
 */
export const READ_ONLY_TOOLS: ReadonlySet<string> = new Set([
  'Read',
  'Grep',
  'Glob',
  'LS',
  'NotebookRead',
  'WebSearch',
  'ToolSearch',
])

/** How much of each piece the judge reads. */
export const MESSAGE_LIMIT = 2_000
export const CALL_LIMIT = 500
export const MEMORY_LIMIT = 4_000
export const STEP_LIMIT = 4_000
/** Room for one sentence and the verdict. */
export const ANSWER_TOKENS = 300

/**
 * What is judged: a step the assistant takes inside a turn -- what it just
 * said, and the calls it is making now.
 */
export type Step = { text: string; calls: readonly { name: string; input: unknown }[] }

/**
 * The question. A compaction pays for itself only when the work moves on to a
 * piece that does not need the detail of the one before, so that is what is
 * asked -- not whether a piece is done. The last piece of a list is done, and
 * nothing follows it yet: whatever the person says next may well be about it.
 *
 * One sentence of reasoning before the verdict is what makes a small answer
 * reliable: asked for the word alone, the judge reads "task 2 is done; now task
 * 3" as the same work and misses the boundary it was asked to find.
 */
export const JUDGE_SYSTEM = [
  'You watch an assistant working through what a person asked for. You are shown what the person',
  "said, the commands the assistant ran (not their output), the project's instructions if it has",
  'any, and the latest step the assistant is taking: what it just said and the calls it is making now.',
  '',
  'The conversation may open with a summary Claude Code wrote when it compacted what came before: it',
  'is a record of past work, not a request.',
  '',
  'Decide whether, at this step, the work moves on from a finished piece to another piece. A piece',
  'is one of the things the person asked for -- one task in a list, one fix, one feature, one',
  'question answered -- or one clearly separate phase of a single task.',
  '',
  'Apply these rules in order, and stop at the first that fits:',
  `1. The step asks the person something, waits for their decision, or proposes work it has not`,
  `   done: ${SAME}.`,
  `2. The step itself says, in its own words, that a piece is complete (checked, where it could be`,
  `   checked), and another piece the person asked for is still to do -- the step names or starts`,
  `   it, or the person's request plainly lists more: ${NEXT}. A piece finished before this step,`,
  `   whatever came after it, does not count.`,
  `3. Anything else: ${SAME}. That includes the last piece asked for being complete, wrapping up`,
  '   once every piece is done (a final check, a summary, a commit), and work on a piece not yet',
  '   said to be complete.',
  '',
  `First say in one sentence what the step does. Then, on its own last line, write ${NEXT} or ${SAME}.`,
].join('\n')

function head(text: string, limit: number): string {
  return text.length <= limit ? text : `${text.slice(0, limit)} [...]`
}

function tail(text: string, limit: number): string {
  return text.length <= limit ? text : `[...] ${text.slice(-limit)}`
}

/**
 * The conversation as the judge reads it: what the person said and what the
 * assistant did, oldest first, with no tool output anywhere in it.
 */
export function conversationLines(messages: readonly SessionMessage[]): string[] {
  const lines: string[] = []
  for (const message of messages) {
    if (message.role === 'user') {
      // A user message carrying tool results is the output of a call, not
      // something the person said.
      if ((message.toolResults?.length ?? 0) > 0 || !message.text.trim()) continue
      lines.push(`Person: ${head(message.text.trim(), MESSAGE_LIMIT)}`)
      continue
    }
    for (const use of message.toolUses) {
      if (READ_ONLY_TOOLS.has(use.tool)) continue
      lines.push(`Assistant ran ${use.tool}: ${head(JSON.stringify(use.input), CALL_LIMIT)}`)
    }
  }
  return lines
}

/**
 * The messages before the step. Whether the transcript already holds the step
 * when it is judged is the engine's business; if it does, it is left out here
 * so that the step's calls are not read twice.
 */
export function beforeStep(messages: readonly SessionMessage[], step: Step): readonly SessionMessage[] {
  const last = messages[messages.length - 1]
  if (last?.role !== 'assistant') return messages
  const same =
    last.toolUses.length === step.calls.length &&
    last.toolUses.every((use, i) => use.tool === step.calls[i]!.name && JSON.stringify(use.input) === JSON.stringify(step.calls[i]!.input))
  return same ? messages.slice(0, -1) : messages
}

/**
 * Whether the step is worth asking about. A step says a piece is complete or
 * it is not a boundary, so a step that says nothing is not one -- and after a
 * compaction, whose summary reads as a message saying which pieces are done, a
 * silent first step would otherwise look like the move to the next.
 */
export function judgeable(step: Step): boolean {
  return step.text.trim() !== ''
}

/**
 * Whether calls change anything. Until a step after a compaction has, nothing
 * can have been finished since it -- and the summary, which says which pieces
 * are done, makes the first step of the next one look like the move to it.
 */
export function acts(calls: readonly { name: string }[]): boolean {
  return calls.some((call) => !READ_ONLY_TOOLS.has(call.name))
}

/**
 * Everything the judge is shown: all of the conversation, as the classifier
 * reads all of its transcript. The step comes last, so that everything before
 * it is what the judgement before this one was shown, and then some.
 */
export function judgePrompt(messages: readonly SessionMessage[], step: Step, memory: readonly string[]): string {
  return [
    ...(memory.length > 0 ? ['--- project instructions (CLAUDE.md) ---', ...memory.map((m) => head(m.trim(), MEMORY_LIMIT)), ''] : []),
    '--- conversation ---',
    ...conversationLines(beforeStep(messages, step)),
    '',
    '--- latest step: what the assistant is doing now ---',
    tail(step.text.trim(), STEP_LIMIT) || '(no text)',
    ...step.calls.map((call) => `Calls ${call.name}: ${head(JSON.stringify(call.input), CALL_LIMIT)}`),
  ].join('\n')
}

/**
 * The judge's reply, whichever shape `$.model.complete` resolved: the reply's
 * text up to Claude Code 2.1.278, `{ isAnswered, text }` or
 * `{ isAnswered: false, reason }` from 2.1.280. Either is read here, where the
 * engine's answer enters, and nothing past this point knows there were two.
 */
export type Reply = { text: string } | { reason: string }

export function readReply(answer: unknown): Reply {
  if (typeof answer === 'string') return { text: answer }
  if (typeof answer === 'object' && answer !== null && 'isAnswered' in answer) {
    const { isAnswered, text, reason } = answer as { isAnswered: unknown; text?: unknown; reason?: unknown }
    if (isAnswered === true && typeof text === 'string') return { text }
    if (isAnswered === false) return { reason: String(reason) }
  }
  return { reason: 'a reply of no shape taskcut knows' }
}

/**
 * Whether the judge's answer says the work moves on: its last line, stripped
 * of the emphasis a model sometimes puts round it. Anything else, including no
 * answer, is not.
 */
export function saysNext(answer: string): boolean {
  const lines = answer.trim().split('\n')
  const last = lines[lines.length - 1] ?? ''
  return last.replace(/[^A-Za-z]/g, '').toUpperCase() === NEXT
}
