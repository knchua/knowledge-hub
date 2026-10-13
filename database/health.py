"""Database health checks for Knowledge Hub.

These checks are intended to verify server-side database availability
without exposing database contents or credentials.
"""

from database.client import get_supabase_admin_client


def check_database_connection() -> bool:
    """Check whether the application can reach the Phase 1 database schema.

    The check performs a minimal query against the profiles table using
    the trusted server-side Supabase client.

    Returns:
        bool: True when the database query succeeds, otherwise False.
    """

    try:
        client = get_supabase_admin_client()

        (
            client
            .table("profiles")
            .select("user_id")
            .limit(1)
            .execute()
        )

        return True

    except Exception:
        return False