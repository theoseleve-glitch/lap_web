"""
Over/understeer event detection via 7-method fusion.

Each corner is analyzed by 7 independent detectors. Each outputs:
  - direction: -1 (oversteer) to +1 (understeer)
  - confidence: 0 to 1
  - zone: 'entry', 'mid', 'exit'

Events are fused per corner-zone via weighted voting.

Detectors:
  1. Apex timing     — min-speed position vs geometric apex
  2. Corner balance   — entry vs exit time split
  3. Speed recovery   — d(speed)/dt after apex
  4. Lat G build rate — d(a_lat)/dt at corner entry (jerk)
  5. Trail braking    — overlap of braking + turning
  6. GG shape         — combined G boundary asymmetry
  7. Path divergence  — multi-lap path comparison at same corner
"""
import sys, pathlib, warnings
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch
from scipy.signal import butter, filtfilt
from dataclasses import dataclass, field

warnings.filterwarnings("ignore", category=RuntimeWarning)

# -- Config ---------------------------------------------------------------
WHEELBASE    = 1.0
V_MIN        = 3.0
LPF_HZ       = 1.5
LPF_ORDER    = 2
CORNER_G_THR = 0.25   # min |lat G| to be considered "in a corner"
CORNER_MIN_S = 0.8    # min corner duration (seconds)
CORNER_GAP_S = 0.3    # merge corners closer than this
EVENT_MIN_S  = 0.3    # min event duration — shorter = noise

# -- Data structures -------------------------------------------------------
@dataclass
class Event:
    corner_id: int
    zone: str              # 'entry', 'mid', 'exit'
    direction: float       # -1=oversteer, +1=understeer
    confidence: float      # 0-1
    start_dist: float
    end_dist: float
    duration_s: float
    detectors: dict = field(default_factory=dict)  # name -> (direction, confidence)

    @property
    def label(self):
        if self.direction > 0.15:
            return "UNDERSTEER"
        elif self.direction < -0.15:
            return "OVERSTEER"
        return "NEUTRAL"

@dataclass
class Corner:
    idx: int
    start_i: int
    end_i: int
    apex_geo_i: int        # geometric apex (max curvature)
    apex_speed_i: int      # speed apex (min speed)
    peak_g: float
    events: list = field(default_factory=list)
    phases: dict = field(default_factory=dict)  # {zone: (start_i, end_i)}

# -- Load & prepare --------------------------------------------------------
csv_path = sys.argv[1] if len(sys.argv) > 1 else str(
    pathlib.Path(__file__).resolve().parents[1] / "data" / "raw" / "OK_R1.csv"
)

with open(csv_path, "r", encoding="utf-8-sig") as f:
    for i, line in enumerate(f):
        if line.strip().startswith("Time (s)"):
            header_row = i
            break
    else:
        raise ValueError("No header found")

df = pd.read_csv(csv_path, skiprows=header_row, low_memory=False)
df.columns = df.columns.str.strip()

time_s  = pd.to_numeric(df.iloc[:, 0], errors="coerce").values
speed   = pd.to_numeric(df.get("Speed (m/s) *calc", df.get("Speed (m/s)")), errors="coerce").values
lap_col = pd.to_numeric(df["Lap #"], errors="coerce").values
dist    = pd.to_numeric(df["Distance (m)"], errors="coerce").values
bearing = pd.to_numeric(df["Bearing (deg)"], errors="coerce").values
a_lat   = pd.to_numeric(df.get("Lateral acceleration (G) *calc"), errors="coerce").values
a_lon   = pd.to_numeric(df.get("Longitudinal acceleration (G) *calc"), errors="coerce").values
lat_deg = pd.to_numeric(df.get("Latitude (deg)"), errors="coerce").values
lon_deg = pd.to_numeric(df.get("Longitude (deg)"), errors="coerce").values

dt_med = np.nanmedian(np.diff(time_s))
fs = 1.0 / dt_med if dt_med > 0 else 25.0
nyq = fs / 2.0
b_lp, a_lp = butter(LPF_ORDER, min(LPF_HZ / nyq, 0.99), btype="low")

def filt(s):
    c = pd.Series(s).interpolate(limit_direction="both").values
    return filtfilt(b_lp, a_lp, c)

speed_f = filt(speed)
a_lat_f = filt(a_lat)
a_lon_f = filt(a_lon)
dt_arr  = np.diff(time_s, prepend=time_s[0])
dt_arr[dt_arr <= 0] = 1e-6

# GPS yaw rate & kinematic steering
db = np.diff(bearing, prepend=bearing[0])
db = (db + 180) % 360 - 180
yaw_dps = filt(db / dt_arr)
speed_safe = np.where(speed_f > V_MIN, speed_f, np.nan)
steer_kin = np.rad2deg(np.arctan(WHEELBASE * np.deg2rad(yaw_dps) / speed_safe))

# Curvature from GPS
dx = np.gradient(filt(lon_deg) * 111320 * np.cos(np.radians(np.nanmean(lat_deg))))
dy = np.gradient(filt(lat_deg) * 110540)
ddx = np.gradient(dx)
ddy = np.gradient(dy)
denom = (dx**2 + dy**2)**1.5 + 1e-12
curvature = np.abs(dx * ddy - dy * ddx) / denom

