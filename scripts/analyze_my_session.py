"""Run the full handling analysis on a kart session and produce a report + plot."""
import sys, pathlib, json
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
from matplotlib.patches import Patch
from scipy.signal import butter, filtfilt

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from telemetry_tool.handling.runner import run_handling_analysis
from telemetry_tool.handling.setup_recommender import recommend_setup_changes

csv_path = sys.argv[1] if len(sys.argv) > 1 else str(ROOT / "data" / "raw" / "OK_R1.csv")

# Load CSV
with open(csv_path, "r", encoding="utf-8-sig") as f:
    for i, line in enumerate(f):
        if line.strip().startswith("Time (s)"):
            hr = i
            break
    else:
        raise ValueError("No header found")

df = pd.read_csv(csv_path, skiprows=hr, low_memory=False)
df.columns = df.columns.str.strip()

time_s = pd.to_numeric(df.iloc[:, 0], errors="coerce").values
speed = pd.to_numeric(df.get("Speed (m/s) *calc", df.get("Speed (m/s)")), errors="coerce").values
a_lat = pd.to_numeric(df.get("Lateral acceleration (G) *calc"), errors="coerce").values
a_lon = pd.to_numeric(df.get("Longitudinal acceleration (G) *calc"), errors="coerce").values
bearing = pd.to_numeric(df["Bearing (deg)"], errors="coerce").values
lat = pd.to_numeric(df["Latitude (deg)"], errors="coerce").values
lon = pd.to_numeric(df["Longitude (deg)"], errors="coerce").values
lap_col = pd.to_numeric(df["Lap #"], errors="coerce").values
dist = pd.to_numeric(df["Distance (m)"], errors="coerce").values

# Find best lap
valid_laps = pd.Series(lap_col).dropna()
valid_laps = valid_laps[valid_laps > 0].unique()
best_lap, best_time = None, np.inf
for ln in valid_laps:
    m = lap_col == ln
    t = time_s[m]
    if len(t) < 50:
        continue
    lt = t[-1] - t[0]
    if 10 < lt < best_time:
        best_time = lt
        best_lap = int(ln)

session_name = pathlib.Path(csv_path).stem

# Run analysis
result = run_handling_analysis(
    time_s=time_s, dist_m=dist, speed_mps=speed,
    a_lat_g=a_lat, a_lon_g=a_lon, bearing_deg=bearing,
    lat_deg=lat, lon_deg=lon, lap_col=lap_col,
    best_lap=best_lap, wheelbase_m=1.0, vehicle_class="kart",
)

recs = recommend_setup_changes(result["events"])
summary = result["summary"]

# Load baseline if available
baseline_corners = []
try:
    with open(ROOT / "artifacts" / "kart_corner_baseline.json") as f:
        baseline_corners = json.load(f).get("corners", [])
except Exception:
    pass

# Print report
print("=" * 70)
print(f" HANDLING ANALYSIS - {session_name}")
print(f" Best Lap #{best_lap} ({best_time:.2f}s)")
print("=" * 70)
print(f"\nCorners: {summary['n_corners']}")
print(f"Events:  {summary['n_events']} ({summary['n_understeer']} understeer, {summary['n_oversteer']} oversteer)")
print(f"Avg confidence: {summary['avg_confidence']:.0%}")
print(f"Tendency: {summary['tendency'].upper()} (dir={summary['overall_direction']:+.3f})")

print(f"\n{'=' * 70}")
print(f" CORNERS")
print(f"{'=' * 70}")

for ci, corner in enumerate(result["corners"]):
    events = corner["events"]
    bl_info = ""
    for bc in baseline_corners:
        if bc.get("corner_id") == ci:
            bl_info = f"  [{bc.get('tendency', '?')} {bc.get('agreement', 0):.0%} {bc.get('confidence', '?')}]"

    print(f"\nC{ci+1} [{corner['start_m']:.0f}-{corner['end_m']:.0f}m] "
          f"peak={corner['peak_g']:.2f}G{bl_info}")

    if not events:
        print(f"  NEUTRAL")
        continue

    for ev in events:
        etype = ev["event_type"].upper()
        zone = ev["corner_phase"]
        conf = ev["confidence"]
        dur = ev["duration_s"]
        dirn = ev["direction"]
        voters = ev.get("n_voters", 0)
        conflict = " CONFLICT" if ev.get("conflict") else ""

        bar = "|" * int(conf * 20)
        print(f"  {etype:10s} [{zone:5s}] dir={dirn:+.2f} conf={conf:.0%} {bar} "
              f"dur={dur:.1f}s voters={voters}{conflict}")

        votes = ev.get("detector_votes", {})
        if votes:
            parts = []
            for vn, vd in sorted(votes.items(),
                                  key=lambda x: -abs(x[1].get("direction", 0)
                                                     if isinstance(x[1], dict) else 0)):
                if isinstance(vd, dict):
                    parts.append(f"{vn}({vd.get('direction', 0):+.2f})")
            print(f"     {' '.join(parts[:6])}")

print(f"\n{'=' * 70}")
print(f" SETUP RECOMMENDATIONS")
print(f"{'=' * 70}")
print(f"\n{recs['summary']}")
for r in recs["recommendations"][:5]:
    print(f"\n  {r['change']}")
    print(f"    {r['reason']}")

