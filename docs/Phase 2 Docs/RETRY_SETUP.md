# Phase 2 Milestone 4 — Safe retry patch

This patch adds explicit administrator-initiated retry for **failed initial versions only**. It does not add replacement, deletion, automatic background retries or stale-processing recovery. It uses the same OpenAI ingestion pipeline and may incur API charges.

## 1. Install safely

1. Commit/back up your current Knowledge Hub source. Do not include `.streamlit/secrets.toml` or `.env`.
2. Copy the files in this patch into your repository, **merging** subfolders. Replace the three named existing files `database/knowledge_repository.py`, `services/knowledge_ingestion_service.py` and `pages/knowledge_management.py` with their corresponding patch files. Add the new SQL migration and test file. Do not delete any other files.
3. In Supabase SQL Editor, execute `database/migrations/003_phase2_failed_ingestion_retry.sql` *once*, after the existing migration 002. No Storage bucket changes are required.
4. Run `python -m pytest -q` in your activated virtual environment; confirm all previous tests and four new focused tests pass.
5. Restart `streamlit run app.py` and sign in as an active admin. In Knowledge Management, open a previously failed **version 1** document with no active version, then click **Retry processing** once. Watch the output and check the result.

## 2. Verify in Supabase SQL Editor

```sql
select d.display_name, d.status as document_status,
       v.version_number, v.status as version_status, v.chunk_count,
       (select count(*) from public.knowledge_chunks c where c.version_id = v.id) as stored_chunks,
       (d.active_version_id = v.id) as is_active
from public.knowledge_documents d
join public.knowledge_document_versions v on v.document_id = d.id
where d.deleted_at is null
order by d.created_at desc;
```

After a successful retry: document and version `ready`, `is_active = true`, and `stored_chunks = chunk_count > 0`. Check `audit_logs` for `knowledge_document_reprocessed`. The `knowledge_chunks` table must not have duplicate `(version_id, chunk_index)` entries (also prevented by a unique constraint).

A failed retry should return to `failed`, with 0 chunks and no active version. If you see a cleanup error or `processing` that never finishes, **do not edit database states manually**. Report the error; stale claim recovery needs a separate controlled operation.

## 3. SQL permission check

```sql
select routine_name from information_schema.routines
where routine_schema = 'public' and routine_name = 'claim_failed_knowledge_version';

select has_function_privilege('authenticated',
  'public.claim_failed_knowledge_version(uuid,uuid)', 'EXECUTE')
  as authenticated_can_execute;
```

Expected `authenticated_can_execute = false`. The RPC must be callable only with the server-side service role after application administrator checks. Do not grant direct execute privileges to ordinary clients.

## Limitations and security

- Retry is supported only where document `status=failed`, version 1 `status=failed`, and `active_version_id IS NULL`. It will not touch an active version.
- An interrupted process can leave a version in `processing`; this patch does **not** automatically reclaim stale work. Safe stale claim recovery requires extra locking/lease design and belongs to the lifecycle milestone.
- Existing initial processing remains unchanged in concurrency semantics; this patch addresses concurrency specifically for retries.
- Provider exception text is not logged in this version, reducing accidental credential/content disclosure; the console reports the exception class and version ID. UI/database only show safe error summaries.
- SQL `SECURITY DEFINER` permissions have been narrowed to `service_role`; never expose a service-role key in client code.
