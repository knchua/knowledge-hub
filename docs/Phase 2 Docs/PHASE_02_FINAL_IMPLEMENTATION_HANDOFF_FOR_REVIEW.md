# Knowledge Hub — Phase 2 implementation handoff (FOR REVIEW)

**Prepared:** 30 October 2026
**Status:** Final handoff draft, awaiting explicit user approval. **Phase 2 is not formally closed; Phase 3 has not started.**
**Evidence basis:** Phase 2 specification, implementation packages and user-reported Supabase/Streamlit/pytest verification results. A current, post-patch integrated repository and live Supabase environment were not independently audited for this handoff.

## 1. Purpose and scope

Phase 2 implements the administrator-managed shared knowledge repository and ingestion foundation for a future document-grounded RAG chatbot. Scope: PDF/DOCX/TXT upload, validation, duplicate detection, private original-file storage, LangChain extraction/chunking, OpenAI embeddings, pgvector storage, citation metadata, document status, version-aware replacement, deletion, recovery, and administrative audit events.

**Out of scope:** chatbot answer generation, conversational memory, user-uploaded document summarisation/analysis, OCR, sophisticated table-layout reconstruction, document-level ACLs, dedicated background worker/scheduler.

## 2. Technology and configuration

- UI/runtime: Streamlit and Python; target Streamlit Community Cloud.
- Identity/access: Existing Supabase Auth, active-account/role validation and administrator-only server-side operations. Existing Phase 1 authorisation, privileged Supabase client and audit facilities reused.
- Original document storage: private Supabase Storage bucket `knowledge-documents`; PDF, DOCX and TXT only; 20 MB application/Streamlit/bucket limit as configured.
- Parsing/chunking: PyMuPDF (PDF), python-docx (DOCX), Python text handling (TXT); LangChain `RecursiveCharacterTextSplitter`, initial chunk size 1,000 characters and overlap 200.
- Embeddings: OpenAI `text-embedding-3-small`, default dimension 1,536, stored via pgvector.
- Secrets: untracked local `.streamlit/secrets.toml` and deployment-provided secrets; OpenAI key at top level, separate from nested TOML sections. Never commit API or service-role keys.

## 3. Database and Storage design

| Object | Function |
|---|---|
| `public.knowledge_documents` | Logical document, status, active-version pointer, soft deletion |
| `public.knowledge_document_versions` | Immutable version identifiers, Storage paths, checksum, ingestion/cleanup statuses and lease ownership |
| `public.knowledge_chunks` | Chunk text, order, page/source metadata, `vector(1536)` embedding |
| `knowledge-documents` (private bucket) | Original PDF/DOCX/TXT objects under UUID-based paths |

**Retrieval-ready contract:** select chunks only when the document is non-deleted, the version is `ready`, and `active_version_id` matches the chunk's version. The project uses the `match_knowledge_chunks` retrieval interface. Phase 3 must confirm its grants, active-account checks, and citation return fields against the deployed schema before consuming it.

**Lifecycle invariants:** keep the previous ready version active until replacement ingestion is fully committed; activate the candidate atomically; do not expose processing/failed/superseded/deleted content through retrieval; exclude deleted content before asynchronous cross-service cleanup. Superseded files/vectors are cleaned up while version metadata and audit trace are retained as agreed.

## 4. Applied SQL migrations (user-reported)

1. `001_phase1_foundation.sql` — Phase 1 profiles, audit and RLS baseline (pre-existing).
2. `002_phase2_knowledge_management.sql` — knowledge schema, pgvector, RLS/retrieval and Storage foundation.
3. `003_phase2_failed_ingestion_retry.sql` — controlled retry for failed initial ingestion.
4. `004_phase2_document_lifecycle.sql` — replacement, deletion and cleanup support.
5. `005_phase2_failed_replacement_retry.sql` — controlled retry for failed replacement candidates.
6. `006_phase2_ingestion_leases.sql` — per-attempt processing ownership, lease timeout and fenced DB operations (`kh_claim_ingestion`, `kh_append_ingestion_chunks`, `kh_finish_ingestion`, `kh_fail_ingestion`). The implementation uses a 30-minute lease, refreshed on successful chunk batches.

No subsequent schema migration is recorded for the Step 3A/3B verification scripts. Step 3A used a corrected pgvector test literal (`[... ]` rather than a PostgreSQL `{...}` array).

## 5. Implemented service and interface areas

- Administrator Knowledge Management page: upload, list/inspect, process ingestion, replacement, deletion, retry actions and cleanup where supported.
- Document service: size/type/content validation, SHA-256 duplicate checking, UUID-based Storage paths, metadata and audit events.
- Ingestion service: extract source text and PDF page references, chunk, generate embeddings, store vectors, set processing outcomes.
- Repository and SQL functions: manage versions and active pointer; enforce ownership tokens for chunk writes and finalisation; reject stale workers following a successful reclaim.
- Diagnostic service: report potentially stale processing versions without modifying them. The optional administrator diagnostic UI was not manually verified.

