import { test, describe } from 'node:test'
import assert from 'node:assert/strict'

import {
  CLOSE_TOOL,
  FINISHED,
  HEADLINE_LIMIT,
  JUDGE_ANSWER_LIMIT,
  JUDGE_REQUEST_LIMIT,
  LEDGER_HEADER,
  LEDGER_PREFIX,
  STALE_LEDGER_MS,
  TOOL_SEARCH,
  UNFINISHED,
  boundedHumanTurns,
  finishedWork,
  foldPrompt,
  foldedEntry,
  headline,
  humanTurnsOf,
  isLedgerMessage,
  judgeText,
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

function said(text: string, ...calls: Array<{ id: string; tool: string; input?: Record<string, unknown> }>): Message {
  return {
    role: 'assistant',
    text,
    toolUses: calls.map((call) => ({ tool_use_id: call.id, tool: call.tool, input: call.input ?? {} })),
  }
}

function ledgerMessage(entries: Entry[]): Message {
  return { role: 'user', text: renderLedger(entries), toolUses: [] }
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

  test('does not mistake an earlier ledger for something the person typed', () => {
    // Kept as a human turn, an old ledger would sit beside the new one and
    // say everything twice.
    const kept = humanTurnsOf([human('a'), ledgerMessage([entry(1)]), human('b')])
    assert.deepEqual(kept.map((m) => m.text), ['a', 'b'])
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
    assert.match(folded.task, /2 earlier pieces of work/)
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
  test('says so when nothing has been recorded', () => {
    assert.match(renderLedger([]), /Nothing earlier/)
  })

  test('marks entries closed and says not to redo them', () => {
    // A ledger that lists findings without stating they are settled reads as an
    // open to-do list, and the model redoes the work.
    const text = renderLedger([entry(1)])
    assert.match(text, /\[CLOSED\]/)
    assert.match(text, /Do not redo it/)
  })

  test('carries every conclusion', () => {
    const text = renderLedger([entry(1), entry(2), entry(3)])
    for (const n of [1, 2, 3]) assert.match(text, new RegExp(`outcome ${n}`))
  })

  test('never mentions close_task', () => {
    // A cut must not tell the model to cut again: the ledger is the one thing
    // taskcut leaves in the context.
    assert.doesNotMatch(renderLedger([entry(1)]), /close_task/)
  })
})

describe('isLedgerMessage', () => {
  test('recognises a ledger, empty or not', () => {
    assert.ok(isLedgerMessage(ledgerMessage([])))
    assert.ok(isLedgerMessage(ledgerMessage([entry(1)])))
    assert.ok(renderLedger([entry(1)]).startsWith(LEDGER_HEADER))
  })

  test('a person quoting the header mid-message is still a person', () => {
    assert.equal(isLedgerMessage(human(`what does ${LEDGER_HEADER} mean?`)), false)
    assert.equal(isLedgerMessage(said(LEDGER_HEADER)), false)
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

describe('headline', () => {
  test('is the first line that says anything', () => {
    assert.equal(headline('\n\n  Issue 3 of 20. Bug report.\n\nThe details.'), 'Issue 3 of 20. Bug report.')
  })

  test('is clipped when a single line runs long', () => {
    assert.equal(headline('x'.repeat(HEADLINE_LIMIT + 50)).length, HEADLINE_LIMIT + 3)
  })

  test('is empty for an empty request', () => {
    assert.equal(headline(''), '')
  })
})

describe('finishedWork', () => {
  test('pairs a request with what was said after its last piece of work', () => {
    // The narration on the way was about the working context being dropped.
    const got = finishedWork(
      [human('fix issue 3'), said('reading the parser', { id: 't1', tool: 'Read' }), toolResult('t1'), said('fixed: off-by-one')],
      7,
    )
    assert.deepEqual(got, [{ task: 'fix issue 3', outcome: 'fixed: off-by-one', at: 7 }])
  })

  test('covers every answered request since the last cut, in order', () => {
    // close_task is only offered past the floor, so most work was never closed;
    // without an entry the first cut would erase any record of it.
    const got = finishedWork([human('one'), said('a1'), human('two'), said('a2'), human('three'), said('a3')], 0)
    assert.deepEqual(got.map((e) => [e.task, e.outcome]), [['one', 'a1'], ['two', 'a2'], ['three', 'a3']])
  })

  test('skips a request nobody answered', () => {
    assert.deepEqual(finishedWork([human('one'), human('two'), said('a2')], 0).map((e) => e.task), ['two'])
  })

  test('adds nothing for requests an earlier cut kept', () => {
    // After a cut the transcript reads: kept requests, their answers gone into
    // the ledger, then the ledger. They must not be recorded twice.
    const afterCut = [human('goal'), human('recent'), ledgerMessage([entry(1)]), human('next'), said('done next')]
    assert.deepEqual(finishedWork(afterCut, 0).map((e) => e.task), ['next'])
  })

  test('never takes an answer from inside a ledger', () => {
    assert.deepEqual(finishedWork([ledgerMessage([entry(1)]), said('stray')], 0), [])
  })

  test('loading a tool and closing the task are not work', () => {
    // A conclusion given before either is still the conclusion.
    const got = finishedWork(
      [
        human('fix it'),
        said('the cause was X; fixed', { id: 's', tool: TOOL_SEARCH }),
        toolResult('s'),
        said('', { id: 'c', tool: CLOSE_TOOL }),
        toolResult('c'),
        said('Done.'),
      ],
      0,
    )
    assert.equal(got[0]?.outcome, 'the cause was X; fixed\n\nDone.')
  })

  test('keeps a written outcome in place of the answer', () => {
    const got = finishedWork(
      [
        human('fix issues 1 and 2'),
        said('', { id: 'c1', tool: CLOSE_TOOL, input: { task: 'issue 1', outcome: 'X was wrong' } }),
        toolResult('c1'),
        said('', { id: 'c2', tool: CLOSE_TOOL, input: { task: 'issue 2', outcome: 'Y was wrong' } }),
        toolResult('c2'),
        said('both fixed'),
      ],
      0,
    )
    assert.deepEqual(got.map((e) => [e.task, e.outcome]), [['issue 1', 'X was wrong'], ['issue 2', 'Y was wrong']])
  })

  test('names an outcome by the request when the model gave no name', () => {
    const got = finishedWork([human('fix it'), said('', { id: 'c', tool: CLOSE_TOOL, input: { outcome: 'done' } })], 0)
    assert.equal(got[0]?.task, 'fix it')
  })

  test('is empty for an empty transcript', () => {
    assert.deepEqual(finishedWork([], 0), [])
  })
})

describe('judgeText', () => {
  test('carries the request, the answer and both labels', () => {
    const text = judgeText('fix issue 3', 'fixed; tests pass')
    assert.match(text, /fix issue 3/)
    assert.match(text, /fixed; tests pass/)
    assert.match(text, new RegExp(`"${FINISHED}"`))
    assert.match(text, new RegExp(`"${UNFINISHED}"`))
  })

  test('keeps the end of a long answer, where a model says whether it is done', () => {
    const text = judgeText('go', 'x'.repeat(JUDGE_ANSWER_LIMIT * 2) + 'Should I continue?')
    assert.match(text, /Should I continue\?/)
    assert.ok(text.length < JUDGE_ANSWER_LIMIT + JUDGE_REQUEST_LIMIT + 1000)
  })

  test('keeps the start of a long request, where the ask is', () => {
    const text = judgeText('Fix the parser. ' + 'y'.repeat(JUDGE_REQUEST_LIMIT * 2), 'done')
    assert.match(text, /Fix the parser\./)
    assert.ok(text.length < JUDGE_ANSWER_LIMIT + JUDGE_REQUEST_LIMIT + 1000)
  })

  test('says so when there is nothing to judge', () => {
    assert.match(judgeText('', ''), /\(empty\)/)
  })
})
