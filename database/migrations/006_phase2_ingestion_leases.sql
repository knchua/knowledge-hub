-- Recovery 2B. Run after 005. Application must switch ALL ingestion writes to fenced RPCs.
begin;
alter table public.knowledge_document_versions
  add column if not exists processing_token uuid,
  add column if not exists processing_lease_until timestamptz;
create index if not exists idx_knowledge_versions_lease
  on public.knowledge_document_versions(processing_lease_until)
  where status='processing';

-- Claim an unstarted, failed or expired lease. An expired worker is fenced by token rotation.
create or replace function public.kh_claim_ingestion(
  p_document_id uuid, p_version_id uuid, p_mode text, p_allow_stale boolean default false
) returns table(original_filename text, storage_path text, attempt_token uuid)
language plpgsql security definer set search_path='' as $$
declare d public.knowledge_documents%rowtype; v public.knowledge_document_versions%rowtype;
        t uuid := gen_random_uuid();
begin
  if coalesce(auth.role(),'') <> 'service_role' then raise exception 'Forbidden' using errcode='42501'; end if;
  if p_mode not in ('initial','replacement','retry_initial','retry_replacement','recover') then
    raise exception 'Invalid mode' using errcode='22023'; end if;
  select * into d from public.knowledge_documents where id=p_document_id for update;
  if not found or d.deleted_at is not null or d.status not in ('ready','processing','failed') then
    raise exception 'Unavailable document' using errcode='22023'; end if;
  select * into v from public.knowledge_document_versions
    where id=p_version_id and document_id=p_document_id for update;
  if not found or v.id=d.active_version_id or v.cleanup_status <> 'none' then
    raise exception 'Unavailable version' using errcode='22023'; end if;
  if exists (select 1 from public.knowledge_document_versions x where x.document_id=d.id
      and x.id<>v.id and x.status='processing' and x.processing_token is not null
      and x.processing_lease_until>clock_timestamp()) then
    raise exception 'Another ingestion is in progress' using errcode='55000'; end if;
  if p_mode='recover' then
    if not p_allow_stale or v.status<>'processing' or v.processing_token is null
       or v.processing_lease_until is null or v.processing_lease_until>=clock_timestamp()
    then raise exception 'Lease is not stale' using errcode='55000'; end if;
  elsif p_mode in ('retry_initial','retry_replacement') then
    if v.status<>'failed' then raise exception 'Not failed' using errcode='55000'; end if;
  else
    if v.status<>'processing' or v.processing_token is not null or v.processing_claimed_at is not null then
      raise exception 'Already claimed' using errcode='55000'; end if;
  end if;
  if p_mode in ('initial','retry_initial') and (v.version_number<>1 or d.active_version_id is not null) then
    raise exception 'Initial version required' using errcode='22023'; end if;
  if p_mode in ('replacement','retry_replacement') and
    (v.version_number<=1 or d.active_version_id is null or d.status<>'ready'
     or not exists (select 1 from public.knowledge_document_versions av where av.id=d.active_version_id and av.status='ready')) then
    raise exception 'Active version required' using errcode='22023'; end if;
  -- Discard partial writes transactionally before a new owner is granted.
  delete from public.knowledge_chunks where version_id=v.id;
  update public.knowledge_document_versions set status='processing',chunk_count=0,
    completed_at=null,error_summary=null,processing_token=t,
    processing_claimed_at=clock_timestamp(),
    processing_lease_until=clock_timestamp()+interval '30 minutes'
  where id=v.id;
  if d.active_version_id is null then update public.knowledge_documents set status='processing' where id=d.id; end if;
  return query select v.original_filename,v.storage_path,t;
end $$;

create or replace function public.kh_append_ingestion_chunks(
 p_document_id uuid,p_version_id uuid,p_token uuid,p_rows jsonb
) returns integer language plpgsql security definer set search_path='' as $$
declare v public.knowledge_document_versions%rowtype; n integer;
begin
 if coalesce(auth.role(),'')<>'service_role' then raise exception 'Forbidden' using errcode='42501'; end if;
 perform 1 from public.knowledge_documents where id=p_document_id and deleted_at is null
   and status in ('ready','processing') and active_version_id is distinct from p_version_id for update;
 if not found then raise exception 'Document unavailable' using errcode='55000'; end if;
 select * into v from public.knowledge_document_versions where id=p_version_id and document_id=p_document_id for update;
 if not found or v.status<>'processing' or v.processing_token is distinct from p_token
   or v.processing_lease_until<=clock_timestamp() then
   raise exception 'Processing ownership lost' using errcode='55000'; end if;
 if jsonb_typeof(p_rows)<>'array' or jsonb_array_length(p_rows) not between 1 and 50 then
   raise exception 'Invalid batch' using errcode='22023'; end if;
 insert into public.knowledge_chunks(document_id,version_id,chunk_index,content,page_number,source_metadata,embedding,embedding_model)
 select p_document_id,p_version_id,(r->>'chunk_index')::integer,r->>'content',
        (r->>'page_number')::integer,r->'source_metadata',
        (r->>'embedding')::extensions.vector,'text-embedding-3-small'
 from jsonb_array_elements(p_rows) r;
 get diagnostics n=row_count;
 update public.knowledge_document_versions set processing_lease_until=clock_timestamp()+interval '30 minutes' where id=v.id;
 return n;
