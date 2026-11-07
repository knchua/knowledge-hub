# Knowledge Hub — Phase 3 Final Implementation Handoff (FOR REVIEW)

**Prepared:** 30 October 2026
**Status:** Implementation/evaluation handoff prepared; **Phase 3 is not formally closed pending explicit user approval in the master planning chat.**
**Scope:** AI Bootcamp; Streamlit Community Cloud deployment.
**Evidence basis:** Project Phase 3 specification; earlier Phase 2 handoff; inspected application/authentication source and deployed SQL function text; user-provided Supabase outputs, local terminal logs, pytest results, and manual Streamlit Cloud verification. Results reported by the user are identified as such, and do not constitute an independent production audit.

## 1. Executive summary

Phase 3 delivers an authenticated, document-grounded conversational RAG chatbot with retrieved-document citations, session-scoped multi-turn history, history-aware follow-up reformulation, insufficient-evidence abstention, and safe error handling. It reuses Phase 1 Supabase authentication/role enforcement and Phase 2 knowledge ingestion, pgvector and `match_knowledge_chunks` retrieval. No Phase 3 database migration was required. Phase 4 document analysis/summarisation was not implemented.

**Final user-reported verification:** 106 automated tests passed locally; six of six final functional/security evaluation scenarios passed; seven of seven Streamlit Community Cloud verification scenarios passed. Commit `78faf07` (`Complete Phase 3 RAG chatbot and document citations`) on local `main` and `origin/main` was shown in terminal output. Phase 3 closure still requires explicit approval.

## 2. Milestone disposition

| Milestone | Implementation/outcome | Disposition |
|---|---|---|
| 1 — Repository and retrieval security | Existing SQL, grants, RLS, active-account checks and citation contract reviewed; active-user/anonymous RPC tests performed | Conditionally closed; **live inactive-account direct RPC test pending** |
| 2 — Retrieval integration | Authenticated user-scoped embedding and pgvector retrieval, bounded results, metadata validation, diagnostics | Conditionally closed; **similarity threshold calibration pending** |
| 3 — Grounded answer generation | LangChain/OpenAI generation, context-only prompting, citation label validation and abstention; live answer and injection checks | Conditionally closed |
| 4 — Streamlit chatbot | Chat interface, source excerpts, bounded session history, follow-ups, Clear Conversation, session isolation; UI fixes | Conditionally closed; final regression **106 tests passed (user-reported)** |
| 5 — Evaluation and handoff | Six final manual checks and seven deployed Cloud checks passed (user-reported); deployment dependencies/Git reviewed | Handoff prepared; explicit Phase 3 closure pending |

## 3. Architecture and implemented modules

- **Protected UI:** `pages/chatbot.py`, using existing `app.py` protected navigation and authoritative user/session validation. Presents questions, answers, validated source references, excerpts and page numbers when available.
- **Retrieval:** `services/retrieval_service.py` uses existing embedding service (`text-embedding-3-small`, 1,536 dimensions), fresh authenticated Supabase user clients, and `public.match_knowledge_chunks`. Initial `top_k` 5; RPC allows up to 20. Similarity floor remains configurable, **not fully calibrated**.
- **Answer generation:** `services/rag_service.py` uses LangChain/OpenAI with bounded retrieved context, evidence-grounded answers, abstention and safe exception handling. The implementation used a configurable chat model; `gpt-4o-mini` was the initial model in development.
- **Citation validation:** `services/citation_service.py` maps cited source labels to retrieved chunk metadata, rather than accepting LLM-invented filenames, pages or source IDs. Citation-label validity does not independently establish that every claim is supported.
- **Conversation:** `services/conversation_service.py` reformulates follow-up retrieval questions from bounded prior turns; Streamlit session state stores only in-session conversation. `services/session_service.py` was updated to clear Phase 3 chat state on logout; `pages/chatbot.py` was updated to refresh Clear Conversation after the first answer.
- **Tests:** `tests/test_phase3_retrieval_service.py`, `test_phase3_grounded_answers.py`, `test_phase3_conversation.py`, `test_phase3_chat_session_cleanup.py`, plus the preserved Phase 1/2 suite. Diagnostic scripts existed locally under `scripts/` but were **not** included in the reported 18-file Git commit.

