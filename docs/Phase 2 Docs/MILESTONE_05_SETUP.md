# Knowledge Hub — Phase 2 Milestone 5 setup (NOT YET VERIFIED IN LIVE SUPABASE)

## Preconditions
- Milestones 1–4 and retry patch applied successfully; 64 tests passing.
- Commit your code or take a backup; keep local secrets excluded from Git.
- **Do not copy folders wholesale**. Files in this patch replace only the listed paths.
- Have Supabase SQL Editor access and credentials properly configured server-side.

## Files
- `database/migrations/004_phase2_document_lifecycle.sql` — SQL migration 004
- `services/knowledge_lifecycle_service.py` — new lifecycle service
- `services/knowledge_service.py` — same Milestone 3 service, with `cleanup_status` in `list_versions` query
- `services/knowledge_ingestion_service.py` — existing retry service + `process_replacement`
- `database/knowledge_repository.py` — existing repository + replacement claim
- `pages/knowledge_management.py` — existing page + management actions
- `tests/test_knowledge_lifecycle.py` — security and state tests

## Apply and verify
1. In Supabase SQL Editor, review and run migration 004 once, after migrations 001–003.
2. Check new function grants: `register_knowledge_replacement`, `claim_knowledge_replacement`, `fail_knowledge_candidate`, `claim_knowledge_cleanup`, `finalize_knowledge_deletion` must grant execute only to `service_role`.
3. Merge patch files into your project and run `python -m pytest -q`. Baseline is **64 tests**; five tests are added (expect **at least 69** if collection is unchanged).
4. Run `streamlit run app.py` locally, sign in as a current active administrator.
5. Upload and process a new TXT file as the initial version. Verify `ready`, `active_version_id`, and retrievable chunks.
6. Stage a second, materially different TXT file through the **Manage** expander. While it is `processing`, verify the old version is still active and retrievable.
7. Click **Process replacement**. Verify the new version is `ready` and active, and the old version is `superseded` with `cleanup_status=pending`. Test retrieval returns only the new version.
8. Click **Clean superseded** and confirm old chunks and Storage object are gone; retained metadata stays in `knowledge_document_versions`.
9. For a *disposable test document only*, type `DELETE` and delete. Check that retrieval immediately excludes this document, that Storage objects and chunks are cleaned, and `knowledge_documents.status='deleted'`.
10. Verify `audit_logs` for `knowledge_replacement_staged`, `knowledge_document_ingested`, `knowledge_version_cleaned`, `knowledge_document_delete_requested` and `knowledge_document_deleted`.
11. Re-run Phase 1 and Phase 2 regression suite. Do not commit API keys or secret configs.

### SQL verification
```sql
select d.display_name,d.status,d.active_version_id,v.version_number,v.status as version_status,
       v.cleanup_status,v.chunk_count
from public.knowledge_documents d
join public.knowledge_document_versions v on v.document_id=d.id
order by d.created_at desc,v.version_number desc;
```

### Known boundaries / issues to assess before production
- Replacements with failed processing remain recorded as failed and do **not** affect the active version. Failed candidate retry is not yet supported by the Milestone 4 initial-version retry RPC. A new replacement can be staged after investigating the failure.
- Interrupted ingestion of `processing` replacements is not automatically recovered. The candidate's `processing_claimed_at` records the claim; a timeout/lease and controlled stale-claim recovery are **not** implemented here. Do not reset the flag manually.
- Storage deletion and PostgreSQL cannot share an atomic transaction; cleanup can be retried after an interruption.
- Retained metadata after deletion includes the original filename and checksum. Reassess retention/privacy policy before production.
- Run manual concurrency, failure-injection, audit-failure and retrieval access tests before considering production-ready.
- A cleanup attempt can be retried using `cleanup_version` for superseded versions, but the UI may not refresh if an old client is still running.

**Pause for your verification and approval before Milestone 6.**
