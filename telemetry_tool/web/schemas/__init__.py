"""Pydantic v2 request/response schemas — barrel exports.

Import from here for convenience::

    from web.schemas import StrictSchema, LoginSchema, PaginationParams
"""

try:
    from web.schemas.common import LenientSchema, PaginationParams, StrictSchema  # noqa: F401

    from web.schemas.auth import (  # noqa: F401
        LoginSchema,
        RegisterSchema,
        RefreshSchema,
        VerifyEmailSchema,
    )

    from web.schemas.account import (  # noqa: F401
        ProfileUpdateSchema,
        ExportRequestSchema,
    )

    from web.schemas.sessions import SessionListParams  # noqa: F401

    from web.schemas.teams import CreateTeamSchema, InviteMemberSchema  # noqa: F401

    from web.schemas.tracks import TrackListParams  # noqa: F401

    from web.schemas.batch import BatchReanalyzeSchema  # noqa: F401

    from web.schemas.security import (  # noqa: F401
        PasswordChangeSchema,
        ForgotPasswordSchema,
        ResetPasswordSchema,
    )
except ImportError:
    # Barrel imports require telemetry_tool/ on sys.path (web.schemas.* resolution).
    # When this package is traversed as telemetry_tool.web.schemas.* without that
    # path entry (e.g. running _scripts modules directly), the barrel is unavailable
    # but the sub-packages (contracts, etc.) remain fully functional.
    pass
