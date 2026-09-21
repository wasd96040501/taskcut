/**
 * What the judge reads, as a pure function of plain data. A hooks module may
 * only pass `$` to a function declared in the same file, never across an
 * import, which is why the code that fetches these inputs lives in register.ts.
 *
 * The inputs follow auto mode's permission classifier, which decides from a
 * portion of the transcript rather than all of it: the person's messages, the
 * assistant's tool calls other than read-only lookups, and CLAUDE.md, with every
 * tool result stripped. To that the judge adds the one thing it is judging, the
 * reply the assistant just stopped on -- as the classifier adds the pending
 * action.
 */

import type { SessionMessage } from 'claude-code'

/** What the judge answers with. */
export const FINISHED = 'finished'
export const UNFINISHED = 'unfinished'

/**
 * Lookups that change nothing. The permission classifier leaves out "tool
 * calls other than read-only lookups such as file reads and searches"; what
 * the assistant read says nothing about whether the work is done.
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
export const REPLY_LIMIT = 4_000
/** How much of the conversation, all told, before the oldest of it is left out. */
export const CONVERSATION_LIMIT = 40_000

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
 * Everything the judge is shown. The conversation is cut from the front when
 * it runs long: whether the work that was just asked for is done lives at the
 * end of it.
 */
export function judgeText(messages: readonly SessionMessage[], reply: string, memory: readonly string[]): string {
  const lines = conversationLines(messages)
  const kept: string[] = []
  let size = 0
  for (let i = lines.length - 1; i >= 0; i--) {
    size += lines[i]!.length + 1
    if (size > CONVERSATION_LIMIT) break
    kept.unshift(lines[i]!)
  }
  const omitted = lines.length - kept.length
  return [
    'Below is a conversation between a person and an assistant: what the person said and what',
    'the assistant did, without the output of anything it ran. The assistant has just stopped',
    'on the reply at the end.',
    '',
    `Answer "${FINISHED}" if the work the person most recently asked for is done and the reply`,
    'reports it, so that the files the assistant read and the output of the commands it ran',
    `are no longer needed. Answer "${UNFINISHED}" if the assistant is asking a question, waiting`,
    'for a decision, reporting partial progress, or proposing work it has not done yet.',
    ...(memory.length > 0 ? ['', '--- project instructions (CLAUDE.md) ---', ...memory.map((m) => head(m.trim(), MEMORY_LIMIT))] : []),
    '',
    '--- conversation ---',
    ...(omitted > 0 ? [`[${omitted} earlier line(s) left out]`] : []),
    ...kept,
    '',
    '--- reply ---',
    tail(reply.trim(), REPLY_LIMIT) || '(empty)',
  ].join('\n')
}
