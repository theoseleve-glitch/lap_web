"""
acd_parser.py
-------------
Read Assetto-Corsa-style ``data.acd`` files and extract kart engine curves.

The parser:
1. Parses ACD entries (name + payload).
2. Infers the ACD decryption key from encrypted text payloads.
3. Decrypts ``engine.ini`` / ``car.ini`` / ``power.lut``.
4. Builds an RPM/torque/power curve and summary scalars.
"""
from __future__ import annotations

import logging
import math
import re
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any

import numpy as np

from kart_envelope.ingest.metadata import SessionMetadata

logger = logging.getLogger(__name__)

_KEY_CHAR_BYTES = [ord("-")] + [ord(str(i)) for i in range(10)]
_PRINTABLE = set(range(32, 127)) | {9, 10, 13}
_INI_LIKE = (
    set(map(ord, "[]_=;,.:+-*/(){}<>\\'\"#%!?&$@`~|^ \t\r\n"))
    | set(range(ord("0"), ord("9") + 1))
    | set(range(ord("A"), ord("Z") + 1))
    | set(range(ord("a"), ord("z") + 1))
)
_LUT_SPLIT_RE = re.compile(r"[|,;\t ]+")
_FLOAT_RE = re.compile(r"[-+]?\d*\.?\d+")


class ACDParseError(ValueError):
    """Raised when an ACD file cannot be parsed."""


@dataclass
class ACDEngineData:
    """Parsed engine/kart data from one ``data.acd`` file."""

    acd_path: str
    key: str
    key_score: float
    entry_count: int
    engine_curve_file: str | None
    limiter_rpm: float | None
    minimum_rpm: float | None
    coast_rpm: float | None
    coast_torque_nm: float | None
    total_mass_kg: float | None
    screen_name: str | None
    displacement_cc: float | None
    rpm: np.ndarray = field(default_factory=lambda: np.array([], dtype=float))
    torque_nm: np.ndarray = field(default_factory=lambda: np.array([], dtype=float))
    power_kw: np.ndarray = field(default_factory=lambda: np.array([], dtype=float))

    @property
    def peak_power_kw(self) -> float | None:
        if len(self.power_kw) == 0:
            return None
        val = float(np.nanmax(self.power_kw))
        return val if math.isfinite(val) and val > 0 else None

    @property
    def peak_power_hp(self) -> float | None:
        kw = self.peak_power_kw
        if kw is None:
            return None
        return kw / 0.745699872

    @property
    def peak_torque_nm(self) -> float | None:
        if len(self.torque_nm) == 0:
            return None
        val = float(np.nanmax(self.torque_nm))
        return val if math.isfinite(val) and val > 0 else None

    def to_dict(self) -> dict[str, Any]:
        return {
            "acd_path": self.acd_path,
            "key": self.key,
            "key_score": round(float(self.key_score), 4),
            "entry_count": int(self.entry_count),
            "engine_curve_file": self.engine_curve_file,
            "limiter_rpm": _round_or_none(self.limiter_rpm, 1),
            "minimum_rpm": _round_or_none(self.minimum_rpm, 1),
            "coast_rpm": _round_or_none(self.coast_rpm, 1),
            "coast_torque_nm": _round_or_none(self.coast_torque_nm, 4),
            "total_mass_kg": _round_or_none(self.total_mass_kg, 3),
            "screen_name": self.screen_name,
            "displacement_cc": _round_or_none(self.displacement_cc, 2),
            "peak_power_kw": _round_or_none(self.peak_power_kw, 4),
            "peak_power_hp": _round_or_none(self.peak_power_hp, 4),
            "peak_torque_nm": _round_or_none(self.peak_torque_nm, 4),
            "curve_points": int(len(self.rpm)),
            "rpm_curve": [round(float(v), 2) for v in np.asarray(self.rpm, dtype=float).tolist()],
            "torque_nm_curve": [round(float(v), 6) for v in np.asarray(self.torque_nm, dtype=float).tolist()],
            "power_kw_curve": [round(float(v), 6) for v in np.asarray(self.power_kw, dtype=float).tolist()],
        }


