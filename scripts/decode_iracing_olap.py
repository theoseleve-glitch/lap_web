#!/usr/bin/env python3
"""Decode iRacing OLAP/BLAP/OLTA lap files and reconstruct a track scaffold."""

from __future__ import annotations

import argparse
import csv
import json
import math
import struct
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable

import cv2
import numpy as np
from PIL import Image
from scipy.signal import savgol_filter
from scipy.spatial import cKDTree


FILE_VERSION_OFFSET = 4
TRACK_ID_OFFSET = 12
DRIVER_OFFSET = 16
LOCATION_OFFSET = 80
CAR_OFFSET = 144
TRACK_SLUG_OFFSET = 1342
BUILD_A_OFFSET = 1406
BUILD_B_OFFSET = 1422
BUILD_C_OFFSET = 1438
UNKNOWN_ID_OFFSET = 1456
LAP_TIME_OFFSET = 1460
FORMAT_VERSION_OFFSET = 1464
SEGMENT_COUNT_OFFSET = 1468
SEGMENT_TABLE_OFFSET = 1472
SEGMENT_SIZE = 32
RECORD_SIZE = 28
SKELETON_CLOSE_KERNEL = 31
GRIP_SMOOTH_WINDOW = 51
SUPPORTED_FORMAT_VERSIONS = {3}


@dataclass
class Segment:
    segment_index: int
    start_distance_m: float
    end_distance_m: float
    sample_count: int
    step_m: float
    unknown_a: float
    unknown_b: float
    segment_time_s: float
    mode: int


@dataclass
class Interval:
    interval_index: int
    segment_index: int
    record_start_index: int
    record_end_index: int
    distance_start_m: float
    distance_end_m: float
    dt_s: float
    speed_mps: float
    speed_kph: float
    heading_start_rad: float
    heading_end_rad: float
    heading_mid_rad: float
    curvature_raw_inv_m: float
    curvature_smooth_inv_m: float
    pitch_like_rad: float
    bank_like_rad: float
    grip_proxy_raw: float
    grip_proxy_smooth: float
    flag_u32: int


def read_c_string(data: bytes, offset: int, max_len: int = 64) -> str:
    raw = data[offset : offset + max_len]
    return raw.split(b"\x00", 1)[0].decode("ascii", errors="ignore")


def read_u32(data: bytes, offset: int) -> int:
    return struct.unpack_from("<I", data, offset)[0]


def read_f32(data: bytes, offset: int) -> float:
    return struct.unpack_from("<f", data, offset)[0]


def unwrap_angles(angles: Iterable[float]) -> np.ndarray:
    angles = list(angles)
    unwrapped = [angles[0]]
    for angle in angles[1:]:
        prev = unwrapped[-1]
        while angle - prev > math.pi:
            angle -= 2.0 * math.pi
        while angle - prev < -math.pi:
            angle += 2.0 * math.pi
        unwrapped.append(angle)
    return np.asarray(unwrapped, dtype=np.float64)


def parse_segments(data: bytes) -> list[Segment]:
    count = read_u32(data, SEGMENT_COUNT_OFFSET)
    segments: list[Segment] = []
    for idx in range(count):
        base = SEGMENT_TABLE_OFFSET + idx * SEGMENT_SIZE
        start_m, end_m, samples, step_m, unk_a, unk_b, seg_time, mode = struct.unpack_from(
            "<ffIffffI", data, base
        )
        segments.append(
            Segment(
                segment_index=idx,
                start_distance_m=float(start_m),
                end_distance_m=float(end_m),
                sample_count=int(samples),
                step_m=float(step_m),
                unknown_a=float(unk_a),
                unknown_b=float(unk_b),
                segment_time_s=float(seg_time),
                mode=int(mode),
            )
        )
    return segments


def parse_records(data: bytes, record_start: int, record_count: int) -> list[tuple[float, float, float, float, float, int, int]]:
    records: list[tuple[float, float, float, float, float, int, int]] = []
    for idx in range(record_count):
        base = record_start + idx * RECORD_SIZE
        local_time_s, field1, yaw, field3, field4, reserved_u32, flag_u32 = struct.unpack_from(
            "<5fII", data, base
        )
        records.append(
            (
                float(local_time_s),
                float(field1),
                float(yaw),
                float(field3),
                float(field4),
                int(reserved_u32),
                int(flag_u32),
            )
        )
    return records


