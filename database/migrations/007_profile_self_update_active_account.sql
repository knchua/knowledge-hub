-- Knowledge Hub — Migration 007
-- Active-account enforcement for self-profile updates.
-- Approved and applied to the live Supabase database during P2.
-- Retained for migration history and reproducibility.
-- Do not reapply automatically during P5 deployment.
-- Preserves the existing SELECT policy and column UPDATE grants.
BEGIN;
DROP POLICY IF EXISTS "users_update_own_profile" ON public.profiles;
CREATE POLICY "users_update_own_profile"
ON public.profiles
FOR UPDATE TO authenticated
USING (
  (SELECT auth.uid()) IS NOT NULL
  AND (SELECT auth.uid()) = user_id
  AND is_active IS TRUE
)
WITH CHECK (
  (SELECT auth.uid()) IS NOT NULL
  AND (SELECT auth.uid()) = user_id
  AND is_active IS TRUE
);
COMMIT;
