import { test, describe } from 'node:test'
import assert from 'node:assert/strict'

import {
  CALL_LIMIT,
  CONVERSATION_LIMIT,
  DONE,
  JUDGE_SYSTEM,
  MESSAGE_LIMIT,
  STEP_LIMIT,
  WORKING,
  beforeStep,
  conversationLines,
  judgePrompt,
  saysDone,
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

const reply = (text: string) => ({ text, calls: [] })

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
  const step = { text: 'task 1 is done; now task 2', calls: [{ name: 'Bash', input: { command: 'pytest' } }] }

  test('leaves out the step when the transcript already holds it', () => {
    const messages = [person('go'), ran('Bash', { command: 'pytest' })]
    assert.deepEqual(beforeStep(messages, step), [person('go')])
  })

  test('keeps everything when the transcript does not hold it yet', () => {
    const messages = [person('go'), ran('Bash', { command: 'ls' })]
    assert.equal(beforeStep(messages, step), messages)
  })

  test('keeps everything for a reply, which has no calls to repeat', () => {
    const messages = [person('go'), ran('Bash', { command: 'pytest' })]
    assert.equal(beforeStep(messages, reply('done')), messages)
  })
})

describe('judgePrompt', () => {
  test('carries the conversation, the step, its calls and the project instructions', () => {
    const text = judgePrompt(
      [person('fix issue 3'), ran('Bash', { command: 'pytest' })],
      { text: 'issue 3 is fixed; on to issue 4', calls: [{ name: 'Edit', input: { file_path: 'b.py' } }] },
      ['Never edit tests.'],
    )
    for (const expected of ['fix issue 3', 'pytest', 'issue 3 is fixed; on to issue 4', 'Calls Edit: {"file_path":"b.py"}', 'Never edit tests.']) {
      assert.ok(text.includes(expected), expected)
    }
    assert.doesNotMatch(text, /handed back/)
  })

  test('says so when the step is a reply the turn ended on', () => {
    assert.match(judgePrompt([], reply('done'), []), /stopped here and handed back to the person/)
  })

  test('keeps the end of a long step, where a model says whether it is done', () => {
    const text = judgePrompt([], reply('x'.repeat(STEP_LIMIT * 2) + 'Should I continue?'), [])
    assert.match(text, /Should I continue\?/)
  })

  test('keeps the most recent conversation when it runs long, and says so', () => {
    const many = Array.from({ length: 200 }, (_, i) => person(`request ${i} ${'z'.repeat(500)}`))
    const text = judgePrompt(many, reply('done'), [])
    assert.match(text, /request 199/)
    assert.doesNotMatch(text, /request 0 /)
    assert.match(text, /earlier line\(s\) left out/)
    assert.ok(text.length < CONVERSATION_LIMIT + STEP_LIMIT + 2000)
  })

  test('has no instructions section when the project has none', () => {
    assert.doesNotMatch(judgePrompt([], reply('done'), []), /CLAUDE\.md/)
  })

  test('says so when the step has no text', () => {
    assert.match(judgePrompt([], reply(''), []), /\(no text\)/)
  })

  test('the question names both answers', () => {
    assert.ok(JUDGE_SYSTEM.includes(DONE) && JUDGE_SYSTEM.includes(WORKING))
  })
})

describe('saysDone', () => {
  test('reads the verdict off the last line', () => {
    assert.equal(saysDone('It reports task 2 complete and starts task 3.\nDONE'), true)
    assert.equal(saysDone('It is still reading the file.\nWORKING'), false)
  })

  test('ignores the emphasis a model puts round the word', () => {
    assert.equal(saysDone('Task 1 is finished.\n**DONE**'), true)
    assert.equal(saysDone('Task 1 is finished.\n"Done."'), true)
  })

  test('a verdict mentioned in the reasoning is not the verdict', () => {
    assert.equal(saysDone('It is not DONE yet; it is still testing.\nWORKING'), false)
  })

  test('no answer is not done', () => {
    assert.equal(saysDone(''), false)
    assert.equal(saysDone('I cannot tell.'), false)
  })
})
