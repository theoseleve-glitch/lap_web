"""Error hierarchy for telemetry format adapters."""
from __future__ import annotations


class ParseError(Exception):
    """Base error for all adapter parse failures."""
    def __init__(self, message: str, *, format_name: str, file_path: str):
        super().__init__(message)
        self.format_name = format_name
        self.file_path = file_path


class UnrecognizedFormat(ParseError):
    """No adapter scored above the confidence threshold."""
    def __init__(self, message: str, *, format_name: str, file_path: str, candidates: list[tuple[str, float]]):
        super().__init__(message, format_name=format_name, file_path=file_path)
        self.candidates = candidates


class MissingColumns(ParseError):
    """Required canonical columns not found after mapping."""
    def __init__(self, message: str, *, format_name: str, file_path: str, missing: list[str], available: list[str]):
        super().__init__(message, format_name=format_name, file_path=file_path)
        self.missing = missing
        self.available = available


class CorruptedFile(ParseError):
    """File matched format but data is unreadable."""
    def __init__(self, message: str, *, format_name: str, file_path: str, offset: int | None = None):
        super().__init__(message, format_name=format_name, file_path=file_path)
        self.offset = offset


class MissingDependency(ParseError):
    """Adapter library not installed."""
    def __init__(self, message: str, *, format_name: str, file_path: str, package: str, install_hint: str):
        super().__init__(message, format_name=format_name, file_path=file_path)
        self.package = package
        self.install_hint = install_hint


class InsufficientData(ParseError):
    """File parsed but has fewer rows than minimum for analysis."""
    def __init__(self, message: str, *, format_name: str, file_path: str, row_count: int, minimum: int):
        super().__init__(message, format_name=format_name, file_path=file_path)
        self.row_count = row_count
        self.minimum = minimum
