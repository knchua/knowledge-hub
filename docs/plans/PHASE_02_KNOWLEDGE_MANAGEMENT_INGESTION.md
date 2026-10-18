# Knowledge Hub — Phase 2: Knowledge Management & Document Ingestion

**Status:** Planned — ready for implementation  
**Prerequisite:** Phase 1 Application Foundation completed and verified (reported >=44 passing tests).  
**Architecture:** Streamlit + Python + Supabase Auth/PostgreSQL/Storage/pgvector + LangChain + OpenAI.  
**Deployment target:** Streamlit Community Cloud; develop locally first.

## 1. Objective

Implement administrator-only management of the central knowledge repository and a reliable pipeline that converts uploaded documents into searchable, source-attributed embeddings. Phase 2 prepares retrieval data; it does **not** implement chatbot answers or summarisation.

## 2. Prerequisites and integration constraints

- Reuse existing Phase 1 authentication, `require_admin()` checks, active-account enforcement, navigation, Supabase clients, secrets conventions, migrations and audit logging. Do not rewrite working Phase 1 services.
- Inspect the actual repository, schema, RLS policies, dependencies and tests before coding. This document is a specification, not a claim that any proposed table/file already exists.
- Privileged service-role operations must remain server-side and must re-check the authenticated actor's effective role and active status. Streamlit session state is not authoritative.
- Preserve current invitation, recovery and user administration functionality.

## 3. Scope

### In scope

1. Administrator-only upload, list, inspect, replace, delete and retry of shared knowledge documents.
2. Support digitally readable PDF, DOCX and TXT initially.
3. Validate extension, actual file format where feasible, file size, non-empty content and duplicate content.
4. Store original documents in a **private** Supabase Storage bucket.
5. Extract text with source metadata (filename, page number for PDFs when available, and chunk ordering).
6. Split text with LangChain `RecursiveCharacterTextSplitter`, starting at 1,000 characters with 200-character overlap; tune later.
7. Generate embeddings using OpenAI `text-embedding-3-small` (1,536 dimensions), configured centrally.
8. Persist document metadata, versions, chunks and vectors in Supabase PostgreSQL with pgvector.
9. Track processing status and errors; provide safe retries.
10. Implement version-aware replacement, controlled deletion, and audit logging.
11. Add automated and manual tests, SQL migrations, setup instructions and configuration documentation.

### Out of scope

- Chatbot responses, prompts, LLM answer generation and conversational memory (Phase 3).
- End-user temporary document upload, summarisation and analysis (Phase 4).
- OCR for scanned PDFs, spreadsheet and presentation extraction, complex table/layout reconstruction.
- Background worker infrastructure and scheduled ingestion at scale, unless needed to resolve demonstrated runtime limits.
- Document-level user permissions beyond the current shared repository (future enhancement).

## 4. Functional design

### Upload

- Check administrator authorisation on the server before any privileged action.
- Enforce configurable upload-size limits, allowlisted types and validation; avoid trusting the filename alone.
- Calculate a SHA-256 content checksum and reject or explicitly flag exact duplicates.
- Create a document/version record in `processing` status; use UUID-based storage paths rather than raw user filenames.
- Upload the original to private Storage, extract text, split chunks, generate embeddings, persist chunks/vectors, and mark the version `ready` only when complete.
- Report understandable errors without leaking secrets or raw provider errors.

### List and inspect

- Show document name, type, size, uploaded/updated dates, active version, processing status, chunk count and any safe error summary.
- Offer an admin-only view of processing details and retry actions.

### Replace

- Create a new immutable version and ingest it separately.
- Keep the prior `ready` version active while the replacement is processing.
- Atomically switch the active-version pointer after the new version and all vectors are committed.
- On failure, retain the previous active version and mark the candidate as `failed`; clean up incomplete candidate artifacts safely.
- Retain or purge superseded originals/vectors according to an explicit retention policy; initial recommendation: retain metadata and audit trail, but clean up superseded files/vectors after a successful cutover unless a rollback requirement is agreed.

### Delete

- Require explicit admin confirmation.
- First make the document unavailable for future retrieval (e.g., soft-delete state or active-version removal in a database transaction), then remove vectors and Storage objects.
- Record and retry partial cleanup failures; do not silently leave deleted documents searchable.
- Preserve minimal audit records without storing deleted document content.

### Retry and failures

- Support retry of failed processing without duplicating ready chunks or changing the active version prematurely.
- Treat Storage, OpenAI and PostgreSQL as separate services; design idempotent operations and compensating cleanup rather than assuming a distributed transaction.
- Provide bounded retries/backoff for transient API failures, and handle Streamlit reruns safely.

## 5. Proposed data model (adapt to existing schema)

- `knowledge_documents`: `id` UUID PK, `display_name`, `mime_type`, `size_bytes`, `checksum_sha256`, `active_version_id` nullable, `status`, `created_by`, `created_at`, `updated_at`, `deleted_at` nullable.
- `knowledge_document_versions`: `id` UUID PK, `document_id` FK, `version_number`, `storage_path`, `checksum_sha256`, `status` (`processing`, `ready`, `failed`, `superseded`), `chunk_count`, `error_summary` nullable, `created_by`, `created_at`, `completed_at` nullable.
- `knowledge_chunks`: `id` UUID PK, `document_id` FK, `version_id` FK, `chunk_index`, `content`, `page_number` nullable, `source_metadata` JSONB, `embedding` vector(1536), `created_at`.
- Add pgvector extension and appropriate index/constraints. For a small corpus, exact similarity search may be sufficient initially; introduce HNSW/IVFFlat only after checking operator compatibility, data size and query performance.
- Provide a parameterised SQL retrieval function or a repository abstraction that returns chunks **only from ready, active, non-deleted versions**. Phase 3 will use this contract.
- Preserve existing Phase 1 audit tables; extend event types for upload, replacement, deletion and retry rather than introducing competing audit mechanisms.

