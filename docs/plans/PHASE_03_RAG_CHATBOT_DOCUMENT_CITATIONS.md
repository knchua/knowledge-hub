# Knowledge Hub — Phase 3: RAG Chatbot & Document Citations

**Status:** Planned — ready for implementation
**Date:** 30 October 2026
**Prerequisites:** Phase 1 completed; Phase 2 accepted and closed for bootcamp scope with documented residual risks.
**Architecture:** Streamlit + Python + Supabase Auth/PostgreSQL/Storage/pgvector + LangChain + OpenAI.
**Deployment target:** Streamlit Community Cloud.

## 1. Objective

Deliver an authenticated, document-grounded conversational chatbot that retrieves only eligible shared knowledge chunks, generates evidence-based responses using LangChain and OpenAI, and presents verifiable document citations. Do not implement user document summarisation/analysis (Phase 4).

## 2. Baseline and integration constraints

- Reuse Phase 1 server-side identity, active-account validation, roles, secrets and tests.
- Reuse Phase 2 document/version/chunk schema and `match_knowledge_chunks` retrieval interface; do not re-ingest documents or create a parallel vector store.
- Inspect the actual code and deployed SQL before changes. Phase 2 handoff was based on reported checks rather than independent audit.
- Confirm retrieval grants, caller identity and active-account checks, and returned metadata. A privileged server client must not bypass effective user authorisation.
- Phase 2's untested two-connection concurrency, lease heartbeat, partial cleanup and optional recovery UI remain deferred risks, not implicitly resolved by Phase 3.

## 3. In scope

1. Streamlit chatbot interface for authenticated, active users and admins.
2. Natural-language questions and session-scoped conversation history; clear/new chat.
3. Question embeddings using existing OpenAI `text-embedding-3-small` (1,536 dimensions).
4. Semantic retrieval via `match_knowledge_chunks`, strictly filtered to active, ready, non-deleted document versions.
5. LangChain-based retrieval/context assembly, history-aware standalone query reformulation where appropriate, and grounded OpenAI answer generation.
6. Citations mapped in application code to retrieved chunk identifiers and document/version/page metadata; display filename, page where available, and supporting excerpt.
7. Explicit insufficient-evidence and empty-repository responses; never fabricate sources.
8. Error handling, context/token budget, retrieval thresholds, safe logging, and regression/security tests.

## 4. Out of scope

- User-uploaded document summarisation/analysis (Phase 4).
- Persistent cross-session chat history, document-level ACLs, OCR, external web search, agentic tool execution.
- Major redesign of Phase 1 authentication or Phase 2 ingestion and document lifecycle.
- Production-grade concurrency, worker infrastructure or full security certification.

## 5. Retrieval contract and security gate (must pass first)

Before answer generation, verify in the deployed schema and application:

- `match_knowledge_chunks` returns only chunks whose document is not deleted, version is `ready`, and version ID matches `knowledge_documents.active_version_id`.
- Ordinary inactive users and unauthenticated users cannot obtain knowledge chunks through the chatbot or direct exposed RPC paths; verify function grants and execution context. Do not assume Streamlit navigation or embeddings enforce permissions.
- Returned data include stable chunk ID, document ID, version ID, source display name, chunk order, page number where available, content, and similarity score (or a documented equivalent).
- The embedding dimension and distance operator match Phase 2's schema; retrieval limit and threshold are bounded.
- Failed/processing/superseded/deleted versions are excluded, including after replacement and deletion.

If the current RPC does not satisfy these conditions, propose the smallest explicit SQL migration and associated tests before building the chatbot.

## 6. Answer pipeline

1. Validate session and resolve current identity/active status from authoritative backend.
2. Accept question; enforce non-empty input and reasonable length limits.
3. For follow-ups, use limited chat history to reformulate a retrieval query without introducing new facts.
4. Generate query embedding with the Phase 2 embedding model.
5. Retrieve a bounded number of eligible chunks (initial `top_k=5`, configurable).
6. Apply calibrated relevance filtering; if no adequate evidence, return an insufficient-information response without an unsupported LLM answer.
7. Assemble context with stable source labels and size limits, avoiding duplicate or irrelevant chunks.
8. Instruct LLM to answer from supplied context only, distinguish uncertainty and treat retrieved text as data rather than instructions.
9. Validate any cited source labels against the retrieved set; display source references and snippets from backend metadata, not model-invented filenames/pages.
10. Render answer and citations; store only needed session-scoped messages and references.

## 7. Chat interface

