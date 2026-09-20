import { test, describe } from 'node:test'
import assert from 'node:assert/strict'

import {
  ENV_VAR,
  INERT,
  MARKER_FILE,
  decideActivation,
  readActivationMode,
  type ActivationInputs,
} from '../hooks/activation.ts'

const base: ActivationInputs = { mode: 'opt-in', markerPresent: false, env: undefined }

describe('decideActivation', () => {
  test('is inert when nothing opts in', () => {
    assert.equal(decideActivation(base).active, false)
  })

  test('a marker at the project root opts the repository in', () => {
    assert.equal(decideActivation({ ...base, markerPresent: true }).active, true)
  })

  test('always runs everywhere', () => {
    assert.equal(decideActivation({ ...base, mode: 'always' }).active, true)
  })

  for (const value of ['1', 'on', 'true', 'yes', 'YES', ' On ']) {
    test(`${ENV_VAR}=${JSON.stringify(value)} opts a session in`, () => {
      assert.equal(decideActivation({ ...base, env: value }).active, true)
    })
  }

  for (const value of ['0', 'off', 'false', 'no', 'OFF']) {
    test(`${ENV_VAR}=${JSON.stringify(value)} is a kill switch`, () => {
      // It has to beat every other way of turning taskcut on, or it is not one.
      assert.equal(decideActivation({ ...base, env: value }).active, false)
      assert.equal(decideActivation({ ...base, env: value, mode: 'always' }).active, false)
      assert.equal(decideActivation({ ...base, env: value, markerPresent: true }).active, false)
    })
  }

  test('an unrecognised value neither opts in nor kills', () => {
    assert.equal(decideActivation({ ...base, env: 'maybe' }).active, false)
    assert.equal(decideActivation({ ...base, env: 'maybe', markerPresent: true }).active, true)
  })

  test('every decision carries a reason', () => {
    for (const inputs of [base, { ...base, markerPresent: true }, { ...base, env: '0' }]) {
      assert.match(decideActivation(inputs).reason, /\S/)
    }
  })

  test('the pre-session state is inert', () => {
    // A session in which session.start never runs must do nothing, not everything.
    assert.equal(INERT.active, false)
  })

  test('the marker is a plain dotfile a repository can commit', () => {
    assert.equal(MARKER_FILE, '.taskcut')
  })
})

describe('readActivationMode', () => {
  test('reads the two known modes', () => {
    assert.equal(readActivationMode('always'), 'always')
    assert.equal(readActivationMode('opt-in'), 'opt-in')
  })

  test('falls back to the safe mode for anything else', () => {
    for (const value of [undefined, null, '', 'ALWAYS', 'yes', 1, true, {}]) {
      assert.equal(readActivationMode(value), 'opt-in')
    }
  })
})
