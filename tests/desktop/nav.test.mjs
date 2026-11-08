// The page follows the frame's own navigation (embed protocol `annotary-nav`).
import { test } from 'node:test'
import assert from 'node:assert/strict'
import { applyNav } from '../../desktop-page/plugin.js'

function run(path, current) {
  const calls = { set: [], toList: 0 }
  const next = applyNav(path, current, { setDoc: d => calls.set.push(d), toList: () => { calls.toList++ } })
  return { next, ...calls }
}

test('going to the list in the frame clears the Document and routes the page to the list', () => {
  assert.deepEqual(run('/', 'abc12345'), { next: null, set: [null], toList: 1 })
  assert.deepEqual(run('/?name=plan', 'abc12345'), { next: null, set: [null], toList: 1 })
})

test('a Version or a Thread of the same Document keeps it', () => {
  assert.deepEqual(run('/d/abc12345/v/2', 'abc12345'), { next: 'abc12345', set: [], toList: 0 })
  assert.deepEqual(run('/d/abc12345#t3', 'abc12345'), { next: 'abc12345', set: [], toList: 0 })
})

test('another Document in the frame selects it', () => {
  assert.deepEqual(run('/d/zz9/v/1', 'abc12345'), { next: 'zz9', set: ['zz9'], toList: 0 })
})

test('after the list, the same Document can be selected again', () => {
  assert.deepEqual(run('/', null), { next: null, set: [], toList: 0 })
  assert.deepEqual(run('/d/abc12345', null), { next: 'abc12345', set: ['abc12345'], toList: 0 })
})
