/**
 * taskcut: compaction at sub-task boundaries.
 *
 * Claude Code compacts when the context window fills, which is rarely the moment
 * a piece of work ends: the compaction lands in the middle of one. taskcut moves
 * it to the end of a piece. Once the context is past the floor, a model judges
 * each step the working model makes -- and the reply a turn ends on -- for
 * whether it reports a piece of the work complete. When it does, taskcut calls
 * `$.session.compact()`, the same call `/compact` makes, and Claude Code
 * compacts as it always does.
 *
 * A compaction can only run between turns. At the end of a turn it runs there
 * and then. Inside a long turn, taskcut ends the turn before its next model
 * request, compacts, and submits one line that picks the work back up: what a
 * person watching would do with Esc, `/compact` and "continue".
 *
 * taskcut decides when; the engine decides what is kept. Below the floor it
 * does nothing at all: no model is asked, nothing is written, and the working
 * model is never told taskcut exists.
 *
 * Everything that touches `$` is declared here, at the top level of this file:
 * the loader follows `$` into a function declared in the same module and refuses
 * one imported from another.
 */

import type { EngineInterface, Register } from 'claude-code'

import { ENV_VAR, INERT, decideActivation, type Activation } from './activation'
import { readConfig, type Config } from './config'
import { ANSWER_TOKENS, JUDGE_SYSTEM, judgePrompt, saysDone, type Step } from './judge'

/**
 * Resolved once, at `session.start`. It starts inert so that a session in which
 * that hook never runs does nothing at all, rather than everything.
 */
let activation: Activation = INERT

/**
 * Whether a person is at the prompt. Only then can a compaction run, and only
 * then is it safe to end a turn early: a `-p` run would end with it.
 */
let interactive = false

/**
 * The context fill at which the step the working model just made was judged
 * to have finished a piece; the turn is ended before the next request.
 */
let finishedAt: number | undefined

/** Set when taskcut itself ended the running turn in order to compact. */
let cutting = false

/**
 * The context fill the last compaction left. When a compaction cannot bring
 * the context back under the floor, the next judgement waits until it has
 * grown by REGROWTH points more, so that the same finished work is not
 * compacted again and again.
 */
let leftAt = 0
const REGROWTH = 5

/** What taskcut submits to pick the work back up after it ended a turn. */
const CONTINUE = 'Continue.'

/** Compile-time guard: the literal below must stay equal to the constant. */
const ENV_VAR_LITERAL: typeof ENV_VAR = 'TASKCUT'
void ENV_VAR_LITERAL

/** The context fill as the status line shows it. Free: read off the last response. */
async function contextPercent($: EngineInterface): Promise<number> {
  const { context } = await $.session.usage()
  return context.percent ?? 0
}

/** The context fill when a judgement is due, or undefined when it is not. */
async function pastFloor($: EngineInterface, config: Config): Promise<number | undefined> {
  const percent = await contextPercent($)
  const floor = leftAt >= config.floorPercent ? leftAt + REGROWTH : config.floorPercent
  return percent >= floor ? percent : undefined
}

/**
 * The project instructions in the context, as the permission classifier reads
 * them. The breakdown is estimated locally, so listing them sends nothing; a
 * file that cannot be read is left out rather than failing the judgement.
 */
async function memoryFiles($: EngineInterface): Promise<string[]> {
  const { context } = await $.session.usage({ breakdown: 'summary' })
  const texts: string[] = []
  for (const file of context.breakdown?.memoryFiles ?? []) {
    try {
      texts.push(await $.fs.read(file.path))
    } catch {
      // Moved or unreadable since it was loaded: the judge does without it.
    }
  }
  return texts
}

/**
 * Whether the step reports a piece of the work complete, as the judge sees it.
 * Anything but a clear yes keeps the context: a compaction in the middle of a
 * piece costs re-reading, and a missed boundary only waits for the next one.
 */
async function judge($: EngineInterface, step: Step, config: Config): Promise<boolean> {
  try {
    const prompt = judgePrompt(await $.session.messages(), step, await memoryFiles($))
    const answer = await $.model.complete({ model: config.model, system: JUDGE_SYSTEM, prompt, maxTokens: ANSWER_TOKENS })
    return saysDone(answer)
  } catch (error) {
    $.ui.log(`could not judge the step (${String(error)})`, { to: 'debug' })
    return false
  }
}

/**
 * Compacts, and never throws. It is unavailable in a headless session and
 * rejects while a turn runs; either way the conversation stays as it is.
 */
async function compact($: EngineInterface): Promise<void> {
  try {
    await $.session.compact()
  } catch (error) {
    $.ui.log(`compaction skipped (${String(error)})`)
  }
  leftAt = await contextPercent($)
}

export const register: Register = (on, options) => {
  const config = readConfig(options)

  on('session.start', async ($, e, next) => {
    const result = await next(e)
    activation = decideActivation({
      // Spelled out: $.env.get takes a literal name so that the loader can list
      // every variable a module reads. ENV_VAR_LITERAL fails the build if this
      // string and the constant ever disagree.
      env: await $.env.get('TASKCUT'),
    })
    interactive = e.isInteractive
    return result
  })

  // Inside a turn: each step the main loop makes is judged once its response
  // is in, while the engine runs the step's tools, and a step that finished a
  // piece ends the turn before the next request goes out -- with every tool
  // result of that step already in. The judgement is a `$` call made inside
  // the step's own hook, so it runs beside the tools and costs the hook's
  // budget nothing; the engine sends the next request once both are done.
  on('turn.step', async function* ($, e, next) {
    if (e.agentId !== undefined || !activation.active || !interactive) return yield* next(e)

    if (finishedAt !== undefined) {
      $.ui.log(`context at ${finishedAt}%, a piece of the work is finished; compacting`)
      finishedAt = undefined
      try {
        await $.turn.abort({ turnId: e.turnId })
        cutting = true
        return { turnId: e.turnId, index: e.index, answer: '', toolUses: [], stopReason: null, usage: null }
      } catch (error) {
        $.ui.log(`compaction skipped (${String(error)})`)
      }
    }

    const result = yield* next(e)
    // A step that ends the turn is judged at turn.complete, as its reply.
    if (result.stopReason !== 'tool_use') return result
    const percent = await pastFloor($, config)
    if (percent === undefined) return result
    const done = await judge($, { text: result.answer, calls: result.toolUses }, config)
    $.ui.log(`context at ${percent}%, step judged ${done ? 'done' : 'working'}`, { to: 'debug' })
    if (done) finishedAt = percent
    return result
  })

  on('turn.complete', async ($, e, next) => {
    // `next` first, so the engine has finished settling the turn before a
    // compaction is raised against it.
    const result = await next(e)
    if (e.agentId !== undefined) return result
    finishedAt = undefined

    if (cutting) {
      cutting = false
      await compact($)
      // Whether or not it compacted, the work taskcut interrupted goes on.
      void $.prompt.submit({ text: CONTINUE })
      return result
    }

    // Only a turn the model finished. One that was interrupted or failed
    // stopped in the middle of its work: that transcript is what explains what
    // went wrong, and it is exactly what a compaction would summarise away.
    if (!activation.active || e.reason !== 'answer') return result

    const percent = await pastFloor($, config)
    if (percent === undefined) return result
    if (!(await judge($, { text: e.answer, calls: [] }, config))) {
      $.ui.log(`context at ${percent}%, the work is not finished; keeping it`)
      return result
    }
    $.ui.log(`context at ${percent}%, the work is finished; compacting`)
    await compact($)
    return result
  })
}
