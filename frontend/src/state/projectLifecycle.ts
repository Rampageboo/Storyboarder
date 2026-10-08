/** Coordinates document actions, domain drafts, and response lifetimes independently of React. */
export class ProjectLifecycle {
  private epoch = 0
  private edits = 0
  private responseRevision = 0
  private active = false
  private committing = false
  private draining: Promise<void> | null = null
  private writes: Promise<unknown> = Promise.resolve()
  private flushers = new Set<() => Promise<void>>()

  capture = () => this.epoch
  accepts = (epoch: number) => epoch === this.epoch
  advance = () => { this.epoch += 1 }
  edited = () => { this.edits += 1 }
  changed = () => { this.responseRevision += 1 }
  captureRead = () => ({ epoch: this.epoch, revision: this.responseRevision })
  acceptsRead = (ticket: { epoch: number; revision: number }) =>
    this.accepts(ticket.epoch) && ticket.revision === this.responseRevision
  seal = () => { this.committing = true }
  get busy() { return this.active }
  get editable() { return !this.committing }

  register = (flush: () => Promise<void>) => {
    this.flushers.add(flush)
    return () => { this.flushers.delete(flush) }
  }

  /** Domain writes share a lane, so whole-project replies cannot race each other. */
  write = <T>(operation: () => Promise<T>): Promise<T> => {
    const epoch = this.capture()
    const result = this.writes.then(() => {
      if (!this.accepts(epoch)) throw new Error('The project changed before the edit could be saved.')
      return operation()
    })
    this.writes = result.catch(() => {})
    return result
  }

  flush = (): Promise<void> => {
    if (this.draining) return this.draining
    const drain = async () => {
      for (let attempt = 0; attempt < 20; attempt += 1) {
        const edits = this.edits
        // Snapshot registrations: a component unmount does not cancel its pending save.
        for (const flush of [...this.flushers]) await flush()
        await this.writes
        if (edits === this.edits) return
      }
      throw new Error('Unsaved edits changed while saving. Try again before continuing.')
    }
    this.draining = drain().finally(() => { this.draining = null })
    return this.draining
  }

  run = async <T>(operation: () => Promise<T>, blocked: boolean, notify: (busy: boolean) => void): Promise<T> => {
    if (blocked) throw new Error('请先保存或关闭绘画编辑器，再保存或切换项目、路线或工作区。')
    if (this.active) throw new Error('Another project action is already in progress.')
    this.active = true
    notify(true)
    try {
      await this.flush()
      return await operation()
    } finally {
      this.committing = false
      this.active = false
      notify(false)
    }
  }
}

/** An immutable domain draft with one in-flight drain. Edits during a save are retried. */
export class DraftBuffer<T> {
  private value: T | null = null
  private pending: Promise<void> | null = null
  private generation = 0
  private readonly persist: (snapshot: T) => Promise<T>
  private readonly changed: (value: T | null, busy: boolean) => void
  private readonly rebase: (newer: T, saved: T) => T
  constructor(persist: (snapshot: T) => Promise<T>, changed: (value: T | null, busy: boolean) => void,
    rebase: (newer: T, saved: T) => T = newer => newer) {
    this.persist = persist
    this.changed = changed
    this.rebase = rebase
  }

  /** Explicit discard/reload waits for an existing request but never retries an invalid draft. */
  settle = async (): Promise<void> => { await this.pending?.catch(() => {}) }

  get current() { return this.value }
  get busy() { return this.pending !== null }
  edit(value: T) { this.value = value; this.changed(value, this.busy) }
  reset() { this.generation += 1; this.value = null; this.changed(null, this.busy) }

  flush = (): Promise<void> => {
    if (this.pending) return this.pending
    if (this.value === null) return Promise.resolve()
    const generation = this.generation
    const drain = async () => {
      for (let attempt = 0; this.value !== null; attempt += 1) {
        if (attempt === 20) throw new Error('Unsaved edits changed while saving. Try again before continuing.')
        const snapshot = this.value
        const saved = await this.persist(snapshot)
        if (generation !== this.generation) return
        this.value = this.value === snapshot ? null : this.value === null ? null : this.rebase(this.value, saved)
        this.changed(this.value, true)
      }
    }
    // Defer persist until pending is assigned, including synchronously resolved saves.
    this.pending = Promise.resolve().then(drain).finally(() => {
      this.pending = null
      this.changed(this.value, false)
    })
    this.changed(this.value, true)
    return this.pending
  }
}
