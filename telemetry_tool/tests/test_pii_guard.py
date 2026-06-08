# tests/test_pii_guard.py
"""Tests for the shared PII guard used by event ingest, marketing collector,
and GDPR export scrubbing."""
from __future__ import annotations

import json
import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))


class TestScrubProperties:
    def test_none_and_non_dict_become_empty(self):
        from web.pii_guard import scrub_properties
        assert scrub_properties(None) == {}
        assert scrub_properties("nope") == {}
        assert scrub_properties(42) == {}
        assert scrub_properties(["a", "b"]) == {}

    def test_drops_denylisted_keys_case_insensitive(self):
        from web.pii_guard import scrub_properties
        out = scrub_properties({
            "source": "hero",
            "email": "a@b.com",
            "IP": "1.2.3.4",
            "Access_Token": "xyz",
            "password": "hunter2",
            "phone": "+33123",
            "ssn": "111-22-3333",
        })
        assert out == {"source": "hero"}

    def test_drops_values_matching_email_or_ipv4(self):
        from web.pii_guard import scrub_properties
        out = scrub_properties({
            "note": "contact me at john@example.com",
            "host": "10.0.0.42",
            "clean": "pricing_page",
        })
        # values containing an email or an IPv4 are dropped entirely
        assert "note" not in out
        assert "host" not in out
        assert out == {"clean": "pricing_page"}

    def test_flattens_by_dropping_nested_containers(self):
        from web.pii_guard import scrub_properties
        out = scrub_properties({
            "utm_source": "ig",
            "nested": {"email": "x@y.com"},
            "list": [1, 2, 3],
        })
        assert out == {"utm_source": "ig"}

    def test_size_cap_drops_keys_until_under_limit(self):
        from web.pii_guard import scrub_properties, MAX_PROPERTIES_BYTES
        big = {f"k{i}": "v" * 200 for i in range(100)}
        out = scrub_properties(big)
        assert len(json.dumps(out).encode("utf-8")) <= MAX_PROPERTIES_BYTES

    def test_clean_payload_passes_through(self):
        from web.pii_guard import scrub_properties
        payload = {"source": "pricing", "platform": "web", "utm_campaign": "launch"}
        assert scrub_properties(payload) == payload