# Lateral G derivative (jerk)
a_lat_jerk = np.gradient(a_lat_f, time_s)
a_lat_jerk_f = filt(a_lat_jerk)

print(f"Loaded: {len(df)} rows, fs={fs:.0f} Hz")

# -- Find best lap ---------------------------------------------------------
valid_laps = pd.Series(lap_col).dropna()
valid_laps = valid_laps[valid_laps > 0].unique()
best_lap, best_time = None, np.inf
for ln in valid_laps:
    m = lap_col == ln
    t = time_s[m]
    if len(t) < 10:
        continue
    lt = t[-1] - t[0]
    if 10 < lt < best_time:
        best_time = lt
        best_lap = int(ln)

print(f"Best lap: #{best_lap} ({best_time:.2f}s)")
lap_mask = lap_col == best_lap

# Get all lap indices for multi-lap analysis (detector 7)
all_lap_nums = sorted([int(ln) for ln in valid_laps
                       if (lap_col == ln).sum() > 100 and 10 < (time_s[lap_col == ln][-1] - time_s[lap_col == ln][0]) < best_time * 1.5])

# -- Detect corners in best lap --------------------------------------------
idx = np.where(lap_mask)[0]
lap_a_lat = np.abs(a_lat_f[idx])

in_corner = lap_a_lat > CORNER_G_THR
# Find contiguous corner segments
changes = np.diff(in_corner.astype(int))
starts = np.where(changes == 1)[0] + 1
ends   = np.where(changes == -1)[0] + 1

if in_corner[0]:
    starts = np.concatenate([[0], starts])
if in_corner[-1]:
    ends = np.concatenate([ends, [len(idx) - 1]])

# Pair starts/ends, filter by duration, merge close ones
corners = []
min_samples = int(CORNER_MIN_S * fs)
gap_samples = int(CORNER_GAP_S * fs)

raw_corners = list(zip(starts, ends))

# Merge close corners
merged = []
for s, e in raw_corners:
    if merged and s - merged[-1][1] < gap_samples:
        merged[-1] = (merged[-1][0], e)
    else:
        merged.append((s, e))

for ci, (s, e) in enumerate(merged):
    if e - s < min_samples:
        continue

    si, ei = idx[s], idx[e]
    seg_curv = curvature[si:ei]
    seg_speed = speed_f[si:ei]
    seg_alat = np.abs(a_lat_f[si:ei])

    geo_apex_local = np.argmax(seg_curv)
    speed_apex_local = np.argmin(seg_speed)

    corners.append(Corner(
        idx=len(corners),
        start_i=si,
        end_i=ei,
        apex_geo_i=si + geo_apex_local,
        apex_speed_i=si + speed_apex_local,
        peak_g=np.max(seg_alat),
    ))

print(f"Detected {len(corners)} corners")

# -- DETECTOR FUNCTIONS ----------------------------------------------------

def det_apex_timing(c: Corner) -> tuple:
    """#1: Where is min-speed relative to max-curvature?
    Calibrated from 109 corners: median=-0.036, std=0.262.
    Neutral zone: [-0.05, +0.05]. Signal outside that is meaningful.
    Strongest detector: r=0.42 with peak G (more signal in hard corners).
    """
    geo_d  = dist[c.apex_geo_i]
    spd_d  = dist[c.apex_speed_i]
    corner_len = dist[c.end_i] - dist[c.start_i]
    if corner_len < 1:
        return 0.0, 0.0, "mid"

    offset = (spd_d - geo_d) / corner_len  # positive = late speed apex = understeer

    # Dead zone: offsets within [-0.05, +0.05] are noise (median is -0.036)
    dead_zone = 0.05
    if abs(offset) < dead_zone:
        return 0.0, 0.0, "mid"

    # Scale: std=0.26, so 1 std from neutral = strong signal
    direction = np.clip((offset - np.sign(offset) * dead_zone) / 0.20, -1, 1)

    # Confidence: higher in severe corners (r=0.42 with peak G)
    base_conf = min(abs(offset) / 0.30, 1.0)  # 30% offset = full confidence
    g_boost = min(c.peak_g / 0.8, 1.0)         # >0.8G = full boost
    confidence = base_conf * g_boost

    zone = "entry" if offset > dead_zone else ("exit" if offset < -dead_zone else "mid")
    return direction, confidence, zone


def det_corner_balance(c: Corner) -> tuple:
    """#2: Does entry or exit take more time?
    Calibrated: median=1.0, std=0.85. Neutral zone: [0.8, 1.2].
    No correlation with peak G (r=-0.12) = independent of severity. Good.
    """
    apex_i = c.apex_geo_i
    t_entry = time_s[apex_i] - time_s[c.start_i]
    t_exit  = time_s[c.end_i] - time_s[apex_i]

    if t_entry < 0.2 or t_exit < 0.2:
        return 0.0, 0.0, "mid"

    ratio = t_entry / t_exit  # >1 = entry-heavy = understeer

    # Dead zone: [0.8, 1.2] is balanced
    if 0.8 < ratio < 1.2:
        return 0.0, 0.0, "mid"

    # Scale: std=0.85, but most signal is in [0.5, 2.0]
    deviation = ratio - 1.0
    direction = np.clip(deviation / 0.8, -1, 1)

    # Confidence: based on how far from neutral, plus corner duration
    base_conf = min(abs(deviation) / 0.6, 1.0)
    duration_boost = min((t_entry + t_exit) / 3.0, 1.0)  # longer corners = more reliable
    confidence = base_conf * duration_boost

    zone = "entry" if direction > 0 else "exit"
    return direction, confidence, zone


