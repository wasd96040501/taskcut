/**
 * Records, at every step of the main loop, the prompt taskcut's judge would be
 * given there: `judgePrompt` over what `$.session.messages()` holds at the
 * point hooks/register.ts reads it, once the step's response is in. The replay
 * rebuilds the same prompt from the transcript alone; `make eval-replay-check`
 * runs a real session with this beside taskcut and says whether the two agree.
 *
 * Every step is recorded, judged or not, and whatever the floor: the check is
 * of the input, and every step's input is built the same way.
 */

import type { Register } from 'claude-code'

import { judgePrompt, type Step } from './judge'

/** A message as the judge reads it, for finding where two lists part: role, words, calls, results. */
type Shape = [string, string, string[], number]

type Entry = { turnId: string; index: number; stopReason: unknown; step: Step; prompt: string; messages: number; shapes: Shape[] }

const entries: Entry[] = []

export const register: Register = (on) => {
  on('turn.step', async function* ($, e, next) {
    const result = yield* next(e)
    if (e.agentId !== undefined) return result
    const step: Step = { text: result.answer, calls: result.toolUses }
    const messages = await $.session.messages()
    const shapes = messages.map((m): Shape => [m.role, m.text.slice(0, 80), m.toolUses.map((use) => use.tool), m.toolResults?.length ?? 0])
    entries.push({ turnId: e.turnId, index: e.index, stopReason: result.stopReason, step, prompt: judgePrompt(messages, step), messages: messages.length, shapes })
    await $.fs.write(`${$.plugin.root}/records.json`, JSON.stringify(entries))
    return result
  })
}
