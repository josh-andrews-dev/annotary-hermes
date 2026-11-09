// The bar above the embedded page says who edits and what was decided; the frame has the buttons.
import { test, afterEach } from 'node:test'
import assert from 'node:assert/strict'
import { Button } from '@hermes/plugin-sdk'
import { ReviewBar } from '../../desktop-page/plugin.js'

afterEach(() => { delete globalThis.testState })

const ACTIONS = [{ id: 'approve', label: 'Approve', intent: 'positive' }, { id: 'send-back', label: 'Send back' }]

function render(d) {
  globalThis.testState = d
  return ReviewBar({ doc: 'abc12345' })
}

function walk(node, out = []) {
  if (Array.isArray(node)) node.forEach(n => walk(n, out))
  else if (node && typeof node === 'object') { out.push(node); walk(node.props?.children, out) }
  return out
}

function texts(node) {
  return walk(node).map(n => n.props?.children).filter(c => typeof c === 'string')
}

test('the bar has no Action buttons, because the embedded page has them', () => {
  const nodes = walk(render({ editor: '@coder', action: null, actions: ACTIONS }))
  assert.ok(nodes.length > 0)
  assert.deepEqual(nodes.filter(n => n.type === Button || n.type === 'button' || (n.props && 'data-annotary-action' in n.props)), [])
})

test('the bar keeps the editor line', () => {
  assert.ok(texts(render({ editor: '@coder', action: null, actions: ACTIONS })).includes('Editor: @coder'))
  assert.ok(texts(render({ editor: null, action: null, actions: ACTIONS })).includes('Editor: none yet'))
})

test('the bar says which Action was taken and by whom', () => {
  const bar = render({ editor: '@coder', action: { label: 'Send back', by: 'owner' }, actions: ACTIONS })
  assert.ok(texts(bar).includes('Send back by @owner'))
  assert.ok(!texts(render({ editor: '@coder', action: null, actions: ACTIONS })).some(t => t.includes(' by @')))
})
