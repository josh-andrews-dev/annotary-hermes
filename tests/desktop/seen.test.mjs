// register() tells the backend the page is on, so the agent's first share skips the page step.
import { test } from 'node:test'
import assert from 'node:assert/strict'
import plugin from '../../desktop/plugin.js'

test('registering the page posts /seen once, and a failure is ignored', async () => {
  const calls = []
  const ctx = {
    rest: (path, opts) => { calls.push([path, opts?.method]); return Promise.reject(new Error('offline')) },
    os: null,
    registerMany: () => {},
    onEvent: () => {}
  }
  plugin.register(ctx)
  await new Promise(resolve => setTimeout(resolve, 0))
  assert.deepEqual(calls, [['/seen', 'POST']])
})