def det_speed_recovery(c: Corner) -> tuple:
    """#3: How fast does speed recover after apex?
    Calibrated: median=0.091, std=0.138. Neutral: [0.05, 0.15].
    r=0.33 with peak G = moderate severity dependence.
    """
    apex_i = c.apex_speed_i
    exit_len = c.end_i - apex_i
    if exit_len < 10:
        return 0.0, 0.0, "exit"

    exit_seg = max(1, int(exit_len * 0.3))
    dt_exit = time_s[apex_i + exit_seg] - time_s[apex_i]
    if dt_exit < 0.05:
        return 0.0, 0.0, "exit"

    exit_accel = (speed_f[apex_i + exit_seg] - speed_f[apex_i]) / dt_exit
    norm_accel = exit_accel / (c.peak_g * 9.81 + 1e-6)

    # Neutral zone: [0.05, 0.15] (centered on median 0.091)
    neutral = 0.091
    if abs(norm_accel - neutral) < 0.04:
        return 0.0, 0.0, "exit"

    # Scale: std=0.138
    direction = np.clip((norm_accel - neutral) / 0.12, -1, 1)

    # Confidence: stronger signal at high G
    base_conf = min(abs(norm_accel - neutral) / 0.10, 1.0)
    confidence = base_conf * min(c.peak_g / 0.6, 1.0)
    return direction, confidence, "exit"


def det_lat_g_jerk(c: Corner) -> tuple:
    """#4: How sharp is the lateral G buildup at corner entry?
    Fixed: use a_lat_jerk directly (was using a_lat_jerk_f which doesn't exist).
    Measures d(lateral_G)/dt during the turn-in phase.
    """
    apex_i = c.apex_geo_i
    if apex_i - c.start_i < 10:
        return 0.0, 0.0, "entry"

    # Get lateral G in entry phase
    entry_alat = a_lat_f[c.start_i:apex_i]
    entry_time = time_s[c.start_i:apex_i]

    # Find the turn-in point: where |a_lat| first exceeds 0.1G
    abs_alat = np.abs(entry_alat)
    turn_in = np.where(abs_alat > 0.1)[0]
    if len(turn_in) < 5:
        return 0.0, 0.0, "entry"

    # Measure jerk from turn-in to peak lateral G
    turn_in_i = turn_in[0]
    peak_i = np.argmax(abs_alat)
    if peak_i <= turn_in_i + 3:
        return 0.0, 0.0, "entry"

    dt_turnin = entry_time[peak_i] - entry_time[turn_in_i]
    if dt_turnin < 0.05:
        return 0.0, 0.0, "entry"

    # Jerk = change in lateral G / time to build
    g_buildup = abs_alat[peak_i] - abs_alat[turn_in_i]
    jerk_rate = g_buildup / dt_turnin  # G/s

    # Normalise by corner severity
    norm_jerk = jerk_rate / (c.peak_g + 1e-6)  # G/s per G

    # Calibrated: median=0.35, std=0.20, range 0.13-0.73
    # High = sharp turn-in = oversteer tendency
    # Low = gradual = understeer tendency
    neutral = 0.35
    dead = 0.10  # wider dead zone to reduce false positives
    if abs(norm_jerk - neutral) < dead:
        return 0.0, 0.0, "entry"

    # Softer scaling to avoid saturation: use full std (0.20) not half
    direction = np.clip(-(norm_jerk - neutral) / 0.30, -1, 1)
    confidence = min(abs(norm_jerk - neutral) / 0.20, 1.0) * min(c.peak_g / 0.5, 1.0) * 0.8
    return direction, confidence, "entry"


def det_trail_braking(c: Corner) -> tuple:
    """#5: Brake-turn overlap, corrected for corner severity.
    Calibrated: median=0.537, bimodal. r=0.77 with peak G = highly confounded.
    Fix: normalise overlap by expected overlap for that G level.
    """
    seg = slice(c.start_i, c.apex_geo_i)
    seg_alon = a_lon_f[seg]
    seg_alat = np.abs(a_lat_f[seg])

    total_entry = len(seg_alon)
    if total_entry < 10:
        return 0.0, 0.0, "entry"

    # Only meaningful if driver actually brakes before this corner
    if (seg_alon < -0.15).sum() < 5:
        return 0.0, 0.0, "entry"  # no braking zone, can't assess

    braking = seg_alon < -0.1
    turning = seg_alat > 0.15
    overlap = braking & turning
    overlap_frac = overlap.sum() / total_entry

    # Expected overlap scales with corner G (r=0.77): regress out severity
    # Linear model from data: expected = 0.60 * peak_g + 0.05
    expected_overlap = 0.60 * c.peak_g + 0.05
    residual = overlap_frac - expected_overlap

    # Residual: positive = more overlap than expected = good front grip
    #           negative = less overlap = front-limited
    # Dead zone: residuals within [-0.15, +0.15] are within normal variation
    if abs(residual) < 0.15:
        return 0.0, 0.0, "entry"

    direction = np.clip(-residual / 0.25, -1, 1)
    base_conf = min(abs(residual) / 0.20, 1.0)
    confidence = base_conf * 0.5  # low weight — this metric is noisy
    return direction, confidence, "entry"