## 4. Database, authorisation, retrieval and citation verification

The deployed `public.match_knowledge_chunks(extensions.vector, integer, double precision)` definition was provided during Milestone 1 and inspected. It is `STABLE SECURITY DEFINER`, uses an empty SQL `search_path`, validates inputs (`match_count` 1–20; threshold -1 to 1), requires an active `public.profiles` record for non-service-role calls, and returns only `knowledge_documents` with `status='ready'`, `deleted_at IS NULL`, and matching ready `active_version_id`/version. It ranks by pgvector cosine distance and returns chunk/document/version identifiers, document name, version number, chunk order, content, page number, JSON metadata and similarity.

User-provided Supabase checks showed: anonymous and PUBLIC execution permissions absent; authenticated and service-role execution granted; RLS enabled on the three knowledge tables; direct anonymous/authenticated SELECT not granted; no policies on those knowledge tables, consistent with the restricted RPC-only design. A live unauthenticated RPC request was rejected. A live authenticated active-user call succeeded and returned five chunks with citation metadata. Four eligible documents with five chunks were shown in the repository test.

**Security qualification:** The service role bypasses the function's active-profile check by design, so ordinary chatbot retrieval uses the authenticated user client. The **inactive-account direct RPC denial was not tested live** and remains a recorded exception. Version-exclusion conditions were inspected in SQL, with live active results consistent with the contract; exhaustive live negative tests for each ineligible lifecycle state were not demonstrated in Phase 3.

## 5. Evaluation evidence

### Retrieval quality diagnostic

| Question type | Highest cosine similarity | Observation |
|---|---:|---|
| Answerable: “What is Knowledge Hub about?” | 0.7052 | Relevant primary test document returned |
| Paraphrase: “What is the purpose of the Knowledge Hub application?” | 0.7250 | Same primary source retrieved |
| Unsupported: “What was Knowledge Hub's annual revenue in 2025?” | 0.5101 | Some semantically related chunks still retrieved despite unsupported question |

An illustrative 0.60 threshold would have retained one chunk in each answerable example and none for the unsupported example, but **this was not accepted as a general calibrated threshold**. Only a limited, test-document corpus was evaluated.

### Live grounded answer evaluation

- Answerable: produced a grounded answer citing actual retrieved sources (`S1`–`S4`); reviewed excerpts supported the core explanation.
- Paraphrase: produced an answer citing `S1`, matching the primary `test_knowledge.txt` source.
- Unsupported revenue question: abstained, with zero citations and no invented figure.
- Synthetic prompt injection: **3/3** mechanical checks passed (direct source instruction, forged system role, fabricated citation). The outputs cited only valid `S1` and expressed benign document-grounded content. These tests do **not** prove immunity to every injection strategy.
- Final Milestone 5 end-to-end evaluation: **6/6 user-reported passes**—single-document answer, follow-up, abstention, citation accuracy, conversation isolation, unauthenticated access.

## 6. Automated testing record

- Milestone 2 retrieval integration: **90 tests passed** (user-reported).
- Milestone 3 after grounded-answer integration: **98 tests passed** (user-reported).
- Milestone 4 and final local regression: **106 tests passed** (user-reported, repeated after final changes).
- Local unit tests and functional flows were run in the user's environment. There was no independent execution of the fully updated repository in this handoff environment. Tests must not be represented as an independently audited production qualification.

## 7. Deployment and source control

The user's environment was Python 3.12.10. Updated `requirements.txt` included:

