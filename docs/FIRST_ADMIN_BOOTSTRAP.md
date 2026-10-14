# Knowledge Hub — First Administrator Bootstrap

## Purpose

Knowledge Hub creates all new application profiles with the `user` role.

The first administrator must therefore be established through a controlled
one-time bootstrap procedure.

This procedure must only be used before a functioning application
administrator exists.

## Preconditions

1. The Supabase project has been configured.
2. Phase 1 database migration 001 has been applied.
3. The intended administrator already exists in Supabase Auth.
4. The corresponding `public.profiles` record exists.
5. The profile is active and currently has role `user`.

## Procedure

Identify the intended administrator:

```sql
select
    u.id,
    u.email,
    p.role,
    p.is_active
from auth.users u
join public.profiles p
    on p.user_id = u.id;