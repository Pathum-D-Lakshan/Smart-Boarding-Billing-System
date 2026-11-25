# Approved Maintenance photos - applied 10 November 2026

User approval: `APPROVE MAINTENANCE PHOTOS 014 SQL + GRANTS + TEST SQL`.
Isolated rollout/tests completed before main additive rollout. Fresh main backup
hash verified; all 29 original tables' record digests remained unchanged. Exact
new-table grants verified: main SELECT/INSERT, isolated SELECT/INSERT/DELETE.
`MAINTENANCE_PHOTOS_ENABLED=1` was activated locally after main verification.
No new dependency was installed. No restore rehearsal is claimed.
Private evidence: `instance/maintenance_photos_isolated_rollout_report.json` and
`instance/maintenance_photos_main_rollout_report.json`.

Core text maintenance requires no schema change. Inspection confirmed only
maintenance_requests and maintenance_events exist; neither stores an attachment.
Do not put photo metadata into expense/payment tables or bypass approval through
untracked public files. No category model is proposed; existing Location/Priority
remain the approved request fields.

Complete SQL is in:

- `014_maintenance_photos.sql`: one additive, one-photo-per-request table.
- `014_grant_maintenance_photos_app.sql`: SELECT/INSERT on that new table only.
- `014_maintenance_photos_test.sql`: matching isolated table with fixture cleanup
  DELETE only for the dedicated approved test account.

No existing tables/records are altered or reset. No app UPDATE/DELETE or broad
schema privileges. Request FK/primary key and unique generated filenames preserve
the existing operational record and one-attachment limit. SHA-256, byte/dimension
checks support integrity verification; the database stores no raw image bytes.

Approved implementation accepts optional JPG/JPEG/PNG only (no PDFs), at most 5 MiB,
validate actual image content using the existing installed Pillow/image validation
infrastructure, normalize orientation/strip metadata, resize within 1920px and
store generated WebP privately under instance/maintenance-photos (not static).
Only reporting Student/correct Boarding Owner may view/download through existing
request authorization. No arbitrary file path/filename from the browser. No public
file URL. No additional dependency is required.

Upload/metadata is part of the existing creation transaction; preserve idempotent
submissions and reject conflicting repeated content. Failure cleanup checks database
references so a lost COMMIT acknowledgement never deletes committed evidence.
Text-only requests remain supported, including when attachment support is disabled.

Completed rollout: fresh main logical backup + private files archive, verified
backup hash, isolated SQL and secure photo/rollback/access tests first, then a
short maintenance window/fresh verified backup and main additive SQL/scoped grants.
All existing record digests and new grants were verified before activating photo
support and restarting the same main app. No restore rehearsal is claimed.
Credentials remain local and were never logged.

Rollback policy: disable photo capability and keep the additive table/files for
review; core text maintenance continues. Do not drop/delete evidence or restore
production data without separate destructive-operation approval. DDL auto-commits.

The original proposal below was approved as described above. Never rerun the
CREATE TABLE scripts against a migrated schema; inspect metadata before changes.