## 6. Verification evidence

| Checkpoint | Reported result |
|---|---|
| Phase 1 baseline | At least 44 tests passing |
| Milestone 3 document management | 57 passing tests |
| Milestone 4 ingestion and initial retry | 64 passing tests |
| Milestone 5 lifecycle | 69 passing tests; eight lifecycle checks passed |
| Milestone 6 SQL/security/manual/deployment readiness review | All four review categories reported passed, at then-current 69 tests |
| Recovery Step 1 failed replacement retry | 72 passing tests; failed replacement successfully retried, active version preserved |
| Recovery Step 2A stale-job detection | 76 passing tests; optional UI and live detection checks deferred |
| Recovery Step 2B updated ingestion | Automated suite passed after compatibility changes (final count not reported); new TXT ingestion succeeded |
| Lease ownership verification | Seven controlled SQL checks passed (expired reclaim, stale-token rejection, etc.) |
| Step 3A atomic activation | Six controlled SQL checks passed, disposable records rolled back |
| Step 3B two-connection concurrency | **Deferred by explicit user decision**; no separate development Supabase project |

**Important test-count qualification:** 76 is the latest *explicitly reported count*, not a confirmed post-Step-2B test total. The user confirmed the suite passed after the Step 2B compatibility fix, without supplying the number. Do not claim 79 or another final total as measured.

## 7. Accepted limitations and residual risk register

| Issue | Current evidence / impact | Disposition and recommended follow-up |
|---|---|---|
| True two-connection concurrency | **Not executed.** Sequential lease and atomicity checks cannot prove simultaneous behaviour. | **Accepted deferred verification** for bootcamp. Run against isolated development Supabase before multi-admin/production workloads. |
| Competing replacement candidates / concurrent activation | Step 3A checks sequential activation; simultaneous competing candidates not independently tested. | Defer; create multi-connection stress/failure-injection tests before broader release. |
| Long embeddings beyond lease window | Lease is 30 minutes and renews on chunk batch writes; prolonged embedding calls may outlast lease. | Monitor timings; add heartbeat/renewal while long external calls run or redesign worker scheduling as needed. |
| Detection of old `processing` jobs | Detection service has automated tests; live dashboard integration and normal-user manual rejection not fully demonstrated for this optional UI. | Accepted manual verification deferral. Verify operational visibility when enabling admin recovery tooling. |
| Interrupted ingestion recovery usability | Token fencing and stale claim reclaim proven in controlled SQL; dedicated UI recovery and automated scheduler are not established. | Use controlled administrator procedure; do not manually edit statuses. Design an operational recovery UX before production. |
| Cross-service cleanup | Supabase Storage and PostgreSQL are not one transaction; partial deletion/cleanup remains possible after failures. | Monitor cleanup status; use idempotent retry and reconciliation; test network-failure injection. |
| Broad production hardening | No independent live production security audit or high-load benchmark. | Limit to bootcamp/demo use pending audits, observability and deployment testing. |

## 8. Operational notes and rollback

- Supabase logical database backup completed before migration 006, per user confirmation; original Storage files require separate backups because database dumps do not contain file bytes.
- Do not apply old migrations again or manually reset processing statuses to force retries.
- Retain Python dependency lock/version information and `.streamlit/config.toml` (`maxUploadSize = 20`) in source control; never commit `.streamlit/secrets.toml`.
- In case of lifecycle problems, stop ingestion, preserve logs and state, diagnose tokens/leases/status, and prepare targeted fixes; avoid full database restore unless necessary and rehearsed.

## 9. Architecture decisions to return to master planning chat

1. Retain Supabase PostgreSQL + pgvector, private Supabase Storage and Streamlit Community Cloud for the bootcamp scope.
2. Use shared, active-ready document retrieval rather than document-level ACLs; add ACL-aware retrieval only as future scope.
3. Treat failed/expired attempts with fenced ownership tokens and controlled admin recovery, rather than direct status edits.
4. Preserve version metadata/audit while cleaning up superseded content, subject to any future retention-policy revision.
5. Defer full multi-connection concurrency verification and longer-running worker/heartbeat architecture; revisit before production.

## 10. Phase 3 prerequisites and boundary

On explicit approval to close Phase 2, Phase 3 can consume the retrieval interface to implement grounded chatbot responses and source citations. Before writing answer-generation code, confirm that retrieval excludes deleted, failed, processing and superseded versions; respects active-account permissions; and exposes document name, `document_id`, `version_id`, page/chunk positions and source metadata. Phase 3 must not treat embedding retrieval alone as permission enforcement.

## 11. Closure decision requested

**For review only.** The user has accepted deferring Recovery Step 3B. The remaining limitations above should be acknowledged in the final closeout. Do **not** mark Phase 2 formally complete or begin Phase 3 unless the user explicitly approves this handoff and closure.
