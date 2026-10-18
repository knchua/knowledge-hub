-- Apply after 001, 002 and 003. All RPC writes restricted to server service_role.
begin;

-- Register a replacement only if a ready active document exists and there is
-- no unfinished candidate. Locking serializes concurrent admins.
create or replace function public.register_knowledge_replacement(
 p_document_id uuid, p_version_id uuid, p_name text,
 p_checksum text, p_mime text, p_size bigint, p_storage_path text,
 p_actor uuid
) returns integer language plpgsql security definer set search_path = '' as $$
declare n integer; current_checksum text;
begin
 if coalesce(auth.role(),'') <> 'service_role' then
   raise exception 'Service role required' using errcode='42501'; end if;
 perform 1 from public.knowledge_documents d
  join public.knowledge_document_versions v on v.id=d.active_version_id
  where d.id=p_document_id and d.status='ready' and d.deleted_at is null and v.status='ready'
  for update of d;
 if not found then raise exception 'Document is not replaceable' using errcode='22023'; end if;
 if exists (select 1 from public.knowledge_document_versions
  where document_id=p_document_id and status='processing') then
  raise exception 'Replacement already in progress' using errcode='22023'; end if;
 select checksum_sha256 into current_checksum from public.knowledge_documents where id=p_document_id;
 if current_checksum=p_checksum then raise exception 'Replacement is identical to active document' using errcode='22023'; end if;
 if p_checksum !~ '^[0-9a-f]{64}$' or p_name is null or length(btrim(p_name)) not between 1 and 255
  or p_size not between 1 and 20971520
  or p_mime not in ('application/pdf','application/vnd.openxmlformats-officedocument.wordprocessingml.document','text/plain')
  or p_storage_path !~ '^documents/[0-9a-f-]{36}/versions/[0-9a-f-]{36}\.(pdf|docx|txt)$'
  or split_part(p_storage_path,'/',2)<>p_document_id::text
  or split_part(split_part(p_storage_path,'/',4),'.',1)<>p_version_id::text
 then raise exception 'Invalid replacement metadata' using errcode='22023'; end if;
 select coalesce(max(version_number),0)+1 into n from public.knowledge_document_versions where document_id=p_document_id;
 insert into public.knowledge_document_versions(id,document_id,version_number,storage_path,original_filename,
  checksum_sha256,mime_type,size_bytes,status,created_by)
 values(p_version_id,p_document_id,n,p_storage_path,p_name,p_checksum,p_mime,p_size,'processing',p_actor);
 return n;
end $$;
revoke all on function public.register_knowledge_replacement(uuid,uuid,text,text,text,bigint,text,uuid) from public,anon,authenticated;
grant execute on function public.register_knowledge_replacement(uuid,uuid,text,text,text,bigint,text,uuid) to service_role;

-- A replacement can be processed only once; acquire a serialized claim.
-- Existing Milestone 4 initial ingestion continues to use its original path.
alter table public.knowledge_document_versions add column if not exists processing_claimed_at timestamptz;
create or replace function public.claim_knowledge_replacement(p_document_id uuid,p_version_id uuid)
returns table(original_filename text,storage_path text) language plpgsql security definer set search_path='' as $$
declare v public.knowledge_document_versions%rowtype;
begin
 if coalesce(auth.role(),'')<>'service_role' then raise exception 'Service role required' using errcode='42501'; end if;
 perform 1 from public.knowledge_documents d where d.id=p_document_id and d.status='ready'
  and d.deleted_at is null and d.active_version_id is not null for update;
 if not found then raise exception 'Document not active' using errcode='22023'; end if;
 select * into v from public.knowledge_document_versions x
  where x.id=p_version_id and x.document_id=p_document_id for update;
 if not found or v.status<>'processing' or v.processing_claimed_at is not null or v.version_number<=1
 then raise exception 'Candidate unavailable' using errcode='22023'; end if;
 update public.knowledge_document_versions set processing_claimed_at=now() where id=p_version_id;
 return query select v.original_filename,v.storage_path;
end $$;
revoke all on function public.claim_knowledge_replacement(uuid,uuid) from public,anon,authenticated;
grant execute on function public.claim_knowledge_replacement(uuid,uuid) to service_role;

-- Mark a replacement candidate failed after a failed Storage upload; active
-- document remains ready, and the candidate can be investigated/cleaned.
create or replace function public.fail_knowledge_candidate(p_document_id uuid,p_version_id uuid,p_summary text)
returns void language plpgsql security definer set search_path='' as $$
begin
 if coalesce(auth.role(),'')<>'service_role' then raise exception 'Service role required' using errcode='42501'; end if;
 perform 1 from public.knowledge_documents where id=p_document_id for update;
 if not found then raise exception 'Document missing' using errcode='22023'; end if;
 update public.knowledge_document_versions set status='failed',chunk_count=0,
  error_summary=left(p_summary,300),processing_claimed_at=null
 where id=p_version_id and document_id=p_document_id and status='processing'
 and id is distinct from (select active_version_id from public.knowledge_documents where id=p_document_id);
end $$;
revoke all on function public.fail_knowledge_candidate(uuid,uuid,text) from public,anon,authenticated;
grant execute on function public.fail_knowledge_candidate(uuid,uuid,text) to service_role;

-- Cleanup is serialized against activation and cannot purge active content.
create or replace function public.claim_knowledge_cleanup(p_document_id uuid,p_version_id uuid)
returns table(storage_path text) language plpgsql security definer set search_path='' as $$
declare d public.knowledge_documents%rowtype; v public.knowledge_document_versions%rowtype;
begin
 if coalesce(auth.role(),'')<>'service_role' then raise exception 'Service role required' using errcode='42501'; end if;
 select * into d from public.knowledge_documents where id=p_document_id for update;
 if not found then raise exception 'Document missing' using errcode='22023'; end if;
 select * into v from public.knowledge_document_versions where id=p_version_id and document_id=p_document_id for update;
 if not found or v.cleanup_status not in ('pending','failed') or d.active_version_id=p_version_id
 or (d.deleted_at is null and v.status<>'superseded') then
  raise exception 'Version not eligible for cleanup' using errcode='22023'; end if;
 update public.knowledge_document_versions set cleanup_status='pending',cleanup_error=null where id=p_version_id;
 return query select v.storage_path;
end $$;
revoke all on function public.claim_knowledge_cleanup(uuid,uuid) from public,anon,authenticated;
grant execute on function public.claim_knowledge_cleanup(uuid,uuid) to service_role;

-- Only mark deleted when every version cleanup is complete.
create or replace function public.finalize_knowledge_deletion(p_document_id uuid)
returns void language plpgsql security definer set search_path='' as $$
begin
 if coalesce(auth.role(),'')<>'service_role' then raise exception 'Service role required' using errcode='42501'; end if;
 perform 1 from public.knowledge_documents where id=p_document_id and status='deleting' and deleted_at is not null for update;
 if not found then raise exception 'Document not deleting' using errcode='22023'; end if;
 if exists (select 1 from public.knowledge_document_versions where document_id=p_document_id and cleanup_status<>'complete')
 then raise exception 'Cleanup incomplete' using errcode='22023'; end if;
 update public.knowledge_documents set status='deleted' where id=p_document_id;
end $$;
revoke all on function public.finalize_knowledge_deletion(uuid) from public,anon,authenticated;
grant execute on function public.finalize_knowledge_deletion(uuid) to service_role;

-- Preserve other RPCs from 002 and 003 unchanged.
commit;
