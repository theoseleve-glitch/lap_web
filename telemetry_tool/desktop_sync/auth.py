"""Desktop authentication via DeviceToken.

Uses the existing ``device_pairings`` system in the backend. The pairing flow
is a one-time browser redirect: desktop generates a pairing code, opens the
webapp, user confirms, desktop polls for the device token.

After pairing, the device token is stored in ``~/.lap/config.json`` and used
for all subsequent API calls.
"""
from __future__ import annotations

import json
import logging
import secrets
import time
import webbrowser
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from desktop_sync.config import UserConfig

logger = logging.getLogger(__name__)

_PAIR_POLL_INTERVAL_S = 3.0
_PAIR_TIMEOUT_S = 300.0   # 5 minutes


class AuthError(Exception):
    """Raised when auth fails (expired, revoked, network)."""
    def __init__(self, message: str, code: str = "AUTH_ERROR"):
        super().__init__(message)
        self.code = code


class DeviceAuth:
    """Manages device token lifecycle."""

    def __init__(self, config: UserConfig | None = None):
        self._config = config or UserConfig()

    @property
    def is_authenticated(self) -> bool:
        return bool(self._config.get("device_token"))

    @property
    def device_token(self) -> str | None:
        return self._config.get("device_token")

    @property
    def device_id(self) -> str | None:
        return self._config.get("device_id")

    def pair_interactive(self) -> dict[str, Any]:
        """Run the browser-redirect pairing flow. Blocks until confirmed or timeout.

        Returns the pairing result dict (device_id, device_token, user_email).
        """
        api_url = self._config.cloud_api_url
        if not api_url:
            raise AuthError("cloud_api_url not configured", "CONFIG_MISSING")

        # Generate a pairing code
        pairing_code = secrets.token_hex(16)

        # Open the webapp pairing page
        pair_url = f"{api_url.rstrip('/')}/app/account/devices?pair={pairing_code}"
        print(f"\n  Opening browser for account pairing...")
        print(f"  If the browser doesn't open, visit: {pair_url}\n")
        try:
            webbrowser.open(pair_url)
        except Exception:
            pass   # manual URL fallback is printed above

        # Register the pairing intent
        try:
            body = json.dumps({"pairing_code": pairing_code}).encode("utf-8")
            req = Request(
                f"{api_url}/api/v1/devices/pair",
                data=body,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            resp = urlopen(req, timeout=30)
            result = json.loads(resp.read().decode("utf-8"))
            device_id = result.get("data", {}).get("device_id")
        except (HTTPError, URLError, OSError) as exc:
            raise AuthError(f"Failed to initiate pairing: {exc}") from exc

        if not device_id:
            raise AuthError("Pairing initiation returned no device_id")

        # Poll until confirmed or timeout
        print("  Waiting for confirmation in browser...")
        start = time.monotonic()
        while time.monotonic() - start < _PAIR_TIMEOUT_S:
            time.sleep(_PAIR_POLL_INTERVAL_S)
            try:
                status = self._poll_pairing_status(api_url, device_id)
                if status.get("confirmed"):
                    token = status["device_token"]
                    email = status.get("user_email", "")
                    self._config.set("device_token", token)
                    self._config.set("device_id", device_id)
                    self._config.set("paired_email", email)
                    print(f"  Paired successfully as {email}")
                    return {"device_id": device_id, "device_token": token, "user_email": email}
            except Exception as exc:
                logger.debug("Pairing poll error: %s", exc)

        raise AuthError("Pairing timed out. Please try again.", "PAIR_TIMEOUT")

    def fetch_entitlements(self) -> dict[str, Any]:
        """Call ``GET /api/v1/me`` and return the full response."""
        token = self.device_token
        if not token:
            raise AuthError("Not authenticated", "NOT_AUTHENTICATED")

        api_url = self._config.cloud_api_url
        if not api_url:
            raise AuthError("cloud_api_url not configured", "CONFIG_MISSING")

        try:
            req = Request(
                f"{api_url}/api/v1/me",
                headers={"Authorization": f"DeviceToken {token}"},
            )
            resp = urlopen(req, timeout=30)
            body = json.loads(resp.read().decode("utf-8"))
            return body.get("data", body)
        except HTTPError as exc:
            if exc.code == 401:
                self.disconnect()
                raise AuthError("Device token expired or revoked. Please reconnect.", "TOKEN_EXPIRED")
            raise AuthError(f"Entitlement fetch failed: HTTP {exc.code}") from exc
        except (URLError, OSError) as exc:
            raise AuthError(f"Network error: {exc}", "NETWORK_ERROR") from exc

    def disconnect(self) -> None:
        """Clear stored credentials."""
        for key in ("device_token", "device_id", "paired_email",
                    "cached_plan_tier", "cached_entitlements", "entitlements_fetched_at"):
            try:
                self._config.set(key, None)
            except Exception:
                pass
        logger.info("[AUTH] Disconnected")

    def _poll_pairing_status(self, api_url: str, device_id: str) -> dict[str, Any]:
        req = Request(f"{api_url}/api/v1/devices/{device_id}/status")
        resp = urlopen(req, timeout=10)
        return json.loads(resp.read().decode("utf-8")).get("data", {})
