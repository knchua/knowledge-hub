-- Milestone 2 read-only verification: run in Supabase SQL Editor.
-- 1. Extension location; vector should be in schema extensions.
select e.extname, n.nspname as schema_name
from pg_extension e join pg_namespace n on n.oid=e.extnamespace
where e.extname='vector';

-- 2. Three tables exist and RLS is enabled.
select c.relname as table_name, c.relrowsecurity as rls_enabled
from pg_class c join pg_namespace n on n.oid=c.relnamespace
where n.nspname='public'
 and c.relname in ('knowledge_documents','knowledge_document_versions','knowledge_chunks')
order by c.relname;

-- 3. Authenticated roles must not have direct table access.
select t.table_name,
 has_table_privilege('anon','public.'||t.table_name,'SELECT') as anon_select,
 has_table_privilege('authenticated','public.'||t.table_name,'SELECT') as authenticated_select,
 has_table_privilege('authenticated','public.'||t.table_name,'INSERT') as authenticated_insert,
 has_table_privilege('authenticated','public.'||t.table_name,'UPDATE') as authenticated_update,
 has_table_privilege('authenticated','public.'||t.table_name,'DELETE') as authenticated_delete
from information_schema.tables t
where t.table_schema='public'
 and t.table_name in ('knowledge_documents','knowledge_document_versions','knowledge_chunks')
order by t.table_name;

-- 4. No permissive browser RLS policies on any of the three tables.
select schemaname, tablename, policyname, roles, cmd
from pg_policies
where schemaname='public'
 and tablename in ('knowledge_documents','knowledge_document_versions','knowledge_chunks');

-- 5. Confirm RPC functions exist and authenticated role can only execute retrieval.
select p.proname, pg_get_function_identity_arguments(p.oid) as arguments,
 has_function_privilege('authenticated',p.oid,'EXECUTE') as authenticated_execute,
 has_function_privilege('anon',p.oid,'EXECUTE') as anon_execute,
 has_function_privilege('service_role',p.oid,'EXECUTE') as service_role_execute
from pg_proc p join pg_namespace n on n.oid=p.pronamespace
where n.nspname='public' and p.proname in
 ('match_knowledge_chunks','activate_knowledge_version','mark_knowledge_document_deleting')
order by p.proname;

-- 6. Bucket properties (create via dashboard first).
select id, name, public, file_size_limit, allowed_mime_types
from storage.buckets where id='knowledge-documents';

-- 7. Review ALL Storage policies. Any generic policy granting users
-- access to every bucket must be examined before using this bucket.
select schemaname, tablename, policyname, roles, cmd, qual, with_check
from pg_policies
where schemaname='storage' and tablename='objects'
order by policyname;

-- 8. Confirm Phase 1 tables remain in place.
select table_name from information_schema.tables
where table_schema='public' and table_name in ('profiles','audit_logs')
order by table_name;
