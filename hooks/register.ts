/**
 * taskcut: compaction at sub-task boundaries.
 *
 * Claude Code compacts when the context window fills, which is rarely the moment
 * a piece of work ends: the compaction lands in the middle of one. taskcut moves
 * it to the end of a sub-task. Once the context is past the floor, at the end of
 * each turn the model finished, a small model judges whether the work that was
 * asked for is done. If it is, taskcut calls `$.session.compact()` -- the same
 * call `/compact` makes -- and Claude Code compacts as it always does.
 *
 * taskcut decides when; the engine decides what is kept. Below the floor it
 * does nothing at all: no model is asked, nothing is registered or written, and
 * the working model is never told taskcut exists.
 *
 * Everything that touches `$` is declared here, at the top level of this file:
 * the loader follows `$` into a function declared in the same module and refuses
 * one imported from another.
 */

import type { EngineInterface, Register } from 'claude-code'

import { ENV_VAR, INERT, decideActivation, type Activation } from './activation'
import { readConfig, type Config } from './config'
import { FINISHED, UNFINISHED, judgeText } from './judge'

/**
 * Resolved once, at `session.start`. It starts inert so that a session in which
 * that hook never runs does nothing at all, rather than everything.
 */
let activation: Activation = INERT

/** Compile-time guard: the literal above must stay equal to the constant. */
const ENV_VAR_LITERAL: typeof ENV_VAR = 'TASKCUT'
void ENV_VAR_LITERAL

/** The context fill as the status line shows it. Free: read off the last response. */
async function contextPercent($: EngineInterface): Promise<number> {
  const { context } = await $.session.usage()
  return context.percent ?? 0
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
 * Whether the work this turn answered is finished, as the small model judges
 * it. Anything but a clear `finished` keeps the context: a compaction in the
 * middle of work costs re-reading, and a missed one only waits for the next
 * turn.
 */
async function judgeFinished($: EngineInterface, reply: string, config: Config): Promise<boolean> {
  try {
    const text = judgeText(await $.session.messages(), reply, await memoryFiles($))
    const verdict = await $.model.classify(text, [FINISHED, UNFINISHED], { model: config.model })
    return verdict === FINISHED
  } catch (error) {
    $.ui.log(`could not judge the turn (${String(error)})`, { to: 'debug' })
    return false
  }
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
    return result
  })

  on('turn.complete', async ($, e, next) => {
    // `next` first, so the engine has finished settling the turn before a
    // compaction is raised against it.
    const result = await next(e)
    if (!activation.active) return result

    // Only a main-loop turn the model finished. A subagent's run is not the
    // person's conversation, and a turn that was interrupted or failed stopped
    // in the middle of its work: that transcript is what explains what went
    // wrong, and it is exactly what a compaction would summarise away.
    if (e.agentId !== undefined || e.reason !== 'answer') return result

    const percent = await contextPercent($)
    if (percent < config.floorPercent) return result

    if (!(await judgeFinished($, e.answer, config))) {
      $.ui.log(`context at ${percent}%, the work is not finished; keeping it`)
      return result
    }
    $.ui.log(`context at ${percent}%, the work is finished; compacting`)

    // Between turns only: `$.session.compact` rejects while one is running, and
    // it is unavailable altogether in a headless session (`-p` or the SDK
    // transport). A failure here must not take the turn down with it.
    try {
      await $.session.compact()
    } catch (error) {
      $.ui.log(`compaction skipped (${String(error)})`)
    }
    return result
  })
}
