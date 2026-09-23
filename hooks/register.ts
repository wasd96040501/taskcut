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
import { judgingFrom, readConfig, type Config } from './config'
import { ANSWER_TOKENS, JUDGE_SYSTEM, acts, judgeable, judgePrompt, readReply, saysNext, type Step } from './judge'
import { NOTHING, addCompaction, addJudgement, judgementLine, readUsage, spendReport, type Spend } from './spend'

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
 * The context fill the last compaction left, until there has been one. See
 * judgingFrom.
 */
let leftAt: number | undefined

/** What taskcut has spent in this session: its judgements, and the compactions it started. */
let spend: Spend = NOTHING

/** The command that says so. */
const COMMAND = 'taskcut'

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
  return percent >= judgingFrom(config.floorPercent, leftAt) ? percent : undefined
}

/**
 * Whether the work moves on from a finished piece to another at this moment,
 * as the judge sees it. Anything but a clear yes keeps the context: a
 * compaction in the middle of a piece costs re-reading, and a missed boundary
 * only waits for the next one.
 *
 * Every call is counted, answered or not, and logged to the debug log with
 * what it cost.
 */
async function judge($: EngineInterface, step: Step, config: Config, percent: number): Promise<boolean> {
  const started = Date.now()
  let verdict: string
  let movesOn = false
  let answer: unknown
  try {
    const prompt = judgePrompt(await $.session.messages(), step)
    // `unknown`: what the call resolves to has changed between releases, and
    // readReply takes every shape it has had.
    answer = await $.model.complete({ model: config.model, system: JUDGE_SYSTEM, prompt, maxTokens: ANSWER_TOKENS })
    const reply = readReply(answer)
    spend = addJudgement(spend, readUsage(answer), 'text' in reply)
    if ('reason' in reply) verdict = `could not judge the step (${reply.reason})`
    else {
      movesOn = saysNext(reply.text)
      verdict = `step judged ${movesOn ? 'a new piece' : 'the same work'}`
    }
  } catch (error) {
    // Refused before it was sent: nothing was spent.
    verdict = `could not judge the step (${String(error)})`
  }
  $.ui.log(judgementLine(percent, verdict, config.model, readUsage(answer), Date.now() - started), { to: 'debug' })
  return movesOn
}

/**
 * Compacts, and never throws. It is unavailable in a headless session and
 * rejects while a turn runs; either way the conversation stays as it is.
 */
async function compact($: EngineInterface): Promise<void> {
  try {
    const result = await $.session.compact()
    if (result.skip === undefined) {
      spend = addCompaction(spend, result.tokensBefore, result.tokensAfter)
      actedSince = false
    } else {
      $.ui.log(`compaction skipped (${result.skip})`)
    }
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
    try {
      // Immediate: a long unattended turn is when what taskcut has spent is
      // worth asking, and the answer needs nothing from the turn.
      await $.command.register({ name: COMMAND, description: 'What taskcut has judged and compacted in this session, and what the judging cost', immediate: true })
    } catch (error) {
      $.ui.log(`/${COMMAND} not registered (${String(error)})`, { to: 'debug' })
    }
    return result
  })

  on('command.run', async ($, e, next) => {
    if (e.command !== COMMAND) return next(e)
    const percent = activation.active && interactive ? await contextPercent($) : undefined
    return { text: spendReport(spend, { active: activation.active, interactive, floorPercent: config.floorPercent, model: config.model, percent }) }
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
    if (await judge($, step, config, percent)) movedOnAt = percent
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
