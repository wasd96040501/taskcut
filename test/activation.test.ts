import { test, describe } from 'node:test'
import assert from 'node:assert/strict'

import { ENV_VAR, INERT, decideActivation } from '../hooks/activation.ts'

describe('decideActivation', () => {
  test('an installed session is active, because installing it is the consent', () => {
    assert.equal(decideActivation({ env: undefined }).active, true)
  })

  test('the environment switches a single session off', () => {
    for (const value of ['0', 'off', 'false', 'no', 'OFF', ' 0 ']) {
      assert.equal(decideActivation({ env: value }).active, false, value)
    }
  })

  test('and switches one back on', () => {
    for (const value of ['1', 'on', 'true', 'yes', 'YES', ' 1 ']) {
      assert.equal(decideActivation({ env: value }).active, true, value)
    }
  })

  test('an unrecognised value is not an off switch', () => {
    // A typo that silently disabled the plugin is the failure hardest to
    // notice: nothing happens, and nothing says why.
    for (const value of ['maybe', 'ON!', 'ture', '']) {
      assert.equal(decideActivation({ env: value }).active, true, value)
    }
  })

  test('every decision says why', () => {
    assert.match(decideActivation({ env: '0' }).reason, new RegExp(ENV_VAR))
    assert.match(decideActivation({ env: '1' }).reason, new RegExp(ENV_VAR))
    assert.match(decideActivation({ env: undefined }).reason, /installed/)
  })
})

describe('INERT', () => {
  test('is inactive, so a session whose start hook never ran does nothing', () => {
    assert.equal(INERT.active, false)
    assert.match(INERT.reason, /session\.start/)
  })
})
