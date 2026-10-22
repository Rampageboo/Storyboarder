import test from 'node:test'
import assert from 'node:assert/strict'
import { shouldRefreshPreviews } from '../src/state/liveBridgeUtils.ts'

const done = (revision, decoded = 2) => ({ state: 'complete', decoded_count: decoded, revision })

test('a finished analysis with new previews refreshes once per revision', () => {
  assert.equal(shouldRefreshPreviews(done(1), undefined), true)
  assert.equal(shouldRefreshPreviews(done(1), 1), false)
  assert.equal(shouldRefreshPreviews(done(2), 1), true)
})

test('running, failed, zero-work or missing analyses do not refresh', () => {
  assert.equal(shouldRefreshPreviews(undefined, undefined), false)
  assert.equal(shouldRefreshPreviews({ state: 'running', decoded_count: 0, revision: 0 }, undefined), false)
  assert.equal(shouldRefreshPreviews({ state: 'failed', decoded_count: 0, revision: 0 }, undefined), false)
  assert.equal(shouldRefreshPreviews(done(3, 0), undefined), false)
})
