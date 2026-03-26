"""Structured import error taxonomy for telemetry file uploads.

Every import/upload failure maps to a specific ImportErrorCode with:
- machine-readable code
- user-facing title and message
- recovery next_steps
- stage where the error occurred
- severity (blocking vs warning)
- whether the user can fix it
- whether retry makes sense
- a unique support reference

Usage::

    from import_errors import ImportError as IE, ImportErrorCode, make_support_ref

    err = IE.from_code(
        ImportErrorCode.MISSING_GPS_LAT_LON,
        support_ref=make_support_ref(),
        extra_context={"detected_columns": ["Time (s)", "Speed (m/s)"]},
    )
    return err.to_dict()
"""
from __future__ import annotations

import hashlib
import time
import uuid
from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any


# ---------------------------------------------------------------------------
# Support reference generator
# ---------------------------------------------------------------------------

def make_support_ref() -> str:
    """Generate a unique, short support reference for an import failure.

    Format: IMP-<8 hex chars>  e.g. IMP-a3f9c0b1
    """
    raw = f"{time.time()}-{uuid.uuid4().hex[:8]}"
    return f"IMP-{hashlib.sha256(raw.encode()).hexdigest()[:8]}"


# ---------------------------------------------------------------------------
# Error codes
# ---------------------------------------------------------------------------

class ImportErrorCode(str, Enum):
    """Machine-readable import error codes."""

    # ── File type / format ────────────────────────────────────────
    UNSUPPORTED_FILE_EXTENSION = "UNSUPPORTED_FILE_EXTENSION"
    UNSUPPORTED_BINARY_FORMAT = "UNSUPPORTED_BINARY_FORMAT"
    UNKNOWN_LOGGER_FORMAT = "UNKNOWN_LOGGER_FORMAT"
    FORMAT_DETECTED_BUT_NOT_ENABLED = "FORMAT_DETECTED_BUT_NOT_ENABLED"

    # ── File structure ────────────────────────────────────────────
    EMPTY_FILE = "EMPTY_FILE"
    CORRUPTED_FILE = "CORRUPTED_FILE"
    UNREADABLE_ENCODING = "UNREADABLE_ENCODING"
    HEADER_NOT_FOUND = "HEADER_NOT_FOUND"
    NO_DATA_ROWS = "NO_DATA_ROWS"
    CSV_DELIMITER_NOT_RECOGNIZED = "CSV_DELIMITER_NOT_RECOGNIZED"

    # ── Required telemetry content ────────────────────────────────
    MISSING_TIME_COLUMN = "MISSING_TIME_COLUMN"
    MISSING_DISTANCE_AND_TIME = "MISSING_DISTANCE_AND_TIME"
    MISSING_GPS_LAT_LON = "MISSING_GPS_LAT_LON"
    MISSING_SPEED_CHANNEL = "MISSING_SPEED_CHANNEL"
    INSUFFICIENT_CHANNEL_COVERAGE = "INSUFFICIENT_CHANNEL_COVERAGE"

    # ── Exporter-specific issues ──────────────────────────────────
    IRACING_NON_CSV_EXPORT = "IRACING_NON_CSV_EXPORT"
    MOTEC_BINARY_NOT_SUPPORTED = "MOTEC_BINARY_NOT_SUPPORTED"
    RACEBOX_EXPORT_SHAPE_INVALID = "RACEBOX_EXPORT_SHAPE_INVALID"

    # ── Analysis readiness ────────────────────────────────────────
    TOO_FEW_VALID_LAPS = "TOO_FEW_VALID_LAPS"
    NO_VALID_MOVING_SEGMENT = "NO_VALID_MOVING_SEGMENT"
    TRACK_RECONSTRUCTION_FAILED = "TRACK_RECONSTRUCTION_FAILED"
    NOT_ENOUGH_DATA_FOR_COACHING = "NOT_ENOUGH_DATA_FOR_COACHING"

    # ── Infrastructure / transient ────────────────────────────────
    UPLOAD_TIMEOUT = "UPLOAD_TIMEOUT"
    QUEUE_FAILURE = "QUEUE_FAILURE"
    PIPELINE_INTERNAL_ERROR = "PIPELINE_INTERNAL_ERROR"

    # ── Entitlement / plan ────────────────────────────────────────
    REPORT_LIMIT_REACHED = "REPORT_LIMIT_REACHED"
    FILE_TOO_LARGE = "FILE_TOO_LARGE"
    PLAN_RESTRICTION = "PLAN_RESTRICTION"
    SESSION_LIMIT_REACHED = "SESSION_LIMIT_REACHED"
    UPLOAD_VOLUME_EXCEEDED = "UPLOAD_VOLUME_EXCEEDED"


