import test from 'node:test'
import assert from 'node:assert/strict'
import { ProjectHistory, replayProjectHistory } from '../src/state/projectHistory.ts'
import { ProjectLifecycle } from '../src/state/projectLifecycle.ts'
import { createBoardCommands } from '../src/state/boardCommands.ts'
import { createReferenceCommands } from '../src/state/referenceCommands.ts'

const clone = value => structuredClone(value)
const noop = () => {}
function deferred() {
  let resolve, reject
  const promise = new Promise((yes, no) => { resolve = yes; reject = no })
  return { promise, resolve, reject }
}
const tick = () => new Promise(resolve => setImmediate(resolve))
const board = id => ({ shot_id: id, title: id, scene_id: `scene-${id}`, scene: `Scene ${id}`, source_file_path: '' })
function project(ids = ['a', 'b', 'c']) {
  return { project_id: 'project', project_json_path: '/project.sbd', storage_revision: 1, settings: {}, shots: ids.map(board) }
}

function setup(initial = project()) {
  const state = { current: clone(initial), server: clone(initial), selectedShotId: initial.shots[0]?.shot_id ?? null,
    selectedShotIds: initial.shots.length ? [initial.shots[0].shot_id] : [], calls: [], gateCalls: 0,
    drawing: false, accept: true, flush: async () => {}, activeSegment: null, token: null, dismissed: 0 }
  const lifecycle = new ProjectLifecycle(), history = new ProjectHistory()
  lifecycle.register(() => state.flush())
  const runExclusive = operation => { state.gateCalls++; return lifecycle.run(operation, state.drawing, noop) }
  const result = () => clone(state.server)
  const response = (name, change) => async (...args) => {
    state.calls.push([name, clone(args)])
    const value = await change(...args)
    return value === undefined ? result() : value
  }
  let nextId = 1
  const api = {
    addShot: response('addShot', body => {
      const index = body.after_shot_id ? state.server.shots.findIndex(shot => shot.shot_id === body.after_shot_id) + 1 : state.server.shots.length
      state.server.shots.splice(index, 0, board(`new-${nextId++}`))
    }),
    deleteShot: response('deleteShot', id => { state.server.shots = state.server.shots.filter(shot => shot.shot_id !== id) }),
    deleteShotsBatch: response('deleteShotsBatch', body => {
      state.server.shots = state.server.shots.filter(shot => !body.shot_ids.includes(shot.shot_id))
      if (state.server.story_graph) {
        state.server.story_graph.revision++
        state.server.story_graph.routes.forEach(route => { route.shot_ids = route.shot_ids.filter(id => !body.shot_ids.includes(id)) })
      }
    }),
    restoreShotsBatch: response('restoreShotsBatch', body => {
      for (const { shot, index } of body.items) state.server.shots.splice(index, 0, clone(shot))
      if (body.story_graph) state.server.story_graph = { ...clone(body.story_graph), revision: body.story_graph.revision + 1 }
    }),
    updateShotsBatch: response('updateShotsBatch', body => {
      for (const update of body.updates) Object.assign(state.server.shots.find(shot => shot.shot_id === update.shot_id), update.changes)
    }),
    reorderShots: response('reorderShots', body => {
      const shots = new Map(state.server.shots.map(shot => [shot.shot_id, shot]))
      state.server.shots = body.shot_ids.map(id => shots.get(id))
    }),
    createQueueBatchRequests: response('createQueueBatchRequests', () => ({ project: result() })),
    moveShotUp: response('moveShotUp', () => {}), moveShotDown: response('moveShotDown', () => {}),
    syncShot: response('syncShot', () => {}),
    createShotCanvas: response('createShotCanvas', id => { state.server.shots.find(shot => shot.shot_id === id).source_file_path = '/source.psd' }),
    openShotSource: response('openShotSource', () => ({})),
    snapshotRefBoards: response('snapshotRefBoards', () => ({ undo_token: `snapshot-${nextId++}` })),
    deleteRefSegment: response('deleteRefSegment', id => {
      state.server.settings.ref_segments = (state.server.settings.ref_segments ?? []).filter(segment => segment.id !== id)
    }),
    restoreRefApply: response('restoreRefApply', () => {}),
    getProject: response('getProject', () => {}),
    updateSettings: response('updateSettings', changes => { Object.assign(state.server.settings, clone(changes)) }),
  }
  const accept = (payload, selected) => {
    if (!state.accept) return false
    state.current = clone(payload)
    if (selected !== undefined) {
      state.selectedShotId = selected
      state.selectedShotIds = selected ? [selected] : []
    }
    lifecycle.changed()
    return true
  }
  // The production read port names the canonical payload `project`.
  const boards = createBoardCommands({ api, read: () => ({ ...state, project: state.current }), runExclusive, accept, history })
  const refs = createReferenceCommands({ api, readProject: () => state.current,
    readActiveSegment: () => state.activeSegment, dismiss: () => { state.dismissed++; state.activeSegment = null },
    setUndoToken: token => { state.token = token }, runExclusive, accept, history })
  const replay = direction => runExclusive(() => history.replay(direction, ({ payload, select }) => accept(payload, select)))
  return { state, api, boards, refs, history, lifecycle, replay, accept, runExclusive }
}
const ids = state => state.current.shots.map(shot => shot.shot_id)

