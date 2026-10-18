# Knowledge Hub Phase 2 — Milestone 4

## Scope

This package adds on-demand processing of previously uploaded PDF/DOCX/TXT originals using PyMuPDF, python-docx, LangChain's RecursiveCharacterTextSplitter, OpenAI text-embedding-3-small and the existing pgvector database. The Process button starts indexing explicitly; uploading alone remains a staging operation. Automatic retries of failed document versions, replacement and deletion are deferred to Milestone 5.

## 1. Install

Back up or commit your existing changes first. Copy `services/`, `database/`, `pages/` and `tests/` into the existing project (merge folders, don't replace folders wholesale). Add the dependencies in `requirements-phase2.txt` to the existing `requirements.txt` without deleting its Phase 1 dependencies. Install:

```bash
python -m pip install -r requirements.txt
```

Keep OpenAI credentials only in your local untracked `.streamlit/secrets.toml` and the Streamlit Community Cloud secrets dashboard:

```toml
OPENAI_API_KEY = "your-own-key-here"
```

Do not commit a real API key or paste it into logs or GitHub.

## 2. Run regression tests

```bash
python -m pytest -q
```

The user-reported Milestone 3 baseline was 57 passing tests. This package adds three tests; the final number may vary with your local branch. These tests never call OpenAI.

## 3. Process an existing staged document

1. Run `streamlit run app.py` and sign in as a currently active administrator.
2. Open Knowledge Management; expand a staged document and click **Process document** once.
3. Confirm the UI reports its chunk count and `ready` status. No extra SQL migration is needed.
4. Check the private Storage original remains present.
5. In Supabase SQL Editor run:

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

Expected: successful document and version are `ready`, `chunk_count` equals `stored_chunks` and is greater than 0, and `is_active` is true. In `audit_logs`, look for `knowledge_document_ingested`.

## 4. Failure and authorisation checks

- Try a blank scanned PDF: it should fail with a safe message and should never become ready.
- Only administrator sessions should be able to trigger processing. Ordinary users cannot access the page or use its service-role operations.
- Failed versions are not retried in this milestone; controlled retry and cleanup are Milestone 5.
- If a file is slow or too large for Streamlit Community Cloud, use a smaller file (20 MB is an upload ceiling, not a guarantee of processing within runtime limits).
- PDF page references are 1-based. Word/TXT content does not have stable page numbers.

## 5. Important operational constraints

- The Milestone 2 activation RPC makes the version visible only after all chunks are stored and the version is ready.
- Indexing a document calls the paid OpenAI embeddings API. Keep test documents small.
- Document processing is synchronous. Streamlit reruns/restarts can interrupt work. If a process is interrupted, inspect its status; do not click repeatedly or edit database statuses manually. Recovery tooling is part of Milestone 5.
- The current package is intentionally limited to **initial** version ingestion; replacement, deletion and retries are future work.
- Do not begin Milestone 5 until tests and the live ingestion checks pass and you approve.
