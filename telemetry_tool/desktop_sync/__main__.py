"""CLI entry point for manual sync operations.

Usage::

    python -m desktop_sync status     # show sync queue status
    python -m desktop_sync upload     # promote all skipped → pending, drain
    python -m desktop_sync retry      # retry failed uploads
    python -m desktop_sync config     # show current config
"""
from __future__ import annotations

import argparse
import sys

from desktop_sync.config import UserConfig
from desktop_sync.hooks import _get_queue, _ensure_worker, shutdown_worker
from desktop_sync.queue import SyncQueue
from desktop_sync.worker import SyncWorker


def cmd_status(args):
    queue = _get_queue()
    counts = queue.count_by_status()
    total = sum(counts.values())
    print(f"Sync queue: {total} entries")
    for status in ("pending", "skipped", "uploading", "uploaded", "failed"):
        n = counts.get(status, 0)
        if n > 0:
            print(f"  {status:12s}  {n}")
    if total == 0:
        print("  (empty)")


def cmd_upload(args):
    queue = _get_queue()
    promoted = queue.promote_all_skipped()
    if promoted:
        print(f"Promoted {promoted} skipped session(s) to pending.")

    pending = queue.get_pending()
    if not pending:
        print("No sessions to upload.")
        return

    config = UserConfig()
    api_url = config.cloud_api_url
    if not api_url:
        print("Error: cloud_api_url not configured in ~/.lap/config.json")
        sys.exit(1)

    print(f"Uploading {len(pending)} session(s) to {api_url}...")
    worker = SyncWorker(queue=queue, api_url=api_url)
    count = worker.drain_once()
    print(f"Uploaded: {count}")


def cmd_retry(args):
    queue = _get_queue()
    retried = queue.retry_failed()
    if retried == 0:
        print("No failed uploads to retry.")
        return
    print(f"Reset {retried} failed upload(s) to pending.")
    cmd_upload(args)


def cmd_config(args):
    config = UserConfig()
    print(f"Config file: {config._path}")
    print(f"  auto_upload:        {config.auto_upload}")
    print(f"  cloud_api_url:      {config.cloud_api_url or '(not set)'}")
    print(f"  max_upload_attempts: {config.max_upload_attempts}")
    print(f"  device_token:       {'***' + config.get('device_token', '')[-8:] if config.get('device_token') else '(not paired)'}")
    print(f"  paired_email:       {config.get('paired_email') or '(not paired)'}")


def cmd_pair(args):
    from desktop_sync.auth import DeviceAuth, AuthError
    config = UserConfig()
    if not config.cloud_api_url:
        print("Error: Set cloud_api_url first:")
        print("  python -m desktop_sync set-url https://api.lap-coach.racing")
        sys.exit(1)
    auth = DeviceAuth(config)
    if auth.is_authenticated:
        email = config.get("paired_email", "unknown")
        print(f"Already paired as {email}. Use 'disconnect' first to re-pair.")
        return
    try:
        result = auth.pair_interactive()
        print(f"\nPaired as: {result.get('user_email', 'unknown')}")
        print(f"Device ID: {result['device_id'][:12]}...")
    except AuthError as exc:
        print(f"Pairing failed: {exc}")
        sys.exit(1)


def cmd_whoami(args):
    from desktop_sync.auth import DeviceAuth, AuthError
    auth = DeviceAuth()
    if not auth.is_authenticated:
        print("Not connected. Run: python -m desktop_sync pair")
        return
    try:
        ent = auth.fetch_entitlements()
        print(f"Email:  {ent.get('email', '?')}")
        print(f"Plan:   {ent.get('plan_tier', '?')}")
        entitlements = ent.get("entitlements", {})
        print(f"Analyses/month: {entitlements.get('analyses_per_month', '?')}")
    except AuthError as exc:
        print(f"Error: {exc}")
        sys.exit(1)


def cmd_disconnect(args):
    from desktop_sync.auth import DeviceAuth
    auth = DeviceAuth()
    auth.disconnect()
    print("Disconnected. Device token cleared.")


def cmd_set_url(args):
    config = UserConfig()
    config.cloud_api_url = args.url
    print(f"Cloud API URL set to: {args.url}")


def main():
    parser = argparse.ArgumentParser(prog="desktop_sync",
                                     description="Lap session sync CLI")
    sub = parser.add_subparsers(dest="command")

    sub.add_parser("status", help="Show sync queue status")
    sub.add_parser("upload", help="Upload all pending/skipped sessions")
    sub.add_parser("retry", help="Retry failed uploads")
    sub.add_parser("config", help="Show current config")
    sub.add_parser("pair", help="Connect your Lap account")
    sub.add_parser("whoami", help="Show current account info")
    sub.add_parser("disconnect", help="Disconnect account")
    url_parser = sub.add_parser("set-url", help="Set cloud API URL")
    url_parser.add_argument("url", help="e.g. https://api.lap-coach.racing")
    sub.add_parser("gui", help="Open the sync panel GUI")

    args = parser.parse_args()
    if not args.command:
        parser.print_help()
        return

    cmds = {
        "status": cmd_status,
        "upload": cmd_upload,
        "retry": cmd_retry,
        "config": cmd_config,
        "pair": cmd_pair,
        "whoami": cmd_whoami,
        "disconnect": cmd_disconnect,
        "set-url": cmd_set_url,
        "gui": lambda _: _cmd_gui(),
    }
    cmds[args.command](args)


def _cmd_gui():
    from desktop_sync.ui_sync_panel import launch_sync_panel
    launch_sync_panel()


if __name__ == "__main__":
    main()