def enrich_metadata_from_acd(
    metadata: SessionMetadata,
    *,
    csv_path: Path | None = None,
    kart_data_root: Path | None = None,
) -> ACDEngineData | None:
    """
    Load ACD data and enrich metadata in place.

    Returns parsed ACD data if available, otherwise ``None``.
    """
    acd_path = resolve_acd_path(metadata, csv_path=csv_path, kart_data_root=kart_data_root)
    if acd_path is None:
        return None

    try:
        acd = load_acd_engine_data(acd_path)
    except Exception as exc:
        logger.warning("ACD parse failed for %s: %s", acd_path, exc)
        return None

    metadata.kart_data_acd = str(acd_path)
    if metadata.kart_model is None and acd.screen_name:
        metadata.kart_model = acd.screen_name

    if metadata.engine_size_cc is None and acd.displacement_cc is not None:
        metadata.engine_size_cc = float(acd.displacement_cc)

    if metadata.kart_weight_kg is None and acd.total_mass_kg is not None:
        est = float(acd.total_mass_kg) - float(metadata.driver_weight_kg)
        if est > 1.0:
            metadata.kart_weight_kg = est

    if metadata.engine_peak_torque_nm is None and acd.peak_torque_nm is not None:
        metadata.engine_peak_torque_nm = float(acd.peak_torque_nm)

    if metadata.engine_peak_power_kw is None and acd.peak_power_kw is not None:
        metadata.engine_peak_power_kw = float(acd.peak_power_kw)

    if metadata.engine_peak_power_hp is None and acd.peak_power_hp is not None:
        metadata.engine_peak_power_hp = float(acd.peak_power_hp)

    return acd


def resolve_acd_path(
    metadata: SessionMetadata,
    *,
    csv_path: Path | None = None,
    kart_data_root: Path | None = None,
) -> Path | None:
    """Resolve the ``data.acd`` path from explicit metadata or heuristics."""
    explicit = getattr(metadata, "kart_data_acd", None)
    if explicit:
        p = Path(str(explicit))
        for cand in _candidate_paths(p, csv_path=csv_path, kart_data_root=kart_data_root):
            if cand.exists() and cand.is_file():
                return cand

    root = _default_kart_data_root(csv_path=csv_path, kart_data_root=kart_data_root)
    chassis = _infer_chassis_dir(metadata)
    engine_dir = _infer_engine_dir(metadata)
    if chassis is None or engine_dir is None:
        return None
    cand = root / chassis / engine_dir / "data.acd"
    if cand.exists() and cand.is_file():
        return cand
    return None


def load_acd_engine_data(acd_path: str | Path) -> ACDEngineData:
    """
    Load and parse an ACD file.

    Parsed results are cached by absolute path.
    """
    p = Path(acd_path).expanduser().resolve()
    return _load_acd_engine_data_cached(str(p))


@lru_cache(maxsize=32)
def _load_acd_engine_data_cached(path_str: str) -> ACDEngineData:
    path = Path(path_str)
    if not path.exists():
        raise ACDParseError(f"ACD file not found: {path}")

    raw = path.read_bytes()
    entries = _parse_entries(raw)
    if not entries:
        raise ACDParseError(f"No entries parsed from {path}")

    key, score = _infer_key(entries)
    if not key:
        raise ACDParseError(f"Failed to infer decryption key for {path}")
    key_bytes = key.encode("latin1", errors="ignore")

    text_by_name: dict[str, str] = {}
    for name, enc in entries:
        dec = _decrypt_payload(enc, key_bytes)
        text_by_name[name.lower()] = dec.decode("latin1", errors="ignore")

    engine_ini = text_by_name.get("engine.ini", "")
    car_ini = text_by_name.get("car.ini", "")
    engine_vals = _parse_ini(engine_ini)
    car_vals = _parse_ini(car_ini)

    power_curve_file = _pick_power_curve_file(engine_vals, text_by_name)
    rpm, torque_nm = _extract_torque_curve(
        engine_vals=engine_vals,
        text_by_name=text_by_name,
        power_curve_file=power_curve_file,
    )
    power_kw = (rpm * torque_nm) / 9549.29658551372

    limiter = _ini_float(engine_vals, "ENGINE_DATA", "LIMITER")
    minimum = _ini_float(engine_vals, "ENGINE_DATA", "MINIMUM")
    coast_rpm = _ini_float(engine_vals, "COAST_REF", "RPM")
    coast_torque = _ini_float(engine_vals, "COAST_REF", "TORQUE")
    total_mass = _ini_float(car_vals, "BASIC", "TOTALMASS")
    screen_name = _ini_text(car_vals, "INFO", "SCREEN_NAME")
    displacement = _infer_displacement_cc(path, screen_name)

    return ACDEngineData(
        acd_path=str(path),
        key=key,
        key_score=float(score),
        entry_count=len(entries),
        engine_curve_file=power_curve_file,
        limiter_rpm=limiter,
        minimum_rpm=minimum,
        coast_rpm=coast_rpm,
        coast_torque_nm=coast_torque,
        total_mass_kg=total_mass,
        screen_name=screen_name,
        displacement_cc=displacement,
        rpm=rpm,
        torque_nm=torque_nm,
        power_kw=power_kw,
    )


