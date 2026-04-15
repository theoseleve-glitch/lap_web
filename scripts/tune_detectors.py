"""
Diagnostic tool: run each of the 7 detectors in isolation across ALL corners
of ALL laps in a session, print raw values BEFORE scaling, and plot histograms.

This lets us see the actual signal distributions and calibrate the scaling.
"""
import sys, pathlib, warnings
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
from scipy.signal import butter, filtfilt

warnings.filterwarnings("ignore", category=RuntimeWarning)

# -- Config ---------------------------------------------------------------
WHEELBASE    = 1.0
V_MIN        = 3.0
LPF_HZ       = 1.5
LPF_ORDER    = 2
CORNER_G_THR = 0.25
CORNER_MIN_S = 0.8
CORNER_GAP_S = 0.3

# -- Load ------------------------------------------------------------------
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
b_lp, a_lp_c = butter(LPF_ORDER, min(LPF_HZ / nyq, 0.99), btype="low")

def filt(s):
    c = pd.Series(s).interpolate(limit_direction="both").values
    return filtfilt(b_lp, a_lp_c, c)

speed_f = filt(speed)
a_lat_f = filt(a_lat)
a_lon_f = filt(a_lon)
dt_arr  = np.diff(time_s, prepend=time_s[0])
dt_arr[dt_arr <= 0] = 1e-6

db = np.diff(bearing, prepend=bearing[0])
db = (db + 180) % 360 - 180
yaw_dps = filt(db / dt_arr)

dx = np.gradient(filt(lon_deg) * 111320 * np.cos(np.radians(np.nanmean(lat_deg))))
dy = np.gradient(filt(lat_deg) * 110540)
ddx = np.gradient(dx)
ddy = np.gradient(dy)
denom = (dx**2 + dy**2)**1.5 + 1e-12
curvature = np.abs(dx * ddy - dy * ddx) / denom

a_lat_jerk = filt(np.gradient(a_lat_f, time_s))

# -- Get all valid laps ----------------------------------------------------
valid_laps = pd.Series(lap_col).dropna()
valid_laps = valid_laps[valid_laps > 0].unique()
lap_times = {}
for ln in valid_laps:
    m = lap_col == ln
    t = time_s[m]
    if len(t) < 50:
        continue
    lt = t[-1] - t[0]
    if 10 < lt < 300:
        lap_times[int(ln)] = lt

best_lap = min(lap_times, key=lap_times.get) if lap_times else None
print(f"Loaded: {len(df)} rows, {len(lap_times)} valid laps, best=#{best_lap} ({lap_times.get(best_lap, 0):.2f}s)")

# -- Detect corners across ALL laps ----------------------------------------
all_corners = []  # (lap_num, start_i, end_i, apex_geo_i, apex_speed_i, peak_g)

for ln in sorted(lap_times.keys()):
    idx = np.where(lap_col == ln)[0]
    lap_alat = np.abs(a_lat_f[idx])

    in_corner = lap_alat > CORNER_G_THR
    changes = np.diff(in_corner.astype(int))
    starts = np.where(changes == 1)[0] + 1
    ends = np.where(changes == -1)[0] + 1

    if in_corner[0]:
        starts = np.concatenate([[0], starts])
    if in_corner[-1]:
        ends = np.concatenate([ends, [len(idx) - 1]])

    min_samples = int(CORNER_MIN_S * fs)
    gap_samples = int(CORNER_GAP_S * fs)

    raw = list(zip(starts, ends))
    merged = []
    for s, e in raw:
        if merged and s - merged[-1][1] < gap_samples:
            merged[-1] = (merged[-1][0], e)
        else:
            merged.append((s, e))

    for s, e in merged:
        if e - s < min_samples:
            continue
        si, ei = idx[s], idx[e]
        seg_curv = curvature[si:ei]
        seg_speed = speed_f[si:ei]
        seg_alat = np.abs(a_lat_f[si:ei])

        geo_apex = si + np.argmax(seg_curv)
        speed_apex = si + np.argmin(seg_speed)

        all_corners.append((ln, si, ei, geo_apex, speed_apex, np.max(seg_alat)))

print(f"Detected {len(all_corners)} corner-passes across all laps")

# -- Run each detector and collect RAW values ------------------------------

