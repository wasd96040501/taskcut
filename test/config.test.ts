import { test, describe } from 'node:test'
import assert from 'node:assert/strict'

import { DEFAULTS, REGROWTH, judgingFrom, readConfig } from '../hooks/config.ts'

describe('judgingFrom', () => {
  test('is the floor before any compaction', () => {
    assert.equal(judgingFrom(35, undefined), 35)
  })

  test('a floor of 0 judges from the first step', () => {
    // It once waited for 5%: an unset "left at" read as a compaction that left 0%.
    assert.equal(judgingFrom(0, undefined), 0)
  })

  test('is the floor again once a compaction took the context under it', () => {
    assert.equal(judgingFrom(35, 12), 35)
  })

  test('waits for regrowth after a compaction that could not get under it', () => {
    assert.equal(judgingFrom(35, 40), 40 + REGROWTH)
    assert.equal(judgingFrom(0, 3), 3 + REGROWTH)
  })
})

describe('readConfig', () => {
  test('returns the defaults for an empty manifest', () => {
    assert.deepEqual(readConfig({}), DEFAULTS)
  })

  test('reads values that are in range', () => {
    assert.deepEqual(readConfig({ floorPercent: 0, model: 'haiku' }), { floorPercent: 0, model: 'haiku' })
  })

  test('accepts a numeric string, as a settings file may hold one', () => {
    assert.equal(readConfig({ floorPercent: '60' }).floorPercent, 60)
  })

  test('falls back rather than accepting a value out of range', () => {
    assert.equal(readConfig({ floorPercent: -1 }).floorPercent, DEFAULTS.floorPercent)
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

  test('the shipped floor is a real threshold', () => {
    // Zero would judge every turn and compact at every finished one, spending
    // the prompt cache each time.
    assert.ok(DEFAULTS.floorPercent > 0)
  })

  test('ignores settings earlier versions had', () => {
    const old = { ledgerMode: 'directed', foldModel: 'opus', outcome: true, recentHumanTurns: 5, ledgerVerbatim: 3 }
    assert.deepEqual(readConfig(old as never), DEFAULTS)
  })
})
