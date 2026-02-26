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
from typing import Any, Type

from flask import g, request
from pydantic import BaseModel, ValidationError

from .api_utils import ErrorCode, api_error


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