- Use `st.chat_message` and `st.chat_input` within the existing protected Chatbot page.
- Show prior messages during the current session and provide Clear Conversation.
- Show document name and PDF page number when available, with a supporting excerpt; do not promise page numbers for DOCX/TXT.
- Handle no documents, no matching evidence, model/API failure and timeouts with user-friendly messages.
- Keep service-role keys, OpenAI keys, internal prompts and raw exception details out of rendered UI.

## 8. Configuration defaults to validate

| Parameter | Starting value | Note |
|---|---|---|
| Embedding model | `text-embedding-3-small` | Match Phase 2, 1,536 dimensions |
| Retrieval `top_k` | 5 | Tune with evaluation set |
| Similarity threshold | Configurable; no arbitrary fixed universal value | Calibrate for actual metric and documents |
| LLM | Configurable OpenAI chat model | Select available model/cost in implementation |
| History | Session-scoped | Bound history length and token budget |
| Context size | Bounded | Avoid oversized prompts and latency |

## 9. Suggested modules (adapt to existing repository)

- `pages/chatbot.py`: Streamlit chat presentation and protected entry point.
- `services/rag_service.py`: answer orchestration and grounded generation.
- `services/retrieval_service.py`: embeddings, retrieval and result validation.
- `services/citation_service.py`: source label mapping, citation validation and display data.
- `database/knowledge_repository.py`: reuse/extend existing retrieval adapter only as necessary.
- `tests/`: retrieval permissions, grounding, citations, chat history and regression coverage.

## 10. Milestones

1. **Repository and retrieval-security review:** inspect Phase 1/2 implementation, deployed RPC/grants and active-version filter; document discrepancies.
2. **Retrieval integration:** implement question embedding, eligible chunk retrieval, relevance filtering and retrieval-only diagnostics/tests.
3. **Grounded answer generation:** LangChain pipeline, prompts, context budget, abstention, error handling and citation validation.
4. **Streamlit chatbot:** protected UI, chat history, follow-up handling, clear conversation and source display.
5. **Evaluation and handoff:** curated test questions, security and regression tests, manual verification, deployment configuration and final report.

Pause for user verification after each milestone. Avoid broad refactors or implementation of Phase 4.

## 11. Acceptance criteria

- [ ] Active admin and user can ask questions; inactive and anonymous accounts are denied.
- [ ] Retrieval RPC grants and active-account restrictions verified, including direct-call paths.
- [ ] Retrieval excludes deleted, failed, processing and superseded versions.
- [ ] Question embeddings and vector similarity queries work with existing Phase 2 schema.
- [ ] Chatbot answers are supported by retrieved content and do not rely on uncited general knowledge.
- [ ] No-evidence and empty-repository questions produce clear abstention.
- [ ] Citations refer to actual retrieved chunks and display accurate filename and available page metadata.
- [ ] Malicious instructions in retrieved documents do not override system instructions in tested cases.
- [ ] Follow-up questions work within bounded session history; clearing chat removes displayed history.
- [ ] API errors and rate limits are handled without leaking secrets.
- [ ] Phase 1/2 regression tests continue to pass; new Phase 3 tests pass.
- [ ] Documentation includes configuration, evaluation results, known limitations and Streamlit Community Cloud considerations.

## 12. Evaluation scenarios

Prepare a small, known-answer set spanning single-document questions, multiple-document synthesis, ambiguous or conflicting evidence, missing answers, follow-up questions, deleted/replaced documents, source/page accuracy, irrelevant retrieval, prompt-injection attempts and unauthorised access. Record expected sources and observed outcomes. Treat answer correctness, citation correctness and abstention as separate measures.

## 13. Risks and mitigations

| Risk | Mitigation |
|---|---|
| Ineligible content returned | Verify RPC security and active-version filtering before answer generation |
| Hallucinated answer or citation | Context-only prompt, abstention, backend citation mapping and evaluation |
| Irrelevant retrieval | Calibrate threshold, tune chunk count, evaluate known questions |
| Prompt injection inside documents | Treat retrieved content as untrusted data; test adversarial examples |
| Oversized context or API cost | Bound history, chunk count, prompt size and retries |
| Streamlit reruns duplicate API calls | Use controlled submission and session state |
| Old Phase 2 lifecycle/concurrency risks | Keep in risk register; no claim that Phase 3 resolves them |

## 14. Phase 3 handoff

Return to master planning chat with: implemented modules, SQL changes (if any), verified retrieval security, example questions and citation outcomes, test count, remaining risks, deployment notes, and any architecture deviations. Do not start Phase 4 until Phase 3 is reviewed and explicitly closed.
