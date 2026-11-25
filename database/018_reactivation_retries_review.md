# Reactivation retries 018 — approved

Approval: `APPROVE REACTIVATION RETRIES 018 MAIN + TEST SQL` (14 November 2026).
Isolated and main schemas applied; six focused retry tests and 101 relevant regression tests passed.

The user now requests another appeal after rejection. The approved 017 UNIQUE(user,event)
currently allows only one lifetime request for a suspension. Reusing that row would erase
the original request/decision; this proposal instead preserves every existing record.

Exact SQL: `018_reactivation_retries.sql` (main), `018_reactivation_retries_test.sql` (isolated).
One ALTER adds a generated nullable pending-event column, a UNIQUE(user,pending-event)
index and a user/event/history index, replacing the lifetime UNIQUE(user,event) index.
MySQL permits multiple NULLs in UNIQUE: historical decided requests remain; only one
Pending request for each user/current event can exist. Existing foreign keys stay in place.
No new tables, account/status changes, DELETE, broad grants or dependencies are required.
All current application grants already cover the necessary SELECT/INSERT/status updates.

Both roles use the same restricted routes and service. Retry requires a currently suspended,
credential-bound restricted identity, the latest rejected request ID from the reviewed form,
CSRF, message validation and the existing five-attempts-per-15-minutes limit. Locks serialize
submissions with Admin decisions. Pending duplicates and stale retry forms are rejected.
Each retry has its own request ID, immutable previous decision and append-only audit events.
The latest rejection remains visible alongside a Request Again form and recent history.
Approval continues to require Admin password/CSRF and a fresh normal user Login.

Activation: ACCOUNT_REACTIVATION_RETRY_ENABLED=1 only after approved isolated SQL/tests,
fresh verified main backup, main DDL/integrity checks and a controlled main app restart.
Without that flag the existing 017 one-request policy remains in force. Queue visibility
fixes (All default, counts, dashboard and user-details links) do not require this migration.

Risks: MySQL DDL auto-commits and the STORED generated column may rebuild/lock the table.
Use a short maintenance window and stop if preflight finds unexpected/partial schema.
Verify backup hashes; restore rehearsal is not claimed. Compare all original-column rows
before/after and verify one-Pending enforcement with disposable isolated fixtures only.
Do not create/suspend/reactivate real accounts for testing.

Rollback: keep additive history and indexes. Disabling only the retry feature prevents new
retries without weakening restricted-session enforcement. Never automatically recreate the
old lifetime UNIQUE after multiple historical appeals exist; that would fail or lose history.
Any schema rollback/restore needs its own reviewed approval. Never disable normal token scope
guards or the existing ACCOUNT_REACTIVATION_ENABLED security flag.

## Completed rollout

Applied to isolated and main databases on 14 November 2026 after approval.
Main backup: `instance/backups/before_reactivation_retry_20261114T052709Z_935291.sql` (UTC filename).
Hashes verified; restore rehearsal not performed. Original-column row digests for all 34 existing
tables remained identical. No new grants or dependencies were installed, and no main account or
appeal was created/decided for testing. ACCOUNT_REACTIVATION_RETRY_ENABLED=1 activated after tests;
main Flask app restarted on port 5000 and readonly HTTP/asset/schema/aggregate queue checks passed.
