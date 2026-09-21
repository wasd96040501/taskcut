/**
 * taskcut: compaction at sub-task boundaries.
 *
 * The engine compacts when the context window fills, which is rarely the moment
 * a piece of work ends. This module moves the cut to the end of a sub-task. When
 * a turn ends with the context past the floor, a small model reads what was
 * asked and what the assistant answered and judges whether that piece of work
 * is finished. If it is, a `session.compact` hook answers with a transcript it
 * builds itself: the human turns, kept whole by their engine handles, followed
 * by a ledger of the work finished so far. It never calls `next` on that
 * dispatch, so no summariser runs and nothing kept is paraphrased.
 *
 * Below the floor taskcut does nothing at all: no model is asked, nothing is
 * registered, nothing is written, and the working model is never told taskcut
 * exists. An earlier version had the working model declare each boundary by
 * calling a tool. A tool call ends the model's response, so every boundary was
 * one more request that read the whole context again -- about ten percent of a
 * twenty-change session, measured -- and a tool, once registered, cannot be
 * taken back. The judge reads a request and an answer, a few thousand
 * characters, and only past the floor.
 *
 * Everything that touches `$` is declared here, at the top level of this file:
 * the loader follows `$` into a function declared in the same module and refuses
 * one imported from another.
 */

import type { EngineInterface, Register, SessionMessage } from 'claude-code'

import { ENV_VAR, INERT, decideActivation, type Activation } from './activation'
import { readConfig, type Config } from './config'
import {
  CLOSE_TOOL,
  FINISHED,
  LEDGER_PREFIX,
  UNFINISHED,
  boundedHumanTurns,
  finishedWork,
  foldPrompt,
  foldedEntry,
  humanTurnsOf,
  judgeText,
  planFold,
  renderLedger,
  staleLedgerKeys,
  type Entry,
} from './ledger'

/**
 * The instructions taskcut passes to its own compaction. Another plugin can
 * trigger a `plugin` compaction too, and this plugin's other hooks see it; the
 * marker is how the boundary cut tells its own dispatch from someone else's,
 * instead of hijacking every plugin compaction in the session.
 */
const COMPACTION_MARKER = 'taskcut: sub-task boundary'

/**
 * What the working model is told under the `outcome` setting, once the context
 * is past the floor. The judge still decides when to cut; this only asks for a
 * conclusion to keep in place of the answer.
 */
const OUTCOME_REMINDER =
  'The context window is filling up. When the sub-task you are working on is finished, ' +
  `call close_task (${CLOSE_TOOL}) with what the next one will need; the rest of its ` +
  'working context will be dropped.'

/** Whether `close_task` has been registered. The engine has no way to take a tool back. */
let closeTaskOffered = false

/** Whether this turn has carried the outcome reminder. Once a turn is enough. */
let remindedThisTurn = false

/**
 * Resolved once, at `session.start`. It starts inert so that a session in which
 * that hook never runs does nothing at all, rather than everything.
 */
let activation: Activation = INERT

/** Compile-time guard: the literal above must stay equal to the constant. */
const ENV_VAR_LITERAL: typeof ENV_VAR = 'TASKCUT'
void ENV_VAR_LITERAL

/**
 * The plugin store is shared by every session on the machine, so the ledger is
 * keyed by session. Without this, two jobs running at once read each other's
 * conclusions, and a model is told work is finished that this session never did.
 */
async function ledgerKey($: EngineInterface): Promise<string> {
  return `ledger:${await $.session.id()}`
}

async function readLedger($: EngineInterface): Promise<Entry[]> {
  return ((await $.store.get(await ledgerKey($))) as Entry[] | undefined) ?? []
}

async function writeLedger($: EngineInterface, ledger: readonly Entry[]): Promise<void> {
  await $.store.set(await ledgerKey($), ledger)
}

/**
 * Drops ledgers left behind by sessions that never ended cleanly. `session.end`
 * handles the ordinary case; a killed session never reaches it, and the plugin
 * store has a hard size limit, so the leftovers have to be swept from somewhere.
 */
async function sweepStaleLedgers($: EngineInterface): Promise<void> {
  const keys = (await $.store.keys()).filter((key) => key.startsWith(LEDGER_PREFIX))
  if (keys.length === 0) return
  const entriesByKey = new Map<string, Entry[]>()
  for (const key of keys) {
    entriesByKey.set(key, ((await $.store.get(key)) as Entry[] | undefined) ?? [])
  }
  const current = await ledgerKey($)
  for (const key of staleLedgerKeys(entriesByKey, current, await $.clock.now())) {
    await $.store.delete(key)
  }
}

/**
 * Folds the oldest entries into one when the ledger has grown past the verbatim
 * limit. The ledger survives every cut, so without this it becomes the growth
 * the cuts were meant to stop.
 *
 * A fold that cannot reach a model leaves the ledger long rather than failing
 * the cut: a cut that did not happen is the worse outcome, and the next cut
 * tries the fold again.
 */
async function foldLedger($: EngineInterface, ledger: readonly Entry[], config: Config): Promise<Entry[]> {
  const plan = planFold(ledger, config.ledgerVerbatim)
  if (plan === null) return [...ledger]
  try {
    const rolled = await $.model.complete({ model: config.model, prompt: foldPrompt(plan.fold), maxTokens: 1024 })
    return [foldedEntry(plan.fold, rolled), ...plan.keep]
  } catch (error) {
    $.ui.log(`fold skipped (${String(error)})`, { to: 'debug' })
    return [...ledger]
  }
}

/** The context fill as the status line shows it. Free: read off the last response. */
async function contextPercent($: EngineInterface): Promise<number> {
  const { context } = await $.session.usage()
  return context.percent ?? 0
}