def build_intervals(
    records: list[tuple[float, float, float, float, float, int, int]],
    segments: list[Segment],
) -> tuple[list[Interval], np.ndarray]:
    headings = unwrap_angles(record[2] for record in records)
    smoothed = headings.copy()

    flat = 0
    for segment in segments:
        seg_headings = headings[flat : flat + segment.sample_count]
        window = min(GRIP_SMOOTH_WINDOW, len(seg_headings) if len(seg_headings) % 2 == 1 else len(seg_headings) - 1)
        if window >= 5:
            smoothed[flat : flat + segment.sample_count] = savgol_filter(
                seg_headings,
                window_length=window,
                polyorder=3,
                mode="interp",
            )
        flat += segment.sample_count

    intervals: list[Interval] = []
    flat = 0
    interval_index = 0
    for segment in segments:
        for local_idx in range(segment.sample_count - 1):
            a = records[flat + local_idx]
            b = records[flat + local_idx + 1]
            dt = max(b[0] - a[0], 1e-9)
            speed = segment.step_m / dt
            raw_curvature = (headings[flat + local_idx + 1] - headings[flat + local_idx]) / segment.step_m
            smooth_curvature = (smoothed[flat + local_idx + 1] - smoothed[flat + local_idx]) / segment.step_m
            grip_raw = abs(raw_curvature) * speed * speed / 9.80665
            grip_smooth = abs(smooth_curvature) * speed * speed / 9.80665
            dist_start = segment.start_distance_m + local_idx * segment.step_m
            dist_end = dist_start + segment.step_m
            intervals.append(
                Interval(
                    interval_index=interval_index,
                    segment_index=segment.segment_index,
                    record_start_index=flat + local_idx,
                    record_end_index=flat + local_idx + 1,
                    distance_start_m=dist_start,
                    distance_end_m=dist_end,
                    dt_s=dt,
                    speed_mps=speed,
                    speed_kph=speed * 3.6,
                    heading_start_rad=float(headings[flat + local_idx]),
                    heading_end_rad=float(headings[flat + local_idx + 1]),
                    heading_mid_rad=float(0.5 * (headings[flat + local_idx] + headings[flat + local_idx + 1])),
                    curvature_raw_inv_m=float(raw_curvature),
                    curvature_smooth_inv_m=float(smooth_curvature),
                    pitch_like_rad=float(0.5 * (a[3] + b[3])),
                    bank_like_rad=float(0.5 * (a[4] + b[4])),
                    grip_proxy_raw=float(grip_raw),
                    grip_proxy_smooth=float(grip_smooth),
                    flag_u32=int(a[6]),
                )
            )
            interval_index += 1
        flat += segment.sample_count

    return intervals, headings


def integrate_centerline(intervals: list[Interval]) -> tuple[np.ndarray, float]:
    xy = np.zeros((len(intervals) + 1, 2), dtype=np.float64)
    for idx, interval in enumerate(intervals):
        ds = interval.distance_end_m - interval.distance_start_m
        theta = interval.heading_mid_rad
        xy[idx + 1, 0] = xy[idx, 0] + ds * math.cos(theta)
        xy[idx + 1, 1] = xy[idx, 1] + ds * math.sin(theta)

    closure = xy[-1] - xy[0]
    closure_error = float(np.linalg.norm(closure))
    correction = np.linspace(0.0, 1.0, len(xy), dtype=np.float64)[:, None] * closure[None, :]
    return xy - correction, closure_error


def skeletonize_mask(mask: np.ndarray) -> np.ndarray:
    skeleton = np.zeros_like(mask, dtype=np.uint8)
    element = cv2.getStructuringElement(cv2.MORPH_CROSS, (3, 3))
    work = mask.copy()
    while True:
        opened = cv2.morphologyEx(work, cv2.MORPH_OPEN, element)
        residue = cv2.subtract(work, opened)
        skeleton = cv2.bitwise_or(skeleton, residue)
        work = cv2.erode(work, element)
        if cv2.countNonZero(work) == 0:
            break
    return skeleton


