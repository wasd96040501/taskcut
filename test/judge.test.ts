import { test, describe } from 'node:test'
import assert from 'node:assert/strict'

import {
  CALL_LIMIT,
  CONVERSATION_LIMIT,
  FINISHED,
  MESSAGE_LIMIT,
  REPLY_LIMIT,
  UNFINISHED,
  conversationLines,
  judgeText,
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

describe('conversationLines', () => {
  test('keeps what the person said and what the assistant ran, in order', () => {
    const lines = conversationLines([person('fix issue 3'), ran('Bash', { command: 'pytest' }), person('thanks')])
    assert.deepEqual(lines, ['Person: fix issue 3', 'Assistant ran Bash: {"command":"pytest"}', 'Person: thanks'])
  })

  test('strips every tool result, as the permission classifier does', () => {
    // Output is where hostile or irrelevant content lives; neither decides
    // whether the work is done.
    const lines = conversationLines([person('go'), ran('Bash', { command: 'cat x' }), output('SECRET FILE CONTENT')])
    assert.ok(!lines.join('\n').includes('SECRET FILE CONTENT'))
    assert.ok(!lines.join('\n').includes('OUTPUT OF THE CALL'))
  })

  test('leaves out read-only lookups', () => {
    const lines = conversationLines([ran('Read', { file_path: 'a.py' }), ran('Grep', { pattern: 'x' }), ran('Edit', { file_path: 'a.py' })])
    assert.deepEqual(lines, ['Assistant ran Edit: {"file_path":"a.py"}'])
  })

  test('leaves out what the assistant said on the way', () => {
    // The permission classifier reads actions, not narration; the reply being
    // judged is passed on its own.
    assert.deepEqual(conversationLines([{ role: 'assistant', text: 'let me look', toolUses: [] }]), [])
  })

  test('clips a long message and a long call', () => {
    const [message, call] = conversationLines([person('x'.repeat(MESSAGE_LIMIT * 2)), ran('Write', { content: 'y'.repeat(CALL_LIMIT * 2) })])
    assert.ok(message!.length < MESSAGE_LIMIT + 50)
    assert.ok(call!.length < CALL_LIMIT + 50)
  })
})

describe('judgeText', () => {
  test('carries the conversation, the reply, the project instructions and both labels', () => {
    const text = judgeText([person('fix issue 3'), ran('Bash', { command: 'pytest' })], 'fixed; tests pass', ['Never edit tests.'])
    for (const expected of ['fix issue 3', 'pytest', 'fixed; tests pass', 'Never edit tests.', `"${FINISHED}"`, `"${UNFINISHED}"`]) {
      assert.ok(text.includes(expected), expected)
    }
  })

  test('keeps the end of a long reply, where a model says whether it is done', () => {
    const text = judgeText([], 'x'.repeat(REPLY_LIMIT * 2) + 'Should I continue?', [])
    assert.match(text, /Should I continue\?/)
  })

  test('keeps the most recent conversation when it runs long, and says so', () => {
    const many = Array.from({ length: 200 }, (_, i) => person(`request ${i} ${'z'.repeat(500)}`))
    const text = judgeText(many, 'done', [])
    assert.match(text, /request 199/)
    assert.doesNotMatch(text, /request 0 /)
    assert.match(text, /earlier line\(s\) left out/)
    assert.ok(text.length < CONVERSATION_LIMIT + REPLY_LIMIT + 2000)
  })

  test('has no instructions section when the project has none', () => {
    assert.doesNotMatch(judgeText([], 'done', []), /CLAUDE\.md/)
  })

  test('says so when there is no reply', () => {
    assert.match(judgeText([], '', []), /\(empty\)/)
  })
})
