# Phase 2 — Recovery Step 1: retry failed replacement versions

This is the **first** of the three requested post-Milestone-6 hardening steps. It does not close Phase 2 or implement stale-job recovery.

## Scope

- Retry a failed replacement (version 2+) while an existing ready version remains active.
- Only a fresh administrator session may initiate the operation.
- The privileged database RPC atomically claims the failed candidate under a document row lock, rejecting a concurrent retry or another processing candidate.
- On successful ingestion, the existing activation RPC switches the active version. On failure, the existing failure handler marks the candidate failed; the old active version stays ready.
- Uses existing `knowledge_document_reprocessed` audit action.

## Installation

1. Commit/back up your working source, then extract this ZIP and merge `database/`, `services/`, `pages/`, `tests/` into `knowledge-hub/` (copy files, do not replace whole directories). These files were generated from the Milestone 5 package; if you modified those same Python files after installing Milestone 5, compare and merge changes rather than overwriting them blindly.
2. In Supabase SQL Editor execute `database/migrations/005_phase2_failed_replacement_retry.sql` **after migrations 001–004**. Do not execute a migration twice without first checking its effect. The function is replaceable; the transaction does not modify existing document records.
3. Restart Streamlit and run `python -m pytest -q`. Prior verified baseline: 69 tests. The patch adds 3 focused tests, so expect **72 passing** if your test suite matches that baseline.

## Manual verification with disposable test content

1. Use an existing disposable ready document with version 1 active.
2. Stage a replacement version 2 and cause it to fail naturally with a non-sensitive test condition, such as temporarily removing the OpenAI key from *local* secrets before clicking Process replacement. Restore the key and restart Streamlit afterward. Never deliberately interrupt an active database transaction or change statuses manually.
3. Verify the version 2 candidate is `failed` and the document is `ready` with version 1 active.
4. In Knowledge Management → Manage, click **Retry failed replacement v2** once.
5. Confirm version 2 is now `ready` and active, and version 1 is `superseded`; retrieval must not mix the two versions. Verify the audit action `knowledge_document_reprocessed`.
6. Confirm the Retry button disappears after successful processing, and normal users cannot invoke it.

Read-only status check:

```sql
select d.display_name, d.status as document_status, d.active_version_id,
       v.id as version_id, v.version_number, v.status as version_status,
       v.processing_claimed_at, v.chunk_count, v.error_summary
from public.knowledge_documents d
join public.knowledge_document_versions v on v.document_id=d.id
where d.deleted_at is null
order by d.created_at desc, v.version_number desc;
```

## Boundaries and cautions

- This does not recover an interrupted job stuck in `processing`, nor does it add timeout/ownership tokens. Do not reset those records manually.
- This does not introduce scheduled workers or asynchronous processing.
- If a failed replacement had a Storage upload failure, its original object may not exist. Retry will fail safely again; a future workflow may permit uploading a new candidate.
- If a service-role credential is compromised, SQL-level service-role-only checks cannot protect against that; keep credentials server-side.
- Python syntax was checked. Full pytest and live SQL execution were **not** possible in the isolated environment because the `supabase` package is missing. Please verify in your actual environment.

After testing, report the test count, migration result, retry behaviour, old-version availability during processing, audit result, and any errors. We will not proceed to Step 2 until you confirm.
