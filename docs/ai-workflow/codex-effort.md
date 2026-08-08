# Codex Effort and Session Lifecycle

Creator selects child-session effort. Execution chain: Lead creates Implementer;
Implementer creates Verifier.

```text
<=low      trivial / mechanical
medium     routine implementation + focused checks
high       difficult debug / shared workflow / persistence / schema / concurrency / security
xhigh+     exceptional ambiguity / impact / repeated failed approaches
```

Available tiers are model/account scoped. Server validation is authoritative.

Session creation binds:

```text
model + effort + opening assignment
```

Model and effort remain fixed for session life. Effort change => new session.

Replacement assignment carries minimum contract plus decisions and verified
evidence whose recovery cost is material.

Report actual runtime values. Session rollout
`~/.codex/sessions/<yyyy>/<mm>/<dd>/rollout-*.jsonl` records model and effort per
turn; assignment records intent.