/**
 * Whether the piece of work this turn answered is finished, as the small model
 * judges it from the request and the answer alone. Anything but a clear
 * `finished` keeps the context: a cut in the middle of work costs re-reading,
 * and a missed cut only waits for the next turn.
 */
async function judgeFinished($: EngineInterface, answer: string, config: Config): Promise<boolean> {
  const request = humanTurnsOf(await $.session.messages()).at(-1)?.text ?? ''
  try {
    const verdict = await $.model.classify(judgeText(request, answer), [FINISHED, UNFINISHED], { model: config.model })
    return verdict === FINISHED
  } catch (error) {
    $.ui.log(`could not judge the turn (${String(error)})`, { to: 'debug' })
    return false
  }
}

/**
 * Registers `close_task`, once, under the `outcome` setting. It stays deferred,
 * as every plugin tool is: a tool that joined the prompt's own tool list
 * mid-session would change the prefix every cached request shares.
 */
async function offerCloseTask($: EngineInterface): Promise<void> {
  if (closeTaskOffered) return
  await $.tool.register({
    name: 'close_task',
    description:
      'Call this the moment a sub-task is finished and you are moving on to the next one. ' +
      'Everything you did for it — the files you read, the commands you ran, the dead ends — ' +
      'is dropped from your context. Only the text you write in `outcome` survives, so write ' +
      'what the next sub-task will need: the decisions you made, the paths and names and ' +
      'numbers, and what is now known to be true.',
    inputSchema: {
      type: 'object',
      properties: {
        task: { type: 'string', description: 'The sub-task you are closing, in one line.' },
        outcome: { type: 'string', description: 'Everything worth carrying forward.' },
      },
      required: ['task', 'outcome'],
    },
  })
  // After the registration, so that one which failed is tried again.
  closeTaskOffered = true
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
    if (!activation.active) return result

    await sweepStaleLedgers($)
    return result
  })

  // Under `outcome` alone. Without it taskcut never touches a tool call, so the
  // working model is never offered anything and never told taskcut is there.
  if (config.outcome) {
    on('tool.call', async ($, e, next) => {
      const result = await next(e)
      // On the main loop, once a turn, and only past the floor. With the tool's
      // result rather than the person's prompt: a cut keeps prompts and drops
      // tool results, so the reminder goes with the context it was about.
      if (!activation.active || e.agentId !== undefined || e.tool === CLOSE_TOOL) return result
      if (remindedThisTurn || result.deny !== undefined) return result
      if ((await contextPercent($)) < config.floorPercent) return result
      await offerCloseTask($)
      remindedThisTurn = true
      return { ...result, context: [...(result.context ?? []), OUTCOME_REMINDER] }
    })

    on('tool.call', { tool: 'mcp__taskcut__close_task' }, async () => {
      // The conclusion is the call's own argument, so the transcript already
      // holds it; the cut reads it from there.
      return { result: 'Recorded. What you wrote is what will be kept when this sub-task is cut.' }
    })
  }

  on('turn.complete', async ($, e, next) => {
    remindedThisTurn = false

    // `next` first, so the engine has finished settling the turn before a
    // compaction is raised against it.
    const result = await next(e)
    if (!activation.active) return result

    // Only a main-loop turn the model finished. A subagent's run is not the
    // person's conversation, and a turn that was interrupted or failed stopped
    // in the middle of its work: that transcript is what explains what went
    // wrong, and it is exactly what a cut would discard.
    if (e.agentId !== undefined || e.reason !== 'answer') return result

    const percent = await contextPercent($)
    if (percent < config.floorPercent) return result

    if (!(await judgeFinished($, e.answer, config))) {
      $.ui.log(`context at ${percent}%, the work is not finished; keeping it`)
      return result
    }
    $.ui.log(`context at ${percent}%, the work is finished; dropping its working context`)

    // Between turns only: `$.session.compact` rejects while one is running, and
    // it is unavailable altogether in a headless session (`-p` or the SDK
    // transport). A failure here must not take the turn down with it.
    try {
      await $.session.compact({ instructions: COMPACTION_MARKER })
    } catch (error) {
      $.ui.log(`compaction skipped (${String(error)})`)
    }
    return result
  })

  on('session.compact', { trigger: 'plugin' }, async ($, e, next) => {
    // Someone else's plugin compaction passes straight through: this hook only
    // answers the dispatch taskcut itself raised.
    if (!activation.active || e.instructions !== COMPACTION_MARKER) return next(e)
    // What earlier cuts recorded, then everything finished since. The ledger
    // is only written and folded here, so below the floor nothing is.
    const finished = finishedWork(e.messages, await $.clock.now())
    const ledger = await foldLedger($, [...(await readLedger($)), ...finished], config)
    await writeLedger($, ledger)
    const kept = boundedHumanTurns(e.messages, config.recentHumanTurns)
    const summary: SessionMessage = { role: 'user', text: renderLedger(ledger), toolUses: [] }
    // No `next(e)`: the cut is deterministic, so no summariser runs and the
    // messages kept carry their engine handles, standing exactly as recorded.
    return { messages: [...kept, summary] }
  })

  on('session.compact', { trigger: 'auto' }, async ($, e, next) => {
    // The engine's own threshold compaction stays in place for the sub-task too
    // large to reach a boundary. Core summarises, as it would without this
    // plugin, but it is told what the finished work already settled.
    if (!activation.active) return next(e)
    const ledger = await readLedger($)
    if (ledger.length === 0) return next(e)
    const instructions = [e.instructions ?? '', renderLedger(ledger)].filter(Boolean).join('\n\n')
    return next({ ...e, instructions })
  })

  on('session.end', async ($, e, next) => {
    const result = await next(e)
    if (!activation.active) return result
    await $.store.delete(await ledgerKey($))
    return result
  })
}
