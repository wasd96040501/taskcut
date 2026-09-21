/**
 * What the judge reads, and how its answer is read back, as pure functions of
 * plain data. A hooks module may only pass `$` to a function declared in the
 * same file, never across an import, which is why the code that fetches these
 * inputs lives in register.ts.
 *
 * The inputs follow auto mode's permission classifier, which decides from a
 * portion of the transcript rather than all of it: the person's messages, the
 * assistant's tool calls other than read-only lookups, and CLAUDE.md, with every
 * tool result stripped. To that the judge adds the one thing it is judging, the
 * step the assistant just made -- as the classifier adds the pending action.
 */

import type { SessionMessage } from 'claude-code'

/** The two answers the judge gives, as it writes them. */
export const DONE = 'DONE'
export const WORKING = 'WORKING'

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
/** How much of the conversation, all told, before the oldest of it is left out. */
export const CONVERSATION_LIMIT = 40_000
/** Room for one sentence and the verdict. */
export const ANSWER_TOKENS = 300

/**
 * The step being judged: what the assistant just said, and the calls it is
 * making now. No calls means it stopped and handed back to the person.
 */
export type Step = {
  text: string
  calls: readonly { name: string; input: unknown }[]
}

/**
 * The question. One sentence of reasoning before the verdict is what makes a
 * small answer reliable: asked for the word alone, the judge reads "starting
 * the next task" as "working" and misses the boundary it was asked to find.
 */
export const JUDGE_SYSTEM = [
  'You watch an assistant working through what a person asked for. You are shown what the person',
  "said, the commands the assistant ran (not their output), the project's instructions if it has",
  'any, and the latest step: what the assistant just said, and either the calls it is making now',
  'or that it stopped and handed back to the person.',
  '',
  'Decide whether the latest step reports that a piece of the work has just been completed. A piece',
  'is one of the things the person asked for -- one task in a list, one fix, one feature, one',
  'question answered -- or one clearly separate phase of a single task.',
  '',
  'Apply these rules in order, and stop at the first that fits:',
  `1. The step ends by asking the person something, waiting for their decision, or proposing work`,
  `   it has not done: ${WORKING}. This holds even when asking is exactly what the person told it to`,
  '   do, because their answer carries the same piece on.',
  `2. The step says a piece is complete (checked, where it could be checked): ${DONE}. It does not`,
  '   matter whether the assistant is already starting the next piece in the same step.',
  `3. Anything else -- reading, editing, running or fixing things for a piece it has not said is`,
  `   complete: ${WORKING}.`,
  '',
  `First say in one sentence what the latest step does. Then, on its own last line, write ${DONE} or ${WORKING}.`,
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
  if (last?.role !== 'assistant' || step.calls.length === 0) return messages
  const same =
    last.toolUses.length === step.calls.length &&
    last.toolUses.every((use, i) => use.tool === step.calls[i]!.name && JSON.stringify(use.input) === JSON.stringify(step.calls[i]!.input))
  return same ? messages.slice(0, -1) : messages
}

/**
 * Everything the judge is shown. The conversation is cut from the front when
 * it runs long: whether a piece of work just ended lives at the end of it.
 */
export function judgePrompt(messages: readonly SessionMessage[], step: Step, memory: readonly string[]): string {
  const lines = conversationLines(beforeStep(messages, step))
  const kept: string[] = []
  let size = 0
  for (let i = lines.length - 1; i >= 0; i--) {
    size += lines[i]!.length + 1
    if (size > CONVERSATION_LIMIT) break
    kept.unshift(lines[i]!)
  }
  const omitted = lines.length - kept.length
  return [
    ...(memory.length > 0 ? ['--- project instructions (CLAUDE.md) ---', ...memory.map((m) => head(m.trim(), MEMORY_LIMIT)), ''] : []),
    '--- conversation ---',
    ...(omitted > 0 ? [`[${omitted} earlier line(s) left out]`] : []),
    ...kept,
    '',
    '--- latest step ---',
    tail(step.text.trim(), STEP_LIMIT) || '(no text)',
    ...(step.calls.length > 0
      ? step.calls.map((call) => `Calls ${call.name}: ${head(JSON.stringify(call.input), CALL_LIMIT)}`)
      : ['(stopped here and handed back to the person)']),
  ].join('\n')
}

/**
 * Whether the judge's answer says a piece is done: its last line, stripped of
 * the emphasis a model sometimes puts round it. Anything else, including no
 * answer, is not.
 */
export function saysDone(answer: string): boolean {
  const lines = answer.trim().split('\n')
  const last = lines[lines.length - 1] ?? ''
  return last.replace(/[^A-Za-z]/g, '').toUpperCase() === DONE
}
