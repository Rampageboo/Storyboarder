# Codex Model Routing

Read this module when choosing a Codex model. Verify availability in the active
environment and report the model that actually ran.

Route by whether a material decision remains:

- `gpt-5.6-luna` at `max`: execution when the goal, scope, and success criteria
  are already decided.
- `gpt-5.6-sol` at `medium`, `high`, or `xhigh`: architecture, ambiguity,
  difficult diagnosis, cross-module judgment, or consequential risk.
- `gpt-5.6-spark` at `xhigh`: verification runs — reproduction, tests, builds,
  and checks against a stated expected result. Effort is not lowered because the
  commands are mechanical; judging whether a check actually tests the stated
  acceptance criterion is not.

Task size is not the deciding factor. A small unresolved design choice belongs
to the judgment model; a large mechanical change may belong to the executor.

Escalate when the executor cannot establish the cause, repeats the same failure,
needs materially broader scope, or reaches an architecture, compatibility,
migration, security, or data-risk decision. Carry forward the minimum sufficient
contract in `capability-routing.md` plus the verified work the replacement would
otherwise repeat, rather than starting over.

Model choice does not change engineering role or authority. Parallel workers
still follow `capability-routing.md`.
