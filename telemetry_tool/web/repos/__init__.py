"""Repository package — re-exports all public functions for backward compatibility.

Callers can continue to use ``from web.models import X`` or switch to
``from web.repos import X`` or ``from web.repos.session_repo import X``.
"""

# ── helpers ──────────────────────────────────────────────────────
from web.repos._helpers import (  # noqa: F401
    _safe_float,
    _json_dumps,
    _np_to_json,
    _parse_json_or_list,
)

# ── session ──────────────────────────────────────────────────────
from web.repos.session_repo import (  # noqa: F401
    upsert_session,
    get_sessions,
    count_sessions_filtered,
    get_session_by_id,
    update_session_field,
    count_sessions,
    get_dashboard_stats,
    soft_delete_session,
    restore_session,
)

# ── lap ──────────────────────────────────────────────────────────
from web.repos.lap_repo import (  # noqa: F401
    insert_laps,
    revalidate_session_laps,
    get_laps_for_session,
    get_gps_lap_numbers,
)

# ── driver ───────────────────────────────────────────────────────
from web.repos.driver_repo import (  # noqa: F401
    upsert_driver,
    _get_all_drivers_simple,
    upsert_driver_profile,
    get_driver_profile,
    update_driver_profile_field,
    insert_driver_progression,
    get_driver_progression,
    insert_driving_style_features,
    get_driving_style,
    get_driver_style_history,
    get_all_drivers,
    delete_driver_cascade,
    compute_best_ever_relative,
)

# ── track ────────────────────────────────────────────────────────
from web.repos.track_repo import (  # noqa: F401
    upsert_track,
    get_all_tracks,
    rename_track,
    _update_tracks_json,
    merge_duplicate_tracks,
    get_track_by_id,
    sync_tracks_from_json,
    upsert_track_record,
    delete_track_record,
    get_track_records,
    update_track_start_finish,
    reset_track_start_finish,
    get_track_sectors,
    upsert_track_sector,
    delete_track_sector,
    delete_track_cascade,
    create_track_from_predefined,
    auto_set_track_reference,
)

# ── gps / channels ──────────────────────────────────────────────
from web.repos.gps_repo import (  # noqa: F401
    insert_gps_traces,
    get_gps_trace,
    get_channel_data,
    get_channel_availability,
)

# ── scores / corners ────────────────────────────────────────────
from web.repos.score_repo import (  # noqa: F401
    insert_score_details,
    get_score_details,
    insert_corner_metrics,
    get_corner_metrics_for_session,
    get_corner_metrics_for_lap,
    get_corner_metrics_summary,
)

# ── theoretical / reference ─────────────────────────────────────
from web.repos.theoretical_repo import (  # noqa: F401
    insert_theoretical_data,
    get_theoretical_data,
    insert_reference_line,
    get_reference_line,
)

# ── conditions ──────────────────────────────────────────────────
from web.repos.condition_repo import (  # noqa: F401
    insert_condition_phases,
    get_condition_phases,
    insert_condition_marker,
    insert_condition_markers,
    get_condition_markers,
)

# ── weekends ────────────────────────────────────────────────────
from web.repos.weekend_repo import (  # noqa: F401
    create_weekend,
    update_weekend,
    delete_weekend,
    get_all_weekends,
    get_weekend_by_id,
    add_session_to_weekend,
    remove_session_from_weekend,
    get_weekend_sessions,
    swap_weekend_session_order,
    reorder_weekend_sessions,
)

# ── karts ────────────────────────────────────────────────────────
from web.repos.kart_repo import (  # noqa: F401
    create_kart,
    get_kart_by_id,
    get_all_karts,
    update_kart,
    delete_kart,
    get_predefined_karts_grouped,
    link_session_kart,
)

# ── analysis ─────────────────────────────────────────────────────
from web.repos.analysis_repo import (  # noqa: F401
    insert_stint_analysis,
    get_stint_analysis,
    get_analysis_json,
    insert_analysis_json,
)

# ── session sectors ──────────────────────────────────────────────
from web.repos.sector_repo import (  # noqa: F401
    get_session_sectors,
    upsert_session_sector,
    delete_session_sector,
    reindex_session_sectors,
)
