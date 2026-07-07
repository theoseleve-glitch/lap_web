"""Test the ``onboarding_task`` email template (Task 11).

Rendered via the shared ``render_email`` entry point used by both
synchronous senders and the async ``send_email_async`` Celery task
(``tasks/onboarding_tasks.py`` calls ``send_email_async.delay("onboarding_task", ...)``).
"""
import sys
from pathlib import Path

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from telemetry_tool.auth.email_templates import (  # noqa: E402
    TEMPLATES,
    render_email,
)

_VARS = {
    "track_label": "Karting Kerpen",
    "track_key": "kerpen_ks",
    "annotator_url": "https://annotator.example.com/?req=abc123#token=xyz",
}


def test_registered_in_templates():
    assert "onboarding_task" in TEMPLATES


def test_subject_contains_track_label():
    subject, _html = render_email("onboarding_task", _VARS)
    assert _VARS["track_label"] in subject


def test_subject_matches_expected_phrasing():
    subject, _html = render_email("onboarding_task", _VARS)
    assert subject == f"Draw limits — {_VARS['track_label']}"


def test_html_contains_annotator_url_verbatim():
    _subject, html = render_email("onboarding_task", _VARS)
    assert _VARS["annotator_url"] in html


def test_html_contains_button_anchor():
    _subject, html = render_email("onboarding_task", _VARS)
    assert f'<a href="{_VARS["annotator_url"]}"' in html
    assert "Open annotator" in html


def test_html_contains_track_key():
    _subject, html = render_email("onboarding_task", _VARS)
    assert _VARS["track_key"] in html


def test_html_contains_reuse_note():
    _subject, html = render_email("onboarding_task", _VARS)
    assert "most recent" in html


def test_missing_required_var_raises():
    with pytest.raises(KeyError):
        render_email("onboarding_task", {"track_key": "kerpen_ks"})
