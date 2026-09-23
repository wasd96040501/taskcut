/**
 * What the judge reads, and how its answer is read back, as pure functions of
 * plain data. A hooks module may only pass `$` to a function declared in the
 * same file, never across an import, which is why the code that fetches these
 * inputs lives in register.ts.
 *
 * The judge is asked one thing -- does the work move on here from a finished
 * piece to another? -- and most of a session says nothing about it. What does,
 * in order of how much:
 *
 *  1. the step itself, which says in its own words that a piece is complete and
 *     names the next;
 *  2. what the person asked for, which says whether there is a next;
 *  3. a trail of what the assistant has been doing -- what its recent calls
 *     touched, what it said, its task list -- which says where it has got to.
 *
 * So the judge reads those and nothing else: every message the person sent,
 * the first and the latest whole and the rest cut to a line; the assistant's
 * latest messages; what its latest calls touched, a file or what a command
 * says it does, never the call in full; its task list as it last wrote it; and
 * the step. Never any tool output, and not CLAUDE.md, which says how to work
 * and not how far the work has got.
 *
 * Commands in full were nine tenths of what an earlier judge read, and the
 * reason its prompt grew with the session. Without them the prompt is a few
 * thousand tokens however long the session runs, and the judge is as right as
 * it was: see docs/measurement.md.
 */

import type { SessionMessage } from 'claude-code'

/**
 * The two answers the judge gives, as it writes them: the work moves on from a
 * finished piece to another, or it stays where it is.
 */
export const NEXT = 'NEXT'
export const SAME = 'SAME'

/**
 * Lookups that change nothing. What the assistant read says nothing about
 * whether a piece of work is done, and a step made only of them never follows
 * the finishing of one.
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

/** How many of each the judge reads, and how much of each. */
export const RECENT_REQUESTS = 3
export const REQUEST_HEAD = 1_500
export const REQUEST_TAIL = 500
export const REQUEST_LINE = 150
export const SUMMARY_HEAD = 1_500
export const SUMMARY_TAIL = 1_000
export const RECENT_SAYINGS = 10
export const SAYING_LIMIT = 400
export const RECENT_ACTIONS = 12
export const TOUCH_LIMIT = 100
export const TASK_LIMIT = 160
export const STEP_LIMIT = 2_000
export const CALL_LIMIT = 300
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
  "said (older messages shortened), the assistant's latest messages, what its latest commands",
  'touched, its task list if it keeps one, and the latest step the assistant is taking: what it just',
  'said and the calls it is making now. The output of every command is left out.',
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

function ends(text: string, first: number, last: number): string {
  return text.length <= first + last ? text : `${text.slice(0, first)} [...] ${text.slice(-last)}`
}

function oneLine(text: string): string {
  return text.replace(/\s+/g, ' ').trim()
}

/** How Claude Code opens the message a compaction leaves in place of what it summarised. */
const SUMMARY_OPENING = 'This session is being continued from a previous conversation'

/**
 * User messages nobody typed: a background task reporting in, a prompt a
 * plugin submitted (taskcut's own `Continue.` among them), the record of a
 * local command, an interruption. None of them asks for anything.
 */