def similarity_fit(a: np.ndarray, b: np.ndarray) -> tuple[float, np.ndarray, np.ndarray]:
    mu_a = a.mean(axis=0)
    mu_b = b.mean(axis=0)
    ac = a - mu_a
    bc = b - mu_b
    u, svals, vt = np.linalg.svd(ac.T @ bc)
    rotation = vt.T @ u.T
    if np.linalg.det(rotation) < 0:
        vt[-1, :] *= -1
        rotation = vt.T @ u.T
    scale = float(np.sum(svals) / np.sum(ac * ac))
    translation = mu_b - scale * (mu_a @ rotation.T)
    return scale, rotation, translation


def apply_similarity(points: np.ndarray, scale: float, rotation: np.ndarray, translation: np.ndarray) -> np.ndarray:
    return scale * (points @ rotation.T) + translation


def align_centerline_to_outline(centerline_xy: np.ndarray, outline_path: Path) -> tuple[dict[str, object], np.ndarray, np.ndarray, np.ndarray]:
    rgb = np.asarray(Image.open(outline_path).convert("RGB"))
    mask = np.where(rgb.max(axis=2) > 10, 255, 0).astype(np.uint8)
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (SKELETON_CLOSE_KERNEL, SKELETON_CLOSE_KERNEL))
    closed_mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel)
    skeleton = skeletonize_mask(closed_mask)

    ys, xs = np.where(skeleton > 0)
    target = np.column_stack([xs, ys]).astype(np.float64)
    target_sub = target[::2]

    center = centerline_xy.mean(axis=0)
    best: dict[str, object] | None = None

    for swap in (False, True):
        base = centerline_xy[:, [1, 0]] if swap else centerline_xy.copy()
        base = base - center
        for flip_x in (1.0, -1.0):
            for flip_y in (1.0, -1.0):
                variant = base * np.array([flip_x, flip_y], dtype=np.float64)
                variant_sub = variant[::2]
                diag_variant = np.linalg.norm(variant_sub.max(axis=0) - variant_sub.min(axis=0))
                diag_target = np.linalg.norm(target_sub.max(axis=0) - target_sub.min(axis=0))
                scale_total = float(diag_target / diag_variant)
                rotation_total = np.eye(2, dtype=np.float64)
                translation_total = target_sub.mean(axis=0) - scale_total * (variant_sub.mean(axis=0) @ rotation_total.T)
                probe = apply_similarity(variant_sub, scale_total, rotation_total, translation_total)

                for _ in range(20):
                    tree = cKDTree(target_sub)
                    distances, indices = tree.query(probe, k=1)
                    matched = target_sub[indices]
                    scale_step, rotation_step, translation_step = similarity_fit(probe, matched)
                    probe = apply_similarity(probe, scale_step, rotation_step, translation_step)
                    scale_total = scale_step * scale_total
                    rotation_total = rotation_step @ rotation_total
                    translation_total = scale_step * (translation_total @ rotation_step.T) + translation_step

                rmse = float(np.sqrt(np.mean(distances * distances)))
                if best is None or rmse < best["rmse_px"]:
                    best = {
                        "rmse_px": rmse,
                        "swap_axes": swap,
                        "flip_x": int(flip_x),
                        "flip_y": int(flip_y),
                        "scale_px_per_m": scale_total,
                        "rotation": rotation_total,
                        "translation": translation_total,
                        "centerline_center": center,
                    }

    assert best is not None
    variant = centerline_xy[:, [1, 0]] if best["swap_axes"] else centerline_xy.copy()
    variant = (variant - best["centerline_center"]) * np.array([best["flip_x"], best["flip_y"]], dtype=np.float64)
    aligned = apply_similarity(
        variant,
        float(best["scale_px_per_m"]),
        np.asarray(best["rotation"]),
        np.asarray(best["translation"]),
    )
    return best, rgb, closed_mask, aligned


def inverse_similarity(points_px: np.ndarray, align: dict[str, object]) -> np.ndarray:
    rotation = np.asarray(align["rotation"])
    translation = np.asarray(align["translation"])
    scale = float(align["scale_px_per_m"])
    local = ((points_px - translation) / scale) @ rotation
    local = local * np.array([align["flip_x"], align["flip_y"]], dtype=np.float64)
    if align["swap_axes"]:
        local = local[:, [1, 0]]
    return local + np.asarray(align["centerline_center"])