def _candidate_paths(
    p: Path,
    *,
    csv_path: Path | None = None,
    kart_data_root: Path | None = None,
) -> list[Path]:
    out: list[Path] = []
    if p.is_absolute():
        out.append(p)
    else:
        out.append(Path.cwd() / p)
        out.append(Path("data") / p)
        if csv_path is not None:
            out.append(csv_path.parent / p)
        root = _default_kart_data_root(csv_path=csv_path, kart_data_root=kart_data_root)
        out.append(root / p)
    # stable order + dedupe
    deduped: list[Path] = []
    seen: set[str] = set()
    for cand in out:
        key = str(cand)
        if key not in seen:
            seen.add(key)
            deduped.append(cand)
    return deduped


def _default_kart_data_root(
    *,
    csv_path: Path | None = None,
    kart_data_root: Path | None = None,
) -> Path:
    if kart_data_root is not None:
        return Path(kart_data_root)
    if csv_path is not None:
        return csv_path.parent / "kart_data"
    return Path("data") / "kart_data"


def _infer_chassis_dir(metadata: SessionMetadata) -> str | None:
    model = str(metadata.kart_model or "").lower()
    kart_id = str(metadata.kart_id or "").lower()
    blob = f"{model} {kart_id}"
    if "rt10" in blob:
        return "rt10"
    if "sr4" in blob or "sr5" in blob or "sodi" in blob:
        return "sr4-5"
    return None


def _infer_engine_dir(metadata: SessionMetadata) -> str | None:
    cc = metadata.engine_size_cc
    if cc is None:
        cc = _extract_first_float(str(metadata.kart_model or ""))
    if cc is None:
        return None
    if cc >= 330.0:
        return "gx390cc"
    if cc >= 200.0:
        return "gx270cc"
    return None


def _parse_entries(raw: bytes) -> list[tuple[str, bytes]]:
    entries: list[tuple[str, bytes]] = []
    pos = 0
    n_bytes = len(raw)

    while pos + 8 <= n_bytes:
        name_len = int.from_bytes(raw[pos:pos + 4], "little", signed=True)
        pos += 4
        if name_len <= 0 or name_len > 1024 or pos + name_len > n_bytes:
            break
        name = raw[pos:pos + name_len].decode("latin1", errors="ignore")
        pos += name_len

        if pos + 4 > n_bytes:
            break
        payload_len = int.from_bytes(raw[pos:pos + 4], "little", signed=True)
        pos += 4
        if payload_len < 0:
            break

        span = payload_len * 4
        if pos + span > n_bytes:
            break
        enc = bytes(raw[pos:pos + span:4])
        pos += span
        entries.append((name, enc))
    return entries


def _infer_key(entries: list[tuple[str, bytes]]) -> tuple[str, float]:
    # Prioritize known readable files.
    candidates: list[tuple[str, bytes]] = []
    names = {n.lower(): e for n, e in entries}
    for prefer in ("aero.ini", "engine.ini", "car.ini", "drivetrain.ini"):
        enc = names.get(prefer)
        if enc is not None and len(enc) >= 16:
            candidates.append((prefer, enc))
    for name, enc in entries:
        ln = name.lower()
        if ln.endswith((".ini", ".lut")) and len(enc) >= 16:
            candidates.append((ln, enc))
    if not candidates:
        for name, enc in entries:
            if len(enc) >= 16:
                candidates.append((name.lower(), enc))
        if not candidates:
            return "", -1.0

    payloads = [enc for _, enc in candidates[:12]]
    best_score = -1.0
    best_key = b""

    for key_len in range(15, 32):
        key = bytearray()
        for j in range(key_len):
            vals: list[int] = []
            for enc in payloads:
                vals.extend(enc[j::key_len][:500])
            if not vals:
                key.append(ord("-"))
                continue

            best_char_score = -1e18
            best_char = ord("-")
            for kc in _KEY_CHAR_BYTES:
                p = 0
                i = 0
                bad = 0
                for v in vals:
                    d = (v - kc) & 0xFF
                    if d in _PRINTABLE:
                        p += 1
                    if d in _INI_LIKE:
                        i += 1
                    if d < 9 or (13 < d < 32) or d > 126:
                        bad += 1
                score = p * 0.6 + i * 0.5 - bad * 1.0
                if score > best_char_score:
                    best_char_score = score
                    best_char = kc
            key.append(best_char)

        key_b = bytes(key)
        score = float(np.mean([_score_decryption(enc[:7000], key_b) for enc in payloads]))
        score += _token_bonus(payloads, key_b)
        if score > best_score:
            best_score = score
            best_key = key_b

    try:
        return best_key.decode("latin1"), best_score
    except Exception:
        return "", -1.0


