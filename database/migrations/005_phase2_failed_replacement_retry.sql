-- 005: Atomic retry claim for a failed replacement candidate.
-- Install after 004. The active ready version remains untouched.
begin;
create or replace function public.claim_failed_knowledge_replacement(
 p_document_id uuid, p_version_id uuid
) returns table(original_filename text, storage_path text)
language plpgsql security definer set search_path = '' as $$
declare d public.knowledge_documents%rowtype; v public.knowledge_document_versions%rowtype;
begin
 if coalesce(auth.role(), '') <> 'service_role' then
   raise exception 'Service role required' using errcode='42501';
 end if;
 select * into d from public.knowledge_documents where id=p_document_id for update;
 if not found or d.deleted_at is not null or d.status <> 'ready' or d.active_version_id is null then
   raise exception 'Active document required' using errcode='22023';
 end if;
 perform 1 from public.knowledge_document_versions a where a.id=d.active_version_id
   and a.document_id=d.id and a.status='ready';
 if not found then raise exception 'Active version not ready' using errcode='22023'; end if;
 select * into v from public.knowledge_document_versions x
   where x.id=p_version_id and x.document_id=p_document_id for update;
 if not found or v.status <> 'failed' or v.version_number <= 1 or v.id=d.active_version_id
   or v.cleanup_status is distinct from 'none' then
   raise exception 'Replacement is not eligible for retry' using errcode='22023';
 end if;
 if exists (select 1 from public.knowledge_document_versions x
   where x.document_id=p_document_id and x.status='processing') then
   raise exception 'Another replacement is processing' using errcode='22023';
 end if;
 update public.knowledge_document_versions set status='processing', chunk_count=0,
   error_summary=null, completed_at=null, processing_claimed_at=now()
   where id=p_version_id;
 return query select v.original_filename,v.storage_path;
end $$;
revoke all on function public.claim_failed_knowledge_replacement(uuid,uuid) from public,anon,authenticated;
grant execute on function public.claim_failed_knowledge_replacement(uuid,uuid) to service_role;
commit;