def det_gg_shape(c: Corner) -> tuple:
    """#6: GG diagram asymmetry between entry and exit quadrants.
    Calibrated: median=1.074, std=0.175. Neutral: [0.95, 1.15].
    r=0.13 with peak G = low correlation with severity. Good.
    """
    seg = slice(c.start_i, c.end_i)
    alon = a_lon_f[seg]
    alat = np.abs(a_lat_f[seg])

    entry_quad = (alon < -0.05) & (alat > 0.15)
    exit_quad  = (alon > 0.05) & (alat > 0.15)

    if entry_quad.sum() < 3 or exit_quad.sum() < 3:
        return 0.0, 0.0, "mid"

    combined_entry = np.sqrt(alon[entry_quad]**2 + alat[entry_quad]**2)
    combined_exit  = np.sqrt(alon[exit_quad]**2 + alat[exit_quad]**2)

    mean_entry = np.mean(combined_entry)
    mean_exit  = np.mean(combined_exit)

    ratio = mean_exit / (mean_entry + 1e-6)

    # Calibrated: median=1.074, neutral=[0.95, 1.15]
    neutral = 1.074
    if abs(ratio - neutral) < 0.08:
        return 0.0, 0.0, "mid"

    # Scale by std=0.175
    direction = np.clip((ratio - neutral) / 0.15, -1, 1)
    # Confidence: more data points = more reliable
    n_points = min(entry_quad.sum(), exit_quad.sum())
    confidence = min(abs(ratio - neutral) / 0.12, 1.0) * min(n_points / 20, 1.0)
    return direction, confidence, "mid"


def det_path_divergence(c: Corner, all_laps: list) -> tuple:
    """#7: Cross-lap speed-curvature regression per corner.
    Improvement: use full corner window (not single point), fit regression,
    use slope as direction and R-squared as confidence.
    """
    if len(all_laps) < 3:
        return 0.0, 0.0, "mid"

    lap_start_d = dist[np.where(lap_mask)[0][0]]
    lap_end_d   = dist[np.where(lap_mask)[0][-1]]
    lap_len = lap_end_d - lap_start_d
    if lap_len < 10:
        return 0.0, 0.0, "mid"

    # Corner position as fraction of lap
    corner_start_frac = (dist[c.start_i] - lap_start_d) / lap_len
    corner_end_frac   = (dist[c.end_i] - lap_start_d) / lap_len

    # For each lap, collect mean speed and mean curvature through the whole corner
    speeds_corner = []
    curvatures_corner = []

    for ln in all_laps:
        lm = lap_col == ln
        li = np.where(lm)[0]
        if len(li) < 50:
            continue
        ld = dist[li]
        ll = ld[-1] - ld[0]
        if ll < 10:
            continue

        # Find corner boundaries in this lap
        cs = ld[0] + corner_start_frac * ll
        ce = ld[0] + corner_end_frac * ll
        in_corner = (ld >= cs) & (ld <= ce)
        if in_corner.sum() < 10:
            continue

        ci = li[in_corner]
        speeds_corner.append(np.mean(speed_f[ci]))
        curvatures_corner.append(np.mean(curvature[ci]))

    if len(speeds_corner) < 4:
        return 0.0, 0.0, "mid"

    sv = np.array(speeds_corner)
    cv = np.array(curvatures_corner)
    valid = ~(np.isnan(sv) | np.isnan(cv))
    if valid.sum() < 4:
        return 0.0, 0.0, "mid"

    # Linear regression: curvature = slope * speed + intercept
    coeffs = np.polyfit(sv[valid], cv[valid], 1)
    slope = coeffs[0]

    # R-squared
    predicted = np.polyval(coeffs, sv[valid])
    ss_res = np.sum((cv[valid] - predicted)**2)
    ss_tot = np.sum((cv[valid] - np.mean(cv[valid]))**2)
    r2 = 1 - ss_res / (ss_tot + 1e-12)

    # Negative slope = faster laps have lower curvature = wider line = understeer
    # Positive slope = faster laps have higher curvature = tighter = oversteer
    direction = np.clip(-slope * 500, -1, 1)  # scale for typical slope magnitude
    confidence = max(r2, 0) * min(len(speeds_corner) / 6, 1.0)
    return direction, confidence, "mid"


