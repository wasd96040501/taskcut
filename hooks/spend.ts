/**
 * What taskcut has spent in a session, as pure functions of plain data.
 *
 * The judge's calls are taskcut's own cost, and nothing else counts them:
 * `$.model.complete` is not on the session's cost ledger, so `/cost` and the
 * status line leave them out, and they are not in the transcript. Each call
 * resolves the API's own token counts, so the tally is exact and free to keep:
 * a sum of numbers already in hand, held in memory, never written anywhere.
 *
 * It is shown two ways. `/taskcut` gives the session's totals. The debug log
 * (`claude --debug`, or `--debug-file`) gets one line per judgement, in a
 * format kept stable so that a harness can add the lines up: see
 * `judgementLine`.
 *
 * Tokens, not dollars: a price is the host's to know -- it differs by model,
 * by plan and by contract -- and a price list in a plugin would be wrong the
 * day it changed.
 */

/** The four token counts a call reports, as the API does. */
export type Usage = {
  input_tokens: number
  output_tokens: number
  cache_read_input_tokens: number
  cache_creation_input_tokens: number
}

export type Spend = {
  /** Calls made to the judge. */
  judgements: number
  /** Of those, the calls that came back without an answer. */
  unanswered: number
  /** Of those, the calls whose cost the engine did not report (before 2.1.280). */
  unmetered: number
  input: number
  cacheRead: number
  cacheWrite: number
  output: number
  /** Compactions taskcut started, and the context before and after them, summed. */
  compactions: number
  compactedFrom: number
  compactedTo: number
}

export const NOTHING: Spend = {
  judgements: 0,
  unanswered: 0,
  unmetered: 0,
  input: 0,
  cacheRead: 0,
  cacheWrite: 0,
  output: 0,
  compactions: 0,
  compactedFrom: 0,
  compactedTo: 0,
}

function count(value: unknown): number | undefined {
  return typeof value === 'number' && Number.isFinite(value) && value >= 0 ? value : undefined
}

/**
 * The token counts a model call resolved with, whichever shape it had; none
 * when it reported none, as a reply that was only text did up to 2.1.278.
 */
export function readUsage(answer: unknown): Usage | undefined {
  if (typeof answer !== 'object' || answer === null || !('usage' in answer)) return undefined
  const usage = (answer as { usage: unknown }).usage
  if (typeof usage !== 'object' || usage === null) return undefined
  const fields = usage as Record<string, unknown>
  const input = count(fields.input_tokens)
  const output = count(fields.output_tokens)
  if (input === undefined || output === undefined) return undefined
  return {
    input_tokens: input,
    output_tokens: output,
    cache_read_input_tokens: count(fields.cache_read_input_tokens) ?? 0,
    cache_creation_input_tokens: count(fields.cache_creation_input_tokens) ?? 0,
  }
}

/** The tally with one more judgement in it. */
export function addJudgement(spend: Spend, usage: Usage | undefined, answered: boolean): Spend {
  return {
    ...spend,
    judgements: spend.judgements + 1,
    unanswered: spend.unanswered + (answered ? 0 : 1),
    unmetered: spend.unmetered + (usage ? 0 : 1),
    input: spend.input + (usage?.input_tokens ?? 0),
    cacheRead: spend.cacheRead + (usage?.cache_read_input_tokens ?? 0),
    cacheWrite: spend.cacheWrite + (usage?.cache_creation_input_tokens ?? 0),
    output: spend.output + (usage?.output_tokens ?? 0),
  }
}

/** The tally with one more compaction in it, and the context either side of it when the engine said. */
export function addCompaction(spend: Spend, before: number | undefined, after: number | undefined): Spend {
  const known = count(before) !== undefined && count(after) !== undefined
  return {
    ...spend,
    compactions: spend.compactions + 1,
    compactedFrom: spend.compactedFrom + (known ? before! : 0),
    compactedTo: spend.compactedTo + (known ? after! : 0),
  }
}

/**
 * The debug line for one judgement:
 *
 *     context at 41%, step judged the same work [judge sonnet: in=1834 cache_read=0 cache_write=0 out=52 ms=2140]
 *
 * The bracket is the record: the model asked, the four token counts and how
 * long the call took. It is left out when the engine reported no counts. Its
 * format is part of what taskcut promises, because the benchmark reads it.
 */
export function judgementLine(percent: number, verdict: string, model: string, usage: Usage | undefined, ms: number): string {
  const record = usage
    ? ` [judge ${model}: in=${usage.input_tokens} cache_read=${usage.cache_read_input_tokens} cache_write=${usage.cache_creation_input_tokens} out=${usage.output_tokens} ms=${Math.round(ms)}]`
    : ''
  return `context at ${percent}%, ${verdict}${record}`
}

function thousands(n: number): string {
  return Math.round(n).toLocaleString('en-US')
}

function plural(n: number, one: string, many = `${one}s`): string {
  return `${thousands(n)} ${n === 1 ? one : many}`
}

/** What `/taskcut` says: whether taskcut is at work in this session, and what it has spent. */
export function spendReport(
  spend: Spend,
  state: { active: boolean; interactive: boolean; floorPercent: number; model: string; percent: number | undefined },
): string {
  const lines: string[] = []
  if (!state.active) lines.push('taskcut is off in this session (TASKCUT=0).')
  else if (!state.interactive) lines.push('taskcut does nothing in a session nobody is at: it cannot compact there.')
  else {
    const now = state.percent === undefined ? '' : ` The context is at ${state.percent}%.`
    lines.push(`taskcut is on: past ${state.floorPercent}% of the context, ${state.model} judges each step.${now}`)
  }

  if (spend.judgements === 0) {
    lines.push('Nothing judged yet, so nothing spent.')
    return lines.join('\n')
  }
  const read = spend.input + spend.cacheRead + spend.cacheWrite
  const cached = spend.cacheRead > 0 ? ` (${thousands(spend.cacheRead)} from the cache)` : ''
  const failed = spend.unanswered > 0 ? `, ${thousands(spend.unanswered)} of them unanswered` : ''
  lines.push(`Judged ${plural(spend.judgements, 'step')}${failed}: ${thousands(read)} tokens read${cached}, ${thousands(spend.output)} written.`)
  if (spend.unmetered > 0) lines.push(`${plural(spend.unmetered, 'call')} reported no token counts, and ${spend.unmetered === 1 ? 'is' : 'are'} not in these.`)
  if (spend.compactions > 0) {
    const sizes = spend.compactedFrom > 0 ? `, ${thousands(spend.compactedFrom)} tokens of context down to ${thousands(spend.compactedTo)}` : ''
    lines.push(`Compacted ${plural(spend.compactions, 'time')}${sizes}.`)
  }
  lines.push("/cost does not count the judge's calls: they are all here. It does count the compactions, which are Claude Code's own.")
  return lines.join('\n')
}
