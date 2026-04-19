"""Assetto Corsa Python app -- TCP bridge for external control injection.

This file runs INSIDE the Assetto Corsa process as a Python app.
It starts a TCP server on ``127.0.0.1:9876`` and applies steering,
throttle, and brake commands received as JSON.

Install by copying this folder to:
  ``<AC>/apps/python/lap_oracle_bridge/``

Requires ``config.ini`` alongside this file.

Protocol:
  Client sends JSON lines: ``{"steer": 0.1, "throttle": 0.8, "brake": 0.0}\\n``
  The app reads the latest command each physics tick and applies it.

Note: ``ac.ext_setDriverSteer/Gas/Brake`` require Content Manager's
Custom Shaders Patch (CSP).  On vanilla AC, the try/except falls back
to logging only.
"""
from __future__ import annotations

import json
import socket
import threading
import traceback

# -- AC SDK imports (only available inside AC) -----------------------------
try:
    import ac  # type: ignore[import-untyped]
    import acsys  # type: ignore[import-untyped]
    _IN_AC = True
except ImportError:
    _IN_AC = False

# -- Globals ---------------------------------------------------------------
_HOST = "127.0.0.1"
_PORT = 9876
_latest_command: dict = {"steer": 0.0, "throttle": 0.0, "brake": 0.0}
_server_thread: threading.Thread | None = None
_server_socket: socket.socket | None = None
_client_socket: socket.socket | None = None
_running = False
_app_window = None


# -- TCP server ------------------------------------------------------------

def _accept_loop() -> None:
    """Accept one client and read commands until disconnect."""
    global _client_socket, _running
    if _server_socket is None:
        return
    while _running:
        try:
            _server_socket.settimeout(2.0)
            conn, addr = _server_socket.accept()
            _client_socket = conn
            if _IN_AC:
                ac.log("LapOracle: client connected from {}".format(addr))
            _recv_loop(conn)
        except socket.timeout:
            continue
        except OSError:
            break


def _recv_loop(conn: socket.socket) -> None:
    """Read JSON commands from the connected client."""
    global _latest_command, _running
    buf = ""
    conn.settimeout(1.0)
    while _running:
        try:
            data = conn.recv(4096)
            if not data:
                break
            buf += data.decode("utf-8", errors="replace")
            while "\n" in buf:
                line, buf = buf.split("\n", 1)
                line = line.strip()
                if not line:
                    continue
                try:
                    cmd = json.loads(line)
                    _latest_command = {
                        "steer": float(cmd.get("steer", 0.0)),
                        "throttle": float(cmd.get("throttle", 0.0)),
                        "brake": float(cmd.get("brake", 0.0)),
                    }
                except (json.JSONDecodeError, ValueError, TypeError):
                    pass
        except socket.timeout:
            continue
        except OSError:
            break
    try:
        conn.close()
    except OSError:
        pass


# -- AC app callbacks ------------------------------------------------------

def acMain(ac_version: int) -> int:
    """AC app entry point -- called once when the app loads."""
    global _app_window, _server_socket, _server_thread, _running

    if not _IN_AC:
        return -1

    _app_window = ac.newApp("Lap Oracle Bridge")
    ac.setSize(_app_window, 200, 50)
    ac.setTitle(_app_window, "LO Bridge")

    # Start TCP server
    _running = True
    try:
        _server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        _server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        _server_socket.bind((_HOST, _PORT))
        _server_socket.listen(1)
        ac.log("LapOracle: TCP server on {}:{}".format(_HOST, _PORT))
    except OSError as exc:
        ac.log("LapOracle: cannot bind TCP: {}".format(exc))
        return -1

    _server_thread = threading.Thread(target=_accept_loop, daemon=True)
    _server_thread.start()

    return _app_window


def acUpdate(delta_t: float) -> None:
    """AC physics tick -- apply the latest control command."""
    if not _IN_AC:
        return

    steer = _latest_command.get("steer", 0.0)
    throttle = _latest_command.get("throttle", 0.0)
    brake = _latest_command.get("brake", 0.0)

    # CSP extended API for control injection
    try:
        ac.ext_setDriverSteer(0, steer)
        ac.ext_setDriverGas(0, throttle)
        ac.ext_setDriverBrake(0, brake)
    except AttributeError:
        # Vanilla AC without CSP -- no control injection available
        pass
    except Exception:
        pass


def acShutdown() -> None:
    """AC app shutdown -- cleanup resources."""
    global _running, _server_socket, _client_socket
    _running = False

    if _client_socket is not None:
        try:
            _client_socket.close()
        except OSError:
            pass
        _client_socket = None

    if _server_socket is not None:
        try:
            _server_socket.close()
        except OSError:
            pass
        _server_socket = None