def det_yaw_residual(c: Corner) -> tuple:
    """#8: Yaw rate TREND within the corner (entry vs exit).

    The absolute yaw ratio (actual/expected) has a systematic GPS offset (~1.6x)
    that makes absolute thresholds unreliable. Instead, compare the yaw ratio
    in the ENTRY half vs the EXIT half of the same corner.

    If entry ratio >> exit ratio: car rotation slows through the corner = understeer
    If exit ratio >> entry ratio: car rotation accelerates = oversteer

    This is self-normalizing — the GPS offset cancels in the comparison.
    """
    seg = slice(c.start_i, c.end_i)
    seg_speed = speed_f[seg]
    seg_curv  = curvature[seg]
    seg_yaw   = np.abs(np.deg2rad(yaw_dps[seg]))

    expected_yaw = seg_curv * seg_speed
    valid = (seg_speed > V_MIN) & (expected_yaw > 1e-4)
    if valid.sum() < 20:
        return 0.0, 0.0, "mid"

    ratio = np.full(len(seg_speed), np.nan)
    ratio[valid] = seg_yaw[valid] / expected_yaw[valid]

    # Split into entry/exit halves
    n = len(ratio)
    entry_ratio = ratio[:n//2]
    exit_ratio  = ratio[n//2:]

    entry_med = np.nanmedian(entry_ratio)
    exit_med  = np.nanmedian(exit_ratio)

    if np.isnan(entry_med) or np.isnan(exit_med):
        return 0.0, 0.0, "mid"

    # Relative change: (exit - entry) / mean
    mean_ratio = (entry_med + exit_med) / 2
    if mean_ratio < 0.1:
        return 0.0, 0.0, "mid"

    relative_change = (exit_med - entry_med) / mean_ratio

    # Positive change = yaw rate increases through corner = oversteer
    # Negative change = yaw rate decreases = understeer
    # Dead zone: within 10% change = neutral
    if abs(relative_change) < 0.10:
        return 0.0, 0.0, "mid"

    direction = np.clip(-relative_change / 0.30, -1, 1)

    # Confidence: higher when the trend is consistent and corner is severe
    entry_std = np.nanstd(entry_ratio) / (entry_med + 1e-6)
    exit_std  = np.nanstd(exit_ratio) / (exit_med + 1e-6)
    consistency = max(0, 1.0 - (entry_std + exit_std) / 2)
    base_conf = min(abs(relative_change) / 0.25, 1.0)
    confidence = base_conf * consistency * min(c.peak_g / 0.5, 1.0)

    zone = "entry" if relative_change < -0.05 else ("exit" if relative_change > 0.05 else "mid")
    return direction, confidence, zone


def det_heading_accel(c: Corner) -> tuple:
    """#9: Heading acceleration d2(heading)/ds2.
    Rotation stall (d2h near zero mid-corner) = understeer.
    Rotation spike (sudden d2h) = snap oversteer.
    """
    seg = slice(c.start_i, c.end_i)
    seg_bear = bearing[seg]
    seg_dist = dist[seg]
    seg_speed = speed_f[seg]

    n = len(seg_bear)
    if n < 20:
        return 0.0, 0.0, "mid"

    # d(heading)/d(distance) = curvature with sign
    ds = np.diff(seg_dist)
    ds[ds == 0] = 1e-6
    dh = np.diff(seg_bear)
    dh = (dh + 180) % 360 - 180  # unwrap
    dh_ds = dh / ds  # deg/m

    # d2(heading)/d(distance)2 = heading acceleration
    d2h_ds2 = np.diff(dh_ds) / ds[:-1]

    if len(d2h_ds2) < 10:
        return 0.0, 0.0, "mid"

    # Filter — smaller window than before (5% of corner, not 30% of fs)
    win = max(5, min(int(0.05 * len(d2h_ds2)), int(0.1 * fs)))
    d2h_smooth = pd.Series(d2h_ds2).rolling(win, center=True, min_periods=1).mean().values

    mid_pt = len(d2h_smooth) // 2
    exit_d2h = d2h_smooth[mid_pt:]
    sixth = max(1, len(d2h_smooth) // 6)
    mid_region = d2h_smooth[max(0, mid_pt - sixth) : mid_pt + sixth]

    if len(mid_region) < 3:
        return 0.0, 0.0, "mid"

    overall = np.nanmean(np.abs(d2h_smooth)) + 1e-12
    mid_norm = np.nanmean(np.abs(mid_region)) / overall
    exit_norm = np.nanmean(np.abs(exit_d2h)) / overall if len(exit_d2h) > 3 else 1.0

    # Calibrated from 109 corners:
    #   mid_norm:  median=1.27, IQR=[0.72, 1.59]
    #   exit_norm: median=1.05, IQR=[0.68, 1.27]
    mid_neutral  = 1.27
    exit_neutral = 1.05

    # Low mid = rotation stall = understeer
    if mid_norm < mid_neutral - 0.25:
        deviation = mid_neutral - mid_norm
        direction = np.clip(deviation / 0.50, 0, 1)
        confidence = min(deviation / 0.40, 1.0) * min(c.peak_g / 0.5, 1.0) * 0.7
        return direction, confidence, "mid"

    # High exit = instability = oversteer
    if exit_norm > exit_neutral + 0.20:
        deviation = exit_norm - exit_neutral
        direction = np.clip(-deviation / 0.50, -1, 0)
        confidence = min(deviation / 0.40, 1.0) * min(c.peak_g / 0.5, 1.0) * 0.7
        return direction, confidence, "exit"

    return 0.0, 0.0, "mid"


# -- Run all detectors per corner ------------------------------------------
# -- Phase segmentation (improvement #4) -----------------------------------
# Split corners by d(lateral_G)/dt crossing zero instead of fixed apex split.
# Phases: turn-in (G building), mid (G steady), exit (power-on).

def segment_corner_phases(c: Corner) -> dict:
    """Return phase boundaries: {phase: (start_i, end_i)}"""
    seg_alat = np.abs(a_lat_f[c.start_i:c.end_i])
    seg_alon = a_lon_f[c.start_i:c.end_i]
    n = len(seg_alat)
    if n < 20:
        # Fallback to apex-based split
        return {
            "entry": (c.start_i, c.apex_geo_i),
            "mid":   (c.apex_geo_i, c.apex_geo_i),
            "exit":  (c.apex_geo_i, c.end_i),
        }

    # d(lat_G)/dt
    d_alat = np.gradient(seg_alat)
    # Smooth to avoid noise-triggered phase changes
    kernel = max(1, int(0.2 * fs))
    d_alat_smooth = pd.Series(d_alat).rolling(kernel, center=True, min_periods=1).mean().values

    # Turn-in ends when d(lat_G)/dt drops below 10% of its peak
    peak_rate = np.max(np.abs(d_alat_smooth[:n//2])) if n > 4 else 1e-6
    threshold = peak_rate * 0.10

    # Find where G buildup ends (turn-in → mid transition)
    turnin_end = n // 3  # default
    for i in range(n // 6, n * 2 // 3):
        if abs(d_alat_smooth[i]) < threshold and seg_alat[i] > 0.5 * c.peak_g:
            turnin_end = i
            break

    # Exit starts when longitudinal accel crosses zero (net positive)
    exit_start = n * 2 // 3  # default
    for i in range(n // 3, n):
        if seg_alon[i] > 0.02:
            exit_start = i
            break

    # Ensure ordering
    turnin_end = min(turnin_end, exit_start)

    return {
        "entry": (c.start_i, c.start_i + turnin_end),
        "mid":   (c.start_i + turnin_end, c.start_i + exit_start),
        "exit":  (c.start_i + exit_start, c.end_i),
    }

# Store phase boundaries per corner
for c in corners:
    c.phases = segment_corner_phases(c)

# Weights calibrated from distribution analysis + research:
# - Yaw Residual: strongest GPS-only signal (ported from handling_detector.py)
# - Apex Timing: strong (r=0.42 with G), independent
# - Corner Balance: uncorrelated with G (r=-0.12), reliable
# - Heading Accel: new, detects rotation stalls and snap events
# - Speed Recovery: moderate (r=0.33 with G)
# - GG Shape: low G correlation (r=0.13), reliable
# - Lat G Jerk: fixed, moderate
# - Trail Braking: severity-corrected
# - Path Divergence: cross-lap regression (improved)
DETECTORS = [
    ("Yaw Residual",     det_yaw_residual,      1.0),
    ("Apex Timing",      det_apex_timing,        1.0),
    ("Corner Balance",   det_corner_balance,     0.9),
    ("Heading Accel",    det_heading_accel,       0.9),
    ("Speed Recovery",   det_speed_recovery,     0.8),
    ("GG Shape",         det_gg_shape,           0.8),
    ("Lat G Jerk",       det_lat_g_jerk,         0.7),
    ("Trail Braking",    det_trail_braking,      0.4),
    ("Path Divergence",  lambda c: det_path_divergence(c, all_lap_nums), 0.5),
]

all_events = []

for c in corners:
    zone_votes = {}  # zone -> list of (direction, confidence, weight, name)

    for det_name, det_fn, weight in DETECTORS:
        direction, confidence, zone = det_fn(c)
        if confidence < 0.05:
            continue
        if zone not in zone_votes:
            zone_votes[zone] = []
        zone_votes[zone].append((direction, confidence * weight, det_name))

    # Fuse votes per zone — FIXED: divide by voters, not total detectors
    for zone, votes in zone_votes.items():
        if not votes:
            continue

        n_voters = len(votes)
        total_weight = sum(conf for _, conf, _ in votes)
        if total_weight < 0.1:
            continue

        fused_dir = sum(d * co for d, co, _ in votes) / total_weight

        # Agreement: how much the voters agree in direction
        directions = [d for d, _, _ in votes]
        if n_voters > 1:
            agreement = 1.0 - np.std(directions)  # low std = high agreement
        else:
            agreement = 0.5

        # FIXED: divide by n_voters, not len(DETECTORS)
        # More voters with agreement = higher confidence
        voter_coverage = n_voters / len(DETECTORS)
        fused_conf = min(total_weight / n_voters, 1.0) * max(agreement, 0.1) * (1.0 + voter_coverage)

        # Penalty: single-detector events get halved confidence (could be noise)
        if n_voters == 1:
            fused_conf *= 0.5

        fused_conf = min(fused_conf, 1.0)

        # Use phase-based boundaries instead of fixed apex split
        if zone in c.phases:
            start_i, end_i = c.phases[zone]
        elif zone == "entry":
            start_i, end_i = c.start_i, c.apex_geo_i
        elif zone == "exit":
            start_i, end_i = c.apex_geo_i, c.end_i
        else:
            start_i, end_i = c.start_i, c.end_i

        if end_i <= start_i:
            continue

        duration = time_s[end_i] - time_s[start_i]

        if duration < EVENT_MIN_S:
            continue  # too short to be a real handling event

        if abs(fused_dir) > 0.1 and fused_conf > 0.08:
            ev = Event(
                corner_id=c.idx,
                zone=zone,
                direction=fused_dir,
                confidence=fused_conf,
                start_dist=dist[start_i],
                end_dist=dist[end_i],
                duration_s=duration,
                detectors={name: (d, co) for d, co, name in votes},
            )
            c.events.append(ev)
            all_events.append(ev)

# -- Cross-lap consistency boost -------------------------------------------
# Run detection on OTHER laps and see if the same corners show the same tendency.
# If they do, boost confidence. If they don't, reduce it.
if len(all_lap_nums) >= 3:
    # For each corner in best lap, find matching corners in other laps
    lap_d0_best = dist[np.where(lap_mask)[0][0]]
    lap_len_best = dist[np.where(lap_mask)[0][-1]] - lap_d0_best

    for ev in all_events:
        corner_frac = (ev.start_dist - lap_d0_best) / (lap_len_best + 1e-6)
        consistent_count = 0
        total_laps_checked = 0

        for other_ln in all_lap_nums:
            if other_ln == best_lap:
                continue
            om = lap_col == other_ln
            oi = np.where(om)[0]
            if len(oi) < 50:
                continue
            od = dist[oi]
            ol = od[-1] - od[0]
            if ol < 10:
                continue

            # Find the equivalent position in this lap
            target_d = od[0] + corner_frac * ol
            ci = np.argmin(np.abs(od - target_d))
            ai = oi[ci]

            # Check handling tendency at this position (simple: check lat G jerk sign)
            win = max(10, int(1.0 * fs))
            ws = max(oi[0], ai - win)
            we = min(oi[-1], ai + win)

            seg_alat = a_lat_f[ws:we]
            if len(seg_alat) < 10:
                continue

            # Quick proxy: is the speed trace rising or falling after this point?
            # Falling = losing time = handling issue
            mid = len(seg_alat) // 2
            first_half_g = np.mean(np.abs(seg_alat[:mid]))
            second_half_g = np.mean(np.abs(seg_alat[mid:]))

            total_laps_checked += 1
            # Same tendency? Entry understeer = more G first half; exit oversteer = more G second half
            if ev.direction > 0 and first_half_g > second_half_g * 1.1:
                consistent_count += 1
            elif ev.direction < 0 and second_half_g > first_half_g * 1.1:
                consistent_count += 1

        if total_laps_checked >= 2:
            consistency_ratio = consistent_count / total_laps_checked
            # Boost if consistent (>60%), penalize if inconsistent (<30%)
            if consistency_ratio > 0.6:
                boost = 1.0 + 0.3 * consistency_ratio  # up to +30%
                ev.confidence = min(ev.confidence * boost, 1.0)
            elif consistency_ratio < 0.3:
                ev.confidence *= 0.7  # reduce by 30%

# -- Print results ---------------------------------------------------------
lap_d0 = dist[np.where(lap_mask)[0][0]]

print(f"\n{'='*80}")
print(f" HANDLING BALANCE ANALYSIS -- Lap #{best_lap} ({best_time:.2f}s)")
print(f" {len(all_events)} events detected across {len(corners)} corners")
print(f"{'='*80}\n")

for c in corners:
    d_start = dist[c.start_i] - lap_d0
    d_end   = dist[c.end_i] - lap_d0
    print(f"Corner {c.idx+1}  [{d_start:.0f}m - {d_end:.0f}m]  peak {c.peak_g:.2f}G")

    if not c.events:
        print(f"  >> NEUTRAL (no significant events)")
    for ev in c.events:
        bar_len = int(abs(ev.direction) * 10)
        bar = (">" * bar_len if ev.direction > 0 else "<" * bar_len)
        det_strs = [f"{n}({d:+.2f})" for n, (d, _) in ev.detectors.items()]
        print(f"  >> {ev.label:10s} [{ev.zone:5s}]  "
              f"dir={ev.direction:+.2f}  conf={ev.confidence:.0%}  "
              f"dur={ev.duration_s:.2f}s  "
              f"[{ev.start_dist - lap_d0:.0f}-{ev.end_dist - lap_d0:.0f}m]")
        print(f"     detectors: {', '.join(det_strs)}")
    print()

# -- Summary stats ---------------------------------------------------------
us_events = [e for e in all_events if e.direction > 0.15]
os_events = [e for e in all_events if e.direction < -0.15]
print(f"Summary:")
print(f"  Understeer events: {len(us_events)}  (total {sum(e.duration_s for e in us_events):.1f}s)")
print(f"  Oversteer events:  {len(os_events)}  (total {sum(e.duration_s for e in os_events):.1f}s)")
avg_conf = np.mean([e.confidence for e in all_events]) if all_events else 0
print(f"  Average confidence: {avg_conf:.0%}")

# Overall tendency
if all_events:
    overall = np.mean([e.direction * e.confidence for e in all_events])
    if overall > 0.1:
        print(f"  Overall tendency: UNDERSTEER ({overall:+.2f})")
    elif overall < -0.1:
        print(f"  Overall tendency: OVERSTEER ({overall:+.2f})")
    else:
        print(f"  Overall tendency: BALANCED ({overall:+.2f})")

# -- Plot ------------------------------------------------------------------
fig, axes = plt.subplots(4, 1, figsize=(16, 11), sharex=True,
                         gridspec_kw={"height_ratios": [2.5, 1.5, 1.5, 1.5]})
fig.patch.set_facecolor("#0a0a0a")

for ax in axes:
    ax.set_facecolor("#141414")
    ax.tick_params(colors="#949494", labelsize=8)
    ax.spines["bottom"].set_color("#333")
    ax.spines["left"].set_color("#333")
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)

li = np.where(lap_mask)[0]
ld = dist[li] - lap_d0

# Panel 1: Steering angle + events
ax1 = axes[0]
ax1.plot(ld, steer_kin[li], color="#F0EDE5", linewidth=0.8, label="Steering angle")
ax1.axhline(0, color="#949494", linewidth=0.4, linestyle="--")

for ev in all_events:
    sd = ev.start_dist - lap_d0
    ed = ev.end_dist - lap_d0
    if ev.direction > 0.15:
        color = "#FF2A2A"
        label_txt = "US"
    elif ev.direction < -0.15:
        color = "#8B5CF6"
        label_txt = "OS"
    else:
        continue
    alpha = 0.15 + 0.35 * ev.confidence
    ax1.axvspan(sd, ed, alpha=alpha, color=color, zorder=0)
    mid = (sd + ed) / 2
    ax1.text(mid, ax1.get_ylim()[1] if ax1.get_ylim()[1] != 0 else 15, label_txt,
             ha="center", va="top", fontsize=7, color=color, fontweight="bold")

ax1.set_ylabel("Steering (deg)", color="#F0EDE5", fontsize=10)
ax1.set_title(
    f"Handling Balance Analysis -- Lap #{best_lap} ({best_time:.2f}s) -- "
    f"{len(us_events)} understeer / {len(os_events)} oversteer events",
    color="#F0EDE5", fontsize=12, pad=10
)

# Legend patches
from matplotlib.patches import Patch
ax1.legend(handles=[
    Patch(facecolor="#FF2A2A", alpha=0.4, label=f"Understeer ({len(us_events)})"),
    Patch(facecolor="#8B5CF6", alpha=0.4, label=f"Oversteer ({len(os_events)})"),
], loc="upper right", facecolor="#1a1a1a", edgecolor="#333", labelcolor="#F0EDE5", fontsize=8)

# Panel 2: Fused direction + confidence per sample
ax2 = axes[1]
event_trace = np.zeros(len(li))
conf_trace  = np.zeros(len(li))
for ev in all_events:
    em = (dist[li] >= ev.start_dist) & (dist[li] <= ev.end_dist)
    event_trace[em] = ev.direction
    conf_trace[em] = ev.confidence

ax2.fill_between(ld, event_trace, 0, where=event_trace > 0.15, color="#FF2A2A", alpha=0.5)
ax2.fill_between(ld, event_trace, 0, where=event_trace < -0.15, color="#8B5CF6", alpha=0.5)
ax2.plot(ld, event_trace, color="#F0EDE5", linewidth=0.5)
ax2.axhline(0, color="#949494", linewidth=0.4, linestyle="--")
ax2.set_ylabel("Over/Under", color="#F0EDE5", fontsize=10)
ax2.set_ylim(-1.2, 1.2)

# Confidence as thin line
ax2t = ax2.twinx()
ax2t.plot(ld, conf_trace, color="#C9A84C", linewidth=0.5, alpha=0.6)
ax2t.set_ylabel("Confidence", color="#C9A84C", fontsize=8)
ax2t.set_ylim(0, 1.5)
ax2t.tick_params(colors="#C9A84C", labelsize=7)
ax2t.spines["right"].set_color("#333")
ax2t.spines["top"].set_visible(False)

# Panel 3: Speed
ax3 = axes[2]
ax3.plot(ld, speed_f[li] * 3.6, color="#22C55E", linewidth=0.8)
ax3.set_ylabel("Speed (km/h)", color="#F0EDE5", fontsize=10)

# Panel 4: Lateral G
ax4 = axes[3]
ax4.plot(ld, a_lat_f[li], color="#C9A84C", linewidth=0.8)
ax4.axhline(CORNER_G_THR, color="#949494", linewidth=0.3, linestyle=":")
ax4.axhline(-CORNER_G_THR, color="#949494", linewidth=0.3, linestyle=":")
ax4.set_ylabel("Lat G", color="#F0EDE5", fontsize=10)
ax4.set_xlabel("Distance (m)", color="#F0EDE5", fontsize=11)

# Mark corners
for c in corners:
    for ax in axes:
        ax.axvline(dist[c.start_i] - lap_d0, color="#949494", linewidth=0.3, alpha=0.3)
        ax.axvline(dist[c.end_i] - lap_d0, color="#949494", linewidth=0.3, alpha=0.3)
    ax4.text(dist[c.apex_geo_i] - lap_d0, ax4.get_ylim()[0],
             f"C{c.idx+1}", color="#949494", fontsize=7, ha="center", va="bottom")

plt.tight_layout()
out_path = str(pathlib.Path(__file__).resolve().parents[1] / "artifacts" / "handling_balance.png")
plt.savefig(out_path, dpi=150, facecolor=fig.get_facecolor())
plt.close()
print(f"\nSaved to {out_path}")
