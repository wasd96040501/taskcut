import { test, describe } from 'node:test'
import assert from 'node:assert/strict'

import {
  CALL_LIMIT,
  JUDGE_SYSTEM,
  MESSAGE_LIMIT,
  NEXT,
  SAME,
  STEP_LIMIT,
  beforeStep,
  conversationLines,
  acts,
  judgeable,
  judgePrompt,
  readReply,
  saysNext,
} from '../hooks/judge.ts'

type Message = Parameters<typeof conversationLines>[0][number]

function person(text: string): Message {
  return { role: 'user', text, toolUses: [] }
}

function ran(tool: string, input: Record<string, unknown>, text = ''): Message {
  return { role: 'assistant', text, toolUses: [{ tool_use_id: tool, tool, input, text: 'OUTPUT OF THE CALL' }] }
}

function output(text: string): Message {
  return { role: 'user', text: '', toolUses: [], toolResults: [{ tool_use_id: 't', text, isError: false }] }
}

const step = (text: string, calls: { name: string; input: unknown }[] = [{ name: 'Bash', input: { command: 'ls' } }]) => ({ text, calls })

describe('conversationLines', () => {
  test('keeps what the person said and what the assistant ran, in order', () => {
    const lines = conversationLines([person('fix issue 3'), ran('Bash', { command: 'pytest' }), person('thanks')])
    assert.deepEqual(lines, ['Person: fix issue 3', 'Assistant ran Bash: {"command":"pytest"}', 'Person: thanks'])
  })

  test('strips every tool result, as the permission classifier does', () => {
    // Output is where hostile or irrelevant content lives; neither decides
    // whether a piece of work is done.
    const lines = conversationLines([person('go'), ran('Bash', { command: 'cat x' }), output('SECRET FILE CONTENT')])
    assert.ok(!lines.join('\n').includes('SECRET FILE CONTENT'))
    assert.ok(!lines.join('\n').includes('OUTPUT OF THE CALL'))
  })

  test('leaves out read-only lookups', () => {
    const lines = conversationLines([ran('Read', { file_path: 'a.py' }), ran('Grep', { pattern: 'x' }), ran('Edit', { file_path: 'a.py' })])
    assert.deepEqual(lines, ['Assistant ran Edit: {"file_path":"a.py"}'])
  })

  test('leaves out what the assistant said on the way', () => {
    // The permission classifier reads actions, not narration; the step being
    // judged is passed on its own.
    assert.deepEqual(conversationLines([{ role: 'assistant', text: 'let me look', toolUses: [] }]), [])
  })

  test('clips a long message and a long call', () => {
    const [message, call] = conversationLines([person('x'.repeat(MESSAGE_LIMIT * 2)), ran('Write', { content: 'y'.repeat(CALL_LIMIT * 2) })])
    assert.ok(message!.length < MESSAGE_LIMIT + 50)
    assert.ok(call!.length < CALL_LIMIT + 50)
  })
})

describe('beforeStep', () => {
  const judged = step('task 1 is done; now task 2', [{ name: 'Bash', input: { command: 'pytest' } }])

  test('leaves out the step when the transcript already holds it', () => {
    const messages = [person('go'), ran('Bash', { command: 'pytest' })]
    assert.deepEqual(beforeStep(messages, judged), [person('go')])
  })

  test('keeps everything when the transcript does not hold it yet', () => {
    const messages = [person('go'), ran('Bash', { command: 'ls' })]
    assert.equal(beforeStep(messages, judged), messages)
  })
})

describe('judgeable', () => {
  test('a step that says nothing is never a boundary, so it is not asked about', () => {
    assert.equal(judgeable(step('')), false)
    assert.equal(judgeable(step('  \n')), false)
    assert.equal(judgeable(step('Task 1 done. Now task 2.')), true)
  })
})

describe('acts', () => {
  test('a call that changes something acts; a lookup does not', () => {
    assert.equal(acts([{ name: 'Read' }, { name: 'Grep' }]), false)
    assert.equal(acts([{ name: 'Read' }, { name: 'Write' }]), true)
    assert.equal(acts([]), false)
  })
})

