import test from 'node:test'
import assert from 'node:assert/strict'
import { DraftBuffer, ProjectLifecycle } from '../src/state/projectLifecycle.ts'
import { acceptsProjectPayload, mergeComicResponse, reloadComicDraft } from '../src/state/projectResponses.ts'

function deferred() {
  let resolve, reject
  const promise = new Promise((yes, no) => { resolve = yes; reject = no })
  return { promise, resolve, reject }
}
const tick = () => new Promise(resolve => setImmediate(resolve))
const noop = () => {}

test('one flush drains a newer draft arriving during an in-flight save', async () => {
  const first = deferred()
  const sent = []
  const draft = new DraftBuffer(async snapshot => {
    sent.push(snapshot)
    if (sent.length === 1) await first.promise
    return { ...snapshot, revision: snapshot.revision + 1 }
  }, noop, (newer, saved) => ({ ...newer, revision: saved.revision }))
  draft.edit({ text: 'old', revision: 0 })
  const flush = draft.flush()
  await tick()
  draft.edit({ text: 'new', revision: 0 })
  first.resolve()
  await flush
  assert.deepEqual(sent, [{ text: 'old', revision: 0 }, { text: 'new', revision: 1 }])
  assert.equal(draft.current, null)
})

test('simultaneous flush callers join the same full drain', async () => {
  const saved = deferred()
  let writes = 0
  const draft = new DraftBuffer(async snapshot => { writes++; await saved.promise; return snapshot }, noop)
  draft.edit('one')
  const a = draft.flush(), b = draft.flush(), c = draft.flush()
  assert.equal(a, b)
  assert.equal(b, c)
  await tick()
  assert.equal(writes, 1)
  saved.resolve()
  await Promise.all([a, b, c])
  assert.equal(draft.current, null)
})

test('a failed draft save retains edits and prevents a document transition', async () => {
  const lifecycle = new ProjectLifecycle()
  let fail = true, transitioned = false
  const draft = new DraftBuffer(async snapshot => { if (fail) throw new Error('disk unavailable'); return snapshot }, noop)
  lifecycle.register(draft.flush)
  draft.edit('unsaved')
  await assert.rejects(lifecycle.run(async () => { transitioned = true }, false, noop), /disk unavailable/)
  assert.equal(transitioned, false)
  assert.equal(draft.current, 'unsaved')
  assert.equal(lifecycle.busy, false)
  fail = false
  await lifecycle.run(async () => { transitioned = true }, false, noop)
  assert.equal(transitioned, true)
})

test('save, save-as, workspace and project actions reject overlap and release after failure', async () => {
  const lifecycle = new ProjectLifecycle(), pending = deferred(), states = []
  const save = lifecycle.run(() => pending.promise, false, busy => states.push(busy))
  await assert.rejects(lifecycle.run(async () => {}, false, noop), /already in progress/)
  assert.equal(lifecycle.busy, true)
  pending.reject(new Error('save failed'))
  await assert.rejects(save, /save failed/)
  await lifecycle.run(async () => {}, false, busy => states.push(busy))
  assert.deepEqual(states, [true, false, true, false])
})

test('drawing blocks document and workspace transitions before draft flushing', async () => {
  const lifecycle = new ProjectLifecycle()
  let flushed = false, transitioned = false
  lifecycle.register(async () => { flushed = true })
  await assert.rejects(lifecycle.run(async () => { transitioned = true }, true, noop))
  assert.equal(flushed, false)
  assert.equal(transitioned, false)
})

test('all domains settle before save, including a Shot edit arriving while Comic drains', async () => {
  const lifecycle = new ProjectLifecycle(), comicSave = deferred(), order = []
  const shot = new DraftBuffer(snapshot => lifecycle.write(async () => { order.push(snapshot); return snapshot }), noop)
  const comic = new DraftBuffer(snapshot => lifecycle.write(async () => {
    order.push(snapshot); await comicSave.promise; return snapshot
  }), noop)
  lifecycle.register(shot.flush)
  lifecycle.register(comic.flush)
  shot.edit('shot 1'); comic.edit('comic 1'); lifecycle.edited()
  const action = lifecycle.run(async () => { order.push('save project') }, false, noop)
  await tick()
  shot.edit('shot 2'); lifecycle.edited()
  comicSave.resolve()
  await action
  assert.deepEqual(order, ['shot 1', 'comic 1', 'shot 2', 'save project'])
})

