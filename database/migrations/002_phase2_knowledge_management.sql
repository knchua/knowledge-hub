-- Knowledge Hub Phase 2 — Migration 002
-- Run once through Supabase SQL Editor after migration 001.
-- The SQL Editor runs with database-owner privileges; do not run through the app.
begin;

create schema if not exists extensions;
create extension if not exists vector with schema extensions;

-- Document identity and deletion lifecycle.
create table public.knowledge_documents (
    id uuid primary key default gen_random_uuid(),
    display_name text not null check (length(btrim(display_name)) between 1 and 255),
    mime_type text not null check (mime_type in (
        'application/pdf',
        'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
        'text/plain'
    )),
    size_bytes bigint not null check (size_bytes between 1 and 20971520),
    checksum_sha256 text not null check (checksum_sha256 ~ '^[0-9a-f]{64}$'),
    active_version_id uuid,
    status text not null default 'processing'
        check (status in ('processing', 'ready', 'failed', 'deleting', 'deleted')),
    created_by uuid references auth.users(id) on delete set null,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    deleted_at timestamptz,
    constraint knowledge_documents_deleted_consistent
        check ((status in ('deleting', 'deleted')) = (deleted_at is not null))
);

-- Versions are separate from the currently active, retrieval-visible version.
create table public.knowledge_document_versions (
    id uuid primary key default gen_random_uuid(),
    document_id uuid not null references public.knowledge_documents(id),
    version_number integer not null check (version_number > 0),
    storage_path text not null unique
        check (storage_path ~ '^documents/[0-9a-f-]{36}/versions/[0-9a-f-]{36}\.(pdf|docx|txt)$'),
    original_filename text not null check (length(btrim(original_filename)) between 1 and 255),
    checksum_sha256 text not null check (checksum_sha256 ~ '^[0-9a-f]{64}$'),
    mime_type text not null check (mime_type in (
        'application/pdf',
        'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
        'text/plain'
    )),
    size_bytes bigint not null check (size_bytes between 1 and 20971520),
    status text not null default 'processing'
        check (status in ('processing', 'ready', 'failed', 'superseded')),
    chunk_count integer not null default 0 check (chunk_count >= 0),
    error_summary text,
    -- Cleanup is tracked separately from ingestion; a failed cleanup is retryable.
    cleanup_status text not null default 'none'
        check (cleanup_status in ('none', 'pending', 'complete', 'failed')),
    cleanup_error text,
    created_by uuid references auth.users(id) on delete set null,
    created_at timestamptz not null default now(),
    completed_at timestamptz,
    unique (document_id, version_number),
    unique (document_id, id)
);

alter table public.knowledge_documents
    add constraint knowledge_documents_active_version_fk
    foreign key (id, active_version_id)
    references public.knowledge_document_versions(document_id, id)
    deferrable initially immediate;

-- Every chunk is attached to exactly one version of its owning document.
create table public.knowledge_chunks (
    id uuid primary key default gen_random_uuid(),
    document_id uuid not null,
    version_id uuid not null,
    chunk_index integer not null check (chunk_index >= 0),
    content text not null check (length(btrim(content)) > 0),
    page_number integer check (page_number > 0),
    source_metadata jsonb not null default '{}'::jsonb
        check (jsonb_typeof(source_metadata) = 'object'),
    embedding extensions.vector(1536) not null,
    embedding_model text not null default 'text-embedding-3-small'
        check (embedding_model = 'text-embedding-3-small'),
    created_at timestamptz not null default now(),
    foreign key (document_id, version_id)
        references public.knowledge_document_versions(document_id, id)
        on delete cascade,
    unique (version_id, chunk_index)
);

create index idx_knowledge_documents_status
    on public.knowledge_documents(status);
create unique index idx_knowledge_documents_active_checksum
    on public.knowledge_documents(checksum_sha256)
    where deleted_at is null and status not in ('deleting', 'deleted');
create index idx_knowledge_versions_document_status
    on public.knowledge_document_versions(document_id, status);
create index idx_knowledge_versions_cleanup
    on public.knowledge_document_versions(cleanup_status)
    where cleanup_status in ('pending', 'failed');
create index idx_knowledge_chunks_version
    on public.knowledge_chunks(version_id);
-- Exact cosine search initially; no ANN index until performance justifies it.

create trigger knowledge_documents_set_updated_at
before update on public.knowledge_documents
for each row execute function private.set_updated_at();

-- Keep all tables inaccessible to browser clients. The only browser-accessible
-- retrieval surface is the narrowly scoped RPC declared below.
alter table public.knowledge_documents enable row level security;
alter table public.knowledge_document_versions enable row level security;
alter table public.knowledge_chunks enable row level security;

revoke all on public.knowledge_documents from public, anon, authenticated;
revoke all on public.knowledge_document_versions from public, anon, authenticated;
revoke all on public.knowledge_chunks from public, anon, authenticated;

grant all on public.knowledge_documents to service_role;
grant all on public.knowledge_document_versions to service_role;
grant all on public.knowledge_chunks to service_role;

