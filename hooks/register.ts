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

import { ENV_VAR, INERT, decideActivation, type Activation } from './activation'
import { readConfig, type Config } from './config'
import {
  LEDGER_PREFIX,
  boundedHumanTurns,
  directedPrompt,
  droppedMessages,
  foldPrompt,
  foldedEntry,
  subtaskReply,
  planFold,
  renderDropped,
  openingRequest,
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

/** Set by the `close_task` handler, read and cleared at the end of the turn. */
let boundaryReached = false

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

/**
 * Rewrites the entry just closed from the work itself, rather than from the
 * working model's account of it.
 *
 * A model closing its own sub-task is told nothing else will survive, and
 * answers that by writing down everything it noticed: a large record and a poor
 * conclusion. This writer is under no such pressure and knows something the
 * other did not -- the standing task, against which most of what happened does
 * not matter. It costs one small-model call per cut, out of band.
 *
 * Any failure falls back to the written outcome. A cut that cannot reach a
 * model must still cut.
 */
async function directLastEntry(
  $: EngineInterface,
  all: readonly SessionMessage[],
  kept: readonly SessionMessage[],
  config: Config,
): Promise<Entry[]> {
  const ledger = await readLedger($)
  const last = ledger[ledger.length - 1]
  const dropped = droppedMessages(all, kept)
  if (last === undefined || dropped.length === 0) return ledger
  try {
    const written = await $.model.complete({
      model: config.foldModel,
      prompt: directedPrompt(openingRequest(all), last.task, renderDropped(dropped)),
      maxTokens: 1024,
    })
    if (!written.trim()) return ledger
    const directed = [...ledger.slice(0, -1), { ...last, outcome: written.trim() }]
    await writeLedger($, directed)
    return directed
  } catch (error) {
    await $.ui.log(`taskcut: directed entry skipped (${String(error)})`)
    return ledger
  }
}

/**
 * Fills the entry just closed from the model's own last reply for it. No model
 * call, and no output spent on writing the conclusion a second time.
 */
async function replyLastEntry($: EngineInterface, all: readonly SessionMessage[]): Promise<Entry[]> {
  const ledger = await readLedger($)
  const last = ledger[ledger.length - 1]
  const reply = subtaskReply(all)
  if (last === undefined || !reply) return ledger
  const filled = [...ledger.slice(0, -1), { ...last, outcome: reply }]
  await writeLedger($, filled)
  return filled
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

    await $.tool.register({
      name: 'close_task',
      // The two modes need different descriptions, and not for tidiness: under
      // `outcome` the warning that nothing else survives is what makes the
      // model write a usable conclusion, and under `directed` it would be a
      // lie that buys an inventory nobody reads.
      description:
        config.ledgerMode === 'reply'
          ? 'Call this the moment a sub-task is finished and you are moving on to the next one. ' +
            'Name the sub-task in one line. The working context of the sub-task is dropped ' +
            'afterwards; your reply for it is what is kept, so end the sub-task by saying what ' +
            'you did and what you found, as you normally would.'
          : config.ledgerMode === 'directed'
          ? 'Call this the moment a sub-task is finished and you are moving on to the next one. ' +
            'Name what you finished and give the result in a line or two. The working context of ' +
            'the sub-task is dropped afterwards; what is kept in its place is written from the ' +
            'work itself, so you do not have to inventory it here.'
          : 'Call this the moment a sub-task is finished and you are moving on to the next one. ' +
            'Everything you did for it — the files you read, the commands you ran, the dead ends — ' +
            'is dropped from your context. Only the text you write in `outcome` survives, so write ' +
            'what the next sub-task will need: the decisions you made, the paths and names and ' +
            'numbers, and what is now known to be true.',
      // Under `reply` there is no conclusion to write: asking for one would
      // spend output on what the reply already says.
      inputSchema:
        config.ledgerMode === 'reply'
          ? {
              type: 'object',
              properties: { task: { type: 'string', description: 'The sub-task you are closing, in one line.' } },
              required: ['task'],
            }
          : {
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
    // Under `reply` there is no outcome argument; the entry is filled from the
    // reply when the cut happens.
    const outcome = e.outcome === undefined ? '' : String(e.outcome)
    ledger.push({ task: String(e.task), outcome, at: await $.clock.now() })
    const folded = await foldLedger($, ledger, config)
    await writeLedger($, folded)
    boundaryReached = true
    return { result: `Closed. ${folded.length} sub-task(s) in this session's ledger.` }
  })

  on('turn.complete', async ($, e, next) => {
    // Read and clear before anything that can throw. A turn that fails after
    // `close_task` has run leaves the conclusion in the ledger but drops the
    // boundary: if the flag survived, the next turn to complete would inherit a
    // cut it did not earn, and the transcript that explains the failure is
    // exactly what the cut would discard. The tool call has already happened by
    // the time this dispatches, so nothing is missed by reading it here.
    const reached = boundaryReached
    boundaryReached = false

    // `next` first, so the engine has finished settling the turn before a
    // compaction is raised against it.
    const result = await next(e)
    if (!activation.active || !reached) return result

    const { context } = await $.session.usage()
    if ((context.percent ?? 0) < config.floorPercent) return result

    // Between turns only: `$.session.compact` rejects while one is running, and
    // it is unavailable altogether in a headless session (`-p` or the SDK
    // transport). A failure here must not take the turn down with it.
    try {
      await $.session.compact({ instructions: COMPACTION_MARKER })
    } catch (error) {
      await $.ui.log(`taskcut: compaction skipped (${String(error)})`)
    }
    return result
  })

  on('session.compact', { trigger: 'plugin' }, async ($, e, next) => {
    // Someone else's plugin compaction passes straight through: this hook only
    // answers the dispatch taskcut itself raised.
    if (!activation.active || e.instructions !== COMPACTION_MARKER) return next(e)
    const kept = boundedHumanTurns(e.messages, config.recentHumanTurns)
    const ledger =
      config.ledgerMode === 'directed'
        ? await directLastEntry($, e.messages, kept, config)
        : config.ledgerMode === 'reply'
          ? await replyLastEntry($, e.messages)
          : await readLedger($)
    const summary: SessionMessage = { role: 'user', text: renderLedger(ledger), toolUses: [] }
    // No `next(e)`: the cut is deterministic, so no summariser runs and the
    // messages kept carry their engine handles, standing exactly as recorded.
    return { messages: [...kept, summary] }
  })

  on('session.compact', { trigger: 'auto' }, async ($, e, next) => {
    // The engine's own threshold compaction stays in place for the sub-task too
    // large to reach a boundary. Core summarises, as it would without this
    // plugin, but it is told what the closed sub-tasks already settled.
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