test('board commands capture source and selection after the shared draft drain', async () => {
  const h = setup(), pending = deferred()
  h.state.flush = () => pending.promise
  const command = h.boards.deleteSelectedShot()
  await tick()
  assert.deepEqual(h.state.calls, [])
  h.state.current.shots[1].title = 'saved newer draft'
  h.state.server = clone(h.state.current)
  h.state.selectedShotIds = ['b']
  pending.resolve()
  await command
  assert.deepEqual(ids(h.state), ['a', 'c'])
  await h.replay('undo')
  const restored = h.state.calls.find(([name]) => name === 'restoreShotsBatch')[1][0].items[0]
  assert.equal(restored.shot.title, 'saved newer draft')
  assert.equal(restored.index, 1)
})

test('add undo/redo follows regenerated shot IDs rather than deleting the original ID twice', async () => {
  const h = setup()
  await h.boards.addShotAfterSelection()
  assert.deepEqual(ids(h.state), ['a', 'new-1', 'b', 'c'])
  assert.equal(h.history.getSnapshot().undoLabel, 'Add board')
  await h.replay('undo'); await h.replay('redo')
  assert.equal(h.state.selectedShotId, 'new-2')
  await h.replay('undo')
  assert.deepEqual(h.state.calls.filter(([name]) => name === 'deleteShot').map(([, args]) => args[0]), ['new-1', 'new-2'])
})

test('inserting at index zero restores order and uses the replacement ID on redo', async () => {
  const h = setup()
  await h.boards.insertShotAtIndex(0)
  assert.deepEqual(ids(h.state), ['new-1', 'a', 'b', 'c'])
  assert.equal(h.history.getSnapshot().undoLabel, 'Insert board')
  await h.replay('undo'); await h.replay('redo')
  assert.deepEqual(ids(h.state), ['new-2', 'a', 'b', 'c'])
  assert.deepEqual(h.state.calls.filter(([name]) => name === 'reorderShots').map(([, args]) => args[0].shot_ids),
    [['new-1', 'a', 'b', 'c'], ['new-2', 'a', 'b', 'c']])
})

test('batch delete undo preserves graph memberships/layout with the current revision', async () => {
  const initial = project()
  initial.settings.story_graph = { version: 1 }
  initial.story_graph = { version: 1, revision: 7, active_route_id: 'branch',
    routes: [{ id: 'main', shot_ids: ['a', 'b'] }, { id: 'branch', shot_ids: ['b', 'c'] }], positions: { b: { x: 10, y: 20 } } }
  const h = setup(initial)
  h.state.selectedShotIds = ['b', 'c']
  await h.boards.deleteSelectedShot()
  assert.equal(h.history.getSnapshot().undoLabel, 'Delete 2 boards')
  h.state.current.story_graph.revision = 21
  h.state.server.story_graph.revision = 21
  await h.replay('undo')
  const body = h.state.calls.find(([name]) => name === 'restoreShotsBatch')[1][0]
  assert.deepEqual(body.items.map(item => [item.shot.shot_id, item.index]), [['b', 1], ['c', 2]])
  assert.equal(body.story_graph.revision, 21)
  assert.deepEqual(body.story_graph.routes, initial.story_graph.routes)
  assert.deepEqual(body.story_graph.positions, initial.story_graph.positions)
  assert.equal(body.story_graph.active_route_id, 'branch')
  assert.equal(h.state.selectedShotId, 'b')
})

