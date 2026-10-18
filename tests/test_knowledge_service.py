"""Milestone 3 deterministic validation/security unit tests."""
import io
import zipfile
from unittest.mock import patch
import pytest
from services.knowledge_service import KnowledgeError, validate_file, upload_document, list_documents


def sample_docx():
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as z:
        z.writestr("[Content_Types].xml", "<Types/>")
        z.writestr("word/document.xml", "<document/>")
    return buffer.getvalue()


def test_txt_valid():
    result = validate_file("memo.TXT", b"Knowledge content")
    assert result.mime_type == "text/plain"
    assert len(result.checksum) == 64


def test_txt_utf8_bom():
    assert validate_file("a.txt", b"\xef\xbb\xbfHello").extension == ".txt"


def test_docx_valid():
    assert validate_file("a.docx", sample_docx()).extension == ".docx"


@pytest.mark.parametrize("name,data", [
    ("sample.exe", b"hello"), ("x.txt", b""),
    ("x.txt", b"\x00"), ("x.txt", b"\xff"),
    ("x.pdf", b"fake"), ("x.docx", b"not zip"),
    ("bad.txt", b" " ),
])
def test_invalid_files(name, data):
    with pytest.raises(KnowledgeError):
        validate_file(name, data)


def test_oversize():
    with pytest.raises(KnowledgeError):
        validate_file("big.txt", b"x" * (20 * 1024 * 1024 + 1))


def test_upload_rejects_missing_actor_before_privileged_client():
    with patch("services.knowledge_service.get_supabase_admin_client") as factory:
        with pytest.raises(KnowledgeError):
            upload_document(None, "good.txt", b"hello")
        factory.assert_not_called()


def test_list_rejects_missing_actor():
    with patch("services.knowledge_service.get_supabase_admin_client") as factory:
        with pytest.raises(KnowledgeError):
            list_documents(None)
        factory.assert_not_called()