```text
streamlit==1.65.0
supabase==2.32.0
pytest==9.1.1
openai==3.41.0
langchain-core==1.7.3
langchain-openai==1.7.3
langchain-text-splitters==1.0.0
PyMuPDF==1.26.5
python-docx==1.2.0
```

`pip check` returned “No broken requirements found.” `.streamlit/config.toml` specified `[server] maxUploadSize = 20`. Git reported `.streamlit/secrets.toml` and `.env` ignored and not tracked, with the placeholder `secrets.toml.example` tracked. These are limited file-level checks; they do not constitute a comprehensive secrets scan.

Reported commit `78faf07` on `main` matched `origin/main`. The staged commit covered Phase 3 services/UI/tests/requirements and pre-existing Phase 2 migration 006 and compatibility updates. **Migration 006 belongs to Phase 2, not a new Phase 3 migration**; committing it does not mean it should be re-executed. SQL verification scripts, the Phase 2 review handoff and `scripts/` remained untracked; they were not part of the 18-file committed set.

**Streamlit Community Cloud verification:** all **7/7 user-reported checks passed**—startup, active-user login/chatbot access, answer plus citations, follow-up context, immediate Clear Conversation availability, no history restoration after logout/login, and abstention for an unanswerable question. This supports bootcamp deployment readiness for the tested flows. It is not a fresh-install reproducibility or load/security audit.

## 8. Outstanding risk register (carry forward without closing)

| Risk / gap | Status and recommended follow-up |
|---|---|
| Inactive-account direct RPC call | **Pending live security verification** with a disposable deactivated user, independent of UI denial |
| Relevance threshold / retrieval precision | **Pending calibration** with a larger representative known-answer set, including negatives and ambiguous/conflicting evidence |
| Live failed/processing/superseded/deleted version negative cases | SQL exclusion confirmed by inspection; expand controlled direct-RPC regression testing before production |
| Phase 2 real two-connection concurrency | **Accepted deferral**; test competing workers in isolated Supabase environment |
| Competing replacement candidates / simultaneous activation | **Accepted deferral**; multi-connection stress and failure-injection tests |
| Embedding call exceeding 30-minute ingestion lease | **Accepted deferral**; implement/validate heartbeat or scheduling design as needed |
| Old processing detection and recovery UI | **Accepted deferral**; optional live UI and standard-user denial were not fully demonstrated |
| Interrupted ingestion operational recovery | **Accepted deferral**; use controlled admin process rather than manual status edits; improve recovery UX later |
| Partial cross-service cleanup | **Accepted deferral**; reconciliation/retry and network-failure injection before production |
| Transient chatbot failure message | Latest manual run succeeded; **root cause not confirmed**, monitor recurrence |
| Broader security, performance, cost and observability | Outside bootcamp acceptance; necessary for production hardening |
| Source support despite valid labels | Citation matching is not factual entailment validation; evaluate at claim level over larger corpus |

## 9. Changes and deviations

- Phase 3 uses existing Supabase pgvector and Phase 2 active-version retrieval contract, without a parallel vector store.
- No new Phase 3 SQL migration was necessary. A previously deferred Phase 2 ingestion-lease migration was committed for source tracking.
- Chat history is session-scoped, not persistent across logins; follow-up reformulation is bounded.
- A Streamlit Clear Conversation refresh issue was resolved via rerun after saving the completed turn, and session cleanup was extended at logout.
- Phase 4 document summarisation/analysis remains explicitly out of scope.

## 10. Master planning chat review request

**Proposed decision:** Approve **Phase 3 closure for the AI Bootcamp scope only**, based on the reported functional, security, regression and cloud-deployment evidence, while explicitly accepting the unresolved items in §8. Do not mark the unexecuted inactive-user direct RPC test, broad relevance calibration, or deferred Phase 2 concurrency/cleanup verification as passed.

**Approval required:** User/master-planning explicit decision. Until given, this document is a **FOR REVIEW** handoff and Phase 3 remains open. Do not begin Phase 4 without that decision.