describe('judgePrompt', () => {
  test('carries the conversation, the step, its calls and the project instructions', () => {
    const text = judgePrompt(
      [person('fix issue 3'), ran('Bash', { command: 'pytest' })],
      step('issue 3 is fixed; on to issue 4', [{ name: 'Edit', input: { file_path: 'b.py' } }]),
      ['Never edit tests.'],
    )
    for (const expected of ['fix issue 3', 'pytest', 'issue 3 is fixed; on to issue 4', 'Calls Edit: {"file_path":"b.py"}', 'Never edit tests.']) {
      assert.ok(text.includes(expected), expected)
    }
    assert.ok(text.indexOf('Never edit tests.') < text.indexOf('fix issue 3'))
    assert.ok(text.indexOf('pytest') < text.indexOf('issue 3 is fixed'))
  })

  test('keeps the end of a long step, where a model says whether it is done', () => {
    const text = judgePrompt([], step('x'.repeat(STEP_LIMIT * 2) + 'Now task 3.'), [])
    assert.match(text, /Now task 3\./)
  })

  test('keeps all of a long conversation, as the classifier keeps its transcript', () => {
    const many = Array.from({ length: 200 }, (_, i) => person(`request ${i} ${'z'.repeat(500)}`))
    const text = judgePrompt(many, step('go on'), [])
    assert.match(text, /request 0 /)
    assert.match(text, /request 199/)
  })

  test('begins with the whole of the judgement before it, up to that one\'s step', () => {
    // What a prefix cache serves: as the conversation grows, each prompt
    // starts with everything the one before it was shown ahead of its step.
    const messages = Array.from({ length: 300 }, (_, i) => (i % 3 === 0 ? person(`task ${i}`) : ran('Bash', { command: `step ${i}` })))
    const marker = '\n\n--- latest step'
    for (let n = 1; n < messages.length; n++) {
      const before = judgePrompt(messages.slice(0, n), step('go on'), ['Never edit tests.'])
      const after = judgePrompt(messages.slice(0, n + 1), step('go on'), ['Never edit tests.'])
      assert.ok(after.startsWith(before.slice(0, before.indexOf(marker))), `at ${n}`)
    }
  })

  test('has no instructions section when the project has none', () => {
    assert.doesNotMatch(judgePrompt([], step('go'), []), /CLAUDE\.md/)
  })

  test('says so when there is no text', () => {
    assert.match(judgePrompt([], step(''), []), /\(no text\)/)
  })

  test('the question names both answers', () => {
    assert.ok(JUDGE_SYSTEM.includes(NEXT) && JUDGE_SYSTEM.includes(SAME))
  })
})

describe('readReply', () => {
  test('reads the text $.model.complete resolved up to 2.1.278', () => {
    assert.deepEqual(readReply('It moves on.\nNEXT'), { text: 'It moves on.\nNEXT' })
  })

  test('reads the result it resolves from 2.1.280', () => {
    const usage = { input_tokens: 1, output_tokens: 1, cache_read_input_tokens: 0, cache_creation_input_tokens: 0 }
    assert.deepEqual(readReply({ isAnswered: true, text: 'SAME', usage }), { text: 'SAME' })
    assert.deepEqual(readReply({ isAnswered: false, reason: 'api-error', status: 529, error: 'overloaded', usage }), { reason: 'api-error' })
  })

  test('anything else is no reply, never a verdict', () => {
    for (const odd of [undefined, null, 42, {}, { isAnswered: true }, { text: 'NEXT' }]) {
      assert.ok('reason' in readReply(odd), JSON.stringify(odd))
    }
  })
})

describe('saysNext', () => {
  test('reads the verdict off the last line', () => {
    assert.equal(saysNext('It reports task 2 complete and starts task 3.\nNEXT'), true)
    assert.equal(saysNext('It reports the last task complete.\nSAME'), false)
  })

  test('ignores the emphasis a model puts round the word', () => {
    assert.equal(saysNext('Task 1 is finished; task 2 starts.\n**NEXT**'), true)
    assert.equal(saysNext('Task 1 is finished; task 2 starts.\n"Next."'), true)
  })

  test('a verdict mentioned in the reasoning is not the verdict', () => {
    assert.equal(saysNext('It does not move to the NEXT task yet.\nSAME'), false)
  })

  test('no answer is not a new piece', () => {
    assert.equal(saysNext(''), false)
    assert.equal(saysNext('I cannot tell.'), false)
  })
})
