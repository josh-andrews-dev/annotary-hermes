// A link's Document survives Hermes's sign-in (query only) and waits for the page to be turned on.
import { test } from 'node:test'
import assert from 'node:assert/strict'
import { keepLinked, linkedDoc, takeLinked } from '../../desktop/plugin.js'

function memory() {
  const m = new Map()
  return { getItem: k => (m.has(k) ? m.get(k) : null), setItem: (k, v) => m.set(k, String(v)), removeItem: k => m.delete(k) }
}

test('after sign-in only the query is left, and it names the Document', () => {
  assert.equal(linkedDoc('?annotary=nveriy5x', '#/'), 'nveriy5x')
  assert.equal(linkedDoc('?annotary=nveriy5x', ''), 'nveriy5x')
})

test('the page route names the Document too', () => {
  assert.equal(linkedDoc('', '#/annotary?doc=nveriy5x'), 'nveriy5x')
})

test('other routes, other parameters and bad ids name nothing', () => {
  assert.equal(linkedDoc('', '#/'), null)
  assert.equal(linkedDoc('', '#/some-session?doc=nveriy5x'), null)
  assert.equal(linkedDoc('?doc=nveriy5x', '#/'), null)
  assert.equal(linkedDoc('?annotary=../x', '#/'), null)
  assert.equal(linkedDoc('', '#/annotary'), null)
})

test('a kept Document is handed over once', () => {
  const s = memory()
  keepLinked(s, 'nveriy5x', 1000)
  assert.equal(takeLinked(s, 2000), 'nveriy5x')
  assert.equal(takeLinked(s, 2000), null)
})

test('a kept Document goes stale, so turning the page on much later jumps nowhere', () => {
  const s = memory()
  keepLinked(s, 'nveriy5x', 0)
  assert.equal(takeLinked(s, 11 * 60 * 1000), null)
})

test('storage that refuses is not an error', () => {
  const broken = { getItem() { throw new Error('denied') }, setItem() { throw new Error('denied') }, removeItem() {} }
  keepLinked(broken, 'nveriy5x', 0)
  assert.equal(takeLinked(broken, 0), null)
})
