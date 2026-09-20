import { test, describe } from 'node:test'
import assert from 'node:assert/strict'

import { DEFAULTS, readConfig } from '../hooks/config.ts'

describe('readConfig', () => {
  test('returns the defaults for an empty manifest', () => {
    assert.deepEqual(readConfig({}), DEFAULTS)
  })

  test('reads values that are in range', () => {
    const config = readConfig({ floorPercent: 0, recentHumanTurns: 5, ledgerVerbatim: 4, foldModel: 'sonnet', ledgerMode: 'outcome' })
    assert.deepEqual(config, { floorPercent: 0, recentHumanTurns: 5, ledgerVerbatim: 4, foldModel: 'sonnet', ledgerMode: 'outcome' })
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
    assert.equal(readConfig({ foldModel: '' }).foldModel, DEFAULTS.foldModel)
    assert.equal(readConfig({ foldModel: 7 as never }).foldModel, DEFAULTS.foldModel)
  })

  test('the shipped defaults are the cautious ones', () => {
    // A floor of zero would cut at every boundary and spend the prompt cache
    // each time; the default has to be a real threshold.
    assert.ok(DEFAULTS.floorPercent > 0)
    assert.ok(DEFAULTS.recentHumanTurns >= 1)
    assert.ok(DEFAULTS.ledgerVerbatim >= 2)
  })
})

describe('ledgerMode', () => {
  test('takes the directed mode when it is asked for by name', () => {
    assert.equal(readConfig({ ledgerMode: 'directed' }).ledgerMode, 'directed')
  })

  test('falls back to outcome for anything it does not recognise', () => {
    for (const value of ['DIRECTED', 'smart', '', null, undefined, 1, {}]) {
      assert.equal(readConfig({ ledgerMode: value } as never).ledgerMode, 'outcome')
    }
  })
})
