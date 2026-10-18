"""Deterministic extraction tests, no OpenAI network calls."""
import pytest
from services.ingestion_service import extract_chunks, CHUNK_SIZE
from services.knowledge_service import KnowledgeError
from services.knowledge_ingestion_service import ingest_pending_document
from unittest.mock import patch


def test_txt_extraction_and_metadata():
    chunks = extract_chunks("manual.txt", b"Knowledge Hub documentation " * 90)
    assert len(chunks) > 1
    assert all(len(c.content) <= CHUNK_SIZE for c in chunks)
    assert [c.index for c in chunks] == list(range(len(chunks)))
    assert all(c.source_metadata["source_filename"] == "manual.txt" for c in chunks)
    assert all(c.page_number is None for c in chunks)


def test_scanned_pdf_not_falsely_ready():
    import fitz
    document = fitz.open()
    document.new_page()
    payload = document.tobytes()
    document.close()
    with pytest.raises(KnowledgeError, match="No readable text"):
        extract_chunks("scan.pdf", payload)


def test_unauthorised_ingestion_never_obtains_admin_client():
    with patch("services.knowledge_ingestion_service.get_supabase_admin_client") as admin_client:
        with pytest.raises(KnowledgeError):
            ingest_pending_document(None, "00000000-0000-0000-0000-000000000000", "00000000-0000-0000-0000-000000000000")
        admin_client.assert_not_called()
