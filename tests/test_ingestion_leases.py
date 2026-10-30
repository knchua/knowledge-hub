"""Source-level controls plus isolated orchestration tests; SQL needs live checks."""
from pathlib import Path


def test_all_entry_points_use_fenced_pipeline():
    import services.knowledge_ingestion_service as m
    assert all(callable(getattr(m, name)) for name in (
        "ingest_pending_document", "retry_failed_document", "process_replacement",
        "retry_failed_replacement", "recover_stale_ingestion"))


def test_no_legacy_unfenced_writer_imports():
    import services.knowledge_ingestion_service as m
    src = Path(m.__file__).read_text()
    assert "replace_chunks(" not in src
    assert "activate(client" not in src
    assert "kh_finish_ingestion" in src
    assert "kh_fail_ingestion" in src


def test_recovery_claim_needs_explicit_stale_mode():
    import services.knowledge_ingestion_service as m
    from unittest.mock import patch
    with patch.object(m, "_process", return_value=3) as run:
        assert m.recover_stale_ingestion(None, "doc", "ver") == 3
        assert run.call_args.kwargs == {"mode": "recover", "allow_stale": True}