def _infer_key_for_payload(enc: bytes) -> tuple[str, float]:
    best_score = -1.0
    best_key = b""
    sample = enc[: min(len(enc), 7000)]

    for key_len in range(15, 32):
        key = bytearray()
        for j in range(key_len):
            vals = sample[j::key_len][:2200]
            if not vals:
                key.append(ord("-"))
                continue
            best_char_score = -1e18
            best_char = ord("-")
            for kc in _KEY_CHAR_BYTES:
                p = 0
                i = 0
                bad = 0
                for v in vals:
                    d = (v - kc) & 0xFF
                    if d in _PRINTABLE:
                        p += 1
                    if d in _INI_LIKE:
                        i += 1
                    if d < 9 or (13 < d < 32) or d > 126:
                        bad += 1
                score = p * 0.6 + i * 0.5 - bad * 1.0
                if score > best_char_score:
                    best_char_score = score
                    best_char = kc
            key.append(best_char)

        score = _score_decryption(sample, bytes(key))
        if score > best_score:
            best_score = score
            best_key = bytes(key)

    try:
        return best_key.decode("latin1"), float(best_score)
    except Exception:
        return "", -1.0


def _score_decryption(enc_sample: bytes, key: bytes) -> float:
    dec = _decrypt_payload(enc_sample, key)
    if len(dec) == 0:
        return -1.0

    n = float(len(dec))
    printable = sum(1 for x in dec if x in _PRINTABLE) / n
    ini_like = sum(1 for x in dec if x in _INI_LIKE) / n
    weird = sum(1 for x in dec if x < 9 or (13 < x < 32) or x > 126) / n
    n_new = (dec.count(10) + dec.count(13))
    n_eq = dec.count(ord("="))
    n_lb = dec.count(ord("["))
    n_rb = dec.count(ord("]"))
    return (
        printable * 0.55
        + ini_like * 0.40
        - weird * 0.70
        + min(n_new / 120.0, 1.0) * 0.03
        + min(n_eq / 60.0, 1.0) * 0.02
        + min(min(n_lb, n_rb) / 20.0, 1.0) * 0.02
    )


def _token_bonus(payloads: list[bytes], key: bytes) -> float:
    """
    Reward key candidates that decrypt obvious INI/LUT tokens.
    """
    tokens = ("[header]", "version=", "power_curve", "totalmass", "screen_name", "|")
    bonus = 0.0
    for enc in payloads[:6]:
        dec = _decrypt_payload(enc[:1200], key).decode("latin1", errors="ignore").lower()
        for tok in tokens:
            if tok in dec:
                bonus += 0.01
    return bonus


def _decrypt_payload(enc: bytes, key: bytes) -> bytes:
    if not key:
        return enc
    out = bytearray(len(enc))
    k_len = len(key)
    for idx, val in enumerate(enc):
        dec = int(val) - int(key[idx % k_len])
        if dec < 0:
            dec += 256
        out[idx] = dec
    return bytes(out)


def _parse_ini(text: str) -> dict[str, dict[str, str]]:
    out: dict[str, dict[str, str]] = {}
    sec = ""
    for raw in text.replace("\r", "\n").split("\n"):
        line = raw.strip()
        if not line:
            continue
        # Remove comments.
        if ";" in line:
            line = line.split(";", 1)[0].strip()
        if "//" in line:
            line = line.split("//", 1)[0].strip()
        if not line:
            continue
        if line.startswith("[") and "]" in line:
            sec = line[1:line.find("]")].strip().upper()
            out.setdefault(sec, {})
            continue
        if "=" not in line:
            continue
        k, v = line.split("=", 1)
        out.setdefault(sec, {})[k.strip().upper()] = v.strip()
    return out


def _ini_text(
    ini: dict[str, dict[str, str]],
    section: str,
    key: str,
) -> str | None:
    return ini.get(section.upper(), {}).get(key.upper())


def _ini_float(
    ini: dict[str, dict[str, str]],
    section: str,
    key: str,
) -> float | None:
    raw = _ini_text(ini, section, key)
    return _extract_first_float(raw)