const NOT_ASKED = [
  /^<task-notification>/,
  /^The \S+ plugin sent a message/,
  /^<local-command-/,
  /^Caveat: The messages below were generated by the user while running local commands/,
  /^\[Request interrupted by user/,
]

/** Whether a user message is the person asking for something. */
export function isRequest(message: SessionMessage): boolean {
  if (message.role !== 'user' || (message.toolResults?.length ?? 0) > 0) return false
  const text = message.text.trim()
  return text !== '' && !NOT_ASKED.some((pattern) => pattern.test(text))
}

/**
 * What a call touched: the file it read or wrote, or what a command says it
 * does. Enough to tell one piece of work from the next; the call in full is
 * what made an earlier judge's prompt grow with the session.
 */
export function touched(tool: string, input: unknown): string {
  const fields = (typeof input === 'object' && input !== null ? input : {}) as Record<string, unknown>
  if (typeof fields.file_path === 'string') return `${tool} ${fields.file_path}`
  if (tool === 'Bash') return `Bash: ${head(oneLine(String(fields.description || fields.command || '')), TOUCH_LIMIT)}`
  return `${tool}: ${head(oneLine(JSON.stringify(input) ?? ''), TOUCH_LIMIT)}`
}

/**
 * The assistant's task list as it last wrote it, through `TodoWrite` or the
 * `TaskCreate` and `TaskUpdate` tools, the step's own calls included. Empty
 * when it keeps none. `TaskCreate` numbers its tasks from 1, in order.
 */
export function taskList(messages: readonly SessionMessage[], step: Step): string[] {
  const calls = [
    ...messages.flatMap((message) => (message.role === 'assistant' ? message.toolUses.map((use) => ({ name: use.tool, input: use.input })) : [])),
    ...step.calls,
  ]
  let todos: { content: string; status: string }[] | undefined
  const tasks = new Map<string, { subject: string; status: string }>()
  for (const { name, input } of calls) {
    const fields = (typeof input === 'object' && input !== null ? input : {}) as Record<string, unknown>
    if (name === 'TodoWrite' && Array.isArray(fields.todos)) {
      todos = (fields.todos as Record<string, unknown>[]).map((todo) => ({ content: String(todo.content ?? ''), status: String(todo.status ?? '') }))
    } else if (name === 'TaskCreate' && typeof fields.subject === 'string') {
      tasks.set(String(tasks.size + 1), { subject: fields.subject, status: 'pending' })
    } else if (name === 'TaskUpdate' && typeof fields.status === 'string') {
      const task = tasks.get(String(fields.taskId))
      if (task) task.status = fields.status
    }
  }
  const mark = (status: string) => (status === 'completed' ? '[done]' : status === 'in_progress' ? '[doing]' : '[todo]')
  const items = todos?.map((todo) => ({ subject: todo.content, status: todo.status })) ?? [...tasks.values()].filter((task) => task.status !== 'deleted')
  return items.map((item) => `${mark(item.status)} ${head(oneLine(item.subject), TASK_LIMIT)}`)
}

/**
 * The messages before the step. Whether the transcript already holds the step
 * when it is judged is the engine's business; if it does, it is left out here
 * so that the step is not read twice.
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
 * The conversation as the judge reads it, oldest first: every request, the
 * first and the latest few whole; the assistant's latest messages; what its
 * latest calls other than lookups touched. Nothing else, and no output.
 */
export function conversationLines(messages: readonly SessionMessage[]): string[] {
  const indexed = messages.map((message, i) => ({ message, i }))
  const requests = indexed.filter(({ message }) => isRequest(message)).map(({ i }) => i)
  const asked = new Set(requests)
  const whole = new Set([...requests.slice(0, 1), ...requests.slice(-RECENT_REQUESTS)])
  const sayings = new Set(indexed.filter(({ message }) => message.role === 'assistant' && message.text.trim()).map(({ i }) => i).slice(-RECENT_SAYINGS))
  const actions = new Set(
    indexed.filter(({ message }) => message.role === 'assistant' && message.toolUses.some((use) => !READ_ONLY_TOOLS.has(use.tool))).map(({ i }) => i).slice(-RECENT_ACTIONS),
  )

  const lines: string[] = []
  let unsaid = 0
  const skipped = () => {
    if (unsaid > 0) lines.push(`(${unsaid} earlier assistant message${unsaid > 1 ? 's' : ''} left out)`)
    unsaid = 0
  }
  for (const [i, message] of messages.entries()) {
    if (message.role === 'user') {
      if (!asked.has(i)) continue
      skipped()
      const text = message.text.trim()
      if (text.startsWith(SUMMARY_OPENING)) lines.push(`Summary of the conversation before it was compacted: ${ends(text, SUMMARY_HEAD, SUMMARY_TAIL)}`)
      else if (whole.has(i)) lines.push(`Person: ${ends(text, REQUEST_HEAD, REQUEST_TAIL)}`)
      else lines.push(`Person (shortened): ${head(oneLine(text), REQUEST_LINE)}`)
      continue
    }
    if (sayings.has(i)) {
      skipped()
      lines.push(`Assistant: ${head(message.text.trim(), SAYING_LIMIT)}`)
    } else if (message.text.trim()) {
      unsaid++
    }
    if (actions.has(i)) {
      skipped()
      for (const use of message.toolUses) if (!READ_ONLY_TOOLS.has(use.tool)) lines.push(`Assistant ran ${touched(use.tool, use.input)}`)
    }
  }
  skipped()
  return lines
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

/** Everything the judge is shown: the conversation, the task list, and the step last. */
export function judgePrompt(messages: readonly SessionMessage[], step: Step): string {
  const before = beforeStep(messages, step)
  const tasks = taskList(before, step)
  return [
    '--- the conversation, oldest first (recent commands shortened, output left out) ---',
    ...conversationLines(before),
    ...(tasks.length > 0 ? ['', "--- the assistant's task list, as it last wrote it ---", ...tasks] : []),
    '',
    '--- latest step: what the assistant is doing now ---',
    tail(step.text.trim(), STEP_LIMIT) || '(no text)',
    ...step.calls.map((call) => `Calls ${call.name}: ${head(JSON.stringify(call.input) ?? '', CALL_LIMIT)}`),
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
    const { isAnswered, text, reason, status, error } = answer as { isAnswered: unknown; text?: unknown; reason?: unknown; status?: unknown; error?: unknown }
    if (isAnswered === true && typeof text === 'string') return { text }
    // An API error says which: a spent rate limit and a refused request
    // otherwise read the same.
    if (isAnswered === false) return { reason: [reason, status, error].filter((part) => part !== undefined && part !== null).join(' ') }
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
