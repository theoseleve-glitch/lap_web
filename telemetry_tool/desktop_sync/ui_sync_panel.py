"""Tkinter Sync Panel — desktop GUI for cloud sync status and actions.

A standalone Toplevel window showing:
  - Account status (paired / plan tier / usage)
  - Per-session sync + analysis state
  - Action buttons: Upload, Retry, View in Browser, Disconnect

Launched from main.py after pipeline finalize, or standalone via CLI.
Auto-refreshes every 5 seconds. Non-blocking — runs in the main thread.
"""
from __future__ import annotations

import logging
import threading
import webbrowser
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_WEBAPP_BASE = "https://lap-coach.racing"
_REFRESH_MS = 5_000

# ── Status display helpers ──────────────────────────────────

_STATUS_DISPLAY = {
    "skipped":    ("Local Only",  "#949494"),
    "pending":    ("Queued",      "#C9A84C"),
    "uploading":  ("Uploading",   "#C9A84C"),
    "uploaded":   ("Uploaded",    "#22C55E"),
    "failed":     ("Failed",      "#FF2A2A"),
}

_ANALYSIS_DISPLAY = {
    "queued":     ("Analyzing...",    "#C9A84C"),
    "running":    ("Analyzing...",    "#C9A84C"),
    "succeeded":  ("Analyzed",        "#22C55E"),
    "failed":     ("Analysis Failed", "#FF2A2A"),
    None:         ("",                "#949494"),
}

_TIER_DISPLAY = {
    "A": ("Full",     "#22C55E"),
    "B": ("Standard", "#C9A84C"),
    "C": ("Basic",    "#FACC15"),
    "D": ("Limited",  "#FF2A2A"),
}


def _format_date(iso: str | None) -> str:
    if not iso:
        return ""
    try:
        from datetime import datetime
        dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
        return dt.strftime("%b %d %H:%M")
    except Exception:
        return iso[:16] if iso else ""


def _session_label(entry) -> str:
    parts = []
    if entry.track_name:
        parts.append(entry.track_name)
    if entry.vehicle_name:
        parts.append(entry.vehicle_name)
    if not parts:
        parts.append(Path(entry.bundle_path).stem)
    return " — ".join(parts)


def _combined_status(entry) -> tuple[str, str]:
    """Return (label, hex_color) for the combined upload+analysis state."""
    if entry.status == "uploaded" and entry.analysis_status:
        label, color = _ANALYSIS_DISPLAY.get(
            entry.analysis_status, ("", "#949494")
        )
        if entry.analysis_tier:
            tier_label, tier_color = _TIER_DISPLAY.get(
                entry.analysis_tier, ("", "#949494")
            )
            if tier_label:
                return f"{label} ({tier_label})", tier_color
        return label, color
    return _STATUS_DISPLAY.get(entry.status, (entry.status, "#949494"))