-- The retrieval RPC is deliberately SECURITY DEFINER because its underlying
-- tables are inaccessible to normal clients. Verify the caller against current
-- profiles (not session metadata). Service-role calls are reserved for backend.
create or replace function public.match_knowledge_chunks(
    query_embedding extensions.vector(1536),
    match_count integer default 5,
    min_similarity double precision default 0.0
)
returns table (
    chunk_id uuid,
    document_id uuid,
    version_id uuid,
    document_name text,
    version_number integer,
    chunk_index integer,
    content text,
    page_number integer,
    source_metadata jsonb,
    similarity double precision
)
language plpgsql
stable
security definer
set search_path = ''
as $$
begin
    if query_embedding is null or match_count is null or match_count not between 1 and 20
       or min_similarity is null or min_similarity < -1.0 or min_similarity > 1.0 then
        raise exception 'Invalid retrieval parameters' using errcode = '22023';
    end if;

    if coalesce(auth.role(), '') <> 'service_role' and not exists (
        select 1 from public.profiles p
        where p.user_id = auth.uid() and p.is_active = true
    ) then
        raise exception 'Authentication required' using errcode = '42501';
    end if;

    return query
    select c.id, d.id, v.id, d.display_name, v.version_number,
           c.chunk_index, c.content, c.page_number, c.source_metadata,
           (1.0 - (c.embedding operator(extensions.<=>) query_embedding))::double precision
    from public.knowledge_documents d
    join public.knowledge_document_versions v
      on v.document_id = d.id and v.id = d.active_version_id
    join public.knowledge_chunks c
      on c.version_id = v.id and c.document_id = d.id
    where d.status = 'ready'
      and d.deleted_at is null
      and v.status = 'ready'
      and (1.0 - (c.embedding operator(extensions.<=>) query_embedding)) >= min_similarity
    order by c.embedding operator(extensions.<=>) query_embedding, c.id
    limit match_count;
end;
$$;

revoke all on function public.match_knowledge_chunks(extensions.vector, integer, double precision)
    from public, anon, authenticated;
grant execute on function public.match_knowledge_chunks(extensions.vector, integer, double precision)
    to authenticated, service_role;

-- Version activation is a single transaction (RPC invocation). The caller must
-- write all chunks and set the candidate status to ready before invoking it.
-- No execute permission is granted to ordinary authenticated callers.
create or replace function public.activate_knowledge_version(
    p_document_id uuid,
    p_version_id uuid
)
returns void
language plpgsql
security definer
set search_path = ''
as $$
declare
    v_expected integer;
    v_actual integer;
    v_old uuid;
begin
    if coalesce(auth.role(), '') <> 'service_role' then
        raise exception 'Service role required' using errcode = '42501';
    end if;

    select active_version_id into v_old
    from public.knowledge_documents
    where id = p_document_id and deleted_at is null
      and status not in ('deleting', 'deleted')
    for update;

    if not found then
        raise exception 'Document not available' using errcode = '22023';
    end if;

    select chunk_count into v_expected
    from public.knowledge_document_versions
    where document_id = p_document_id and id = p_version_id and status = 'ready'
    for update;

    if not found or v_expected <= 0 then
        raise exception 'Candidate version is not ready' using errcode = '22023';
    end if;

    select count(*) into v_actual from public.knowledge_chunks
    where document_id = p_document_id and version_id = p_version_id;

    if v_actual <> v_expected then
        raise exception 'Incomplete chunk set' using errcode = '22023';
    end if;

    if v_old is distinct from p_version_id then
        update public.knowledge_document_versions
        set status = 'superseded', cleanup_status = 'pending'
        where id = v_old;
    end if;

    update public.knowledge_documents d
    set active_version_id = p_version_id,
        status = 'ready',
        checksum_sha256 = v.checksum_sha256,
        mime_type = v.mime_type,
        size_bytes = v.size_bytes
    from public.knowledge_document_versions v
    where d.id = p_document_id and v.id = p_version_id;
end;
$$;

revoke all on function public.activate_knowledge_version(uuid, uuid)
    from public, anon, authenticated;
grant execute on function public.activate_knowledge_version(uuid, uuid)
    to service_role;

-- Disable retrieval first when deleting; cleanup happens via Storage API and
-- controlled service_role database operations after this transaction commits.
create or replace function public.mark_knowledge_document_deleting(p_document_id uuid)
returns void
language plpgsql
security definer
set search_path = ''
as $$
begin
    if coalesce(auth.role(), '') <> 'service_role' then
        raise exception 'Service role required' using errcode = '42501';
    end if;

    update public.knowledge_documents
    set status = 'deleting', deleted_at = now(), active_version_id = null
    where id = p_document_id and deleted_at is null;

    if not found then
        raise exception 'Document not found or already deleting' using errcode = '22023';
    end if;

    update public.knowledge_document_versions
    set cleanup_status = 'pending'
    where document_id = p_document_id and cleanup_status <> 'complete';
end;
$$;

revoke all on function public.mark_knowledge_document_deleting(uuid)
    from public, anon, authenticated;
grant execute on function public.mark_knowledge_document_deleting(uuid)
    to service_role;

commit;
