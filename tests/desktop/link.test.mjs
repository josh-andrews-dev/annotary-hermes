// A link's Document survives Hermes's sign-in (query only) and waits for the page to be turned on.
import { test } from 'node:test'
import assert from 'node:assert/strict'
import { bootLink, keepLinked, linkedDoc, takeLinked } from '../../desktop/plugin.js'

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

function page(href) {
  const u = new URL(href)
  const replaced = []
  return {
    win: {
      location: { href, search: u.search, hash: u.hash },
      history: { state: null, replaceState: (_s, _t, url) => replaced.push(url) },
      sessionStorage: memory()
    },
    replaced
  }
}

function boot(href, { registered = false, decisions = {} } = {}) {
  const { win, replaced } = page(href)
  const notes = []
  const navs = []
  let timer = null
  const sdk = { notify: n => notes.push(n), navigate: p => navs.push(p), pluginDecisions: { get: () => decisions } }
  bootLink(win, sdk, () => registered, fn => { timer = fn })
  timer?.()
  return { win, replaced, notes, navs, timer }
}

test('a link opened where the page is off says so and offers the switch', () => {
  const { notes, navs, replaced, win } = boot('https://h.example.test/?annotary=nveriy5x#/')
  assert.equal(notes.length, 1)
  assert.equal(notes[0].title, 'Annotary is off in this browser')
  notes[0].action.onClick()
  assert.deepEqual(navs, ['/capabilities?tab=plugins'])
  assert.deepEqual(replaced, ['/#/'], 'the query leaves the address bar')
  assert.equal(takeLinked(win.sessionStorage, Date.now()), 'nveriy5x', 'kept for when the page is turned on')
})

test('no notice once the page registered, or while it is switched on and still loading', () => {
  assert.equal(boot('https://h.example.test/#/annotary?doc=nveriy5x', { registered: true }).notes.length, 0)
  assert.equal(boot('https://h.example.test/#/annotary?doc=nveriy5x', { decisions: { annotary: true } }).notes.length, 0)
})

test('an address with no Annotary link does nothing', () => {
  const { notes, timer, replaced } = boot('https://h.example.test/#/some-session')
  assert.equal(notes.length, 0)
  assert.equal(timer, null)
  assert.deepEqual(replaced, [])
})

test('a path prefix and other parameters survive taking the link out of the address', () => {
  const { replaced } = boot('https://h.example.test/hermes/?x=1&annotary=nveriy5x#/', { registered: true })
  assert.deepEqual(replaced, ['/hermes/?x=1#/'])
})
