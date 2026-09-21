/** The plugin's settings, as `/config` collects them and `register` receives them. */

import type { PluginOptions } from 'claude-code'

export type Config = {
  /** Context fill, as a percentage, below which taskcut does nothing at all. */
  floorPercent: number
  /** How many of the most recent human turns are kept beside the first one. */
  recentHumanTurns: number
  /** How many ledger entries stay in the model's own words before the oldest are folded. */
  ledgerVerbatim: number
  /**
   * The small model taskcut asks, as a `--model` value: whether a sub-task is
   * finished, and to fold the ledger. It is never asked below the floor.
   */
  model: string
  /**
   * Whether the working model is asked to write down what to carry forward
   * from each sub-task, with a `close_task` tool offered once the context is
   * past the floor. Off, nothing is asked of it and its own answer is what the
   * ledger keeps, so taskcut costs it no output at all.
   */
  outcome: boolean
}

export const DEFAULTS: Config = {
  floorPercent: 40,
  recentHumanTurns: 2,
  ledgerVerbatim: 12,
  model: 'haiku',
  outcome: false,
}

function numberOr(value: unknown, fallback: number, min: number): number {
  // Only a number, or a string that actually spells one. `Number(null)`,
  // `Number('')` and `Number([])` are all 0, so a blank left in a settings file
  // would otherwise read as a deliberate zero.
  const parsed =
    typeof value === 'number'
      ? value
      : typeof value === 'string' && value.trim() !== ''
        ? Number(value)
        : Number.NaN
  if (!Number.isFinite(parsed) || parsed < min) return fallback
  return parsed
}

/** Reads the settings, falling back to the defaults for anything unset or out of range. */
export function readConfig(options: PluginOptions): Config {
  return {
    floorPercent: numberOr(options['floorPercent'], DEFAULTS.floorPercent, 0),
    recentHumanTurns: numberOr(options['recentHumanTurns'], DEFAULTS.recentHumanTurns, 0),
    ledgerVerbatim: numberOr(options['ledgerVerbatim'], DEFAULTS.ledgerVerbatim, 2),
    model: typeof options['model'] === 'string' && options['model'] ? options['model'] : DEFAULTS.model,
    outcome: options['outcome'] === true || options['outcome'] === 'true',
  }
}
