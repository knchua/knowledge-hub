# Knowledge Hub — Phase 4: Document Summarisation & Analysis

**Status:** Planned — ready for implementation
**Date:** 30 October 2026
**Prerequisites:** Phase 1 completed; Phase 2 and Phase 3 formally closed for AI Bootcamp scope, with documented residual risks.
**Architecture:** Streamlit + Python + Supabase Auth/PostgreSQL/Storage/pgvector + LangChain + OpenAI.
**Deployment:** Local development and Streamlit Community Cloud.

## 1. Objective

Enable authenticated, active users (including administrators) to upload their own PDF, DOCX or TXT documents and receive AI-generated summaries, structured findings and document-grounded answers. Temporary user documents **must not** be added to the administrator-managed shared knowledge repository or its pgvector index.

## 2. Existing foundation and integration constraints

- Reuse Phase 1 authoritative session validation, active-account enforcement and protected navigation.
- Reuse Phase 2 extraction/validation utilities where safe, without invoking its ingestion, versioning, Storage upload or embedding persistence paths.
- Reuse Phase 3 grounded-answer and citation design patterns where appropriate, without silently mixing shared knowledge chunks with temporary user documents.
- Inspect actual source and tests before editing; do not assume module names or signatures.
- Keep Phase 1–3 behaviour unchanged and regression-tested.
- No new database schema or Supabase Storage bucket is required for the initial session-only design.

## 3. Scope

### In scope

1. Protected Document Analysis page for authenticated active admins and users.
2. PDF, DOCX and TXT upload, with type, content and size validation. Start with the existing 20 MB application upload limit; also enforce extracted-text/token budgets separately.
3. Text extraction preserving source filename, page number for PDF when available, and segment/chunk positions.
4. Concise, detailed and structured summarisation options.
5. Structured extraction of key points, decisions, action items, dates and risks **only when supported by the document**; label missing items as not found rather than fabricate them.
6. Grounded question answering over the current uploaded document with verifiable source excerpts and available page references.
7. LangChain orchestration and configurable OpenAI chat model, with bounded context and cost.
8. Session-scoped upload, extracted text, analysis results and Q&A history, isolated by authenticated user/session.
9. Clear/replace document controls and logout/session-expiry cleanup.
10. Automated tests, manual security checks, Cloud verification and operational documentation.

### Out of scope

- Adding user documents to the shared knowledge repository, Supabase Storage or persistent pgvector index.
- Cross-session persistence, document sharing, multi-user collaboration or permanent analysis history.
- OCR for scanned PDFs, image analysis, spreadsheets, PowerPoint, complex table reconstruction.
- External web research, autonomous actions or comparing uploaded documents with the central knowledge base.
- Full production security certification, background worker infrastructure and bulk processing.

## 4. Functional workflow

1. Authenticate the user and verify their active status via authoritative backend checks.
2. Accept one document initially; validate extension, actual format where feasible, bytes and text extractability.
3. Parse into source-attributed segments; retain original filename and PDF page numbers where available.
4. Store temporary document data in session-scoped memory only; do not write temporary document bytes/text to logs, shared tables, Storage or vector index.
5. User selects concise/detailed/structured summary or asks a question.
6. For summaries, use bounded hierarchical/map-reduce summarisation when document text exceeds one safe context window; preserve coverage across sections and do not silently omit content.
7. For Q&A, select relevant document segments using an in-memory approach (e.g., local embeddings/retriever if justified) or a bounded full-context path for short documents. No persistent vector writes.
8. Generate grounded output using LangChain and OpenAI; clearly distinguish extracted facts from interpretation and uncertainty.
9. Validate source labels against current document segments and render real excerpts/page references; no fabricated citations.
10. Allow clear or replace; clear temporary document state, summaries, retrieval objects and Q&A history. Also clear on logout and user identity change.

## 5. Privacy, security and data lifecycle

- Only active authenticated users can access analysis functions; protect services as well as page navigation.
- Use a per-session owner identity and reject/reinitialise state if the authenticated identity changes.
- Streamlit session state is **not a security boundary or durable confidential storage**. Treat session-only handling as a bootcamp design, and document memory lifetime/restart limitations.
- Streamlit file upload may use process memory; ensure no application-controlled persistence and avoid accidental caching across users.
- Uploaded content is sent to OpenAI for processing. Disclose this to users and use synthetic/non-sensitive documents for bootcamp tests; do not promise that data never leaves the application.
- No application logging of raw document text, full prompts, file bytes or secrets. Log minimal operational metadata only where needed.
- Limit upload size, extracted text size, total chunks, requests, history length, context size and model output tokens; handle malicious or oversized inputs safely.
- Treat document content as untrusted data, not as instructions; test prompt-injection resistance.
- On clear, replacement, logout or session invalidation, remove references to user document content and derived state from the application session. Do not claim guaranteed immediate physical memory erasure or provider-side deletion.
- Do not accidentally reuse Phase 3 shared-document retrieval results or source labels in Phase 4.

## 6. Suggested UX

- Protected **Document Analysis** page with upload control and visible supported formats/limits.
- File summary panel: name, format, extracted page count when available, character/segment count and extraction warnings.
- Summary mode selector: Concise / Detailed / Structured; explicit Generate Summary action.
- Structured output headings: Overview, Key Points, Decisions, Action Items, Dates, Risks, Missing/Unclear Information, as applicable.
- Ask About This Document input with answers and source excerpts.
- Clear Document / Replace Document controls with visible confirmation of cleared application state.
- Loading states, cost/latency warnings for long files and safe user-facing errors.

