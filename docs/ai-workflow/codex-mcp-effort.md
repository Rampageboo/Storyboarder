# Codex Effort and Thread Lifecycle

Read this module when selecting reasoning effort or replacing a thread.

Use the lowest effort that can reliably complete and verify the work:

- low or below: trivial/mechanical work;
- medium: routine implementation and focused tests;
- high: difficult debugging, shared workflows, persistence, schemas,
  concurrency, or security-sensitive work;
- xhigh or above: exceptional ambiguity, impact, or repeated failed approaches.

Supported tiers depend on the model/account and may include
`none|minimal|low|medium|high|xhigh|ultra|max`; let the server validate them.

Effort is set when a thread is created through
`config.model_reasoning_effort`. Continuing a thread does not change its model
or effort. To upgrade, start a new thread with the minimum contract and material
continuity state defined in `capability-routing.md`. Preserve decisions and
verified evidence that cannot be efficiently recovered; do not prescribe the
new thread's reasoning path or repeat recoverable background.