# ---------------------------------------------------------------------------
# Error catalog — default metadata for each code
# ---------------------------------------------------------------------------

@dataclass
class _ErrorDef:
    title: str
    message: str
    next_steps: list[str]
    stage: str
    severity: str  # "blocking" | "warning"
    recoverable_by_user: bool
    retryable: bool


_CATALOG: dict[ImportErrorCode, _ErrorDef] = {
    # ── File type / format ────────────────────────────────────────

    ImportErrorCode.UNSUPPORTED_FILE_EXTENSION: _ErrorDef(
        title="Unsupported file type",
        message="This file extension is not supported by LAP.",
        next_steps=[
            "Export your session as a CSV file from your logger software",
            "Accepted formats: CSV, TXT, IBT (iRacing), LD/LDX (MoTeC), VBO (VBOX), XRK/DRK (AiM)",
        ],
        stage="preflight",
        severity="blocking",
        recoverable_by_user=True,
        retryable=False,
    ),

    ImportErrorCode.UNSUPPORTED_BINARY_FORMAT: _ErrorDef(
        title="Binary format not supported",
        message="This appears to be a proprietary binary file that LAP cannot read directly.",
        next_steps=[
            "Export the session as CSV from the logger's native software",
            "Check our supported formats page for export instructions",
        ],
        stage="preflight",
        severity="blocking",
        recoverable_by_user=True,
        retryable=False,
    ),

    ImportErrorCode.UNKNOWN_LOGGER_FORMAT: _ErrorDef(
        title="Unrecognized file format",
        message="LAP could not identify the telemetry format of this file.",
        next_steps=[
            "Verify the file is a telemetry export (not a setup or config file)",
            "Try exporting as a standard CSV with time, speed, and GPS columns",
            "Check our supported formats page for compatible loggers",
        ],
        stage="preflight",
        severity="blocking",
        recoverable_by_user=True,
        retryable=False,
    ),

    ImportErrorCode.FORMAT_DETECTED_BUT_NOT_ENABLED: _ErrorDef(
        title="Format recognized but not yet supported",
        message="LAP detected the format of this file, but support is not yet available.",
        next_steps=[
            "Export the session as CSV from your logger software",
            "Contact support if you need this format added",
        ],
        stage="preflight",
        severity="blocking",
        recoverable_by_user=True,
        retryable=False,
    ),

    # ── File structure ────────────────────────────────────────────

    ImportErrorCode.EMPTY_FILE: _ErrorDef(
        title="Empty file",
        message="The uploaded file contains no data.",
        next_steps=[
            "Check that the session was saved correctly in your logger",
            "Re-export the file and try again",
        ],
        stage="preflight",
        severity="blocking",
        recoverable_by_user=True,
        retryable=False,
    ),

    ImportErrorCode.CORRUPTED_FILE: _ErrorDef(
        title="File appears corrupted",
        message="The file content is unreadable or contains invalid data that cannot be parsed.",
        next_steps=[
            "Re-download or re-export the file from your logger",
            "Check that the file transfer completed fully (no truncation)",
        ],
        stage="preflight",
        severity="blocking",
        recoverable_by_user=True,
        retryable=False,
    ),

    ImportErrorCode.UNREADABLE_ENCODING: _ErrorDef(
        title="Unreadable text encoding",
        message="The file uses a character encoding that could not be decoded.",
        next_steps=[
            "Re-export the file with UTF-8 encoding if possible",
            "Try opening the file in a text editor to verify it's readable",
        ],
        stage="preflight",
        severity="blocking",
        recoverable_by_user=True,
        retryable=False,
    ),

    ImportErrorCode.HEADER_NOT_FOUND: _ErrorDef(
        title="No header row found",
        message="LAP could not find a row with column headers (e.g. Time, Speed, Latitude).",
        next_steps=[
            "Verify the file contains a header row with column names",
            "Some loggers add metadata rows before the header — this is usually handled automatically",
            "Re-export with headers enabled in your logger software",
        ],
        stage="preflight",
        severity="blocking",
        recoverable_by_user=True,
        retryable=False,
    ),

    ImportErrorCode.NO_DATA_ROWS: _ErrorDef(
        title="No data rows",
        message="The file has a header but no actual telemetry data rows.",
        next_steps=[
            "Check that the session recorded data (was logging active?)",
            "Re-export the session from your logger",
        ],
        stage="preflight",
        severity="blocking",
        recoverable_by_user=True,
        retryable=False,
    ),

    ImportErrorCode.CSV_DELIMITER_NOT_RECOGNIZED: _ErrorDef(
        title="CSV delimiter not recognized",
        message="LAP could not determine the column separator (comma, semicolon, or tab).",
        next_steps=[
            "Re-export using comma-separated (CSV) format",
            "Avoid custom delimiters or fixed-width formats",
        ],
        stage="preflight",
        severity="blocking",
        recoverable_by_user=True,
        retryable=False,
    ),

    # ── Required telemetry content ────────────────────────────────

    ImportErrorCode.MISSING_TIME_COLUMN: _ErrorDef(
        title="Time column missing",
        message="No time or timestamp column was found. LAP needs a time reference to process laps.",
        next_steps=[
            "Export with a time column enabled (e.g. 'Time (s)', 'Timestamp', 'UTC Time')",
            "Check your logger settings to ensure time recording is active",
        ],
        stage="preflight",
        severity="blocking",
        recoverable_by_user=True,
        retryable=False,
    ),

    ImportErrorCode.MISSING_DISTANCE_AND_TIME: _ErrorDef(
        title="No time or distance data",
        message="The file lacks both time and distance channels, which are required for analysis.",
        next_steps=[
            "Re-export with time and/or distance channels included",
        ],
        stage="preflight",
        severity="blocking",
        recoverable_by_user=True,
        retryable=False,
    ),

    ImportErrorCode.MISSING_GPS_LAT_LON: _ErrorDef(
        title="GPS data missing",
        message="This file does not contain latitude/longitude channels required for track mapping and coaching.",
        next_steps=[
            "Export the session with GPS enabled in your logger",
            "Check that your GPS receiver was connected and had satellite lock",
            "If using iRacing, upload the CSV export (not the raw telemetry file)",
        ],
        stage="preflight",
        severity="blocking",
        recoverable_by_user=True,
        retryable=False,
    ),

    ImportErrorCode.MISSING_SPEED_CHANNEL: _ErrorDef(
        title="Speed channel missing",
        message="No speed data was found. LAP needs speed to compute lap analysis.",
        next_steps=[
            "Export with speed channel enabled",
            "If using GPS-only: speed can be derived from position, but GPS must be present",
        ],
        stage="preflight",
        severity="warning",
        recoverable_by_user=True,
        retryable=False,
    ),

    ImportErrorCode.INSUFFICIENT_CHANNEL_COVERAGE: _ErrorDef(
        title="Not enough telemetry channels",
        message="The file has too few data channels for meaningful analysis.",
        next_steps=[
            "Export with more channels enabled (time, speed, GPS, throttle, brake if available)",
            "A minimum of time + speed or time + GPS is needed",
        ],
        stage="preflight",
        severity="blocking",
        recoverable_by_user=True,
        retryable=False,
    ),

    # ── Exporter-specific issues ──────────────────────────────────

    ImportErrorCode.IRACING_NON_CSV_EXPORT: _ErrorDef(
        title="iRacing raw telemetry file",
        message="This appears to be an iRacing .ibt binary telemetry file. LAP can process this format.",
        next_steps=[
            "Upload accepted — LAP supports .ibt files directly via the iRacing adapter",
            "Alternatively, export as CSV from iRacing or iSpeed for a lighter file",
        ],
        stage="preflight",
        severity="blocking",
        recoverable_by_user=True,
        retryable=False,
    ),

    ImportErrorCode.MOTEC_BINARY_NOT_SUPPORTED: _ErrorDef(
        title="MoTeC binary file",
        message="This appears to be a MoTeC .ld/.ldx binary log file.",
        next_steps=[
            "LAP supports MoTeC LD/LDX files — if this failed, the file may be a newer format variant",
            "Try exporting as CSV from MoTeC i2 Pro: File → Export → CSV",
            "Ensure the export includes Time, Speed, and GPS channels",
        ],
        stage="preflight",
        severity="blocking",
        recoverable_by_user=True,
        retryable=False,
    ),

    ImportErrorCode.RACEBOX_EXPORT_SHAPE_INVALID: _ErrorDef(
        title="RaceBox export format issue",
        message="The file appears to be from RaceBox but has an unexpected structure.",
        next_steps=[
            "Export from the RaceBox app using 'Export to CSV'",
            "Ensure the export includes GPS coordinates and lap timestamps",
        ],
        stage="preflight",
        severity="blocking",
        recoverable_by_user=True,
        retryable=False,
    ),

    # ── Analysis readiness ────────────────────────────────────────

    ImportErrorCode.TOO_FEW_VALID_LAPS: _ErrorDef(
        title="Too few valid laps",
        message="The session does not contain enough valid laps for a meaningful analysis.",
        next_steps=[
            "LAP needs at least 2 clean laps for comparison",
            "Check that the session was long enough and the start/finish line was crossed",
            "If laps were excluded, try reducing the exclusion range",
        ],
        stage="analysis",
        severity="blocking",
        recoverable_by_user=True,
        retryable=False,
    ),

    ImportErrorCode.NO_VALID_MOVING_SEGMENT: _ErrorDef(
        title="No movement detected",
        message="The telemetry data does not contain a segment with sufficient movement for analysis.",
        next_steps=[
            "Check that the logger was recording during on-track driving",
            "The file may contain only pit lane or stationary data",
        ],
        stage="analysis",
        severity="blocking",
        recoverable_by_user=True,
        retryable=False,
    ),

    ImportErrorCode.TRACK_RECONSTRUCTION_FAILED: _ErrorDef(
        title="Track reconstruction failed",
        message="LAP could not reconstruct a track layout from the GPS data.",
        next_steps=[
            "This usually means GPS quality was poor (tall buildings, covered areas)",
            "Check that GPS had satellite lock during the session",
            "Try a session recorded in open-sky conditions",
        ],
        stage="analysis",
        severity="blocking",
        recoverable_by_user=True,
        retryable=False,
    ),

    ImportErrorCode.NOT_ENOUGH_DATA_FOR_COACHING: _ErrorDef(
        title="Insufficient data for coaching",
        message="The session was processed but does not have enough data to generate coaching insights.",
        next_steps=[
            "Record a longer session with more laps",
            "Ensure throttle and brake channels are available for deeper analysis",
        ],
        stage="analysis",
        severity="warning",
        recoverable_by_user=True,
        retryable=False,
    ),

    # ── Infrastructure / transient ────────────────────────────────

    ImportErrorCode.UPLOAD_TIMEOUT: _ErrorDef(
        title="Upload timed out",
        message="The file upload did not complete within the allowed time.",
        next_steps=[
            "Check your internet connection and try again",
            "For large files, ensure a stable connection",
        ],
        stage="upload",
        severity="blocking",
        recoverable_by_user=True,
        retryable=True,
    ),

    ImportErrorCode.QUEUE_FAILURE: _ErrorDef(
        title="Processing queue unavailable",
        message="The analysis queue is temporarily unavailable.",
        next_steps=[
            "Wait a moment and try uploading again",
            "If this persists, our team has been notified",
        ],
        stage="dispatch",
        severity="blocking",
        recoverable_by_user=False,
        retryable=True,
    ),

    ImportErrorCode.PIPELINE_INTERNAL_ERROR: _ErrorDef(
        title="Internal processing error",
        message="An unexpected error occurred during analysis.",
        next_steps=[
            "Try uploading the file again",
            "If the problem persists, contact support with the reference below",
        ],
        stage="analysis",
        severity="blocking",
        recoverable_by_user=False,
        retryable=True,
    ),

    # ── Entitlement / plan ────────────────────────────────────────

    ImportErrorCode.REPORT_LIMIT_REACHED: _ErrorDef(
        title="Report limit reached",
        message="You have reached the report limit for your current plan.",
        next_steps=[
            "Upgrade your plan for more reports",
            "Wait for your monthly quota to reset",
        ],
        stage="dispatch",
        severity="blocking",
        recoverable_by_user=True,
        retryable=False,
    ),

    ImportErrorCode.FILE_TOO_LARGE: _ErrorDef(
        title="File too large",
        message="The uploaded file exceeds the size limit for your plan.",
        next_steps=[
            "Upgrade your plan for larger file support",
            "Try trimming the session to a shorter time range",
        ],
        stage="preflight",
        severity="blocking",
        recoverable_by_user=True,
        retryable=False,
    ),

    ImportErrorCode.PLAN_RESTRICTION: _ErrorDef(
        title="Feature not available on your plan",
        message="Your current plan does not include this feature.",
        next_steps=[
            "Upgrade your plan to unlock this feature",
        ],
        stage="dispatch",
        severity="blocking",
        recoverable_by_user=True,
        retryable=False,
    ),

    ImportErrorCode.SESSION_LIMIT_REACHED: _ErrorDef(
        title="Session limit reached",
        message="You have reached the maximum number of sessions for your plan.",
        next_steps=[
            "Upgrade your plan to upload more sessions",
            "Delete older sessions to free up slots",
        ],
        stage="dispatch",
        severity="blocking",
        recoverable_by_user=True,
        retryable=False,
    ),

    ImportErrorCode.UPLOAD_VOLUME_EXCEEDED: _ErrorDef(
        title="Monthly upload volume exceeded",
        message="You have used your monthly upload allowance.",
        next_steps=[
            "Wait for your monthly quota to reset",
            "Upgrade your plan for more upload volume",
        ],
        stage="dispatch",
        severity="blocking",
        recoverable_by_user=True,
        retryable=False,
    ),
}