test('concurrent domain autosaves serialize their writes and project save waits for both', async () => {
  const lifecycle = new ProjectLifecycle(), first = deferred(), order = []
  const shot = new DraftBuffer(snapshot => lifecycle.write(async () => {
    order.push('shot start'); await first.promise; order.push('shot end'); return snapshot
  }), noop)
  const comic = new DraftBuffer(snapshot => lifecycle.write(async () => { order.push('comic'); return snapshot }), noop)
  lifecycle.register(shot.flush); lifecycle.register(comic.flush)
  shot.edit('shot'); comic.edit('comic')
  const saves = [shot.flush(), comic.flush()]
  const action = lifecycle.run(async () => { order.push('project') }, false, noop)
  await tick()
  assert.deepEqual(order, ['shot start'])
  first.resolve()
  await Promise.all([...saves, action])
  assert.deepEqual(order, ['shot start', 'shot end', 'comic', 'project'])
})

test('delayed replies are rejected after switching, closing, or reopening the same path', async () => {
  const lifecycle = new ProjectLifecycle(), reply = deferred()
  let current = { path: '/same.sbd', text: 'original' }
  const epoch = lifecycle.capture()
  const refresh = reply.promise.then(payload => { if (lifecycle.accepts(epoch)) current = payload })
  lifecycle.advance() // close
  current = null
  lifecycle.advance() // reopen identical path; path equality alone is insufficient
  current = { path: '/same.sbd', text: 'reopened' }
  reply.resolve({ path: '/same.sbd', text: 'stale' })
  await refresh
  assert.equal(current.text, 'reopened')
})

test('queued old-project writes never execute against a newly opened project', async () => {
  const lifecycle = new ProjectLifecycle(), first = deferred()
  const a = lifecycle.write(() => first.promise)
  let executed = false
  const b = lifecycle.write(async () => { executed = true })
  const rejection = assert.rejects(b, /project changed/)
  await tick()
  lifecycle.advance()
  first.resolve()
  await Promise.all([a, rejection])
  assert.equal(executed, false)
})

test('resetting a domain prevents its delayed save from clearing the replacement draft', async () => {
  const pending = deferred()
  const draft = new DraftBuffer(async snapshot => { await pending.promise; return snapshot }, noop)
  draft.edit('old project')
  const flush = draft.flush()
  await tick()
  draft.reset()
  draft.edit('new project')
  pending.resolve()
  await flush
  assert.equal(draft.current, 'new project')
})

test('document sealing prevents new UI edits only during the final transition', async () => {
  const lifecycle = new ProjectLifecycle()
  await lifecycle.run(async () => {
    assert.equal(lifecycle.editable, true) // compound Comic actions may still create drafts
    lifecycle.seal()
    assert.equal(lifecycle.editable, false)
  }, false, noop)
  assert.equal(lifecycle.editable, true)
})

function project(revision = 1) {
  return { project_id: 'one', project_json_path: '/one.sbd', storage_revision: revision, dirty: true,
    settings: { canvas_width: 1920 }, comic_document: { revision, pages: [] },
    shots: [{ shot_id: 'board', title: 'new title', generation_state: {
      freshness_status: 'current', execution_status: 'running', active_output_id: 'new output',
    } }] }
}

test('payload acceptance checks identity, lifetime and storage revision', () => {
  const lifecycle = new ProjectLifecycle(), current = project(5), epoch = lifecycle.capture()
  assert.equal(acceptsProjectPayload(lifecycle, epoch, current, project(4)), false)
  assert.equal(acceptsProjectPayload(lifecycle, epoch, current, project(6)), true)
  assert.equal(acceptsProjectPayload(lifecycle, epoch, current, { ...project(6), project_id: 'other' }), false)
  assert.equal(acceptsProjectPayload(lifecycle, epoch, current, { ...project(6), project_json_path: '/other.sbd' }), false)
  lifecycle.advance()
  assert.equal(acceptsProjectPayload(lifecycle, epoch, current, project(6)), false)
})