# Plot
dt_med = np.nanmedian(np.diff(time_s))
fs = 1.0 / dt_med
b, a = butter(2, min(1.5 / (fs / 2), 0.99), btype="low")


def filt(s):
    return filtfilt(b, a, pd.Series(s).interpolate(limit_direction="both").values)


speed_f = filt(speed)
a_lat_f = filt(a_lat)
db = np.diff(bearing, prepend=bearing[0])
db = (db + 180) % 360 - 180
dt_arr = np.diff(time_s, prepend=time_s[0])
dt_arr[dt_arr <= 0] = 1e-6
yaw_dps = filt(db / dt_arr)
speed_safe = np.where(speed_f > 3, speed_f, np.nan)
steer_kin = np.rad2deg(np.arctan(1.0 * np.deg2rad(yaw_dps) / speed_safe))

li = np.where(lap_col == best_lap)[0]
ld = dist[li] - dist[li][0]

fig, axes = plt.subplots(4, 1, figsize=(16, 12), sharex=True,
                         gridspec_kw={"height_ratios": [2.5, 1.5, 1.5, 1.5]})
fig.patch.set_facecolor("#0a0a0a")
fig.suptitle(
    f"Handling Analysis - {session_name} - Lap #{best_lap} ({best_time:.2f}s)\n"
    f"{summary['n_events']} events ({summary['n_understeer']} US, "
    f"{summary['n_oversteer']} OS), "
    f"conf={summary['avg_confidence']:.0%}, {summary['tendency'].upper()}",
    color="#F0EDE5", fontsize=13,
)

for ax in axes:
    ax.set_facecolor("#141414")
    ax.tick_params(colors="#949494", labelsize=8)
    for sp in ax.spines.values():
        sp.set_color("#333")
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)

ax1 = axes[0]
ax1.plot(ld, steer_kin[li], color="#F0EDE5", linewidth=0.8)
ax1.axhline(0, color="#949494", linewidth=0.4, linestyle="--")
for ev in result["events"]:
    sd = ev["s_start"] - dist[li][0]
    ed = ev["s_end"] - dist[li][0]
    color = "#FF2A2A" if ev["event_type"] == "understeer" else "#8B5CF6"
    alpha = 0.15 + 0.4 * ev["confidence"]
    ax1.axvspan(sd, ed, alpha=alpha, color=color, zorder=0)
ax1.legend(
    handles=[
        Patch(facecolor="#FF2A2A", alpha=0.4, label=f"Understeer ({summary['n_understeer']})"),
        Patch(facecolor="#8B5CF6", alpha=0.4, label=f"Oversteer ({summary['n_oversteer']})"),
    ],
    loc="upper right", facecolor="#1a1a1a", edgecolor="#333", labelcolor="#F0EDE5", fontsize=8,
)
ax1.set_ylabel("Steering (deg)", color="#F0EDE5", fontsize=10)

ax2 = axes[1]
ev_trace = np.zeros(len(li))
conf_trace = np.zeros(len(li))
for ev in result["events"]:
    em = (dist[li] >= ev["s_start"]) & (dist[li] <= ev["s_end"])
    ev_trace[em] = ev["direction"]
    conf_trace[em] = ev["confidence"]
ax2.fill_between(ld, ev_trace, 0, where=ev_trace > 0.15, color="#FF2A2A", alpha=0.5)
ax2.fill_between(ld, ev_trace, 0, where=ev_trace < -0.15, color="#8B5CF6", alpha=0.5)
ax2.plot(ld, ev_trace, color="#F0EDE5", linewidth=0.5)
ax2.axhline(0, color="#949494", linewidth=0.4, linestyle="--")
ax2.set_ylabel("US(+) / OS(-)", color="#F0EDE5", fontsize=10)
ax2.set_ylim(-1.2, 1.2)
ax2t = ax2.twinx()
ax2t.fill_between(ld, conf_trace, alpha=0.2, color="#C9A84C")
ax2t.set_ylabel("Conf", color="#C9A84C", fontsize=8)
ax2t.set_ylim(0, 1.5)
ax2t.tick_params(colors="#C9A84C", labelsize=7)

axes[2].plot(ld, speed_f[li] * 3.6, color="#22C55E", linewidth=0.8)
axes[2].set_ylabel("Speed (km/h)", color="#F0EDE5", fontsize=10)

axes[3].plot(ld, a_lat_f[li], color="#C9A84C", linewidth=0.8)
axes[3].set_ylabel("Lat G", color="#F0EDE5", fontsize=10)
axes[3].set_xlabel("Distance (m)", color="#F0EDE5", fontsize=11)

for ci, corner in enumerate(result["corners"]):
    for ax in axes:
        ax.axvline(corner["start_m"] - dist[li][0], color="#949494", linewidth=0.3, alpha=0.3)
    axes[3].text(corner["start_m"] - dist[li][0] + 2, axes[3].get_ylim()[0] + 0.05,
                 f"C{ci + 1}", color="#949494", fontsize=7)

plt.tight_layout()
out = str(ROOT / "artifacts" / f"{session_name}_handling.png")
plt.savefig(out, dpi=150, facecolor=fig.get_facecolor())
plt.close()
print(f"\nPlot saved to {out}")