test('legacy delete undo omits projected graph from the restore request', async () => {
  const initial = project()
  initial.story_graph = { version: 1, revision: 0, active_route_id: 'main', routes: [{ id: 'main', shot_ids: ['a', 'b', 'c'] }], positions: {} }
  const h = setup(initial)
  await h.boards.deleteSelectedShot(); await h.replay('undo')
  const body = h.state.calls.find(([name]) => name === 'restoreShotsBatch')[1][0]
  assert.equal('story_graph' in body, false)
})

test('scene changes restore each original scene, and reorder retains its own selection/inverse', async () => {
  const h = setup()
  h.state.selectedShotIds = ['a', 'c']
  await h.boards.changeSelectedShotsScene('together', 'Together')
  assert.equal(h.history.getSnapshot().undoLabel, 'Change scene for 2 boards')
  await h.replay('undo')
  assert.deepEqual(h.state.current.shots.map(shot => shot.scene_id), ['scene-a', 'scene-b', 'scene-c'])
  await h.boards.reorderBoards(['c', 'a', 'b'], 'c')
  assert.equal(h.history.getSnapshot().undoLabel, 'Reorder boards')
  assert.equal(h.history.getSnapshot().canRedo, false)
  await h.replay('undo')
  assert.deepEqual(ids(h.state), ['a', 'b', 'c'])
  assert.equal(h.state.selectedShotId, 'c')
})

test('each public board command enters one gate; nudge/queue/source operations do not create history', async () => {
  for (const call of [h => h.boards.moveSelectedShot('up'), h => h.boards.sendSelectedShotsToQueue(),
    h => h.boards.syncSelectedShot(), h => h.boards.openSelectedShotSource()]) {
    const h = setup()
    await call(h)
    assert.equal(h.state.gateCalls, 1)
    assert.equal(h.history.getSnapshot().canUndo, false)
  }
  const h = setup()
  await h.boards.openSelectedShotSource()
  assert.deepEqual(h.state.calls.map(([name]) => name), ['createShotCanvas', 'openShotSource'])
})

test('drawing, failed draft drain and overlapping commands never dispatch an extra mutation', async () => {
  const h = setup()
  h.state.drawing = true
  await assert.rejects(h.boards.deleteSelectedShot())
  assert.deepEqual(h.state.calls, [])
  h.state.drawing = false
  h.state.flush = async () => { throw new Error('draft failed') }
  await assert.rejects(h.boards.deleteSelectedShot(), /draft failed/)
  assert.deepEqual(h.state.calls, [])
  const pending = deferred()
  h.state.flush = () => pending.promise
  const first = h.boards.addShotAfterSelection()
  await assert.rejects(h.boards.deleteSelectedShot(), /already in progress/)
  pending.resolve(); await first
  assert.deepEqual(h.state.calls.map(([name]) => name), ['addShot'])
})

test('unaccepted command replies do not enter history', async () => {
  const h = setup()
  h.state.accept = false
  await h.boards.addShotAfterSelection()
  assert.equal(h.history.getSnapshot().canUndo, false)
})

test('reference apply records without a nested gate, uses fallback GET, and rotates redo tokens', async () => {
  const h = setup()
  h.api.restoreRefApply = async token => { h.state.calls.push(['restore-token', [token]]); throw new Error('expired') }
  await h.runExclusive(async () => {
    h.refs.recordRefApply({ label: 'Apply reference', undoToken: 'original',
      redo: async () => ({ ...clone(h.state.current), undo_token: 'replacement' }) })
  })
  assert.equal(h.state.gateCalls, 1)
  await h.replay('undo')
  assert.equal(h.state.token, null)
  assert.equal(h.state.calls.filter(([name]) => name === 'getProject').length, 1)
  await h.replay('redo')
  assert.equal(h.state.token, 'replacement')
  await h.replay('undo')
  assert.deepEqual(h.state.calls.filter(([name]) => name === 'restore-token').map(([, args]) => args[0]), ['original', 'replacement'])
})