test('same-project background reads cannot overwrite commits even with legacy revision zero', async () => {
  const lifecycle = new ProjectLifecycle(), delayed = deferred()
  let current = project(0)
  const ticket = lifecycle.captureRead()
  const read = delayed.promise.then(payload => { if (lifecycle.acceptsRead(ticket)) current = payload })
  current = { ...current, name: 'newer saved title' }
  lifecycle.changed()
  delayed.resolve({ ...project(0), name: 'old title' })
  await read
  assert.equal(current.name, 'newer saved title')
})

test('Comic response preserves generation freshness side effects without replacing unrelated Shot state', () => {
  const current = project(5), response = project(6)
  response.shots[0].title = 'older title'
  response.shots[0].generation_state = { freshness_status: 'stale', execution_status: 'idle', active_output_id: 'old output' }
  const merged = mergeComicResponse(current, response)
  assert.equal(merged.shots[0].generation_state.freshness_status, 'stale')
  assert.equal(merged.shots[0].generation_state.execution_status, 'running')
  assert.equal(merged.shots[0].generation_state.active_output_id, 'new output')
  assert.equal(merged.shots[0].title, 'new title')
  assert.equal(merged.settings.canvas_width, 1920)
  assert.deepEqual(merged.settings.comic_document, response.comic_document)
})

test('Discard draft and reload recovers from a revision conflict without retrying the invalid draft', async () => {
  const lifecycle = new ProjectLifecycle()
  let attempts = 0, current = project(1)
  const draft = new DraftBuffer(async () => { attempts++; throw new Error('RevisionConflict') }, noop)
  draft.edit({ revision: 0, pages: [] })
  await assert.rejects(draft.flush(), /RevisionConflict/)
  const reloaded = await reloadComicDraft(draft, lifecycle, () => current, async () => project(2),
    payload => { current = mergeComicResponse(current, payload) })
  assert.equal(reloaded, true)
  assert.equal(attempts, 1)
  assert.equal(draft.current, null)
  assert.equal(current.comic_document.revision, 2)
})

test('Discard reload waits for an in-flight failure and still loads saved layout', async () => {
  const lifecycle = new ProjectLifecycle(), failure = deferred()
  let reads = 0, accepted = false
  const draft = new DraftBuffer(async () => { await failure.promise }, noop)
  draft.edit({ revision: 0, pages: [] })
  const save = draft.flush()
  const rejected = assert.rejects(save, /invalid panel/)
  const reload = reloadComicDraft(draft, lifecycle, () => project(1), async () => { reads++; return project(2) },
    () => { accepted = true })
  await tick()
  assert.equal(reads, 0)
  failure.reject(new Error('invalid panel'))
  await Promise.all([rejected, reload])
  assert.equal(reads, 1)
  assert.equal(accepted, true)
  assert.equal(draft.current, null)
})

test('Discard reload does not clear a replacement project draft when GET returns late', async () => {
  const lifecycle = new ProjectLifecycle(), reply = deferred()
  let accepted = false
  const draft = new DraftBuffer(async value => value, noop)
  draft.edit({ revision: 0, pages: [] })
  const reload = reloadComicDraft(draft, lifecycle, () => project(1), () => reply.promise, () => { accepted = true })
  await tick()
  lifecycle.advance()
  draft.edit({ revision: 9, pages: [] })
  reply.resolve(project(2))
  assert.equal(await reload, false)
  assert.equal(accepted, false)
  assert.equal(draft.current.revision, 9)
})

test('flushing a clean draft neither persists nor reports busy', async () => {
  let writes = 0
  const changes = []
  const draft = new DraftBuffer(async snapshot => { writes++; return snapshot },
    (value, busy) => changes.push({ value, busy }))
  await draft.flush()
  assert.equal(writes, 0)
  assert.deepEqual(changes, [])
  draft.edit('saved')
  await draft.flush()
  assert.equal(writes, 1)
  changes.length = 0
  await draft.flush()
  assert.equal(writes, 1)
  assert.deepEqual(changes, [])
  assert.equal(draft.busy, false)
})
