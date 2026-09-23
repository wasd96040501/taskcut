/**
 * taskcut: compaction at sub-task boundaries.
 *
 * Claude Code compacts when the context window fills, which is rarely the moment
 * a piece of work ends: the compaction lands in the middle of one. taskcut moves
 * it to the point where the work moves on from one piece to the next. Once the
 * context is past the floor, a model judges each step the working model makes
 * for whether the work moves on from a finished piece to another. When it
 * does, taskcut calls `$.session.compact()`, the same call `/compact` makes,
 * and Claude Code compacts as it always does.
 *
 * The end of a turn is left alone: the work is back with the person, and what
 * they say next may well be about the piece just finished. When they move on,
 * `/compact` is theirs.
 *
 * A compaction can only run between turns. So taskcut ends the turn before its
 * next model request, compacts, and submits one line that picks the work back
 * up: what a person watching would do with Esc, `/compact` and "continue".
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
import { ANSWER_TOKENS, JUDGE_SYSTEM, acts, judgeable, judgePrompt, readReply, saysNext, type Step } from './judge'

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
 * The context fill at which a step was judged to move the work on to another
 * piece. The turn is ended before its next request.
 */
let movedOnAt: number | undefined

/** Set when taskcut itself ended the running turn in order to compact. */
let cutting = false

/**
 * Whether the last request the main loop sent ended on tool results -- every
 * step's but the first of a turn, whose request ends on the prompt that opened
 * it. Claude Code builds its summary request on the last request it sent, so
 * when that ended on the person's own words, the summary instruction reads as
 * part of them, and the model answers them instead of summarising (2.1.280,
 * `/compact` typed by hand included). taskcut compacts only when it did not.
 */
let lastSentOnResults = false

/**
 * Whether the working model has changed anything since the last compaction.
 * Until it has, no piece can have been finished since, and no step is judged.
 */
let actedSince = true

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
 * Whether the work moves on from a finished piece to another at this moment,
 * as the judge sees it. Anything but a clear yes keeps the context: a
 * compaction in the middle of a piece costs re-reading, and a missed boundary
 * only waits for the next one.
 */
async function judge($: EngineInterface, step: Step, config: Config): Promise<boolean> {
  try {
    const prompt = judgePrompt(await $.session.messages(), step)
    // `unknown`: what the call resolves to has changed between releases, and
    // readReply takes every shape it has had.
    const answer: unknown = await $.model.complete({ model: config.model, system: JUDGE_SYSTEM, prompt, maxTokens: ANSWER_TOKENS })
    const reply = readReply(answer)
    if ('reason' in reply) {
      $.ui.log(`could not judge the step (${reply.reason})`, { to: 'debug' })
      return false
    }
    return saysNext(reply.text)
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
    actedSince = false
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
  // is in, while the engine runs the step's tools, and a step that moves on to
  // another piece ends the turn before the next request goes out -- with every
  // tool result of that step already in. The judgement is a `$` call made
  // inside the step's own hook, so it runs beside the tools and costs the
  // hook's budget nothing; the engine sends the next request once both are done.
  on('turn.step', async function* ($, e, next) {
    if (e.agentId !== undefined || !activation.active || !interactive) return yield* next(e)

    if (movedOnAt !== undefined) {
      $.ui.log(`context at ${movedOnAt}%, compacting before the next piece`)
      movedOnAt = undefined
      try {
        await $.turn.abort({ turnId: e.turnId })
        cutting = true
        return { turnId: e.turnId, index: e.index, answer: '', toolUses: [], stopReason: null, usage: null }
      } catch (error) {
        $.ui.log(`compaction skipped (${String(error)})`)
      }
    }

    lastSentOnResults = e.index > 0
    const result = yield* next(e)
    // A step that ends the turn hands the work back to the person.
    const step: Step = { text: result.answer, calls: result.toolUses }
    const acted = actedSince
    if (acts(step.calls)) actedSince = true
    if (result.stopReason !== 'tool_use' || !acted || !lastSentOnResults || !judgeable(step)) return result
    const percent = await pastFloor($, config)
    if (percent === undefined) return result
    const movesOn = await judge($, step, config)
    $.ui.log(`context at ${percent}%, step judged ${movesOn ? 'a new piece' : 'the same work'}`, { to: 'debug' })
    if (movesOn) movedOnAt = percent
    return result
  })

  on('turn.complete', async ($, e, next) => {
    // `next` first, so the engine has finished settling the turn before a
    // compaction is raised against it.
    const result = await next(e)
    if (e.agentId !== undefined) return result
    movedOnAt = undefined
    if (!cutting) return result

    cutting = false
    await compact($)
    // Whether or not it compacted, the work taskcut interrupted goes on.
    void $.prompt.submit({ text: CONTINUE })
    return result
  })
}
