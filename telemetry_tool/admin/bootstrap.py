"""Admin bootstrap — promote users to superadmin.

Usage:
    python -m telemetry_tool.admin.bootstrap --email admin@lap-coach.racing
    python -m telemetry_tool.admin.bootstrap --email sre@lap-coach.racing --role sre_admin
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

VALID_ADMIN_ROLES = {
    "root_admin",
    "support_admin",
    "billing_admin",
    "sre_admin",
    "auditor",
}


def promote_to_superadmin(
    conn, email: str, admin_role: str = "root_admin"
) -> bool:
    """Set is_superadmin=True and admin_role for the user with *email*.

    Returns False if no user matches the email.
    """
    cur = conn.execute(
        "UPDATE users SET is_superadmin = TRUE, admin_role = %(admin_role)s "
        "WHERE email = %(email)s",
        {"email": email, "admin_role": admin_role},
    )
    conn.commit()
    return cur.rowcount > 0


if __name__ == "__main__":
    import argparse
    import os
    import sys

    parser = argparse.ArgumentParser(description="Promote a user to superadmin")
    parser.add_argument("--email", required=True, help="User email to promote")
    parser.add_argument(
        "--role",
        default="root_admin",
        choices=sorted(VALID_ADMIN_ROLES),
        help="Admin role to assign (default: root_admin)",
    )
    args = parser.parse_args()

    pg_url = os.environ.get(
        "TELEMETRY_PG_URL",
        "postgresql://telemetry:telemetry@localhost:5432/telemetry",
    )

    try:
        import psycopg2
        import psycopg2.extras

        conn = psycopg2.connect(pg_url)
        conn.autocommit = False
        conn.cursor_factory = psycopg2.extras.RealDictCursor

        if promote_to_superadmin(conn, args.email, admin_role=args.role):
            print(f"Promoted {args.email} to {args.role}")
        else:
            print(f"User {args.email} not found")
            sys.exit(1)

        conn.close()
    except ImportError:
        print("psycopg2 not available — run in Docker or install psycopg2-binary")
        sys.exit(1)
