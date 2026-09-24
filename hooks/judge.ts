/**
 * What the judge reads, and how its answer is read back, as pure functions of
 * plain data. A hooks module may only pass `$` to a function declared in the
 * same file, never across an import, which is why the code that fetches these
 * inputs lives in register.ts.
 *
 * The judge is asked one thing -- could the work be handed over here, to a
 * colleague holding only the summary a compaction writes and the workspace? --
 * and most of a session says nothing about it. What does, in order of how much:
 *
 *  1. the step itself, which says what has just been found or finished;
 *  2. what the person asked for, which says what work is still open;
 *  3. a trail of what the assistant has been doing -- what its recent calls
 *     touched, what it said, its task list -- which says where it has got to,
 *     and whether what it found so far was written anywhere.
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
 * The two answers the judge gives, as it writes them: the work could be handed
 * over now, or it still needs detail only the conversation holds.
 */
export const COMPACT = 'COMPACT'
export const KEEP = 'KEEP'

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
 * The question: the handoff test. A compaction keeps what the person asked for,
 * the decisions and conclusions, the files changed and the work in progress; it
 * drops how the work got there. So the moment to compact is one where every
 * piece of work still open would go on as well from the summary and the
 * workspace -- not the moment a task changes, which is only the commonest case
 * of it. A piece just finished stays open until the person has reacted to it,
 * and work set aside for a side question stays open, so neither the end of a
 * list nor a detour is a moment to compact.
 *
 * Nothing is predicted that the work so far does not show: a switch to other
 * work that turns out not to need the earlier detail can still be compacted a
 * few steps later, and uncertainty keeps the context, because a compaction
 * cannot be taken back.
 *
 * One sentence of reasoning before the verdict is what makes a small answer
 * reliable: asked for the word alone, an earlier judge missed two boundaries in
 * three.
 */
export const JUDGE_SYSTEM = [
  "You are deciding whether now is a good moment to compact an assistant's working conversation.",
  '',
  'Compacting replaces the conversation with a summary, written by a model that reads all of it. The',
  'summary keeps what the person asked for, the decisions made, the conclusions the assistant reached and',
  'stated, which files were changed, and the work in progress with its next step. It drops the raw',
  'material: the contents of files that were read, the output of commands, exact figures and tables the',
  'assistant did not save, and the detail of attempts that failed.',
  '',
  'The test: suppose the work were handed over right now to a capable colleague who gets only that',
  'summary and the workspace -- the repository and anything saved to files, which they can read again.',
  'Would they carry on every piece of work that is still open as well as the assistant can with the',
  'full conversation?',
  '',
  'Work is open until it is finished and nothing more is expected of it. A piece the assistant has just',
  'finished is still open while the person has not reacted to it: what they say next is usually about',
  'it. Work set aside for a side question is still open.',
  '',
  'Being in the middle of work is not a reason to keep: the summary records where it stands, and the',
  'colleague picks it up there. What matters is what the next steps will draw on. Answer ' + KEEP + ' only',
  'when you can name detail that open work is about to use, that only the raw material holds, and that',
  'cannot be got back cheaply: figures from recent output the assistant is about to report, compare or',
  'write up and has not saved; the output of a long run, of a remote or changing system, or of a one-off',
  'experiment; a report from a sub-agent or a review that was not saved; why an approach just failed,',
  'when the next attempt turns on it. Detail the colleague can get back by reading a file again or',
  're-running a quick command is no reason to keep: code and files the assistant has just read or',
  'edited are in the workspace, however exactly it needs them. Nor is a conclusion the assistant has',
  'already stated. If you cannot name such detail, answer ' + COMPACT + '.',
  '',
  "You are shown what the person said (older messages shortened), the assistant's latest messages,",
  'what its latest commands touched, its task list if it keeps one, and the step it is taking now: what',
  'it just said and the calls it is making. Command output is never shown. The conversation may open',
  'with a summary from an earlier compaction; it is a record of past work, not a request.',
  '',
  'First say in one sentence what work is still open and what, if anything, it is about to need that',
  `the summary would drop. Then, on its own last line, write ${COMPACT} or ${KEEP}.`,
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
 * The messages before the step, without the step.
 *
 * When the step is judged, `$.session.messages()` (2.1.280) already holds it,
 * and as more than one message: a response is recorded a block at a time, so
 * its words are one message and each call another -- and a call that has
 * already run is followed by its result. Left in, the step would be read
 * twice, once as the latest thing the assistant said, and whether it was
 * would depend on how fast its tools ran.
 *
 * So the step is the shortest run of messages at the end whose words, joined,
 * are the step's and whose calls are the step's, with nothing between them
 * but the results of those calls. When there is none -- the engine does not
 * hold the step yet -- every message is before it.
 */
export function beforeStep(messages: readonly SessionMessage[], step: Step): readonly SessionMessage[] {
  const words = oneLine(step.text)
  const calls = step.calls.map((call) => `${call.name} ${JSON.stringify(call.input)}`)
  const said: string[] = []
  const made: string[] = []
  const madeIds = new Set<string>()
  const resultIds: string[] = []
  for (let i = messages.length - 1; i >= 0; i--) {
    const message = messages[i]!
    if (message.role === 'user') {
      if (!message.toolResults?.length) return messages
      resultIds.push(...message.toolResults.map((result) => result.tool_use_id))
      continue
    }
    said.unshift(message.text)
    made.unshift(...message.toolUses.map((use) => `${use.tool} ${JSON.stringify(use.input)}`))
    for (const use of message.toolUses) madeIds.add(use.tool_use_id)
    if (made.length > calls.length) return messages
    const isStep = oneLine(said.join(' ')) === words && made.length === calls.length && made.every((call, k) => call === calls[k])
    // Nothing may come between the step's messages but its own calls' results.
    if (isStep) return resultIds.every((id) => madeIds.has(id)) ? messages.slice(0, i) : messages
  }
  return messages
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
 * Whether the step is worth asking about: one that says something. A step made
 * of calls alone rarely finds or finishes anything the judge could see, and it
 * costs a judgement all the same.
 */
export function judgeable(step: Step): boolean {
  return step.text.trim() !== ''
}

/**
 * Whether calls change anything. Until a step after a compaction has, the
 * conversation is the summary and a few reads of the workspace, which is what
 * a compaction would leave it as again.
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
 * Whether the judge's answer says to compact: its last line, stripped of the
 * emphasis a model sometimes puts round it. Anything else, including no
 * answer, is not.
 */
export function saysCompact(answer: string): boolean {
  const lines = answer.trim().split('\n')
  const last = lines[lines.length - 1] ?? ''
  return last.replace(/[^A-Za-z]/g, '').toUpperCase() === COMPACT
}