def derive_virtual_track(centerline_px: np.ndarray, closed_mask: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    mask = closed_mask > 0
    height, width = mask.shape
    left = np.zeros_like(centerline_px)
    right = np.zeros_like(centerline_px)
    widths = np.zeros((len(centerline_px),), dtype=np.float64)

    for idx in range(len(centerline_px)):
        prev_pt = centerline_px[idx - 1]
        next_pt = centerline_px[(idx + 1) % len(centerline_px)]
        tangent = next_pt - prev_pt
        normal = np.array([-tangent[1], tangent[0]], dtype=np.float64)
        norm = np.linalg.norm(normal)
        if norm < 1e-9:
            left[idx] = centerline_px[idx]
            right[idx] = centerline_px[idx]
            continue
        normal /= norm
        point = centerline_px[idx]
        hits = []
        for sign in (1.0, -1.0):
            dist = 0.0
            last = point
            while dist < 250.0:
                probe = point + sign * normal * dist
                px = int(round(float(probe[0])))
                py = int(round(float(probe[1])))
                if px < 0 or py < 0 or px >= width or py >= height or not mask[py, px]:
                    break
                last = probe
                dist += 0.5
            hits.append(last)
        right[idx] = hits[0]
        left[idx] = hits[1]
        widths[idx] = float(np.linalg.norm(hits[0] - hits[1]))

    return left, right, widths


def write_csv(path: Path, rows: Iterable[dict[str, object]]) -> None:
    rows = list(rows)
    if not rows:
        return
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def draw_overlay(rgb: np.ndarray, centerline_px: np.ndarray, left_px: np.ndarray, right_px: np.ndarray, output_path: Path) -> None:
    canvas = cv2.cvtColor(rgb.copy(), cv2.COLOR_RGB2BGR)
    for poly, color, thickness in (
        (left_px, (255, 128, 0), 1),
        (right_px, (255, 128, 0), 1),
        (centerline_px, (0, 200, 255), 2),
    ):
        points = np.round(poly).astype(np.int32).reshape((-1, 1, 2))
        cv2.polylines(canvas, [points], True, color, thickness, lineType=cv2.LINE_AA)
    Image.fromarray(cv2.cvtColor(canvas, cv2.COLOR_BGR2RGB)).save(output_path)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("lap_file", type=Path, help="Path to a .olap/.blap/.olapta file")
    parser.add_argument("--outline-image", type=Path, help="Optional DAT-derived track outline PNG")
    parser.add_argument("--outdir", type=Path, default=Path("artifacts/iracing_olap_decode"), help="Output directory")
    args = parser.parse_args()

    data = args.lap_file.read_bytes()
    magic = data[:4].decode("ascii", errors="ignore")
    if magic not in {"OLAP", "BLAP", "OLTA"}:
        raise ValueError(f"Unsupported magic {magic!r}")

    file_version = read_u32(data, FILE_VERSION_OFFSET)
    track_id = read_u32(data, TRACK_ID_OFFSET)
    unknown_id = read_u32(data, UNKNOWN_ID_OFFSET)
    lap_time_s = read_f32(data, LAP_TIME_OFFSET)
    format_version = read_u32(data, FORMAT_VERSION_OFFSET)
    if format_version not in SUPPORTED_FORMAT_VERSIONS:
        raise ValueError(
            f"Unsupported OLAP payload format version {format_version}. "
            f"Known-good versions: {sorted(SUPPORTED_FORMAT_VERSIONS)}"
        )
    segments = parse_segments(data)
    record_start = SEGMENT_TABLE_OFFSET + len(segments) * SEGMENT_SIZE
    record_count = sum(segment.sample_count for segment in segments)
    expected_size = record_start + record_count * RECORD_SIZE
    if expected_size != len(data):
        raise ValueError(
            f"Unexpected file size: expected {expected_size} from segment table, got {len(data)}"
        )

    records = parse_records(data, record_start, record_count)
    reserved_values = {record[5] for record in records}
    if reserved_values != {0}:
        raise ValueError(f"Reserved field was not constant zero: {sorted(reserved_values)}")

    intervals, headings = build_intervals(records, segments)
    centerline_xy, closure_error_m = integrate_centerline(intervals)

    outdir = args.outdir / args.lap_file.stem
    outdir.mkdir(parents=True, exist_ok=True)

    summary = {
        "magic": magic,
        "file_version": file_version,
        "format_version": format_version,
        "track_id": track_id,
        "driver": read_c_string(data, DRIVER_OFFSET),
        "location": read_c_string(data, LOCATION_OFFSET),
        "car": read_c_string(data, CAR_OFFSET),
        "track_slug": read_c_string(data, TRACK_SLUG_OFFSET),
        "build_a": read_c_string(data, BUILD_A_OFFSET, 16),
        "build_b": read_c_string(data, BUILD_B_OFFSET, 16),
        "build_c": read_c_string(data, BUILD_C_OFFSET, 16),
        "unknown_id": unknown_id,
        "lap_time_s": lap_time_s,
        "segment_count": len(segments),
        "record_count": record_count,
        "interval_count": len(intervals),
        "lap_length_m": segments[-1].end_distance_m,
        "closure_error_m": closure_error_m,
        "heading_total_change_rad": float(headings[-1] - headings[0]),
        "speed_mps_min": float(min(interval.speed_mps for interval in intervals)),
        "speed_mps_max": float(max(interval.speed_mps for interval in intervals)),
        "speed_mps_avg": float(sum(interval.speed_mps for interval in intervals) / len(intervals)),
        "grip_proxy_smooth_q95": float(np.quantile([interval.grip_proxy_smooth for interval in intervals], 0.95)),
        "grip_proxy_smooth_max": float(max(interval.grip_proxy_smooth for interval in intervals)),
    }

    (outdir / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    write_csv(outdir / "segments.csv", [asdict(segment) for segment in segments])
    write_csv(outdir / "intervals.csv", [asdict(interval) for interval in intervals])

    center_rows = []
    for idx, point in enumerate(centerline_xy):
        if idx == 0:
            cumulative = 0.0
        else:
            cumulative = intervals[idx - 1].distance_end_m
        center_rows.append(
            {
                "point_index": idx,
                "cumulative_distance_m": cumulative,
                "x_m": float(point[0]),
                "y_m": float(point[1]),
            }
        )
    write_csv(outdir / "centerline_local.csv", center_rows)

    if args.outline_image is not None:
        align, rgb, closed_mask, centerline_px = align_centerline_to_outline(centerline_xy, args.outline_image)
        left_px, right_px, widths_px = derive_virtual_track(centerline_px, closed_mask)
        left_local = inverse_similarity(left_px, align)
        right_local = inverse_similarity(right_px, align)

        track_rows = []
        for idx, point in enumerate(centerline_xy):
            if idx == 0:
                cumulative = 0.0
            else:
                cumulative = intervals[idx - 1].distance_end_m
            track_rows.append(
                {
                    "point_index": idx,
                    "cumulative_distance_m": cumulative,
                    "center_x_m": float(point[0]),
                    "center_y_m": float(point[1]),
                    "left_x_m": float(left_local[idx, 0]),
                    "left_y_m": float(left_local[idx, 1]),
                    "right_x_m": float(right_local[idx, 0]),
                    "right_y_m": float(right_local[idx, 1]),
                    "center_x_px": float(centerline_px[idx, 0]),
                    "center_y_px": float(centerline_px[idx, 1]),
                    "width_px": float(widths_px[idx]),
                    "flag_u32": int(intervals[min(idx, len(intervals) - 1)].flag_u32),
                }
            )
        write_csv(outdir / "virtual_track.csv", track_rows)
        draw_overlay(rgb, centerline_px, left_px, right_px, outdir / "outline_overlay.png")
        align_summary = {
            "rmse_px": float(align["rmse_px"]),
            "swap_axes": bool(align["swap_axes"]),
            "flip_x": int(align["flip_x"]),
            "flip_y": int(align["flip_y"]),
            "scale_px_per_m": float(align["scale_px_per_m"]),
            "width_px_min": float(widths_px.min()),
            "width_px_max": float(widths_px.max()),
            "width_px_avg": float(widths_px.mean()),
        }
        (outdir / "alignment.json").write_text(json.dumps(align_summary, indent=2), encoding="utf-8")

    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
