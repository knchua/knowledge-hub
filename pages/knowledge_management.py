"""Administrator-only shared knowledge management (Phase 2 Milestone 3)."""
import streamlit as st
from services.authorization_service import ApplicationAccessError
from services.session_service import get_stored_tokens
from services.authorization_service import resolve_application_user, require_admin
from services.knowledge_service import KnowledgeError, list_documents, list_versions, upload_document
from services.knowledge_ingestion_service import ingest_pending_document, retry_failed_document

st.title("📚 Knowledge Management")
access, refresh = get_stored_tokens()
try:
    actor = resolve_application_user(access or "", refresh or "")
    require_admin(actor)
except ApplicationAccessError:
    st.error("Administrator access required.")
    st.stop()

st.caption("Phase 2 Milestone 4 — upload and explicitly process knowledge files into searchable vectors.")
st.info("After upload, select Process below. Processing uses OpenAI embeddings and may incur API charges.")
with st.form("knowledge_upload", clear_on_submit=True):
    uploaded = st.file_uploader("PDF, Word (.docx), or UTF-8 TXT", type=["pdf", "docx", "txt"])
    submit = st.form_submit_button("Upload knowledge document", type="primary")
if submit:
    if uploaded is None:
        st.warning("Choose a document first.")
    else:
        try:
            result = upload_document(actor, uploaded.name, uploaded.getvalue())
            st.success(f"Stored {result['display_name']}. Select Process to start ingestion.")
        except KnowledgeError as exc:
            st.error(str(exc))

st.subheader("Knowledge documents")
if st.button("Refresh list"):
    st.rerun()
try:
    docs = list_documents(actor)
    if not docs:
        st.caption("No knowledge documents have been uploaded.")
    for doc in docs:
        with st.expander(f"{doc['display_name']} — {doc['status']}"):
            st.write({k: doc.get(k) for k in ("id", "mime_type", "size_bytes", "status", "created_at", "updated_at")})
            for ver in list_versions(actor, doc["id"]):
                st.write(f"Version {ver['version_number']}: {ver['status']} — "
                         f"{ver['original_filename']} ({ver['size_bytes']} bytes)")
                if ver["status"] == "processing" and doc["status"] == "processing":
                    if st.button("Process document", key=f"process_{ver['id']}"):
                        try:
                            with st.spinner("Extracting text, embedding and indexing…"):
                                count = ingest_pending_document(actor, doc["id"], ver["id"])
                            st.success(f"Indexed {count} chunks. Document is ready for retrieval.")
                            st.rerun()
                        except KnowledgeError as exc:
                            st.error(str(exc))
                if ver["status"] == "failed" and doc["status"] == "failed" and not doc.get("active_version_id") and ver["version_number"] == 1:
                    if st.button("Retry processing", key=f"retry_{ver['id']}"):
                        try:
                            with st.spinner("Retrying extraction, embedding and indexing…"):
                                count = retry_failed_document(actor, doc["id"], ver["id"])
                            st.success(f"Indexed {count} chunks. Document is ready for retrieval.")
                            st.rerun()
                        except KnowledgeError as exc:
                            st.error(str(exc))
                if ver.get("error_summary"):
                    st.warning(ver["error_summary"])
except KnowledgeError as exc:
    st.error(str(exc))

# Milestone 5: lifecycle controls. Every action re-checks admin on the server.
from services.knowledge_lifecycle_service import (
    stage_replacement, delete_document, cleanup_version,
    list_pending_cleanup, finish_deletion,
)
from services.knowledge_ingestion_service import process_replacement

st.subheader("Document lifecycle management")
st.caption("Replacement keeps the active version online until a new version is successfully indexed.")
try:
    for d in list_documents(actor):
        with st.expander(f"Manage: {d['display_name']}"):
            versions = list_versions(actor, d['id'])
            if d['status'] == 'ready':
                with st.form(f"replace_{d['id']}"):
                    replacement = st.file_uploader("Replacement PDF, DOCX or TXT", type=['pdf','docx','txt'],key=f"file_{d['id']}")
                    submitted = st.form_submit_button("Stage replacement")
                if submitted:
                    if replacement is None:
                        st.warning("Choose a replacement file.")
                    else:
                        try:
                            result = stage_replacement(actor, d['id'],replacement.name,replacement.getvalue())
                            st.success(f"Staged version {result['version_number']}. Process it below.")
                            st.rerun()
                        except KnowledgeError as exc:
                            st.error(str(exc))
                for v in versions:
                    if v['version_number'] > 1 and v['status'] == 'processing':
                        if st.button(f"Process replacement v{v['version_number']}",key=f"replace_process_{v['id']}"):
                            try:
                                with st.spinner("Processing replacement…"):
                                    process_replacement(actor,d['id'],v['id'])
                                st.success("Replacement activated. Previous version is now superseded.")
                                st.rerun()
                            except KnowledgeError as exc:
                                st.error(str(exc))
                    if v['status'] == 'superseded' and v.get('cleanup_status') in ('pending','failed'):
                        if st.button(f"Clean superseded v{v['version_number']}",key=f"clean_{v['id']}"):
                            try:
                                cleanup_version(actor,d['id'],v['id'])
                                st.success("Superseded content cleaned.")
                                st.rerun()
                            except KnowledgeError as exc:
                                st.error(str(exc))
                with st.form(f"delete_{d['id']}"):
                    confirmation = st.text_input('Type DELETE to permanently remove this document',key=f"confirm_{d['id']}")
                    request_delete = st.form_submit_button("Delete document",disabled=confirmation!='DELETE')
                if request_delete:
                    try:
                        delete_document(actor,d['id'],confirmation)
                        st.success("Document deleted and cleanup completed.")
                        st.rerun()
                    except KnowledgeError as exc:
                        st.error(str(exc))
            else:
                st.caption("Lifecycle actions require a ready active document.")
    st.subheader("Interrupted deletion cleanup")
    for d in list_pending_cleanup(actor):
        st.write(f"{d['display_name']} — {d['status']}")
        if st.button("Resume deletion cleanup", key=f"resume_{d['id']}"):
            try:
                finish_deletion(actor,d['id'])
                st.success("Deletion completed.")
                st.rerun()
            except KnowledgeError as exc:
                st.error(str(exc))
except KnowledgeError as exc:
    st.error(str(exc))