class SyncPanel:
    """Tkinter Toplevel for sync status. Call ``open()`` to show, ``close()`` to hide."""

    def __init__(
        self,
        queue,
        config=None,
        entitlements=None,
        on_upload=None,
        on_retry=None,
        on_disconnect=None,
    ):
        self._queue = queue
        self._config = config
        self._entitlements = entitlements
        self._on_upload = on_upload
        self._on_retry = on_retry
        self._on_disconnect = on_disconnect
        self._window = None
        self._session_frame = None

    def open(self, parent=None):
        """Show the panel. Creates the window if not already open."""
        try:
            import tkinter as tk
            from tkinter import ttk
        except ImportError:
            logger.warning("[SYNC] Tkinter not available — panel disabled")
            return

        if self._window is not None:
            try:
                self._window.lift()
                return
            except Exception:
                self._window = None

        root = tk.Toplevel(parent) if parent else tk.Tk()
        root.title("Lap — Cloud Analysis")
        root.geometry("480x520")
        root.configure(bg="#141414")
        root.resizable(True, True)
        self._window = root

        # ── Account section ─────────────────────────────────
        acct_frame = tk.Frame(root, bg="#141414", padx=16, pady=12)
        acct_frame.pack(fill="x")

        self._acct_label = tk.Label(
            acct_frame, text="Loading...",
            fg="#F0EDE5", bg="#141414", font=("Inter", 11), anchor="w",
        )
        self._acct_label.pack(fill="x")

        self._plan_label = tk.Label(
            acct_frame, text="",
            fg="#949494", bg="#141414", font=("Space Mono", 9), anchor="w",
        )
        self._plan_label.pack(fill="x")

        self._usage_label = tk.Label(
            acct_frame, text="",
            fg="#949494", bg="#141414", font=("Space Mono", 9), anchor="w",
        )
        self._usage_label.pack(fill="x")

        # ── Separator ──────────────────────────────────────
        sep = tk.Frame(root, bg="#949494", height=1)
        sep.pack(fill="x", padx=16)

        # ── Session list header ─────────────────────────────
        hdr = tk.Frame(root, bg="#141414", padx=16, pady=8)
        hdr.pack(fill="x")
        tk.Label(
            hdr, text="Sessions", fg="#F0EDE5", bg="#141414",
            font=("Space Grotesk", 12, "bold"), anchor="w",
        ).pack(side="left")

        # ── Scrollable session list ─────────────────────────
        canvas_frame = tk.Frame(root, bg="#141414")
        canvas_frame.pack(fill="both", expand=True, padx=16, pady=(0, 8))

        self._canvas = tk.Canvas(canvas_frame, bg="#141414", highlightthickness=0)
        scrollbar = tk.Scrollbar(canvas_frame, orient="vertical", command=self._canvas.yview)
        self._session_frame = tk.Frame(self._canvas, bg="#141414")

        self._session_frame.bind(
            "<Configure>",
            lambda e: self._canvas.configure(scrollregion=self._canvas.bbox("all")),
        )
        self._canvas.create_window((0, 0), window=self._session_frame, anchor="nw")
        self._canvas.configure(yscrollcommand=scrollbar.set)
        self._canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        # ── Bottom buttons ──────────────────────────────────
        btn_frame = tk.Frame(root, bg="#141414", padx=16, pady=8)
        btn_frame.pack(fill="x")

        if self._on_disconnect:
            tk.Button(
                btn_frame, text="Disconnect", fg="#FF2A2A", bg="#1a1a1a",
                font=("Space Mono", 9), relief="flat", cursor="hand2",
                command=self._handle_disconnect,
            ).pack(side="right")

        self._refresh()
        self._schedule_refresh()

    def close(self):
        if self._window:
            try:
                self._window.destroy()
            except Exception:
                pass
            self._window = None

    # ── Refresh logic ───────────────────────────────────────

    def _schedule_refresh(self):
        if self._window:
            try:
                self._window.after(_REFRESH_MS, self._refresh_and_reschedule)
            except Exception:
                pass

    def _refresh_and_reschedule(self):
        self._refresh()
        self._schedule_refresh()

    def _refresh(self):
        try:
            self._update_account()
            self._update_sessions()
        except Exception as exc:
            logger.debug("[SYNC] Panel refresh error: %s", exc)

    def _update_account(self):
        if not self._config:
            return
        email = self._config.get("paired_email") or "Not connected"
        self._acct_label.configure(text=email)

        tier = self._config.get("cached_plan_tier") or "free"
        tier_label = {"free": "Free", "racer": "Racer", "world_class": "World Class"}.get(
            tier, tier.replace("_", " ").title()
        )
        self._plan_label.configure(text=f"Plan: {tier_label}")

    def _update_sessions(self):
        if not self._session_frame:
            return
        # Clear existing rows
        for w in self._session_frame.winfo_children():
            w.destroy()

        entries = self._queue.list_all()
        if not entries:
            tk.Label(
                self._session_frame, text="No sessions yet.",
                fg="#949494", bg="#141414", font=("Inter", 10),
            ).pack(pady=20)
            return

        for entry in entries[:20]:   # cap to 20 rows
            self._build_session_row(entry)

    def _build_session_row(self, entry):
        import tkinter as tk

        row = tk.Frame(self._session_frame, bg="#1a1a1a", padx=8, pady=6)
        row.pack(fill="x", pady=2)

        # Left: session label + date
        left = tk.Frame(row, bg="#1a1a1a")
        left.pack(side="left", fill="x", expand=True)

        tk.Label(
            left, text=_session_label(entry),
            fg="#F0EDE5", bg="#1a1a1a", font=("Inter", 10), anchor="w",
        ).pack(fill="x")

        tk.Label(
            left, text=_format_date(entry.created_at),
            fg="#949494", bg="#1a1a1a", font=("Space Mono", 8), anchor="w",
        ).pack(fill="x")

        # Right: status + action
        right = tk.Frame(row, bg="#1a1a1a")
        right.pack(side="right")

        status_text, status_color = _combined_status(entry)
        tk.Label(
            right, text=status_text, fg=status_color, bg="#1a1a1a",
            font=("Space Mono", 9),
        ).pack(side="left", padx=(0, 8))

        # Action buttons
        if entry.status == "skipped" and self._on_upload:
            tk.Button(
                right, text="Upload", fg="#C9A84C", bg="#1a1a1a",
                font=("Space Mono", 8), relief="flat", cursor="hand2",
                command=lambda qid=entry.queue_id: self._handle_upload(qid),
            ).pack(side="left")
        elif entry.status == "failed" and self._on_retry:
            tk.Button(
                right, text="Retry", fg="#FF2A2A", bg="#1a1a1a",
                font=("Space Mono", 8), relief="flat", cursor="hand2",
                command=lambda qid=entry.queue_id: self._handle_retry(qid),
            ).pack(side="left")
        elif entry.status == "uploaded" and entry.cloud_bundle_id:
            tk.Button(
                right, text="View", fg="#C9A84C", bg="#1a1a1a",
                font=("Space Mono", 8), relief="flat", cursor="hand2",
                command=lambda bid=entry.cloud_bundle_id: self._open_in_browser(bid),
            ).pack(side="left")

    # ── Action handlers ─────────────────────────────────────

    def _handle_upload(self, queue_id: str):
        if self._on_upload:
            threading.Thread(
                target=self._on_upload, args=(queue_id,), daemon=True,
            ).start()

    def _handle_retry(self, queue_id: str):
        if self._on_retry:
            threading.Thread(
                target=self._on_retry, args=(queue_id,), daemon=True,
            ).start()

    def _handle_disconnect(self):
        if self._on_disconnect:
            self._on_disconnect()
            self._refresh()

    @staticmethod
    def _open_in_browser(bundle_id: str):
        url = f"{_WEBAPP_BASE}/app/bundles/{bundle_id}"
        logger.info("[SYNC] Opening: %s", url)
        try:
            webbrowser.open(url)
        except Exception as exc:
            logger.warning("[SYNC] Failed to open browser: %s", exc)


def launch_sync_panel(queue=None, config=None, entitlements=None):
    """Convenience: create and open a SyncPanel as a standalone window.

    Blocks until the user closes the window (Tkinter mainloop).
    """
    from desktop_sync.hooks import _get_queue, _get_config

    queue = queue or _get_queue()
    config = config or _get_config()

    def on_upload(queue_id):
        queue.promote_skipped(queue_id)

    def on_retry(queue_id):
        from desktop_sync.queue import SyncQueue
        q = queue
        entry = q.get(queue_id)
        if entry and entry.status == "failed":
            q._conn.execute(
                "UPDATE sync_queue SET status='pending', attempt_count=0, "
                "error_message=NULL WHERE queue_id=?", (queue_id,),
            )
            q._conn.commit()

    def on_disconnect():
        from desktop_sync.auth import DeviceAuth
        DeviceAuth(config).disconnect()

    panel = SyncPanel(
        queue=queue, config=config, entitlements=entitlements,
        on_upload=on_upload, on_retry=on_retry, on_disconnect=on_disconnect,
    )
    panel.open()

    try:
        import tkinter as tk
        if panel._window:
            panel._window.mainloop()
    except Exception:
        pass
