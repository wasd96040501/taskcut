import { test, describe } from 'node:test'
import assert from 'node:assert/strict'

import { NOTHING, addCompaction, addJudgement, judgementLine, readUsage, spendReport } from '../hooks/spend.ts'

const usage = { input_tokens: 1834, output_tokens: 52, cache_read_input_tokens: 0, cache_creation_input_tokens: 0 }
const on = { active: true, interactive: true, floorPercent: 35, model: 'sonnet', percent: 41 }

describe('readUsage', () => {
  test('reads the counts an answered call resolves with', () => {
    assert.deepEqual(readUsage({ isAnswered: true, text: 'SAME', usage }), usage)
  })

  test('reads them off an unanswered call too, which may still have cost', () => {
    assert.deepEqual(readUsage({ isAnswered: false, reason: 'empty-reply', usage }), usage)
  })

  test('none from a reply that was only text, as up to 2.1.278', () => {
    assert.equal(readUsage('It moves on.\nNEXT'), undefined)
  })

  test('none from anything that is not counts', () => {
    for (const odd of [undefined, null, {}, { usage: null }, { usage: {} }, { usage: { input_tokens: -1, output_tokens: 1 } }, { usage: { input_tokens: '5', output_tokens: 1 } }]) {
      assert.equal(readUsage(odd), undefined, JSON.stringify(odd))
    }
  })

  test('a cache count left out is none used', () => {
    assert.deepEqual(readUsage({ usage: { input_tokens: 3, output_tokens: 4 } }), { input_tokens: 3, output_tokens: 4, cache_read_input_tokens: 0, cache_creation_input_tokens: 0 })
  })
})

describe('addJudgement', () => {
  test('sums every count', () => {
    const cached = { input_tokens: 10, output_tokens: 5, cache_read_input_tokens: 1000, cache_creation_input_tokens: 20 }
    const spend = addJudgement(addJudgement(NOTHING, usage, true), cached, true)
    assert.equal(spend.judgements, 2)
    assert.equal(spend.input, 1844)
    assert.equal(spend.cacheRead, 1000)
    assert.equal(spend.cacheWrite, 20)
    assert.equal(spend.output, 57)
    assert.equal(spend.unanswered, 0)
  })

  test('counts a call that went unanswered, and what it cost', () => {
    const spend = addJudgement(NOTHING, usage, false)
    assert.equal(spend.unanswered, 1)
    assert.equal(spend.input, 1834)
  })

  test('counts a call that reported no cost, apart', () => {
    const spend = addJudgement(NOTHING, undefined, true)
    assert.equal(spend.judgements, 1)
    assert.equal(spend.unmetered, 1)
    assert.equal(spend.input, 0)
  })

  test('leaves the tally it was given alone', () => {
    addJudgement(NOTHING, usage, true)
    assert.equal(NOTHING.judgements, 0)
  })
})

describe('addCompaction', () => {
  test('counts it, and the context either side', () => {
    const spend = addCompaction(NOTHING, 431_567, 10_511)
    assert.equal(spend.compactions, 1)
    assert.equal(spend.compactedFrom, 431_567)
    assert.equal(spend.compactedTo, 10_511)
  })

  test('counts it without sizes the engine did not give', () => {
    const spend = addCompaction(NOTHING, 431_567, undefined)
    assert.equal(spend.compactions, 1)
    assert.equal(spend.compactedFrom, 0)
    assert.equal(spend.compactedTo, 0)
  })
})

describe('judgementLine', () => {
  test('carries the verdict and a record the benchmark reads', () => {
    assert.equal(
      judgementLine(41, 'step judged the same work', 'sonnet', usage, 2140.4),
      'context at 41%, step judged the same work [judge sonnet: in=1834 cache_read=0 cache_write=0 out=52 ms=2140]',
    )
  })

  test('has no record when the engine reported no counts', () => {
    assert.equal(judgementLine(41, 'step judged a new piece', 'haiku', undefined, 10), 'context at 41%, step judged a new piece')
  })

  test('keeps to a shape a harness can parse', () => {
    const line = judgementLine(60, 'could not judge the step (api-error 429 rate_limit)', 'claude-sonnet-5', usage, 5)
    const match = /\[judge (\S+): in=(\d+) cache_read=(\d+) cache_write=(\d+) out=(\d+) ms=(\d+)\]$/.exec(line)
    assert.ok(match, line)
    assert.deepEqual(match!.slice(1).map(String), ['claude-sonnet-5', '1834', '0', '0', '52', '5'])
  })
})

describe('spendReport', () => {
  test('says nothing was spent before the floor', () => {
    const text = spendReport(NOTHING, { ...on, percent: 12 })
    assert.match(text, /taskcut is on: past 35% of the context, sonnet judges each step\. The context is at 12%\./)
    assert.match(text, /Nothing judged yet/)
  })

  test('gives the totals, and says /cost does not have them', () => {
    let spend = addJudgement(NOTHING, usage, true)
    spend = addJudgement(spend, { ...usage, cache_read_input_tokens: 500 }, false)
    spend = addCompaction(spend, 431_567, 10_511)
    const text = spendReport(spend, on)
    assert.match(text, /Judged 2 steps, 1 of them unanswered: 4,168 tokens read \(500 from the cache\), 104 written\./)
    assert.match(text, /Compacted 1 time, 431,567 tokens of context down to 10,511\./)
    assert.match(text, /\/cost does not count the judge's calls/)
  })

  test('says when some calls reported no counts', () => {
    const text = spendReport(addJudgement(NOTHING, undefined, true), on)
    assert.match(text, /1 call reported no token counts, and is not in these\./)
  })

  test('says when taskcut is off, or cannot act', () => {
    assert.match(spendReport(NOTHING, { ...on, active: false }), /off in this session/)
    assert.match(spendReport(NOTHING, { ...on, interactive: false }), /nobody is at/)
  })
})