# ---------------------------------------------------------------------------
# Structured error object
# ---------------------------------------------------------------------------

@dataclass
class ImportFailure:
    """A structured import failure with full context for the frontend."""

    code: str
    title: str
    message: str
    next_steps: list[str]
    stage: str
    severity: str
    recoverable_by_user: bool
    retryable: bool
    support_ref: str
    detected_format: str | None = None
    extra_context: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        # Remove empty optional fields
        if not d.get("detected_format"):
            d.pop("detected_format", None)
        if not d.get("extra_context"):
            d.pop("extra_context", None)
        return d

    @classmethod
    def from_code(
        cls,
        code: ImportErrorCode,
        *,
        support_ref: str | None = None,
        detected_format: str | None = None,
        message_override: str | None = None,
        extra_next_steps: list[str] | None = None,
        extra_context: dict[str, Any] | None = None,
    ) -> ImportFailure:
        """Create an ImportFailure from a catalog code with optional overrides."""
        defn = _CATALOG.get(code)
        if defn is None:
            defn = _ErrorDef(
                title="Import failed",
                message="An unexpected error occurred during import.",
                next_steps=["Try again or contact support"],
                stage="unknown",
                severity="blocking",
                recoverable_by_user=False,
                retryable=True,
            )

        steps = list(defn.next_steps)
        if extra_next_steps:
            steps.extend(extra_next_steps)

        return cls(
            code=code.value if isinstance(code, ImportErrorCode) else str(code),
            title=defn.title,
            message=message_override or defn.message,
            next_steps=steps,
            stage=defn.stage,
            severity=defn.severity,
            recoverable_by_user=defn.recoverable_by_user,
            retryable=defn.retryable,
            support_ref=support_ref or make_support_ref(),
            detected_format=detected_format,
            extra_context=extra_context or {},
        )