def _pick_power_curve_file(
    engine_vals: dict[str, dict[str, str]],
    text_by_name: dict[str, str],
) -> str | None:
    curve = _ini_text(engine_vals, "HEADER", "POWER_CURVE")
    if curve:
        cand = curve.strip().lower()
        if cand in text_by_name:
            return cand

    for name in text_by_name:
        if name.endswith("power.lut"):
            return name
    return None


def _extract_torque_curve(
    engine_vals: dict[str, dict[str, str]],
    text_by_name: dict[str, str],
    power_curve_file: str | None,
) -> tuple[np.ndarray, np.ndarray]:
    if power_curve_file:
        txt = text_by_name.get(power_curve_file, "")
        rpm, y = _parse_lut_curve(txt)
        if len(rpm) >= 3 and float(np.nanmax(np.abs(y))) > 0.1:
            # In Assetto-Corsa engine data, power.lut values are torque [Nm].
            return rpm, y

    # Fallback if LUT is absent or degenerate (e.g. "0|0").
    limiter = _ini_float(engine_vals, "ENGINE_DATA", "LIMITER")
    minimum = _ini_float(engine_vals, "ENGINE_DATA", "MINIMUM")
    coast_rpm = _ini_float(engine_vals, "COAST_REF", "RPM")
    coast_torque = _ini_float(engine_vals, "COAST_REF", "TORQUE")

    lim = float(limiter if limiter is not None and limiter > 0 else 5000.0)
    min_rpm = float(minimum if minimum is not None and minimum > 0 else 1200.0)
    if coast_rpm is None or coast_rpm <= 0:
        coast_rpm = 0.92 * lim
    if coast_torque is None or coast_torque <= 0:
        coast_torque = 20.0

    rpm = np.array(
        [min_rpm, 0.55 * lim, 0.75 * lim, float(coast_rpm), lim],
        dtype=float,
    )
    torque = np.array(
        [0.85, 0.98, 1.00, 0.96, 0.82],
        dtype=float,
    ) * float(coast_torque)

    order = np.argsort(rpm)
    rpm = rpm[order]
    torque = torque[order]
    rpm, idx = np.unique(rpm, return_index=True)
    torque = torque[idx]
    return rpm, torque


def _parse_lut_curve(text: str) -> tuple[np.ndarray, np.ndarray]:
    xs: list[float] = []
    ys: list[float] = []
    for raw in text.replace("\r", "\n").split("\n"):
        line = raw.strip()
        if not line:
            continue
        if ";" in line:
            line = line.split(";", 1)[0].strip()
        if "//" in line:
            line = line.split("//", 1)[0].strip()
        if not line:
            continue
        parts = [p for p in _LUT_SPLIT_RE.split(line) if p]
        if len(parts) < 2:
            continue
        try:
            x = float(parts[0])
            y = float(parts[1])
        except ValueError:
            continue
        if not (math.isfinite(x) and math.isfinite(y)):
            continue
        xs.append(x)
        ys.append(y)
    if not xs:
        return np.array([], dtype=float), np.array([], dtype=float)
    x_arr = np.asarray(xs, dtype=float)
    y_arr = np.asarray(ys, dtype=float)
    order = np.argsort(x_arr)
    x_arr = x_arr[order]
    y_arr = y_arr[order]
    x_arr, idx = np.unique(x_arr, return_index=True)
    y_arr = y_arr[idx]
    return x_arr, y_arr


def _infer_displacement_cc(path: Path, screen_name: str | None) -> float | None:
    candidates = [
        str(path),
        str(path.parent),
        str(path.parent.parent),
        str(screen_name or ""),
    ]
    for text in candidates:
        txt = text.lower()
        # gx270 / gx390 hint
        m = re.search(r"gx\s*([0-9]{3,4})", txt)
        if m:
            try:
                return float(m.group(1))
            except ValueError:
                pass
        # generic cc pattern
        m = re.search(r"([0-9]{2,4})\s*cc", txt)
        if m:
            try:
                return float(m.group(1))
            except ValueError:
                pass
    return None


def _extract_first_float(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        out = float(value)
        return out if math.isfinite(out) else None
    s = str(value).strip().replace(",", ".")
    if not s:
        return None
    m = _FLOAT_RE.search(s)
    if not m:
        return None
    try:
        out = float(m.group(0))
    except ValueError:
        return None
    return out if math.isfinite(out) else None


def _round_or_none(value: float | None, ndigits: int) -> float | None:
    if value is None:
        return None
    return round(float(value), ndigits)
