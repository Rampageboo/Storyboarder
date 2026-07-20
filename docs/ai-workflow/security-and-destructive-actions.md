# Security and Destructive Actions

Read this module when work touches secrets, credentials, personal data,
security/privacy, destructive operations, migrations, releases, billing, or
external-service configuration.

Codex and Claude must not accept risk on the Owner's behalf. Owner approval is
required for:

- deleting user data or destructive migration;
- removing major existing capability;
- accepting security, privacy, data-loss, or automation-input risk;
- adding paid services, external accounts, or billing changes;
- publishing releases;
- introducing secrets or credentials into project files;
- force-push or destructive history rewriting.

Never expose secret values in packets, logs, commits, or `PROJECTCONTEXT.md`.
Reference the approved storage location, not the value.

Before any authorized destructive action, state the exact target, impact,
rollback/recovery path, validation, and approval owner. Prefer reversible,
scoped alternatives. Do not broaden an approval beyond the named action.

Security-sensitive implementation requires risk-focused validation. If evidence
is incomplete, report what remains unverified and stop before risk acceptance.
