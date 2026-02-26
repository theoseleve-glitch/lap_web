"""OAuth provider integration -- Google and GitHub."""
from __future__ import annotations

import logging

from authlib.integrations.flask_client import OAuth

logger = logging.getLogger(__name__)

oauth = OAuth()


def init_oauth(app):
    """Register OAuth providers with the Flask app."""
    oauth.init_app(app)

    if app.config.get("GOOGLE_CLIENT_ID"):
        oauth.register(
            name="google",
            client_id=app.config["GOOGLE_CLIENT_ID"],
            client_secret=app.config["GOOGLE_CLIENT_SECRET"],
            server_metadata_url="https://accounts.google.com/.well-known/openid-configuration",
            client_kwargs={"scope": "openid email profile"},
        )

    if app.config.get("GITHUB_CLIENT_ID"):
        oauth.register(
            name="github",
            client_id=app.config["GITHUB_CLIENT_ID"],
            client_secret=app.config["GITHUB_CLIENT_SECRET"],
            access_token_url="https://github.com/login/oauth/access_token",
            authorize_url="https://github.com/login/oauth/authorize",
            api_base_url="https://api.github.com/",
            client_kwargs={"scope": "user:email"},
        )


def get_or_create_oauth_user(conn, provider: str, profile: dict, secret: str) -> dict:
    """Find or create user from OAuth profile. Returns login result.

    Raises ``AuthError`` if the provider has not verified the user's email
    and we would need to link to an existing account (prevents account takeover).
    """
    from auth.service import (
        create_access_token, create_refresh_token, hash_refresh_token, AuthError,
    )
    from datetime import datetime, timedelta, timezone

    email = profile["email"]
    provider_user_id = str(profile["id"])
    email_verified_by_provider = profile.get("email_verified", False)

    try:
        # Check if OAuth connection exists
        cur = conn.execute(
            "SELECT user_id FROM oauth_connections "
            "WHERE provider = %(provider)s AND provider_user_id = %(puid)s",
            {"provider": provider, "puid": provider_user_id},
        )
        row = cur.fetchone()

        if row:
            user_id = row["user_id"]
        else:
            # Check if user with this email exists (link accounts)
            cur = conn.execute(
                "SELECT id FROM users WHERE email = %(email)s",
                {"email": email},
            )
            existing = cur.fetchone()

            if existing:
                # Only link if the OAuth provider has verified this email
                if not email_verified_by_provider:
                    raise AuthError(
                        "Cannot link account: email not verified by OAuth provider",
                        "OAUTH_EMAIL_UNVERIFIED",
                    )
                user_id = existing["id"]
            else:
                # Create new user (no password -- OAuth only).
                # Use ON CONFLICT to handle concurrent creation race.
                cur = conn.execute(
                    "INSERT INTO users (email, display_name, email_verified) "
                    "VALUES (%(email)s, %(name)s, true) "
                    "ON CONFLICT (email) DO UPDATE SET email = EXCLUDED.email "
                    "RETURNING id",
                    {"email": email, "name": profile.get("name", email.split("@")[0])},
                )
                user_id = cur.fetchone()["id"]

            # Create OAuth connection
            conn.execute(
                "INSERT INTO oauth_connections (user_id, provider, provider_user_id) "
                "VALUES (%(uid)s, %(provider)s, %(puid)s) ON CONFLICT DO NOTHING",
                {"uid": user_id, "provider": provider, "puid": provider_user_id},
            )

        # Issue tokens
        access_token = create_access_token(user_id, secret)
        refresh_token = create_refresh_token()
        expires_at = datetime.now(timezone.utc) + timedelta(days=30)
        conn.execute(
            "INSERT INTO refresh_tokens (user_id, token_hash, expires_at) "
            "VALUES (%(uid)s, %(hash)s, %(exp)s)",
            {"uid": user_id, "hash": hash_refresh_token(refresh_token), "exp": expires_at},
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise

    cur = conn.execute(
        "SELECT id, email, display_name FROM users WHERE id = %(uid)s",
        {"uid": user_id},
    )
    user = dict(cur.fetchone())

    return {
        "access_token": access_token,
        "refresh_token": refresh_token,
        "user": user,
    }
