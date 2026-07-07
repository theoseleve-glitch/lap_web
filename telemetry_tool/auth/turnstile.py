"""Cloudflare Turnstile step-up challenge verification.

Fully optional and fail-open UNTIL configured: with no ``TURNSTILE_SECRET_KEY``
and ``TURNSTILE_SITEKEY`` set, :func:`turnstile_configured` reports the
feature as disabled and :func:`verify_turnstile` never makes a network call
-- nothing in the login path changes until an operator sets both keys (see
auth/lockout.py's ``challenge_required``, which gates on
``turnstile_configured()`` before this module is ever consulted).

``turnstile_configured`` deliberately requires BOTH env vars, not just the
secret: the 428 ``challenge_required`` response (web/routes/auth.py) hands
the frontend widget ``TURNSTILE_SITEKEY`` to render with
(lap-website/src/components/auth/TurnstileWidget.tsx). A secret-only config
would still gate logins behind a 428 with no sitekey for the widget to
render against -- turning the challenge into an attacker-triggerable soft
lockout of the flagged victim for the whole detection window. Treating a
half-configured setup as NOT configured keeps the feature dark instead.

Once configured, a submitted token is verified server-side against
Cloudflare's siteverify endpoint. Any problem verifying a *specific* token
(bad token, network error, timeout, malformed response) is treated as NOT
passed -- fail CLOSED for the token check itself. That is a different
question from *whether a challenge is required at all*, which is decided by
``auth.lockout.challenge_required()``.
"""
from __future__ import annotations

import logging
import os

import requests

logger = logging.getLogger(__name__)

SITEVERIFY_URL = "https://challenges.cloudflare.com/turnstile/v0/siteverify"
_VERIFY_TIMEOUT_SECONDS = 5


def turnstile_configured() -> bool:
    """True only when BOTH ``TURNSTILE_SECRET_KEY`` and ``TURNSTILE_SITEKEY``
    are set -- i.e. the challenge is both enforceable server-side (secret)
    AND renderable client-side (sitekey).

    A secret-only config is deliberately treated as NOT configured (see
    module docstring): otherwise the login route would gate a flagged
    email behind a 428 challenge while handing the widget a null sitekey,
    soft-locking that victim out with no way to obtain a token.

    Read fresh from the environment on every call (not cached at import
    time) so tests -- and an operator flipping the env var -- don't need a
    process restart to take effect.
    """
    return bool(os.environ.get("TURNSTILE_SECRET_KEY")) and bool(
        os.environ.get("TURNSTILE_SITEKEY")
    )


def verify_turnstile(token: str | None, remoteip: str | None = None) -> bool:
    """Verify a Turnstile response *token* against Cloudflare's siteverify API.

    Returns True only on an explicit ``success: true`` from Cloudflare.
    Returns False (never raises) when:

    - ``TURNSTILE_SECRET_KEY`` is unset (feature disabled -- see module
      docstring; no network call is made),
    - *token* is falsy (no network call is made),
    - Cloudflare returns ``success: false``,
    - the request errors out or times out, or
    - the response body isn't valid JSON.
    """
    secret = os.environ.get("TURNSTILE_SECRET_KEY")
    if not secret or not token:
        return False

    try:
        resp = requests.post(
            SITEVERIFY_URL,
            data={"secret": secret, "response": token, "remoteip": remoteip or ""},
            timeout=_VERIFY_TIMEOUT_SECONDS,
        )
        payload = resp.json()
        return bool(payload.get("success"))
    except Exception:
        logger.warning(
            "Turnstile verification failed -- treating token as not passed",
            exc_info=True,
        )
        return False
