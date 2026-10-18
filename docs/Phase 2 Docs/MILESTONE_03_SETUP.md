# Knowledge Hub — Phase 2 Milestone 3

## Scope
Administrator upload, validation, duplicate detection, private original Storage, document and version metadata, and admin listing. **No extraction, embeddings, ready activation, deletion, version replacement, or retry UI in this milestone.** Those belong to Milestones 4 and 5.

## Apply

1. Ensure Milestone 2 migration and private `knowledge-documents` bucket are already installed and tested.
2. Copy `services/knowledge_service.py`, `pages/knowledge_management.py`, and `tests/test_knowledge_service.py` into the existing repository at matching paths. Do not replace unrelated Phase 1 files.
3. Ensure the Storage bucket allows PDF/DOCX/TXT and has a 20 MB size limit.
4. Use your existing local `.streamlit/secrets.toml` with `[supabase]` keys. **Do not commit secrets.**
5. From the application root, in the existing virtual environment:

```bash
python -m pytest -q
streamlit run app.py
```

6. Log in as an active administrator; open **Knowledge Management**; upload a small UTF-8 TXT sample.
7. Confirm that the page shows the document with `processing` status. In Supabase verify its `knowledge_documents` row, version 1 in `knowledge_document_versions`, private Storage object at `documents/<uuid>/versions/<uuid>.txt`, and an `audit_logs` event `knowledge_document_uploaded`.
8. Confirm there are **no knowledge_chunks** for this upload. This is expected; ingestion is Milestone 4.
9. Repeat upload with identical content: the service must reject the duplicate without creating another active document.
10. Test DOCX, readable PDF, unsupported extension, malformed DOCX/PDF, empty TXT and size limit.
11. Sign in as normal user and confirm there is no Knowledge Management navigation. Direct service tests must reject a non-admin actor and validate the actor's current Supabase account state.

## Important operational caveats

- An upload can partially fail across PostgreSQL, Supabase Storage and audit. Rows in `failed` status are deliberately preserved for administrator investigation; the automatic recovery workflow will be added in Milestone 5.
- A successful upload remains in `processing` and is **not retrievable** until Milestone 4 produces embeddings and activates the version. Do not mark versions ready manually.
- Supabase Storage and database aren't one atomic transaction. If upload fails after metadata insertion, check Storage and the version's status before retrying.
- The current checksum uniqueness index prevents two non-deleted documents with identical content. Milestone 5 replacement will need to update document checksum only during activation, already supported by the Milestone 2 RPC.
- UI MIME filters are convenience only. Actual bytes are validated on the server. PDF validation checks signatures, not exhaustive PDF integrity; extraction validation follows in Milestone 4.
- Do not upload confidential documents until organisational data-handling and external embedding-provider approvals are understood.

## Verification checkpoint

Share `python -m pytest -q` output and whether upload, duplicate rejection, list, Storage object, audit and non-admin access checks passed. Do not proceed to Milestone 4 until confirmation.
