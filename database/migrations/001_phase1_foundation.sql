-- ============================================================
-- Knowledge Hub
-- Phase 1 - Application Foundation
-- Migration 001
--
-- Creates:
--   - public.profiles
--   - public.audit_logs
--   - private trigger/helper functions
--   - Row Level Security policies
--   - least-privilege API grants
-- ============================================================


-- ============================================================
-- 1. Private schema
-- ============================================================
--
-- Security-definer functions are kept outside the exposed
-- public schema.
--

create schema if not exists private;

revoke all on schema private from public;
revoke all on schema private from anon;
revoke all on schema private from authenticated;


-- ============================================================
-- 2. User profiles
-- ============================================================

create table if not exists public.profiles (
    user_id uuid primary key
        references auth.users(id)
        on delete cascade,

    display_name text,

    role text not null
        default 'user'
        check (role in ('admin', 'user')),

    is_active boolean not null
        default true,

    created_at timestamptz not null
        default now(),

    updated_at timestamptz not null
        default now()
);


-- ============================================================
-- 3. Administrative audit log
-- ============================================================

create table if not exists public.audit_logs (
    id uuid primary key
        default gen_random_uuid(),

    actor_user_id uuid
        references auth.users(id)
        on delete set null,

    action text not null,

    target_user_id uuid
        references auth.users(id)
        on delete set null,

    created_at timestamptz not null
        default now(),

    details jsonb not null
        default '{}'::jsonb
);


-- ============================================================
-- 4. Useful indexes
-- ============================================================

create index if not exists idx_profiles_role
    on public.profiles(role);

create index if not exists idx_profiles_is_active
    on public.profiles(is_active);

create index if not exists idx_audit_logs_actor_user_id
    on public.audit_logs(actor_user_id);

create index if not exists idx_audit_logs_target_user_id
    on public.audit_logs(target_user_id);

create index if not exists idx_audit_logs_created_at
    on public.audit_logs(created_at);


-- ============================================================
-- 5. updated_at trigger function
-- ============================================================

create or replace function private.set_updated_at()
returns trigger
language plpgsql
security definer
set search_path = ''
as $$
begin
    new.updated_at = now();
    return new;
end;
$$;


drop trigger if exists profiles_set_updated_at
on public.profiles;

create trigger profiles_set_updated_at
before update on public.profiles
for each row
execute function private.set_updated_at();


-- ============================================================
-- 6. Automatically create profile for new Auth users
-- ============================================================
--
-- Every new Supabase Auth identity receives a normal 'user'
-- profile automatically.
--
-- Crucially, role is NOT copied from user-supplied metadata.
--

create or replace function private.handle_new_auth_user()
returns trigger
language plpgsql
security definer
set search_path = ''
as $$
begin
    insert into public.profiles (
        user_id,
        display_name,
        role,
        is_active
    )
    values (
        new.id,
        null,
        'user',
        true
    )
    on conflict (user_id) do nothing;

    return new;
end;
$$;


drop trigger if exists on_auth_user_created
on auth.users;

create trigger on_auth_user_created
after insert on auth.users
for each row
execute function private.handle_new_auth_user();


-- ============================================================
-- 7. Row Level Security
-- ============================================================

alter table public.profiles
enable row level security;

alter table public.audit_logs
enable row level security;


-- ============================================================
-- 8. Remove broad API permissions first
-- ============================================================

revoke all on table public.profiles
from anon, authenticated;

revoke all on table public.audit_logs
from anon, authenticated;


-- ============================================================
-- 9. Explicit authenticated-user grants
-- ============================================================
--
-- Authenticated users may:
--   - SELECT from profiles (RLS limits this to their row)
--   - UPDATE only display_name
--
-- They cannot directly:
--   - INSERT profiles
--   - DELETE profiles
--   - UPDATE role
--   - UPDATE is_active
--

grant select
on table public.profiles
to authenticated;

grant update (display_name)
on table public.profiles
to authenticated;


-- ============================================================
-- 10. Profiles RLS policies
-- ============================================================

drop policy if exists "users_select_own_profile"
on public.profiles;

create policy "users_select_own_profile"
on public.profiles
for select
to authenticated
using (
    (select auth.uid()) is not null
    and
    (select auth.uid()) = user_id
);


drop policy if exists "users_update_own_profile"
on public.profiles;

create policy "users_update_own_profile"
on public.profiles
for update
to authenticated
using (
    (select auth.uid()) is not null
    and
    (select auth.uid()) = user_id
)
with check (
    (select auth.uid()) is not null
    and
    (select auth.uid()) = user_id
);


-- ============================================================
-- 11. Audit log access
-- ============================================================
--
-- No anon/authenticated policies are deliberately created.
--
-- Audit log operations will be performed only by the trusted
-- server-side privileged client.
--

revoke all on table public.audit_logs
from anon, authenticated;


-- ============================================================
-- 12. Privileged service access
-- ============================================================

grant all
on table public.profiles
to service_role;

grant all
on table public.audit_logs
to service_role;


-- ============================================================
-- End migration
-- ============================================================