test('reference deletion restores record alongside existing records and refreshes snapshot token on redo', async () => {
  const initial = project()
  const record = { id: 'ref', anchor_shot_id: 'a', end_shot_id: 'c', extra: 'preserved' }
  initial.settings.ref_segments = [{ id: 'other' }, record]
  const h = setup(initial)
  await h.refs.deleteRefSegmentUndoable('ref')
  assert.equal(h.history.getSnapshot().undoLabel, 'Delete reference')
  await h.replay('undo')
  assert.deepEqual(h.state.current.settings.ref_segments, [{ id: 'other' }, record])
  await h.replay('redo'); await h.replay('undo')
  assert.deepEqual(h.state.calls.filter(([name]) => name === 'restoreRefApply').map(([, args]) => args[0]), ['snapshot-1', 'snapshot-2'])
})

test('reference snapshot failure keeps delete behavior and redo retains the prior usable token', async () => {
  const initial = project()
  initial.settings.ref_segments = [{ id: 'ref', anchor_shot_id: 'a', end_shot_id: 'c' }]
  const h = setup(initial)
  h.api.snapshotRefBoards = async () => { throw new Error('snapshot unavailable') }
  await h.refs.deleteRefSegmentUndoable('ref')
  assert.equal(h.history.getSnapshot().canUndo, false)
  assert.deepEqual(h.state.current.settings.ref_segments, [])
  const second = setup(initial)
  await second.refs.deleteRefSegmentUndoable('ref'); await second.replay('undo')
  second.api.snapshotRefBoards = async () => { throw new Error('snapshot unavailable') }
  await second.replay('redo'); await second.replay('undo')
  assert.deepEqual(second.state.calls.filter(([name]) => name === 'restoreRefApply').map(([, args]) => args[0]), ['snapshot-1', 'snapshot-1'])
})

test('delete-active reference drains before reading selection, dismisses once and enters one gate', async () => {
  const initial = project()
  initial.settings.ref_segments = [{ id: 'ref', anchor_shot_id: 'a', end_shot_id: 'c' }]
  const h = setup(initial)
  h.state.activeSegment = 'old'
  h.state.flush = async () => { h.state.activeSegment = 'ref' }
  await h.refs.deleteActiveRefSegment()
  assert.equal(h.state.gateCalls, 1)
  assert.equal(h.state.dismissed, 1)
  assert.equal(h.state.activeSegment, null)
  assert.deepEqual(h.state.calls.find(([name]) => name === 'deleteRefSegment')[1], ['ref'])
})

test('history keeps 50 entries and new record removes redo', async () => {
  const history = new ProjectHistory(), undone = []
  for (let index = 0; index < 55; index++) history.record({ label: `entry ${index}`,
    undo: async () => { undone.push(index); return { payload: project() } }, redo: async () => ({ payload: project() }) })
  assert.equal(history.getSnapshot().undoLabel, 'entry 54')
  for (let index = 0; index < 55; index++) await history.replay('undo', () => true)
  assert.deepEqual(undone, Array.from({ length: 50 }, (_, index) => 54 - index))
  history.record({ label: 'new', undo: async () => ({ payload: project() }), redo: async () => ({ payload: project() }) })
  assert.equal(history.getSnapshot().canRedo, false)
})

test('failed or unaccepted history replay leaves its source stack unchanged', async () => {
  const history = new ProjectHistory()
  let fail = true
  history.record({ label: 'test', undo: async () => { if (fail) throw new Error('restore failed'); return { payload: project() } },
    redo: async () => { throw new Error('redo failed') } })
  await assert.rejects(history.replay('undo', () => true), /restore failed/)
  assert.equal(history.getSnapshot().undoLabel, 'test')
  assert.equal(history.getSnapshot().canRedo, false)
  fail = false
  await history.replay('undo', () => false)
  assert.equal(history.getSnapshot().undoLabel, 'test')
  await history.replay('undo', () => true)
  await assert.rejects(history.replay('redo', () => true), /redo failed/)
  assert.equal(history.getSnapshot().redoLabel, 'test')
})