## 7. Proposed module boundaries (adapt to actual repository)

- `pages/document_analysis.py`: protected Streamlit UI.
- `services/document_analysis_service.py`: workflow orchestration and validation of user/session ownership.
- `services/summarisation_service.py`: bounded hierarchical summarisation and structured output.
- `services/temporary_document_service.py`: in-memory parsing, segment preparation and lifecycle.
- `services/document_qa_service.py`: temporary-document question answering and evidence selection.
- Existing extraction, citation and model utilities: reuse where appropriate after inspection.
- `tests/test_phase4_*.py`: unit, integration-mock, privacy, security and regression tests.

Do not create redundant services if equivalent safe components already exist.

## 8. Initial configuration and design choices

| Concern | Starting approach |
|---|---|
| File formats | PDF, DOCX, TXT |
| File upload limit | 20 MB, aligned with existing configuration; independent extracted-text/token caps |
| Number of documents | One active temporary document per session initially |
| Storage | Session-scoped memory; no Supabase writes for temporary content |
| LLM | Configurable existing OpenAI chat model through LangChain |
| Summarisation | Short document: bounded context; long document: hierarchical synthesis |
| Document Q&A | Full bounded context for short files; in-memory segment retrieval for longer files |
| Source references | Actual current-file segment IDs, PDF pages when available, excerpts |
| History | Session-only, bounded, reset on document replacement/clear/logout |
| Cost control | Configurable token, segment, concurrency and output limits |

These are starting design choices; implementation must assess real source structure and runtime constraints before finalising thresholds.

## 9. Milestones

1. **Repository review and privacy design:** inspect Phase 1–3 source, auth/session cleanup, existing extraction, citation services and deployment constraints. Confirm session lifecycle and budgets.
2. **Protected upload and extraction:** implement validation, parsing, session isolation, metadata and clear/replace behaviour.
3. **Summarisation:** implement concise, detailed and structured summaries; bounded hierarchical processing; tests for coverage and missing evidence.
4. **Document Q&A and citations:** implement grounded answers against the current temporary document, source validation, insufficient-evidence handling and follow-up behaviour if included.
5. **Security, evaluation and deployment:** test cross-user isolation, logout cleanup, prompt injection, limits, API failures, regression and Streamlit Community Cloud; prepare final handoff.

Pause for user verification after each milestone. Avoid implementing Phase 5 production hardening except where required to keep Phase 4 safe.

## 10. Acceptance criteria

- [ ] Active admin and user can use Document Analysis; anonymous and inactive accounts cannot.
- [ ] PDF, DOCX and TXT parse successfully for supported readable content; invalid/empty/oversized files fail safely.
- [ ] Summaries are grounded in the uploaded document and offer concise, detailed and structured modes.
- [ ] Long-document summarisation respects limits and provides adequate section coverage or warns when coverage is incomplete.
- [ ] Key points, actions, dates and risks are extracted only when supported; missing items are explicitly marked.
- [ ] Document Q&A answers from current uploaded document only and abstains when evidence is insufficient.
- [ ] Source references map to actual segments, with correct page numbers when available.
- [ ] No temporary document is written to the shared knowledge tables, Storage bucket or pgvector index.
- [ ] Clear/replace/logout/user-change removes application session references and derived conversation state.
- [ ] No cross-user or cross-session document content appears in tested flows.
- [ ] API failures and prompt-injection attempts are handled safely in tested scenarios.
- [ ] Phase 1–3 regression suite continues passing; Phase 4 tests and Cloud smoke tests are recorded with actual results.
- [ ] Operational documentation states privacy, retention, cost and session-memory limitations accurately.

## 11. Evaluation scenarios

Test a short PDF with known page references, a longer multi-section document, a DOCX, a TXT, an empty/scanned-only file, unsupported format, unsupported factual question, misleading document instruction, document replacement, logout/login, different-user session, long-document limits and API failures. Record expected versus observed summaries, claims, excerpts, page references and abstentions. Do not claim correctness solely from valid citation labels.

## 12. Risks and deferred items

| Risk | Mitigation / follow-up |
|---|---|
| Sensitive data sent to OpenAI | User notice, synthetic demo content, documented external processing |
| Memory/session leakage | Explicit ownership checks, session cleanup, no cross-user caching of content |
| Streamlit memory/runtime pressure | Bound file and extracted-text size, hierarchical processing, fail safely |
| Summary omission or hallucination | Section coverage, evidence-focused prompts, evaluation set |
| Inaccurate citations | Backend source mapping and claim-level spot checks |
| Prompt injection | Treat documents as data, adversarial tests |
| Excess API cost/latency | Bounded calls, tokens, chunk counts and output |
| Phase 3 inactive-account direct RPC test | Carry to Phase 5; not resolved by Phase 4 |
| Phase 3 relevance calibration and claim support | Carry to Phase 5; not resolved by Phase 4 |
| Phase 2 concurrency, leases, cleanup/recovery | Carry to Phase 5; not resolved by Phase 4 |
| Broader security/performance/observability | Phase 5 / pre-production |

## 13. Phase 4 handoff

Return to the master planning chat with implemented modules, privacy and state-isolation evidence, sample summary and Q&A outcomes, citation checks, automated test count, Streamlit Cloud verification, cost/runtime observations, deviations and unresolved risks. **Do not formally close Phase 4 or begin Phase 5 until the user explicitly approves its handoff.**
