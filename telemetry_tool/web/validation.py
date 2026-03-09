"""Pydantic v2 request validation decorators.

Provides ``@validate_body(Schema)`` and ``@validate_params(Schema)`` that
parse Flask request data through a Pydantic ``BaseModel`` and either store
the validated result on ``flask.g`` or return a ``VALIDATION_ERROR`` envelope
with *all* errors at once.

Usage::

    from web.validation import validate_body, validate_params
    from web.schemas.sessions import CreateSessionSchema

    @bp.route("/sessions", methods=["POST"])
    @validate_body(CreateSessionSchema)
    def create_session():
        session = g.body  # typed CreateSessionSchema
        ...
"""
from __future__ import annotations

import functools
import os
import re
from typing import Any, Type

from flask import g, request
from pydantic import BaseModel, ValidationError

from .api_utils import ErrorCode, api_error

# ---------------------------------------------------------------------------
# Input sanitization helpers
# ---------------------------------------------------------------------------

# Characters not allowed in filenames (covers Windows + Unix)
_UNSAFE_FILENAME_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')

# HTML tag pattern for stripping
_HTML_TAG_RE = re.compile(r"<[^>]+>")


def sanitize_filename(name: str, max_length: int = 200) -> str:
    """Sanitize a user-provided filename.

    Strips path traversal components, unsafe characters, and enforces
    length limits. Returns a safe filename string.

    Examples::

        sanitize_filename("../../etc/passwd")  → "passwd"
        sanitize_filename("my<file>.csv")      → "myfile.csv"
    """
    # Remove path components (directory traversal)
    name = os.path.basename(name)
    # Replace .. sequences
    name = name.replace("..", "")
    # Remove unsafe characters
    name = _UNSAFE_FILENAME_CHARS.sub("", name)
    # Strip leading/trailing whitespace and dots
    name = name.strip(". ")
    # Enforce length limit
    if len(name) > max_length:
        # Preserve extension
        base, ext = os.path.splitext(name)
        name = base[: max_length - len(ext)] + ext
    return name or "unnamed"


def sanitize_html(text: str, max_length: int = 10000) -> str:
    """Strip HTML tags from user-provided text.

    For use on display_name, team_name, and other user-input strings
    that should never contain HTML. Does NOT allow any tags through.

    Examples::

        sanitize_html("<script>alert('xss')</script>Hello")  → "alert('xss')Hello"
        sanitize_html("Normal text")                          → "Normal text"
    """
    cleaned = _HTML_TAG_RE.sub("", text)
    return cleaned[:max_length]


def _format_errors(exc: ValidationError) -> list[dict[str, Any]]:
    """Convert Pydantic ValidationError to a list of ``{field, message}`` dicts."""
    details = []
    for err in exc.errors():
        # loc is a tuple like ("name",) or ("address", "zip_code")
        loc_parts = [str(p) for p in err["loc"]]
        field = ".".join(loc_parts) if loc_parts else "unknown"
        details.append({
            "field": field,
            "message": err["msg"],
        })
    return details


def validate_body(schema_cls: Type[BaseModel]):
    """Decorator: parse ``request.get_json()`` through *schema_cls*.

    On success the validated model is stored as ``g.body``.
    On failure a 422 response with ``VALIDATION_ERROR`` code and all
    error details is returned immediately.
    """

    def decorator(fn):
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            raw = request.get_json(silent=True)
            if raw is None:
                return api_error(
                    ErrorCode.VALIDATION_ERROR,
                    "Request body must be valid JSON",
                    details=[{"field": "body", "message": "Missing or malformed JSON"}],
                    status=422,
                )
            try:
                g.body = schema_cls.model_validate(raw)
            except ValidationError as exc:
                return api_error(
                    ErrorCode.VALIDATION_ERROR,
                    "Request validation failed",
                    details=_format_errors(exc),
                    status=422,
                )
            return fn(*args, **kwargs)
        return wrapper
    return decorator


def validate_params(schema_cls: Type[BaseModel]):
    """Decorator: parse ``request.args`` through *schema_cls*.

    On success the validated model is stored as ``g.params``.
    Query parameters arrive as strings, so Pydantic's type coercion
    handles ``str -> int``, ``str -> float``, etc.
    On failure a 422 response with ``VALIDATION_ERROR`` code is returned.
    """

    def decorator(fn):
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            # request.args is an ImmutableMultiDict; convert to plain dict
            raw = dict(request.args)
            try:
                g.params = schema_cls.model_validate(raw)
            except ValidationError as exc:
                return api_error(
                    ErrorCode.VALIDATION_ERROR,
                    "Query parameter validation failed",
                    details=_format_errors(exc),
                    status=422,
                )
            return fn(*args, **kwargs)
        return wrapper
    return decorator
