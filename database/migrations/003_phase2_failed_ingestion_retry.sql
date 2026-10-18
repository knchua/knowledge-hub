-- Phase 2: atomic, service-role-only claim of a failed initial ingestion.
-- Run in Supabase SQL Editor after migration 002.
begin;
create or replace function public.claim_failed_knowledge_version(
    p_document_id uuid, p_version_id uuid
)
returns table(original_filename text, storage_path text)
language plpgsql
security definer
set search_path = ''
as $$
declare
    v_doc public.knowledge_documents%rowtype;
    v_ver public.knowledge_document_versions%rowtype;
begin
    if coalesce(auth.role(), '') <> 'service_role' then
        raise exception 'Service role required' using errcode = '42501';
    end if;
    -- Lock document first to serialize claims for this document.
    select * into v_doc from public.knowledge_documents d
     where d.id = p_document_id for update;
    if not found or v_doc.deleted_at is not null or
       v_doc.status <> 'failed' or v_doc.active_version_id is not null then
        raise exception 'Document is not eligible for initial retry' using errcode = '22023';
    end if;
    select * into v_ver from public.knowledge_document_versions v
     where v.id = p_version_id and v.document_id = p_document_id for update;
    if not found or v_ver.status <> 'failed' or v_ver.version_number <> 1 then
        raise exception 'Version is not eligible for initial retry' using errcode = '22023';
    end if;
    -- Existing chunks (if any) are never visible without an active ready version.
    -- Python replaces them after this claim.
    update public.knowledge_document_versions
       set status = 'processing', chunk_count = 0, error_summary = null,
           completed_at = null
     where id = p_version_id;
    update public.knowledge_documents set status = 'processing'
     where id = p_document_id;
    return query select v_ver.original_filename, v_ver.storage_path;
end;
$$;
revoke all on function public.claim_failed_knowledge_version(uuid,uuid)
    from public, anon, authenticated;
grant execute on function public.claim_failed_knowledge_version(uuid,uuid)
    to service_role;
commit;