test('clear or a new record during pending replay cannot resurrect history or commit a stale token', async () => {
  for (const invalidate of ['clear', 'record']) {
    const history = new ProjectHistory(), pending = deferred()
    let accepted = false, committed = false
    history.record({ label: 'old', undo: () => pending.promise, redo: async () => ({ payload: project() }) })
    const replay = history.replay('undo', () => { accepted = true; return true })
    if (invalidate === 'clear') history.clear()
    else history.record({ label: 'new', undo: async () => ({ payload: project() }), redo: async () => ({ payload: project() }) })
    pending.resolve({ payload: project(), commit: () => { committed = true } })
    await replay
    assert.equal(accepted, false)
    assert.equal(committed, false)
    assert.equal(history.getSnapshot().canRedo, false)
    assert.equal(history.getSnapshot().undoLabel, invalidate === 'clear' ? null : 'new')
  }
})

test('invalidated successful replay recovers fresh canonical data without resurrecting history or tokens', async () => {
  const history = new ProjectHistory(), lifecycle = new ProjectLifecycle(), pending = deferred()
  let current = { ...project(), name: 'before undo' }, reads = 0, tokenCommitted = false
  const errors = []
  history.record({ label: 'old', undo: () => pending.promise, redo: async () => ({ payload: project() }) })
  const replay = replayProjectHistory(history, lifecycle, 'undo', {
    read: async () => { reads++; return { ...project(), name: 'server after undo' } },
    accept: payload => { current = payload; lifecycle.changed(); return true }, reportError: error => errors.push(error),
  })
  history.clear()
  pending.resolve({ payload: { ...project(), name: 'old reply' }, commit: () => { tokenCommitted = true } })
  await replay
  assert.equal(reads, 1)
  assert.equal(current.name, 'server after undo')
  assert.equal(tokenCommitted, false)
  assert.equal(history.getSnapshot().canUndo, false)
  assert.equal(history.getSnapshot().canRedo, false)
  assert.deepEqual(errors, [])
})

test('invalidated replay never requests recovery for a replacement document', async () => {
  const history = new ProjectHistory(), lifecycle = new ProjectLifecycle(), pending = deferred()
  let reads = 0, accepted = false
  history.record({ label: 'old', undo: () => pending.promise, redo: async () => ({ payload: project() }) })
  const replay = replayProjectHistory(history, lifecycle, 'undo', {
    read: async () => { reads++; return project() }, accept: () => { accepted = true; return true }, reportError: noop,
  })
  lifecycle.advance(); history.clear()
  pending.resolve({ payload: project() })
  await replay
  assert.equal(reads, 0)
  assert.equal(accepted, false)
})

test('late recovery GET cannot replace a newer accepted state in the same document', async () => {
  const history = new ProjectHistory(), lifecycle = new ProjectLifecycle(), pending = deferred(), recovery = deferred()
  let accepted = false, reads = 0
  history.record({ label: 'old', undo: () => pending.promise, redo: async () => ({ payload: project() }) })
  const replay = replayProjectHistory(history, lifecycle, 'undo', {
    read: () => { reads++; return recovery.promise }, accept: () => { accepted = true; return true }, reportError: noop,
  })
  history.clear(); pending.resolve({ payload: project() })
  await tick()
  assert.equal(reads, 1)
  lifecycle.changed()
  recovery.resolve(project())
  await replay
  assert.equal(accepted, false)
  assert.equal(history.getSnapshot().canRedo, false)
})

test('recovery read failure is reported without restoring invalidated history', async () => {
  const history = new ProjectHistory(), lifecycle = new ProjectLifecycle(), pending = deferred(), errors = []
  history.record({ label: 'old', undo: () => pending.promise, redo: async () => ({ payload: project() }) })
  const replay = replayProjectHistory(history, lifecycle, 'undo', {
    read: async () => { throw new Error('recovery failed') }, accept: () => true, reportError: error => errors.push(error.message),
  })
  history.clear(); pending.resolve({ payload: project() })
  await replay
  assert.deepEqual(errors, ['recovery failed'])
  assert.deepEqual(history.getSnapshot(), { canUndo: false, canRedo: false, undoLabel: null, redoLabel: null })
})
