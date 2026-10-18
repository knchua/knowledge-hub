-- Knowledge Hub Phase 2, Milestone 6: READ-ONLY verification.
-- Run in Supabase SQL Editor. Does not mutate any data or policies.
-- SQL Editor uses elevated privileges; results do not prove browser-client RLS by themselves.

-- A. Required tables and RLS
select t.table_name, c.relrowsecurity as rls_enabled
from information_schema.tables t
join pg_class c on c.oid=format('%I.%I',t.table_schema,t.table_name)::regclass
where t.table_schema='public' and t.table_name in
 ('knowledge_documents','knowledge_document_versions','knowledge_chunks')
order by t.table_name;

-- B. Vector dimensions: expect vector(1536), regardless of display of schema-qualified type.
select column_name, udt_schema, udt_name, format_type(a.atttypid,a.atttypmod) as data_type
from pg_attribute a
join pg_class c on c.oid=a.attrelid
join pg_namespace n on n.oid=c.relnamespace
join information_schema.columns col on col.table_schema=n.nspname and col.table_name=c.relname and col.column_name=a.attname
where n.nspname='public' and c.relname='knowledge_chunks' and a.attname='embedding';

-- C. Function grants; inspect for anonymous or public execution.
select n.nspname as schema_name,p.proname as function_name,
       pg_get_function_identity_arguments(p.oid) as args,
       has_function_privilege('anon',p.oid,'EXECUTE') as anon_can_execute,
       has_function_privilege('authenticated',p.oid,'EXECUTE') as authenticated_can_execute,
       has_function_privilege('service_role',p.oid,'EXECUTE') as service_role_can_execute
from pg_proc p join pg_namespace n on n.oid=p.pronamespace
where n.nspname='public' and p.proname in (
 'match_knowledge_chunks','activate_knowledge_version',
 'claim_failed_knowledge_version','register_knowledge_replacement',
 'claim_knowledge_replacement','fail_knowledge_candidate',
 'claim_knowledge_cleanup','finalize_knowledge_deletion','mark_knowledge_document_deleting')
order by function_name;

-- D. Direct table grants: anon/authenticated should have no direct SELECT/INSERT/UPDATE/DELETE.
select table_name, grantee, privilege_type
from information_schema.role_table_grants
where table_schema='public' and table_name in
 ('knowledge_documents','knowledge_document_versions','knowledge_chunks')
 and grantee in ('anon','authenticated')
order by table_name,grantee,privilege_type;

-- E. Private Storage bucket, with 20MB (20971520 bytes) target.
select id,name,public,file_size_limit,allowed_mime_types
from storage.buckets where id='knowledge-documents';

-- F. Review ALL storage.objects policies as a separate security audit step.
select policyname,roles,cmd,qual,with_check
from pg_policies where schemaname='storage' and tablename='objects'
order by policyname;

-- G. Document inventory and lifecycle anomalies.
select d.id,d.display_name,d.status,d.deleted_at,d.active_version_id,
       v.version_number,v.status as version_status,v.cleanup_status,
       v.chunk_count,(select count(*) from public.knowledge_chunks c where c.version_id=v.id) as actual_chunks,
       v.processing_claimed_at
from public.knowledge_documents d
join public.knowledge_document_versions v on v.document_id=d.id
order by d.created_at desc,v.version_number desc;

-- H. Active version consistency violations; expect 0 rows.
select d.id,d.display_name,d.status,d.active_version_id
from public.knowledge_documents d
left join public.knowledge_document_versions v on v.id=d.active_version_id and v.document_id=d.id
where d.active_version_id is not null and
 (d.status <> 'ready' or d.deleted_at is not null or v.id is null or v.status <> 'ready');

-- I. Live visible chunks, by document. Returns counts only, not document text.
select d.id,d.display_name,count(c.id) as active_chunk_count
from public.knowledge_documents d
join public.knowledge_document_versions v on v.id=d.active_version_id and v.document_id=d.id
left join public.knowledge_chunks c on c.version_id=v.id
where d.status='ready' and d.deleted_at is null and v.status='ready'
group by d.id,d.display_name
order by d.display_name;

-- J. Potential stalled processing versions. REVIEW; no automatic reset.
select d.id as document_id, v.id as version_id, d.display_name,
       v.version_number,v.status,v.processing_claimed_at,v.created_at
from public.knowledge_document_versions v
join public.knowledge_documents d on d.id=v.document_id
where v.status='processing' and
 (v.processing_claimed_at is not null or v.created_at < now()-interval '1 hour')
order by v.created_at;

-- K. Cleanup requiring follow-up.
select d.display_name,d.status as document_status,v.id,v.version_number,v.status as version_status,
       v.cleanup_status,v.cleanup_error
from public.knowledge_document_versions v
join public.knowledge_documents d on d.id=v.document_id
where v.cleanup_status in ('pending','failed')
order by d.display_name,v.version_number;