### Security

- Enable RLS and explicitly define grants/policies for new tables; do not leave them publicly writable.
- Admin writes must be restricted. Ordinary authenticated users may retrieve only active shared knowledge through the approved read path, not staging, failed or deleted versions.
- Private Storage bucket and policies must block anonymous/public access. Never expose service-role credentials or OpenAI API keys in UI, logs or Git.
- Parameterise queries and validate storage object paths; do not trust user-provided document IDs without server-side checks.

## 6. Ingestion pipeline

1. Authenticate and authorise administrator.
2. Validate file and check checksum.
3. Create metadata and candidate version.
4. Upload original to private Supabase Storage.
5. Parse PDF/DOCX/TXT and collect source metadata.
6. Split into LangChain document chunks.
7. Generate OpenAI embeddings (batch where appropriate, bounded by provider limits).
8. Persist chunks, vectors and processing result.
9. Mark version ready and activate atomically (for replacement, swap active pointer).
10. Record audit event and show completion details.

Keep ingestion behind services/repositories, not inside Streamlit page functions. Do not invoke LLM answer generation in this phase.

## 7. Proposed code modules

Adapt to the real repository structure rather than creating duplicates:

- `services/knowledge_service.py` — document lifecycle and authorisation integration.
- `services/ingestion_service.py` — parsing, chunking, embedding and status transitions.
- `services/embedding_service.py` — OpenAI embedding wrapper/configuration.
- `database/knowledge_repository.py` — metadata, chunk persistence and retrieval contract.
- `pages/knowledge_management.py` — admin-only Streamlit interface.
- `database/migrations/` — versioned SQL schema, functions, policies and indexes.
- `tests/` — validation, lifecycle, permissions, failure recovery and retrieval-readiness tests.

## 8. Implementation milestones

1. **Repository review and design confirmation:** inspect Phase 1 implementation and finalise schema, security model, file-size limit, and superseded-version retention policy.
2. **Database and Storage setup:** migrations, private bucket, RLS, indexes and safe retrieval contract.
3. **Document management:** upload/list/details, file validation, checksums and metadata.
4. **LangChain ingestion:** text extraction, chunking, OpenAI embeddings and pgvector persistence.
5. **Lifecycle management:** replace, delete, retry, failure cleanup and audit integration.
6. **Verification:** automated tests, manual scenarios, deployment-readiness review and documentation.

Pause for user verification at each milestone; avoid broad refactors of Phase 1.

## 9. Acceptance criteria

- [ ] Only active admins can upload, replace, delete and retry knowledge documents.
- [ ] Ordinary users and anonymous visitors cannot invoke admin operations via direct calls.
- [ ] Supported PDF, DOCX and TXT documents can be uploaded and processed.
- [ ] Invalid, empty, oversized and duplicate uploads are handled predictably.
- [ ] Original files are stored privately in Supabase Storage.
- [ ] Extracted chunks retain source name and PDF page references where available.
- [ ] LangChain chunking and OpenAI embeddings generate 1,536-dimensional vectors.
- [ ] Vectors persist in Supabase pgvector and can be retrieved by a test similarity query.
- [ ] Retrieval excludes processing, failed, superseded and deleted versions.
- [ ] Failed replacement does not disrupt the previous active document.
- [ ] Successful replacement switches active version without mixed-version results.
- [ ] Deleted documents stop appearing in retrieval immediately; cleanup failures are detectable/retryable.
- [ ] Retry does not create duplicate ready chunks.
- [ ] Administrative operations are audited without leaking secrets or document content.
- [ ] Existing Phase 1 tests continue to pass, and new Phase 2 tests pass.
- [ ] Setup, secrets, migrations, operational limits and Streamlit Cloud considerations are documented.

## 10. Risks and mitigations

| Risk | Mitigation |
|---|---|
| Streamlit reruns duplicate ingestion | Explicit operation IDs, idempotent version records, UI submit controls |
| Cloud runtime/memory/time limits for large documents | Configurable size/chunk limits, clear failures, consider async worker later |
| API cost and rate limits | Estimate chunk counts, batch embeddings, bounded retries, report errors |
| Replacement creates mixed results | Active-version pointer and atomic activation |
| Deletion leaves orphaned Storage objects | Retrieval exclusion first, cleanup log and retry |
| Poor PDF extraction or missing page references | Per-page extraction, warnings, defer OCR |
| Vector schema/model mismatch | Pin embedding model and dimension; document migration plan for model changes |
| Sensitive document exposure | Private bucket, RLS, server-side auth, minimal logging |

## 11. Phase 2 handoff

Return to the master planning chat with the final schema and policies, implemented services and UI, sample ingestion/retrieval verification, test counts, deployment implications, unresolved issues and any deviations from this plan. Phase 3 will build the grounded RAG chatbot on the active-document retrieval contract.