# ---------------------------------------------------------------------------
# Exception-to-ImportFailure mapper
# ---------------------------------------------------------------------------

def classify_import_error(
    exc: BaseException,
    *,
    file_path: str | None = None,
    detected_format: str | None = None,
) -> ImportFailure:
    """Map an exception from the adapter/pipeline layer to a structured ImportFailure.

    This is the bridge between the existing exception hierarchy
    (adapters.errors.*, pipeline_errors.*) and the user-facing error taxonomy.
    """
    from telemetry_tool.adapters.errors import (
        CorruptedFile,
        InsufficientData,
        MissingColumns,
        MissingDependency,
        ParseError,
        UnrecognizedFormat,
    )

    support_ref = make_support_ref()
    exc_msg = str(exc)

    # ── Adapter-layer errors ──────────────────────────────────────
    if isinstance(exc, MissingColumns):
        missing = getattr(exc, "missing", [])
        available = getattr(exc, "available", [])
        fmt = getattr(exc, "format_name", detected_format)

        # Determine which specific code to use
        missing_lower = [m.lower() for m in missing]
        if any("lat" in m or "lon" in m for m in missing_lower):
            code = ImportErrorCode.MISSING_GPS_LAT_LON
        elif any("time" in m for m in missing_lower):
            code = ImportErrorCode.MISSING_TIME_COLUMN
        elif any("speed" in m for m in missing_lower):
            code = ImportErrorCode.MISSING_SPEED_CHANNEL
        else:
            code = ImportErrorCode.INSUFFICIENT_CHANNEL_COVERAGE

        return ImportFailure.from_code(
            code,
            support_ref=support_ref,
            detected_format=fmt,
            message_override=f"Required columns are missing: {', '.join(missing)}",
            extra_context={"missing_columns": missing, "available_columns": available[:20]},
        )

    if isinstance(exc, CorruptedFile):
        return ImportFailure.from_code(
            ImportErrorCode.CORRUPTED_FILE,
            support_ref=support_ref,
            detected_format=getattr(exc, "format_name", detected_format),
        )

    if isinstance(exc, InsufficientData):
        return ImportFailure.from_code(
            ImportErrorCode.NO_DATA_ROWS,
            support_ref=support_ref,
            detected_format=getattr(exc, "format_name", detected_format),
            extra_context={
                "row_count": getattr(exc, "row_count", None),
                "minimum": getattr(exc, "minimum", None),
            },
        )

    if isinstance(exc, UnrecognizedFormat):
        return ImportFailure.from_code(
            ImportErrorCode.UNKNOWN_LOGGER_FORMAT,
            support_ref=support_ref,
            extra_context={"candidates": getattr(exc, "candidates", [])},
        )

    if isinstance(exc, MissingDependency):
        return ImportFailure.from_code(
            ImportErrorCode.FORMAT_DETECTED_BUT_NOT_ENABLED,
            support_ref=support_ref,
            detected_format=getattr(exc, "format_name", detected_format),
            message_override=f"Format '{getattr(exc, 'format_name', 'unknown')}' requires a library that is not available.",
        )

    if isinstance(exc, ParseError):
        return ImportFailure.from_code(
            ImportErrorCode.CORRUPTED_FILE,
            support_ref=support_ref,
            detected_format=getattr(exc, "format_name", detected_format),
            message_override=exc_msg,
        )

    # ── Pipeline-level errors ─────────────────────────────────────
    from telemetry_tool.pipeline_errors import (
        FatalError,
        InteractionRequired,
        TransientError,
    )

    if isinstance(exc, TransientError):
        return ImportFailure.from_code(
            ImportErrorCode.QUEUE_FAILURE,
            support_ref=support_ref,
        )

    if isinstance(exc, InteractionRequired):
        # Not really an error — pipeline wants user input
        return ImportFailure.from_code(
            ImportErrorCode.PIPELINE_INTERNAL_ERROR,
            support_ref=support_ref,
        )

    if isinstance(exc, FatalError):
        return ImportFailure.from_code(
            ImportErrorCode.PIPELINE_INTERNAL_ERROR,
            support_ref=support_ref,
            message_override=exc_msg if len(exc_msg) < 200 else exc_msg[:200],
        )

    # ── Generic fallbacks ─────────────────────────────────────────
    if isinstance(exc, (ConnectionError, TimeoutError)):
        return ImportFailure.from_code(
            ImportErrorCode.QUEUE_FAILURE,
            support_ref=support_ref,
        )

    if isinstance(exc, MemoryError):
        return ImportFailure.from_code(
            ImportErrorCode.FILE_TOO_LARGE,
            support_ref=support_ref,
            message_override="The file is too large to process with available memory.",
        )

    # Unknown error — internal
    return ImportFailure.from_code(
        ImportErrorCode.PIPELINE_INTERNAL_ERROR,
        support_ref=support_ref,
        extra_context={"exception_type": type(exc).__name__},
    )