end $$;

create or replace function public.kh_finish_ingestion(
 p_document_id uuid,p_version_id uuid,p_token uuid,p_expected_count integer
) returns void language plpgsql security definer set search_path='' as $$
declare d public.knowledge_documents%rowtype; v public.knowledge_document_versions%rowtype; n integer;
begin
 if coalesce(auth.role(),'')<>'service_role' then raise exception 'Forbidden' using errcode='42501'; end if;
 select * into d from public.knowledge_documents where id=p_document_id for update;
 select * into v from public.knowledge_document_versions where id=p_version_id and document_id=p_document_id for update;
 if not found or d.deleted_at is not null or d.status not in ('ready','processing')
 or d.active_version_id=p_version_id or v.status<>'processing'
 or v.processing_token is distinct from p_token or v.processing_lease_until<=clock_timestamp() then
   raise exception 'Processing ownership lost' using errcode='55000'; end if;
 select count(*) into n from public.knowledge_chunks where version_id=p_version_id;
 if p_expected_count<1 or n<>p_expected_count or exists
 (select 1 from generate_series(0,p_expected_count-1) i
  where not exists(select 1 from public.knowledge_chunks c where c.version_id=p_version_id and c.chunk_index=i))
 then raise exception 'Incomplete chunks' using errcode='22023'; end if;
 update public.knowledge_document_versions set status='ready',chunk_count=n,
  error_summary=null,completed_at=clock_timestamp(),processing_token=null,
  processing_lease_until=null where id=p_version_id;
 if d.active_version_id is not null then
  update public.knowledge_document_versions set status='superseded',cleanup_status='pending'
  where id=d.active_version_id and status='ready';
 end if;
 update public.knowledge_documents set active_version_id=p_version_id,status='ready',
  checksum_sha256=v.checksum_sha256,mime_type=v.mime_type,size_bytes=v.size_bytes where id=p_document_id;
end $$;

create or replace function public.kh_fail_ingestion(
 p_document_id uuid,p_version_id uuid,p_token uuid,p_summary text
) returns boolean language plpgsql security definer set search_path='' as $$
declare d public.knowledge_documents%rowtype; v public.knowledge_document_versions%rowtype;
begin
 if coalesce(auth.role(),'')<>'service_role' then raise exception 'Forbidden' using errcode='42501'; end if;
 select * into d from public.knowledge_documents where id=p_document_id for update;
 select * into v from public.knowledge_document_versions where id=p_version_id and document_id=p_document_id for update;
 if not found or v.processing_token is distinct from p_token or v.status<>'processing' or
   d.deleted_at is not null or d.active_version_id=p_version_id then return false; end if;
 delete from public.knowledge_chunks where version_id=p_version_id;
 update public.knowledge_document_versions set status='failed',chunk_count=0,
  error_summary=left(p_summary,300),processing_token=null,processing_lease_until=null,
  processing_claimed_at=null where id=p_version_id;
 if d.active_version_id is null then
   update public.knowledge_documents set status='failed' where id=p_document_id; end if;
 return true;
end $$;

revoke all on function public.kh_claim_ingestion(uuid,uuid,text,boolean) from public,anon,authenticated;
revoke all on function public.kh_append_ingestion_chunks(uuid,uuid,uuid,jsonb) from public,anon,authenticated;
revoke all on function public.kh_finish_ingestion(uuid,uuid,uuid,integer) from public,anon,authenticated;
revoke all on function public.kh_fail_ingestion(uuid,uuid,uuid,text) from public,anon,authenticated;
grant execute on function public.kh_claim_ingestion(uuid,uuid,text,boolean) to service_role;
grant execute on function public.kh_append_ingestion_chunks(uuid,uuid,uuid,jsonb) to service_role;
grant execute on function public.kh_finish_ingestion(uuid,uuid,uuid,integer) to service_role;
grant execute on function public.kh_fail_ingestion(uuid,uuid,uuid,text) to service_role;
commit;
