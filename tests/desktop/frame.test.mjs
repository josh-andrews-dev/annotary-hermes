// The embed frame keeps its `annotary-ready` across React's ref re-attach, so a second Document opens.
import { test } from 'node:test'
import assert from 'node:assert/strict'
import { attachFrame } from '../../desktop/plugin.js'

const frame = () => ({ contentWindow: {} })

test('a re-attach of the same frame keeps it ready', () => {
  const ref = { current: null }, ready = { current: false }, live = new Set()
  const el = frame()
  attachFrame(ref, ready, el, live)
  ready.current = true // the shell said annotary-ready
  attachFrame(ref, ready, null, live) // React: old callback with null ...
  attachFrame(ref, ready, el, live) // ... then the new one with the same element
  assert.equal(ready.current, true)
  assert.equal(ref.current, el)
  assert.ok(live.has(el))
})

test('a different frame starts not ready, and a detached one leaves the live set', () => {
  const ref = { current: null }, ready = { current: false }, live = new Set()
  const a = frame(), b = frame()
  attachFrame(ref, ready, a, live)
  ready.current = true
  attachFrame(ref, ready, null, live)
  assert.ok(!live.has(a))
  attachFrame(ref, ready, b, live)
  assert.equal(ready.current, false)
  assert.equal(ref.current, b)
})
