/**
 * taskcut: compaction at sub-task boundaries.
 *
 * The engine compacts when the context window fills, which is rarely the moment
 * a piece of work ends. This module moves the decision to the boundary the model
 * itself declares. It registers one tool, `close_task`; the argument the model
 * passes to it is the conclusion, and it is the only thing that survives. At the
 * end of that turn, if the window has filled past the configured floor, a
 * `session.compact` hook answers with a transcript it builds itself: the human
 * turns, kept whole by their engine handles, followed by the ledger. It never
 * calls `next` on that dispatch, so no summariser runs and nothing kept is
 * paraphrased.
 *
 * Everything that touches `$` is declared here, at the top level of this file:
 * the loader follows `$` into a function declared in the same module and refuses
 * one imported from another.
 */

import type { EngineInterface, Register, SessionMessage } from 'claude-code'

import { readConfig, type Config } from './config'
import {
  LEDGER_PREFIX,
  boundedHumanTurns,
  foldPrompt,
  foldedEntry,
  planFold,
  renderLedger,
  staleLedgerKeys,
  type Entry,
} from './ledger'

/** Set by the `close_task` handler, read and cleared at the end of the turn. */
let boundaryReached = false

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
 */
async function foldLedger($: EngineInterface, ledger: readonly Entry[], config: Config): Promise<Entry[]> {
  const plan = planFold(ledger, config.ledgerVerbatim)
  if (plan === null) return [...ledger]
  const rolled = await $.model.complete({
    model: config.foldModel,
    prompt: foldPrompt(plan.fold),
    maxTokens: 1024,
  })
  return [foldedEntry(plan.fold, rolled), ...plan.keep]
}

export const register: Register = (on, options) => {
  const config = readConfig(options)

  on('session.start', async ($, e, next) => {
    const result = await next(e)
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
    await sweepStaleLedgers($)
    return result
  })

  on('tool.call', { tool: 'mcp__taskcut__close_task' }, async ($, e) => {
    const ledger = await readLedger($)
    ledger.push({ task: String(e.task), outcome: String(e.outcome), at: await $.clock.now() })
    const folded = await foldLedger($, ledger, config)
    await writeLedger($, folded)
    boundaryReached = true
    return { result: `Closed. ${folded.length} sub-task(s) in this session's ledger.` }
  })

  on('turn.complete', async ($, e, next) => {
    const result = await next(e)
    if (!boundaryReached) return result
    boundaryReached = false

    const { context } = await $.session.usage()
    if ((context.percent ?? 0) < config.floorPercent) return result

    // Between turns only: `$.session.compact` rejects while one is running, and
    // it is unavailable altogether in a headless session (`-p` or the SDK
    // transport). A failure here must not take the turn down with it.
    try {
      await $.session.compact({ instructions: 'taskcut: sub-task boundary' })
    } catch (error) {
      await $.ui.log(`taskcut: compaction skipped (${String(error)})`)
    }
    return result
  })

  on('session.compact', { trigger: 'plugin' }, async ($, e) => {
    const ledger = await readLedger($)
    const summary: SessionMessage = { role: 'user', text: renderLedger(ledger), toolUses: [] }
    // No `next(e)`: the cut is deterministic, so no summariser runs and the
    // messages kept carry their engine handles, standing exactly as recorded.
    return { messages: [...boundedHumanTurns(e.messages, config.recentHumanTurns), summary] }
  })

  on('session.compact', { trigger: 'auto' }, async ($, e, next) => {
    // The engine's own threshold compaction stays in place for the sub-task too
    // large to reach a boundary. Core summarises, as it would without this
    // plugin, but it is told what the closed sub-tasks already settled.
    const ledger = await readLedger($)
    if (ledger.length === 0) return next(e)
    const instructions = [e.instructions ?? '', renderLedger(ledger)].filter(Boolean).join('\n\n')
    return next({ ...e, instructions })
  })

  on('session.end', async ($, e, next) => {
    const result = await next(e)
    await $.store.delete(await ledgerKey($))
    return result
  })
}
