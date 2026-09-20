/** The plugin's settings, as `/config` collects them and `register` receives them. */

import type { PluginOptions } from 'claude-code'

export type Config = {
  /** Context fill, as a percentage, below which a closed sub-task does not trigger a cut. */
  floorPercent: number
  /** How many of the most recent human turns are kept beside the first one. */
  recentHumanTurns: number
  /** How many ledger entries stay in the model's own words before the oldest are folded. */
  ledgerVerbatim: number
  /** The model that folds them, as a `--model` value. */
  foldModel: string
}

export const DEFAULTS: Config = {
  floorPercent: 40,
  recentHumanTurns: 2,
  ledgerVerbatim: 12,
  foldModel: 'haiku',
}

function numberOr(value: unknown, fallback: number, min: number): number {
  const parsed = typeof value === 'number' ? value : Number(value)
  if (!Number.isFinite(parsed) || parsed < min) return fallback
  return parsed
}

/** Reads the settings, falling back to the defaults for anything unset or out of range. */
export function readConfig(options: PluginOptions): Config {
  return {
    floorPercent: numberOr(options['floorPercent'], DEFAULTS.floorPercent, 0),
    recentHumanTurns: numberOr(options['recentHumanTurns'], DEFAULTS.recentHumanTurns, 0),
    ledgerVerbatim: numberOr(options['ledgerVerbatim'], DEFAULTS.ledgerVerbatim, 2),
    foldModel: typeof options['foldModel'] === 'string' && options['foldModel'] ? options['foldModel'] : DEFAULTS.foldModel,
  }
}
