// Exactly one set of Action buttons is on screen: the embedded page's when its frame is wide
// enough to show them, the bar's when it is not.
import { test, afterEach } from 'node:test'
import assert from 'node:assert/strict'
import { Button } from '@hermes/plugin-sdk'
import { ReviewBar, FRAME_ACTIONS_MIN_WIDTH } from '../../desktop-page/plugin.js'

afterEach(() => { delete globalThis.testState })

const ACTIONS = [{ id: 'approve', label: 'Approve', intent: 'positive' }, { id: 'send-back', label: 'Send back' }]

function render(d, frameWidth) {
  globalThis.testState = d
  return ReviewBar({ doc: 'abc12345', frameWidth, onChanged() {} })
}

function walk(node, out = []) {
  if (Array.isArray(node)) node.forEach(n => walk(n, out))
  else if (node && typeof node === 'object') { out.push(node); walk(node.props?.children, out) }
  return out
}

function texts(node) {
  return walk(node).map(n => n.props?.children).filter(c => typeof c === 'string')
}

function buttons(node) {
  return walk(node).filter(n => n.type === Button || n.type === 'button')
}

const doc = { editor: '@coder', action: null, actions: ACTIONS }

test('the threshold is the width the embedded page folds its buttons at', () => {
  assert.equal(FRAME_ACTIONS_MIN_WIDTH, 850)
})

for (const width of [850, 851, 1200]) {
  test(`at ${width} px the frame shows its buttons, so the bar shows none`, () => {
    assert.deepEqual(buttons(render(doc, width)), [])
  })
}

for (const width of [849, 776, 390]) {
  test(`at ${width} px the frame hides its buttons, so the bar shows them`, () => {
    const shown = buttons(render(doc, width))
    assert.deepEqual(shown.map(b => b.props['data-annotary-action']), ['approve', 'send-back'])
    assert.deepEqual(shown.map(b => b.props.children), ['Approve', 'Send back'])
  })
}

test('before the frame has been measured the bar shows none, so two sets never flash', () => {
  assert.deepEqual(buttons(render(doc, null)), [])
})

test('the bar keeps the editor line at every width', () => {
  for (const width of [390, 1200]) {
    assert.ok(texts(render(doc, width)).includes('Editor: @coder'))
    assert.ok(texts(render({ ...doc, editor: null }, width)).includes('Editor: none yet'))
  }
})

test('the bar says which Action was taken and by whom', () => {
  const bar = render({ ...doc, action: { label: 'Send back', by: 'owner' } }, 1200)
  assert.ok(texts(bar).includes('Send back by @owner'))
  assert.ok(!texts(render(doc, 1200)).some(t => t.includes(' by @')))
})
