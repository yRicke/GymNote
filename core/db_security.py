from contextlib import contextmanager

from django.db import connection


def _context_values(user):
    if getattr(user, "is_authenticated", False):
        return str(user.pk), "true" if user.is_staff else "false"
    return "", "false"


@contextmanager
def database_user_context(user):
    """Set the authenticated Django user for PostgreSQL RLS policies."""
    if connection.vendor != "postgresql":
        yield
        return

    user_id, is_staff = _context_values(user)
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT
                current_setting('gymnote.user_id', true),
                current_setting('gymnote.is_staff', true)
            """
        )
        previous_user_id, previous_is_staff = cursor.fetchone()
        cursor.execute(
            "SELECT set_config('gymnote.user_id', %s, true)",
            [user_id],
        )
        cursor.execute(
            "SELECT set_config('gymnote.is_staff', %s, true)",
            [is_staff],
        )

    try:
        yield
    finally:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT set_config('gymnote.user_id', %s, true)",
                [previous_user_id or ""],
            )
            cursor.execute(
                "SELECT set_config('gymnote.is_staff', %s, true)",
                [previous_is_staff or "false"],
            )