raw_results = {
    "apex_offset": [],         # normalised offset (speed_apex - geo_apex) / corner_len
    "balance_ratio": [],       # entry_time / exit_time
    "exit_accel_norm": [],     # exit acceleration / peak_g
    "entry_jerk_norm": [],     # peak |jerk| at entry / peak_g (G/s per G)
    "trail_overlap_frac": [],  # fraction of entry with brake+turn overlap
    "gg_exit_entry_ratio": [], # combined_G_exit / combined_G_entry
    "yaw_ratio": [],           # actual_yaw / expected_yaw median
    "mid_rotation_norm": [],   # heading accel mid-corner activity / overall
    "exit_rotation_norm": [],  # heading accel exit activity / overall
    "peak_g": [],
    "corner_len_m": [],
    "corner_dur_s": [],        # corner duration
    "lap": [],
}

for ln, si, ei, geo_apex, speed_apex, peak_g in all_corners:
    corner_len = dist[ei] - dist[si]
    if corner_len < 1:
        continue

    # 1. Apex timing
    offset = (dist[speed_apex] - dist[geo_apex]) / corner_len
    raw_results["apex_offset"].append(offset)

    # 2. Corner balance
    t_entry = time_s[geo_apex] - time_s[si]
    t_exit  = time_s[ei] - time_s[geo_apex]
    ratio = t_entry / (t_exit + 1e-6) if t_exit > 0.05 else np.nan
    raw_results["balance_ratio"].append(ratio)

    # 3. Speed recovery
    exit_len = ei - geo_apex
    if exit_len > 10:
        exit_seg = max(1, int(exit_len * 0.3))
        dt_exit = time_s[geo_apex + exit_seg] - time_s[geo_apex]
        if dt_exit > 0.01:
            exit_accel = (speed_f[geo_apex + exit_seg] - speed_f[geo_apex]) / dt_exit
            norm_accel = exit_accel / (peak_g * 9.81 + 1e-6)
        else:
            norm_accel = np.nan
    else:
        norm_accel = np.nan
    raw_results["exit_accel_norm"].append(norm_accel)

    # 4. Lat G jerk at entry (G buildup rate, same as detect_handling_balance.py det_lat_g_jerk)
    entry_alat = np.abs(a_lat_f[si:geo_apex])
    entry_time_arr = time_s[si:geo_apex]
    turn_in_pts = np.where(entry_alat > 0.1)[0]
    if len(turn_in_pts) > 5:
        ti_i = turn_in_pts[0]
        pk_i = np.argmax(entry_alat)
        if pk_i > ti_i + 3:
            dt_ti = entry_time_arr[pk_i] - entry_time_arr[ti_i]
            if dt_ti > 0.05:
                g_buildup = entry_alat[pk_i] - entry_alat[ti_i]
                norm_jerk = (g_buildup / dt_ti) / (peak_g + 1e-6)
            else:
                norm_jerk = np.nan
        else:
            norm_jerk = np.nan
    else:
        norm_jerk = np.nan
    raw_results["entry_jerk_norm"].append(norm_jerk)

    # 5. Trail braking overlap
    seg_alon = a_lon_f[si:geo_apex]
    seg_alat_entry = np.abs(a_lat_f[si:geo_apex])
    if len(seg_alon) > 5:
        braking = seg_alon < -0.1
        turning = seg_alat_entry > 0.15
        overlap = (braking & turning).sum() / len(seg_alon)
    else:
        overlap = np.nan
    raw_results["trail_overlap_frac"].append(overlap)

    # 6. GG shape
    seg_alon_full = a_lon_f[si:ei]
    seg_alat_full = np.abs(a_lat_f[si:ei])
    entry_q = (seg_alon_full < -0.05) & (seg_alat_full > 0.15)
    exit_q  = (seg_alon_full > 0.05)  & (seg_alat_full > 0.15)
    if entry_q.sum() > 2 and exit_q.sum() > 2:
        cg_entry = np.mean(np.sqrt(seg_alon_full[entry_q]**2 + seg_alat_full[entry_q]**2))
        cg_exit  = np.mean(np.sqrt(seg_alon_full[exit_q]**2 + seg_alat_full[exit_q]**2))
        gg_ratio = cg_exit / (cg_entry + 1e-6)
    else:
        gg_ratio = np.nan
    raw_results["gg_exit_entry_ratio"].append(gg_ratio)

    # 7. Yaw ratio (actual / expected)
    seg_speed_full = speed_f[si:ei]
    seg_curv_full = curvature[si:ei]
    seg_yaw_full = np.abs(np.deg2rad(yaw_dps[si:ei]))
    expected_yaw = seg_curv_full * seg_speed_full
    valid_yaw = (seg_speed_full > 3.0) & (expected_yaw > 1e-4)
    if valid_yaw.sum() > 5:
        ratio_arr = seg_yaw_full[valid_yaw] / expected_yaw[valid_yaw]
        yaw_ratio = np.nanmedian(ratio_arr)
    else:
        yaw_ratio = np.nan
    raw_results["yaw_ratio"].append(yaw_ratio)

    # 8/9. Heading acceleration (mid and exit activity)
    seg_bear = bearing[si:ei]
    seg_dist_c = dist[si:ei]
    n_c = len(seg_bear)
    if n_c > 30:
        ds_c = np.diff(seg_dist_c)
        ds_c[ds_c == 0] = 1e-6
        dh_c = np.diff(seg_bear)
        dh_c = (dh_c + 180) % 360 - 180
        dh_ds_c = dh_c / ds_c
        d2h_ds2_c = np.diff(dh_ds_c) / ds_c[:-1]
        # Use smaller window — 5% of corner or 10 samples minimum
        win = max(5, min(int(0.05 * len(d2h_ds2_c)), int(0.1 * fs)))
        d2h_sm = pd.Series(d2h_ds2_c).rolling(win, center=True, min_periods=1).mean().values
        overall_act = np.nanmean(np.abs(d2h_sm)) + 1e-12
        mid_pt = len(d2h_sm) // 2
        sixth = max(1, len(d2h_sm) // 6)
        mid_r = d2h_sm[max(0, mid_pt - sixth) : mid_pt + sixth]
        exit_r = d2h_sm[mid_pt:]
        mid_norm = np.nanmean(np.abs(mid_r)) / overall_act if len(mid_r) > 2 else np.nan
        exit_norm = np.nanmean(np.abs(exit_r)) / overall_act if len(exit_r) > 2 else np.nan
    else:
        mid_norm = np.nan
        exit_norm = np.nan
    raw_results["mid_rotation_norm"].append(mid_norm)
    raw_results["exit_rotation_norm"].append(exit_norm)

    raw_results["peak_g"].append(peak_g)
    raw_results["corner_len_m"].append(corner_len)
    raw_results["corner_dur_s"].append(time_s[ei] - time_s[si])
    raw_results["lap"].append(ln)

# -- Print statistics per detector -----------------------------------------
print(f"\n{'='*70}")
print(f" RAW DETECTOR VALUES across {len(raw_results['peak_g'])} corner-passes")
print(f"{'='*70}\n")

detectors_info = [
    ("apex_offset",         "1. Apex Timing (offset)",
     "positive=late speed apex=understeer, negative=early=oversteer"),
    ("balance_ratio",       "2. Corner Balance (entry/exit)",
     ">1=entry-heavy=understeer, <1=exit-heavy=oversteer"),
    ("exit_accel_norm",     "3. Speed Recovery (norm accel)",
     "high=good traction=understeer, low=rear-limited=oversteer"),
    ("entry_jerk_norm",     "4. Lat G Jerk (G/s per G)",
     "high=sharp turn-in=oversteer, low=gradual=understeer"),
    ("trail_overlap_frac",  "5. Trail Braking (overlap %)",
     "high=good front grip=oversteer, low=front-limited=understeer"),
    ("gg_exit_entry_ratio", "6. GG Shape (exit/entry G)",
     ">1=strong exit=understeer, <1=weak exit=oversteer"),
    ("yaw_ratio",           "8. Yaw Ratio (actual/expected)",
     "<0.9=understeer, >1.1=oversteer, 1.0=neutral"),
    ("mid_rotation_norm",   "9a. Heading Accel Mid (norm)",
     "low=rotation stall=understeer, high=active=neutral"),
    ("exit_rotation_norm",  "9b. Heading Accel Exit (norm)",
     "high=exit instability=oversteer, low=stable=neutral"),
]

for key, label, interpretation in detectors_info:
    vals = np.array(raw_results[key], dtype=float)
    valid = vals[~np.isnan(vals)]
    if len(valid) < 3:
        print(f"{label}: insufficient data")
        continue
    p5, p25, p50, p75, p95 = np.percentile(valid, [5, 25, 50, 75, 95])
    print(f"{label}")
    print(f"  N={len(valid)}  mean={np.mean(valid):.4f}  std={np.std(valid):.4f}")
    print(f"  percentiles: 5%={p5:.4f}  25%={p25:.4f}  50%={p50:.4f}  75%={p75:.4f}  95%={p95:.4f}")
    print(f"  interpretation: {interpretation}")
    print()

# -- Plot histograms -------------------------------------------------------
fig, axes = plt.subplots(3, 3, figsize=(15, 11))
fig.patch.set_facecolor("#0a0a0a")
fig.suptitle(f"Detector Raw Value Distributions ({len(raw_results['peak_g'])} corners)",
             color="#F0EDE5", fontsize=13)

for ax_i, (key, label, _) in enumerate(detectors_info):
    ax = axes[ax_i // 3][ax_i % 3]
    ax.set_facecolor("#141414")
    ax.tick_params(colors="#949494", labelsize=8)
    ax.spines["bottom"].set_color("#333")
    ax.spines["left"].set_color("#333")
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)

    vals = np.array(raw_results[key], dtype=float)
    valid = vals[~np.isnan(vals)]
    if len(valid) < 3:
        ax.text(0.5, 0.5, "No data", color="#949494", ha="center", va="center", transform=ax.transAxes)
        ax.set_title(label, color="#F0EDE5", fontsize=9)
        continue

    # Clip outliers for display
    lo, hi = np.percentile(valid, [2, 98])
    clipped = valid[(valid >= lo) & (valid <= hi)]

    ax.hist(clipped, bins=30, color="#C9A84C", alpha=0.7, edgecolor="#333")
    ax.axvline(np.median(valid), color="#FF2A2A", linewidth=1.5, linestyle="--", label=f"median={np.median(valid):.3f}")
    ax.axvline(np.mean(valid), color="#22C55E", linewidth=1.5, linestyle=":", label=f"mean={np.mean(valid):.3f}")
    ax.set_title(label, color="#F0EDE5", fontsize=9)
    ax.legend(fontsize=7, facecolor="#1a1a1a", edgecolor="#333", labelcolor="#F0EDE5")

plt.tight_layout()
out_path = str(pathlib.Path(__file__).resolve().parents[1] / "artifacts" / "detector_distributions.png")
plt.savefig(out_path, dpi=150, facecolor=fig.get_facecolor())
plt.close()
print(f"Saved distributions to {out_path}")

# -- Scatter: each detector vs peak G (does signal scale with corner severity?) --
fig2, axes2 = plt.subplots(3, 3, figsize=(15, 11))
fig2.patch.set_facecolor("#0a0a0a")
fig2.suptitle("Detector Values vs Corner Severity (Peak G)", color="#F0EDE5", fontsize=13)

peak_gs = np.array(raw_results["peak_g"], dtype=float)

for ax_i, (key, label, _) in enumerate(detectors_info):
    ax = axes2[ax_i // 3][ax_i % 3]
    ax.set_facecolor("#141414")
    ax.tick_params(colors="#949494", labelsize=8)
    ax.spines["bottom"].set_color("#333")
    ax.spines["left"].set_color("#333")
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)

    vals = np.array(raw_results[key], dtype=float)
    valid_mask = ~np.isnan(vals)
    if valid_mask.sum() < 5:
        ax.set_title(label, color="#F0EDE5", fontsize=9)
        continue

    ax.scatter(peak_gs[valid_mask], vals[valid_mask], s=8, alpha=0.4, color="#C9A84C")

    # Correlation
    r = np.corrcoef(peak_gs[valid_mask], vals[valid_mask])[0, 1]
    ax.set_title(f"{label}  (r={r:.2f})", color="#F0EDE5", fontsize=9)
    ax.set_xlabel("Peak G", color="#949494", fontsize=8)

plt.tight_layout()
out_path2 = str(pathlib.Path(__file__).resolve().parents[1] / "artifacts" / "detector_vs_peakg.png")
plt.savefig(out_path2, dpi=150, facecolor=fig2.get_facecolor())
plt.close()
print(f"Saved scatter plots to {out_path2}")
