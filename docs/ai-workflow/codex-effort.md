# Codex Effort and Session Lifecycle

Read this module when creating a role session or replacing one. It is guidance
for whoever creates the session — inside Codex, that is the Lead. It is not
orchestration guidance: Claude states the goal and challenges the framing, and
does not select an executor's effort.

Choose the lowest effort that can reliably complete and verify the work:

- low or below: trivial/mechanical work;
- medium: routine implementation and focused tests;
- high: difficult debugging, shared workflows, persistence, schemas,
  concurrency, or security-sensitive work;
- xhigh or above: exceptional ambiguity, impact, or repeated failed approaches.

Supported tiers depend on the model/account and may include
`none|minimal|low|medium|high|xhigh|ultra|max`; let the server validate them.

Set the effort when the session is created, together with the model and the
opening task. It is fixed for that session's life: continuing a session does not
change either, and naming an effort in the prompt changes nothing at all.

To work at a different effort, create a new session with the minimum contract
and the material continuity state defined in `capability-routing.md`. Preserve
decisions and verified evidence that cannot be efficiently recovered; do not
prescribe the new session's reasoning path or repeat recoverable background.

Verify what actually ran before reporting it. The session rollout under
`~/.codex/sessions/` records the real model and effort per turn; a brief records
only an intention.
