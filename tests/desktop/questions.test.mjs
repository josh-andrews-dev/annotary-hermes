// The cards show Questions read-only: the chat card's count, and each Question's options and Answers.
import { test } from 'node:test'
import assert from 'node:assert/strict'
import { answeredCount, questionText } from '../../desktop/plugin.js'

const QS = [
  { key: 'D1', options: ['A', 'B'], decided: null, answers: [{ by: 'rowan', option: 'B' }] },
  { key: 'D2', options: ['A', 'B'], decided: 'A (@rowan, 2026-11-20)', answers: [] },
  { key: 'D3', options: ['A', 'B', 'C'], decided: null, answers: [] },
  { key: 't4', options: ['A Monday', 'B Friday'], decided: null, answers: [{ by: 'rowan', option: 'A' }, { by: 'sam', option: 'B' }] }
]

test('the count says how many Questions are answered, a decided one included', () => {
  assert.equal(answeredCount(QS), '3 of 4 answered')
})

test('no Questions, no count, so the card line is as before', () => {
  assert.equal(answeredCount(undefined), null)
  assert.equal(answeredCount([]), null)
})

test('a Question reads as its options, then who chose what', () => {
  assert.equal(questionText(QS[0]), 'D1: A · B → B @rowan')
  assert.equal(questionText(QS[1]), 'D2: A · B → decided: A (@rowan, 2026-11-20)')
  assert.equal(questionText(QS[2]), 'D3: A · B · C → unanswered')
  assert.equal(questionText(QS[3]), 't4: A Monday · B Friday → A @rowan, B @sam')
})
