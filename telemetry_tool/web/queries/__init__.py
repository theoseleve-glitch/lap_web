"""Reusable query functions for the Flask API.

Provides standardized database access patterns with per-request caching
to eliminate redundant lookups within a single request lifecycle.
"""
from __future__ import annotations

from flask import g


def get_cached(key: str, loader):
    """Cache a value on Flask g for the duration of the request.

    If the cached value is ``None``, it is still considered a valid cache
    hit (use a sentinel if you need to distinguish ``None`` from "not loaded").
    """
    attr = f"_cache_{key}"
    sentinel = object()
    cached = getattr(g, attr, sentinel)
    if cached is not sentinel:
        return cached
    value = loader()
    setattr(g, attr, value)
    return value
