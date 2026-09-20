import { test, describe } from 'node:test'
import assert from 'node:assert/strict'

import {
  LEDGER_PREFIX,
  STALE_LEDGER_MS,
  boundedHumanTurns,
  foldPrompt,
  foldedEntry,
  humanTurnsOf,
  planFold,
  renderLedger,
  staleLedgerKeys,
  type Entry,
} from '../hooks/ledger.ts'

type Message = Parameters<typeof humanTurnsOf>[0][number]

function entry(n: number, at = n): Entry {
  return { task: `task ${n}`, outcome: `outcome ${n}`, at }
}

function human(text: string): Message {
  return { role: 'user', text, toolUses: [] }
}

function assistantWithCall(id: string): Message {
  return { role: 'assistant', text: '', toolUses: [{ tool_use_id: id, tool: 'Bash', input: {} }] }
}

function toolResult(id: string): Message {
  return { role: 'user', text: '', toolUses: [], toolResults: [{ tool_use_id: id, text: 'out', isError: false }] }
}

describe('humanTurnsOf', () => {
  test('keeps user turns that carry no tool result', () => {
    const kept = humanTurnsOf([human('a'), assistantWithCall('t1'), toolResult('t1'), human('b')])
    assert.deepEqual(kept.map((m) => m.text), ['a', 'b'])
  })

  test('drops both halves of every tool pair together', () => {
    // This is the invariant the API enforces: an assistant message holding a
    // tool_use whose tool_result is gone makes a conversation that is rejected.
    const messages = [human('a'), assistantWithCall('t1'), toolResult('t1')]
    const kept = humanTurnsOf(messages)
    const keptIds = new Set(kept.flatMap((m) => (m.toolResults ?? []).map((r) => r.tool_use_id)))
    const keptCalls = new Set(kept.flatMap((m) => m.toolUses.map((u) => u.tool_use_id)))
    assert.equal(keptIds.size, 0, 'no orphan tool results')
    assert.equal(keptCalls.size, 0, 'no orphan tool calls')
  })

  test('keeps nothing from an empty transcript', () => {
    assert.deepEqual(humanTurnsOf([]), [])
  })
})

describe('boundedHumanTurns', () => {
  const turns = [human('goal'), human('b'), human('c'), human('d'), human('e')]

  test('keeps the turn that set the standing task, whatever else goes', () => {
    assert.equal(boundedHumanTurns(turns, 2)[0]?.text, 'goal')
  })

  test('keeps the first plus the most recent N', () => {
    assert.deepEqual(boundedHumanTurns(turns, 2).map((m) => m.text), ['goal', 'd', 'e'])
  })

  test('does not duplicate when the transcript is shorter than the bound', () => {
    const short = [human('goal'), human('b')]
    assert.deepEqual(boundedHumanTurns(short, 2).map((m) => m.text), ['goal', 'b'])
  })

  test('stays bounded however long the run gets', () => {
    // The growth this bound exists to stop: one human turn per loop iteration.
    const many = Array.from({ length: 500 }, (_, i) => human(`turn ${i}`))
    assert.equal(boundedHumanTurns(many, 2).length, 3)
  })

  test('a bound of zero keeps the standing task alone', () => {
    assert.deepEqual(boundedHumanTurns(turns, 0).map((m) => m.text), ['goal'])
  })
})

describe('planFold', () => {
  test('leaves a short ledger alone', () => {
    assert.equal(planFold([entry(1), entry(2)], 12), null)
    assert.equal(planFold(Array.from({ length: 12 }, (_, i) => entry(i)), 12), null)
  })

  test('folds the oldest and keeps the recent verbatim', () => {
    const ledger = Array.from({ length: 13 }, (_, i) => entry(i))
    const plan = planFold(ledger, 12)
    assert.ok(plan)
    assert.equal(plan.fold.length + plan.keep.length, ledger.length, 'nothing is lost')
    assert.equal(plan.keep.at(-1)?.task, 'task 12', 'the newest entry stays verbatim')
    assert.equal(plan.fold[0]?.task, 'task 0', 'the oldest is the first folded')
  })

  test('keeps the ledger bounded across repeated folds', () => {
    let ledger = [entry(0)]
    for (let i = 1; i < 200; i++) {
      ledger.push(entry(i))
      const plan = planFold(ledger, 12)
      if (plan) ledger = [foldedEntry(plan.fold, 'rolled'), ...plan.keep]
    }
    assert.ok(ledger.length <= 12, `ledger grew to ${ledger.length}`)
  })
})

describe('foldedEntry', () => {
  test('carries the timestamp of the newest entry it folded', () => {
    const folded = foldedEntry([entry(1, 100), entry(2, 300)], '  rolled up  ')
    assert.equal(folded.at, 300)
    assert.equal(folded.outcome, 'rolled up')
    assert.match(folded.task, /2 earlier sub-tasks/)
  })
})

describe('foldPrompt', () => {
  test('carries every entry it is asked to fold', () => {
    const prompt = foldPrompt([entry(1), entry(2)])
    assert.match(prompt, /task 1/)
    assert.match(prompt, /outcome 2/)
  })
})

describe('renderLedger', () => {
  test('says so when nothing has been closed', () => {
    assert.match(renderLedger([]), /No sub-tasks/)
  })

  test('marks entries closed and says not to redo them', () => {
    // A ledger that lists findings without stating they are settled reads as an
    // open to-do list, and the model redoes the work.
    const text = renderLedger([entry(1)])
    assert.match(text, /\[CLOSED\]/)
    assert.match(text, /Do not redo them/)
  })

  test('carries every conclusion', () => {
    const text = renderLedger([entry(1), entry(2), entry(3)])
    for (const n of [1, 2, 3]) assert.match(text, new RegExp(`outcome ${n}`))
  })
})

describe('staleLedgerKeys', () => {
  const now = 10 * STALE_LEDGER_MS
  const current = `${LEDGER_PREFIX}current`

  test('drops a ledger whose newest entry is older than the window', () => {
    const map = new Map([[`${LEDGER_PREFIX}old`, [entry(1, now - STALE_LEDGER_MS - 1)]]])
    assert.deepEqual(staleLedgerKeys(map, current, now), [`${LEDGER_PREFIX}old`])
  })

  test('keeps a ledger still inside the window', () => {
    const map = new Map([[`${LEDGER_PREFIX}fresh`, [entry(1, now - 1000)]]])
    assert.deepEqual(staleLedgerKeys(map, current, now), [])
  })

  test('never drops the current session, however old its newest entry', () => {
    const map = new Map([[current, [entry(1, 0)]]])
    assert.deepEqual(staleLedgerKeys(map, current, now), [])
  })

  test('judges by the newest entry, not the oldest', () => {
    const map = new Map([[`${LEDGER_PREFIX}mixed`, [entry(1, 0), entry(2, now - 1000)]]])
    assert.deepEqual(staleLedgerKeys(map, current, now), [])
  })

  test('drops an empty ledger left behind', () => {
    const map = new Map([[`${LEDGER_PREFIX}empty`, []]])
    assert.deepEqual(staleLedgerKeys(map, current, now), [`${LEDGER_PREFIX}empty`])
  })

  test('ignores keys that are not ledgers', () => {
    const map = new Map([['somethingElse', [entry(1, 0)]]])
    assert.deepEqual(staleLedgerKeys(map, current, now), [])
  })
})
