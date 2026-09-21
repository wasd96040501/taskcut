/** The plugin's settings, as `/plugin` collects them and `register` receives them. */

import type { PluginOptions } from 'claude-code'

export type Config = {
  /** Context fill, as a percentage, below which taskcut does nothing at all. */
  floorPercent: number
  /** The small model that judges whether a turn's work is finished, as a `--model` value. */
  model: string
}

export const DEFAULTS: Config = {
  floorPercent: 40,
  model: 'haiku',
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
    model: typeof options['model'] === 'string' && options['model'] ? options['model'] : DEFAULTS.model,
  }
}
