/**
 * Asks the judge about labelled steps, through the same `$.model.complete`
 * call taskcut makes, and writes down what it answered and what it cost.
 *
 * The benchmark copies a `hooks/judge.ts` in beside this file before a run --
 * the plugin's own, or one from another commit to compare against -- so what
 * is measured is a question taskcut ships. A prompt of the form
 * `taskcut-judgebench <input.json> <output.json>` runs the cases in the input
 * and is dropped; any other prompt is left alone.
 *
 * A case holds its messages, or names a replay set and where in it the step
 * is: a set holds a whole session once, where a case per step would repeat it
 * hundreds of times over, and `$.fs.read` takes no file over 4 MiB.
 */

import type { EngineInterface, Register } from 'claude-code'

import * as judge from './judge'
import { ANSWER_TOKENS, JUDGE_SYSTEM, judgePrompt, readReply, type Step } from './judge'

/**
 * The verdict, in whichever words the judge being measured writes it: a judge
 * up to 0.9 answers NEXT or SAME, the handoff judge COMPACT or KEEP. Read
 * through the module, so that either can be copied in and measured.
 */
const words = judge as unknown as Record<string, unknown>
const YES = String(words.COMPACT ?? words.NEXT)
const NO = String(words.KEEP ?? words.SAME)
const says = (words.saysCompact ?? words.saysNext) as (answer: string) => boolean

type Messages = Parameters<typeof judgePrompt>[0]

type Case = { id: string; step: Step } & ({ messages: Messages } | { set: number; segment: number; pos: number })

type Input = {
  model: string
  repeats: number
  concurrency: number
  /** Replay sets, by the index a case names. */
  sets?: string[]
  cases: Case[]
}

type ReplaySet = { segments: Messages[]; memory?: string[] }

type Answer = {
  id: string
  run: number
  verdict: string
  text: string
  usage: unknown
  attempts: number
  ms: number
  promptChars: number
}

const MARKER = 'taskcut-judgebench '

/** An API error worth asking again: a rate limit, an overload, a server error. */
function transient(answer: unknown): boolean {
  if (typeof answer !== 'object' || answer === null) return false
  const { reason, status } = answer as { reason?: unknown; status?: unknown }
  return reason === 'api-error' && (status === 429 || status === 529 || (typeof status === 'number' && status >= 500) || status === null)
}

const ATTEMPTS = 5

async function ask($: EngineInterface, model: string, messages: Messages, memory: string[], item: Case, run: number): Promise<Answer> {
  // A judge from before 0.9 took CLAUDE.md as a third argument; the current
  // one takes two, and ignores it.
  const prompt = (judgePrompt as (m: Messages, s: Step, memory: string[]) => string)(messages, item.step, memory)
  let answer: unknown
  let attempts = 0
  const started = Date.now()
  do {
    if (attempts > 0) await new Promise((resolve) => setTimeout(resolve, 2_000 * 2 ** attempts))
    answer = await $.model.complete({ model, system: JUDGE_SYSTEM, prompt, maxTokens: ANSWER_TOKENS })
    attempts++
  } while (transient(answer) && attempts < ATTEMPTS)
  const reply = readReply(answer)
  const verdict = 'text' in reply ? (says(reply.text) ? YES : NO) : `unanswered: ${reply.reason}`
  const usage = typeof answer === 'object' && answer !== null && 'usage' in answer ? (answer as { usage: unknown }).usage : null
  return { id: item.id, run, verdict, text: 'text' in reply ? reply.text : '', usage, attempts, ms: Date.now() - started, promptChars: prompt.length }
}

async function runAll($: EngineInterface, input: Input): Promise<Answer[]> {
  const sets: ReplaySet[] = []
  for (const path of input.sets ?? []) sets.push(JSON.parse(await $.fs.read(path)) as ReplaySet)
  const jobs = input.cases.flatMap((item) => Array.from({ length: input.repeats }, (_, run) => ({ item, run })))
  const answers: Answer[] = []
  let next = 0
  const worker = async () => {
    while (next < jobs.length) {
      const { item, run } = jobs[next++]!
      const set = 'set' in item ? sets[item.set]! : undefined
      const messages = set && 'segment' in item ? set.segments[item.segment]!.slice(0, item.pos) : (item as { messages: Messages }).messages
      answers.push(await ask($, input.model, messages, set?.memory ?? [], item, run))
    }
  }
  await Promise.all(Array.from({ length: Math.max(1, input.concurrency) }, worker))
  return answers
}

export const register: Register = (on) => {
  on('prompt.submit', async ($, e, next) => {
    if (!e.text.startsWith(MARKER)) return next(e)
    const [inputPath, outputPath] = e.text.slice(MARKER.length).trim().split(/\s+/)
    if (!inputPath || !outputPath) return { drop: `usage: ${MARKER}<input.json> <output.json>` }
    const input = JSON.parse(await $.fs.read(inputPath)) as Input
    const answers = await runAll($, input)
    await $.fs.write(outputPath, JSON.stringify(answers, null, 1))
    return { drop: `judged ${answers.length} step(s)` }
  })
}
