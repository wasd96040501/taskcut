import { test, describe } from 'node:test'
import assert from 'node:assert/strict'

import { DEFAULTS, readConfig } from '../hooks/config.ts'

describe('readConfig', () => {
  test('returns the defaults for an empty manifest', () => {
    assert.deepEqual(readConfig({}), DEFAULTS)
  })

  test('reads values that are in range', () => {
    const config = readConfig({ floorPercent: 0, recentHumanTurns: 5, ledgerVerbatim: 4, model: 'sonnet', outcome: true })
    assert.deepEqual(config, { floorPercent: 0, recentHumanTurns: 5, ledgerVerbatim: 4, model: 'sonnet', outcome: true })
  })

  test('accepts a numeric string, as a settings file may hold one', () => {
    assert.equal(readConfig({ floorPercent: '60' }).floorPercent, 60)
  })

  test('falls back rather than accepting a value out of range', () => {
    assert.equal(readConfig({ floorPercent: -1 }).floorPercent, DEFAULTS.floorPercent)
    assert.equal(readConfig({ recentHumanTurns: -3 }).recentHumanTurns, DEFAULTS.recentHumanTurns)
    // Folding needs at least two entries to have an oldest and a newest half.
    assert.equal(readConfig({ ledgerVerbatim: 1 }).ledgerVerbatim, DEFAULTS.ledgerVerbatim)
  })

  test('falls back for anything that is not a number', () => {
    for (const value of [undefined, null, '', 'lots', NaN, Infinity, {}, []]) {
      assert.equal(readConfig({ floorPercent: value as never }).floorPercent, DEFAULTS.floorPercent)
    }
  })

  test('falls back for an empty or non-string model', () => {
    assert.equal(readConfig({ model: '' }).model, DEFAULTS.model)
    assert.equal(readConfig({ model: 7 as never }).model, DEFAULTS.model)
  })

  test('the shipped defaults are the cautious ones', () => {
    // A floor of zero would cut at every boundary and spend the prompt cache
    // each time; the default has to be a real threshold.
    assert.ok(DEFAULTS.floorPercent > 0)
    assert.ok(DEFAULTS.recentHumanTurns >= 1)
    assert.ok(DEFAULTS.ledgerVerbatim >= 2)
  })
})

describe('outcome', () => {
  test('is off unless asked for, so the working model is asked for nothing', () => {
    assert.equal(DEFAULTS.outcome, false)
    for (const value of [undefined, null, false, 'false', '', 0, 'yes', {}]) {
      assert.equal(readConfig({ outcome: value } as never).outcome, false)
    }
  })

  test('is on for true, as a boolean or as a settings file may spell it', () => {
    assert.equal(readConfig({ outcome: true }).outcome, true)
    assert.equal(readConfig({ outcome: 'true' }).outcome, true)
  })

  test('ignores the settings 0.4.0 had', () => {
    assert.deepEqual(readConfig({ ledgerMode: 'directed', foldModel: 'opus' } as never), DEFAULTS)
  })
})
