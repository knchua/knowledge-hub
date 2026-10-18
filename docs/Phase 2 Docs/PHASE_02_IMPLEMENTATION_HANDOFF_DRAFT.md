# Knowledge Hub — Phase 2 implementation handoff (DRAFT, pending Milestone 6 approval)

## Objective and implemented scope

Administrator-only shared knowledge repository using Streamlit/Python, Supabase Auth/PostgreSQL/Storage, LangChain, OpenAI text-embedding-3-small and pgvector. Supports PDF, DOCX and UTF-8 TXT originals, validation, checksum duplicate detection, upload/list, chunk extraction with source metadata, vectors, status tracking, failed initial-version retry, replacement and deletion with cleanup/audit.

**Out of scope:** chatbot response generation, user document summarisation/analysis, OCR, per-document user ACLs, distributed worker infrastructure.

## Schema and storage

- `public.knowledge_documents`: logical document and currently active version, document state, soft deletion.
- `public.knowledge_document_versions`: original Storage path, immutable version identifier, processing/failure/cleanup lifecycle, metadata.
- `public.knowledge_chunks`: extracted source text, chunk/page metadata, 1,536-dimensional pgvector embeddings.
- Private `knowledge-documents` Supabase Storage bucket with 20 MiB limit and PDF/DOCX/TXT allowlist.
- SQL migrations `001_phase1_foundation.sql`, `002_phase2_knowledge_management.sql`, `003_phase2_failed_ingestion_retry.sql`, `004_phase2_document_lifecycle.sql` were **reported applied successfully by the user**.
- Retrieval contract: `match_knowledge_chunks` returns only currently active ready chunks from non-deleted documents, for authenticated active users or server-side privileged callers.

## Delivered milestones and reported tests

| Milestone | Reported outcome |
|---|---|
| 1 Architecture review | Approved |
| 2 Database and Storage | Migration/setup verified by user |
| 3 Upload/list/validate | 57 passing automated tests |
| 4 Ingestion/embeddings/retry | 64 passing automated tests |
| 5 Replace/delete/cleanup | 8/8 verification checks and 69 automated tests passing |
| 6 Final security/operational verification | **Pending** |

## Remaining issues and architectural decisions

1. No automatic handling of abandoned `processing` jobs after Streamlit restarts; needs lease/timeouts and atomic recovery decision.
2. Failed replacement candidates are not currently supported by failed-initial-version retry workflow.
3. Initial processing request is not atomically claimed; concurrent processing may duplicate provider calls or race.
4. Candidate `ready` status and version activation happen in separate database requests; consider a single finalisation RPC and structured failure-injection test.
5. Storage/DB deletion spans services; continue testing incomplete cleanup/response handling.
6. Retained filename/checksum/version metadata after deletion requires retention approval.
7. Live Streamlit Cloud tests, adversarial authorisation, and SQL/Storage policy audit required to call production-ready.

## Recommended Phase 3 contract

Use the existing retrieval RPC/repository only for active, ready, non-deleted chunks. Preserve `document_id`, `version_id`, original filename, `page_number`, `chunk_index`, and source metadata for citations. Verify that retrieval filters and role checks are upheld under authenticated application-user context before building answer generation. Do not expose the service-role key or original private Storage paths to browser clients.

## Handoff state

This document is a **draft**. Update test evidence, deployments, risks and decision owners after Milestone 6 verification and explicit user approval.
