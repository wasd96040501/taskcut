/**
 * Asks the judge about labelled steps, through the same `$.model.complete`
 * call taskcut makes, and writes down what it answered.
 *
 * The benchmark copies the plugin's own `hooks/judge.ts` in beside this file
 * before a run, so what is measured is the question taskcut ships. A prompt of
 * the form `taskcut-judgebench <input.json> <output.json>` runs the cases in the
 * input and is dropped; any other prompt is left alone.
 */

import type { EngineInterface, Register } from 'claude-code'

import { ANSWER_TOKENS, JUDGE_SYSTEM, judgePrompt, readReply, saysNext, NEXT, SAME, type Step } from './judge'

type Input = {
  model: string
  repeats: number
  concurrency: number
  cases: { id: string; messages: Parameters<typeof judgePrompt>[0]; step: Step }[]
}

type Answer = {
  id: string
  run: number
  verdict: string
  text: string
  usage: unknown
  error: { status: unknown; error: unknown } | null
  promptChars: number
}

const MARKER = 'taskcut-judgebench '

async function ask($: EngineInterface, model: string, item: Input['cases'][number], run: number): Promise<Answer> {
  const prompt = judgePrompt(item.messages, item.step)
  const answer: unknown = await $.model.complete({ model, system: JUDGE_SYSTEM, prompt, maxTokens: ANSWER_TOKENS })
  const reply = readReply(answer)
  const verdict = 'text' in reply ? (saysNext(reply.text) ? NEXT : SAME) : `unanswered: ${reply.reason}`
  const fields = typeof answer === 'object' && answer !== null ? (answer as Record<string, unknown>) : {}
  // Why a call went unanswered, as the engine put it: a rate limit reads the
  // same as a refusal in the verdict, and only the status tells them apart.
  const error = 'reason' in reply ? { status: fields.status ?? null, error: fields.error ?? null } : null
  return { id: item.id, run, verdict, text: 'text' in reply ? reply.text : '', usage: fields.usage ?? null, error, promptChars: prompt.length }
}

async function runAll($: EngineInterface, input: Input): Promise<Answer[]> {
  const jobs = input.cases.flatMap((item) => Array.from({ length: input.repeats }, (_, run) => ({ item, run })))
  const answers: Answer[] = []
  let next = 0
  const worker = async () => {
    while (next < jobs.length) {
      const job = jobs[next++]!
      answers.push(await ask($, input.model, job.item, job.run))
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
