/** The plugin's settings, as `/plugin` collects them and `register` receives them. */

import type { PluginOptions } from 'claude-code'

export type Config = {
  /** Context fill, as a percentage, below which taskcut does nothing at all. */
  floorPercent: number
  /** The model that judges whether a step finished a piece of the work, as a `--model` value. */
  model: string
}

export const DEFAULTS: Config = {
  floorPercent: 35,
  model: 'sonnet',
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

/**
 * How far past the context a compaction left it the next judgement waits, when
 * that compaction could not bring it back under the floor: so that the same
 * finished work is not compacted again and again.
 */
export const REGROWTH = 5

/**
 * The context fill from which steps are judged: the floor, or -- after a
 * compaction that left the context at or over it -- REGROWTH points past what
 * it left. Before any compaction there is nothing it left, and the floor
 * alone decides: a floor of 0 judges from the first step.
 */
export function judgingFrom(floorPercent: number, leftAt: number | undefined): number {
  return leftAt !== undefined && leftAt >= floorPercent ? leftAt + REGROWTH : floorPercent
}
