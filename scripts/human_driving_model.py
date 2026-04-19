#!/usr/bin/env python
"""Data-driven human driving model — learned from real telemetry.

Extracts statistical fingerprints from TUMFTM (steering+brake) and
kaggle_motorsport (throttle+brake) datasets, then applies them to
transform optimal/AI inputs into realistic human-like traces.

Key behaviors modeled from real data:
  - Steering: 100% power below 2Hz, micro-corrections every 20-40ms
  - Brake: press 22% faster than release (trail-brake signature)
  - Throttle: applies slowly, lifts fast (0.76 press:release ratio)
  - Overlap: 4.3% throttle+brake simultaneous (real trail-braking)
  - All inputs: 95-100% power below 1Hz (very low frequency)

Usage:
    from scripts.human_driving_model import HumanDrivingModel
    model = HumanDrivingModel.from_real_data()
    model.save("data/oracle/human_model.npz")

    model = HumanDrivingModel.load("data/oracle/human_model.npz")
    result = model.humanize(opt_throttle, opt_brake, opt_steer, speed_ms, dt=1/60)
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
from scipy import signal


@dataclass
class HumanFingerprint:
    """Statistical fingerprint of real human driving."""

    # Throttle characteristics (from kaggle_motorsport, 50Hz)
    thr_press_rate_mean: float = 0.0106    # per sample at 50Hz
    thr_press_rate_p90: float = 0.0264
    thr_release_rate_mean: float = 0.0139  # lift is FASTER than press
    thr_release_rate_p90: float = 0.0434
    thr_press_release_ratio: float = 0.76  # <1 means lift faster than press

    # Brake characteristics (from TUMFTM, 50Hz)
    brk_press_rate_mean: float = 0.0356
    brk_press_rate_p90: float = 0.0881
    brk_release_rate_mean: float = 0.0292  # release is SLOWER (trail-brake)
    brk_release_rate_p90: float = 0.0643
    brk_press_release_ratio: float = 1.22  # >1 means press faster = trail-brake

    # Steering characteristics (from TUMFTM, 50Hz)
    steer_rate_mean: float = 0.000472      # rad/sample
    steer_rate_p99: float = 0.00227
    steer_correction_hz: float = 26.0      # micro-corrections per second
    steer_correction_interval_p50: float = 0.020  # seconds

    # Frequency content (fraction of power below cutoff)
    thr_power_below_1hz: float = 0.971
    brk_power_below_1hz: float = 0.958
    steer_power_below_2hz: float = 1.0

    # Overlap
    thr_brk_overlap_frac: float = 0.043

    # Noise PSD shapes (learned from real data, stored as arrays)
    thr_psd_freqs: np.ndarray = field(default_factory=lambda: np.array([]))
    thr_psd_values: np.ndarray = field(default_factory=lambda: np.array([]))
    brk_psd_freqs: np.ndarray = field(default_factory=lambda: np.array([]))
    brk_psd_values: np.ndarray = field(default_factory=lambda: np.array([]))
    steer_psd_freqs: np.ndarray = field(default_factory=lambda: np.array([]))
    steer_psd_values: np.ndarray = field(default_factory=lambda: np.array([]))


class HumanDrivingModel:
    """Transforms optimal inputs into realistic human-like traces.

    Uses spectral shaping: generates white noise, filters it through the
    real human PSD shape, then applies rate-limiting and asymmetric
    ramp constraints learned from real data.
    """

    def __init__(self, fp: HumanFingerprint, sample_hz: int = 60):
        self.fp = fp
        self.hz = sample_hz
        # Scale rates from 50Hz (data source) to target Hz
        self._rate_scale = sample_hz / 50.0

    @classmethod
    def from_real_data(
        cls,
        tumftm_dir: str | Path = "data/external/tumftm",
        kaggle_path: str | Path = "data/external/kaggle_motorsport/motorsport_data.csv",
        sample_hz: int = 60,
        max_files: int = 5,
    ) -> HumanDrivingModel:
        """Learn the human fingerprint from real telemetry datasets."""
        import pandas as pd

        tumftm_dir = Path(tumftm_dir)
        kaggle_path = Path(kaggle_path)

        fp = HumanFingerprint()

        # --- TUMFTM: steering + brake ---
        if tumftm_dir.exists():
            frames = []
            for i in range(max_files):
                f = tumftm_dir / f"data_to_train_{i}.csv"
                if f.exists():
                    frames.append(pd.read_csv(f))
            if frames:
                df = pd.concat(frames, ignore_index=True)
                tum_hz = 50

                # Steering fingerprint
                steer = df["deltawheel_rad"].values
                steer_rate = np.diff(steer)
                fp.steer_rate_mean = float(np.abs(steer_rate).mean())
                fp.steer_rate_p99 = float(np.percentile(np.abs(steer_rate), 99))

                freqs, psd = signal.welch(steer, fs=tum_hz, nperseg=1024)
                fp.steer_psd_freqs = freqs
                fp.steer_psd_values = psd
                fp.steer_power_below_2hz = float(psd[freqs < 2].sum() / psd.sum())

                # Brake fingerprint
                brake = df["pBrakeF_bar"].values
                brake_norm = brake / max(brake.max(), 1.0)
                brk_rate = np.diff(brake_norm)
                press = brk_rate[brk_rate > 0.001]
                release = brk_rate[brk_rate < -0.001]
                if len(press) > 0 and len(release) > 0:
                    fp.brk_press_rate_mean = float(press.mean())
                    fp.brk_press_rate_p90 = float(np.percentile(press, 90))
                    fp.brk_release_rate_mean = float(np.abs(release).mean())
                    fp.brk_release_rate_p90 = float(np.percentile(np.abs(release), 90))
                    fp.brk_press_release_ratio = fp.brk_press_rate_mean / fp.brk_release_rate_mean

                freqs_b, psd_b = signal.welch(brake_norm, fs=tum_hz, nperseg=1024)
                fp.brk_psd_freqs = freqs_b
                fp.brk_psd_values = psd_b
                fp.brk_power_below_1hz = float(psd_b[freqs_b < 1].sum() / psd_b.sum())

        # --- Kaggle: throttle ---
        if kaggle_path.exists():
            df2 = pd.read_csv(kaggle_path)
            kag_hz = 50

            thr = df2["throttle_precise"].values / 100.0
            thr_rate = np.diff(thr)
            press_t = thr_rate[thr_rate > 0.001]
            release_t = thr_rate[thr_rate < -0.001]
            if len(press_t) > 0 and len(release_t) > 0:
                fp.thr_press_rate_mean = float(press_t.mean())
                fp.thr_press_rate_p90 = float(np.percentile(press_t, 90))
                fp.thr_release_rate_mean = float(np.abs(release_t).mean())
                fp.thr_release_rate_p90 = float(np.percentile(np.abs(release_t), 90))
                fp.thr_press_release_ratio = fp.thr_press_rate_mean / fp.thr_release_rate_mean

            freqs_t, psd_t = signal.welch(thr, fs=kag_hz, nperseg=1024)
            fp.thr_psd_freqs = freqs_t
            fp.thr_psd_values = psd_t
            fp.thr_power_below_1hz = float(psd_t[freqs_t < 1].sum() / psd_t.sum())

            # Overlap
            brk_kag = df2["brake_intensity"].values / 100.0
            fp.thr_brk_overlap_frac = float(((thr > 0.1) & (brk_kag > 0.1)).mean())

        return cls(fp, sample_hz)

    def save(self, path: str | Path):
        """Save the learned model to .npz file (no pickle — numpy arrays only)."""
        fp = self.fp
        np.savez_compressed(
            str(path),
            params=np.array([
                fp.thr_press_rate_mean, fp.thr_press_rate_p90,
                fp.thr_release_rate_mean, fp.thr_release_rate_p90,
                fp.brk_press_rate_mean, fp.brk_press_rate_p90,
                fp.brk_release_rate_mean, fp.brk_release_rate_p90,
                fp.steer_rate_mean, fp.steer_rate_p99,
                fp.thr_brk_overlap_frac,
                fp.thr_power_below_1hz, fp.brk_power_below_1hz,
                fp.steer_power_below_2hz,
            ]),
            thr_psd_freqs=fp.thr_psd_freqs,
            thr_psd_values=fp.thr_psd_values,
            brk_psd_freqs=fp.brk_psd_freqs,
            brk_psd_values=fp.brk_psd_values,
            steer_psd_freqs=fp.steer_psd_freqs,
            steer_psd_values=fp.steer_psd_values,
            hz=np.array([self.hz]),
        )

    @classmethod
    def load(cls, path: str | Path) -> HumanDrivingModel:
        """Load a previously saved model (npz, no pickle)."""
        d = np.load(str(path), allow_pickle=False)
        p = d["params"]
        fp = HumanFingerprint(
            thr_press_rate_mean=float(p[0]), thr_press_rate_p90=float(p[1]),
            thr_release_rate_mean=float(p[2]), thr_release_rate_p90=float(p[3]),
            brk_press_rate_mean=float(p[4]), brk_press_rate_p90=float(p[5]),
            brk_release_rate_mean=float(p[6]), brk_release_rate_p90=float(p[7]),
            steer_rate_mean=float(p[8]), steer_rate_p99=float(p[9]),
            thr_brk_overlap_frac=float(p[10]),
            thr_power_below_1hz=float(p[11]),
            brk_power_below_1hz=float(p[12]),
            steer_power_below_2hz=float(p[13]),
            thr_psd_freqs=d["thr_psd_freqs"],
            thr_psd_values=d["thr_psd_values"],
            brk_psd_freqs=d["brk_psd_freqs"],
            brk_psd_values=d["brk_psd_values"],
            steer_psd_freqs=d["steer_psd_freqs"],
            steer_psd_values=d["steer_psd_values"],
        )
        return cls(fp, int(d["hz"][0]))

    # ------------------------------------------------------------------
    # Core humanization
    # ------------------------------------------------------------------

    def humanize(
        self,
        opt_thr: np.ndarray,
        opt_brk: np.ndarray,
        opt_steer: np.ndarray,
        speed_ms: np.ndarray,
        skill: float = 0.85,
        seed: int | None = None,
    ) -> dict:
        """Transform optimal inputs into human-like traces.

        Returns dict with: human_throttle, human_brake, human_steer, driver_skill
        """
        rng = np.random.RandomState(seed)
        n = len(opt_thr)
        noise_scale = 1.0 - skill

        h_thr = self._humanize_throttle(opt_thr.copy(), speed_ms, noise_scale, rng)
        h_brk = self._humanize_brake(opt_brk.copy(), speed_ms, noise_scale, rng)
        h_steer = self._humanize_steering(opt_steer.copy(), speed_ms, noise_scale, rng)

        h_thr, h_brk = self._apply_overlap_constraint(h_thr, h_brk, noise_scale, rng)

        return {
            "human_throttle": np.clip(h_thr, 0, 1).astype(np.float32),
            "human_brake": np.clip(h_brk, 0, 1).astype(np.float32),
            "human_steer": np.clip(h_steer, -1, 1).astype(np.float32),
            "driver_skill": np.full(n, skill, dtype=np.float32),
        }

    def _humanize_throttle(self, thr, speed, noise_scale, rng):
        """Realistic throttle: applies SLOWLY, lifts FAST (ratio 0.76)."""
        n = len(thr)

        # 1. Spectral-shaped noise (real throttle PSD)
        noise = self._spectral_noise(n, self.fp.thr_psd_freqs, self.fp.thr_psd_values, rng)
        thr += noise * noise_scale * 0.08

        # 2. Asymmetric rate limit (slow press, fast lift)
        press_rate = self.fp.thr_press_rate_mean * self._rate_scale * (1 + noise_scale * 0.5)
        release_rate = self.fp.thr_release_rate_mean * self._rate_scale * (1 + noise_scale * 0.3)
        thr = _asymmetric_rate_limit(thr, press_rate, release_rate)

        # 3. Reaction delay (50-200ms based on skill)
        delay = int((0.05 + noise_scale * 0.15) * self.hz)
        if delay > 0:
            thr[delay:] = thr[:-delay].copy()

        # 4. Speed-dependent noise (more at low speed)
        speed_factor = np.clip(1.0 - speed / 50.0, 0, 1)
        low_noise = _low_freq_noise(n, self.hz, rng, max_freq=0.8)
        thr += low_noise * noise_scale * 0.03 * speed_factor

        return thr

    def _humanize_brake(self, brk, speed, noise_scale, rng):
        """Realistic brake: presses FAST, releases SLOWLY (trail-brake, ratio 1.22)."""
        n = len(brk)

        # 1. Spectral noise
        noise = self._spectral_noise(n, self.fp.brk_psd_freqs, self.fp.brk_psd_values, rng)
        brk += noise * noise_scale * 0.06

        # 2. Asymmetric rate limit (fast press, slow release = trail-brake)
        press_rate = self.fp.brk_press_rate_mean * self._rate_scale * (1 + noise_scale * 0.3)
        release_rate = self.fp.brk_release_rate_mean * self._rate_scale * (1 + noise_scale * 0.5)
        brk = _asymmetric_rate_limit(brk, press_rate, release_rate)

        # 3. Brake pressure modulation (pulsing at 0.5-1.5Hz when braking)
        t = np.arange(n) / self.hz
        braking_mask = (brk > 0.1).astype(float)
        for _ in range(2):
            f = rng.uniform(0.5, 1.5)
            phase = rng.uniform(0, 2 * np.pi)
            brk += np.sin(2 * np.pi * f * t + phase) * noise_scale * 0.04 * braking_mask

        # 4. Reaction delay
        delay = int((0.03 + noise_scale * 0.1) * self.hz)
        if delay > 0:
            brk[delay:] = brk[:-delay].copy()

        return brk

    def _humanize_steering(self, steer, speed, noise_scale, rng):
        """Realistic steering: 100% below 2Hz, micro-corrections every 20-40ms."""
        n = len(steer)

        # 1. Spectral noise (real steering PSD — all below 2Hz)
        noise = self._spectral_noise(n, self.fp.steer_psd_freqs, self.fp.steer_psd_values, rng)
        steer += noise * noise_scale * 0.05

        # 2. Micro-corrections (20-40ms intervals, very small amplitude)
        correction_interval = max(1, int(self.fp.steer_correction_interval_p50 * self.hz))
        corrections = np.zeros(n)
        for i in range(0, n, correction_interval):
            corrections[i] = rng.normal(0, self.fp.steer_rate_mean * 3)
        # Blend over 2-3 samples
        if n > 3:
            kernel = np.array([0.25, 0.5, 0.25])
            corrections = np.convolve(corrections, kernel, mode="same")
        steer += corrections * noise_scale * 2.0

        # 3. Speed-dependent precision (more precise at high speed)
        speed_factor = np.clip(speed / 30.0, 0.3, 1.0)
        low_noise = _low_freq_noise(n, self.hz, rng, max_freq=1.5)
        steer += low_noise * noise_scale * 0.02 / speed_factor

        # 4. Rate limit
        max_rate = self.fp.steer_rate_p99 * self._rate_scale * 2.0
        steer = _symmetric_rate_limit(steer, max_rate)

        # 5. Reaction delay
        delay = int((0.02 + noise_scale * 0.05) * self.hz)
        if delay > 0:
            steer[delay:] = steer[:-delay].copy()

        return steer

    def _apply_overlap_constraint(self, thr, brk, noise_scale, rng):
        """Enforce realistic throttle-brake overlap (4.3% from real data).

        Real drivers have very little simultaneous throttle+brake except
        during brief trail-braking transitions (50-200ms).
        """
        target_frac = self.fp.thr_brk_overlap_frac

        # Iteratively reduce overlap until near target
        for _ in range(5):
            overlap_mask = (thr > 0.05) & (brk > 0.05)
            current = overlap_mask.mean()
            if current <= target_frac * 1.5:
                break

            overlap_idx = np.where(overlap_mask)[0]
            # Remove 70% of overlap samples per iteration
            n_remove = int(len(overlap_idx) * 0.7)
            remove_idx = rng.choice(overlap_idx, size=min(n_remove, len(overlap_idx)), replace=False)
            for i in remove_idx:
                if thr[i] > brk[i]:
                    brk[i] *= 0.1
                else:
                    thr[i] *= 0.1

        return thr, brk

    def _spectral_noise(self, n, psd_freqs, psd_values, rng):
        """Generate noise matching real data's power spectral density."""
        if len(psd_freqs) == 0:
            return _low_freq_noise(n, self.hz, rng)

        white = rng.randn(n)
        target_freqs = np.fft.rfftfreq(n, d=1.0 / self.hz)
        target_psd = np.interp(target_freqs, psd_freqs, psd_values, left=psd_values[0], right=0)
        target_psd = np.maximum(target_psd, 1e-12)

        white_fft = np.fft.rfft(white)
        shaped_fft = white_fft * np.sqrt(target_psd / target_psd.max())
        shaped = np.fft.irfft(shaped_fft, n=n)

        if shaped.std() > 0:
            shaped /= shaped.std()
        return shaped


# ------------------------------------------------------------------
# Module-level utility functions (no pickle, pure numpy)
# ------------------------------------------------------------------

def _asymmetric_rate_limit(arr, up_rate, down_rate):
    """Rate-limit with different speeds for increasing vs decreasing."""
    out = arr.copy()
    for i in range(1, len(out)):
        delta = out[i] - out[i - 1]
        if delta > up_rate:
            out[i] = out[i - 1] + up_rate
        elif delta < -down_rate:
            out[i] = out[i - 1] - down_rate
    return out


def _symmetric_rate_limit(arr, max_rate):
    """Rate-limit with same speed both directions."""
    out = arr.copy()
    for i in range(1, len(out)):
        delta = out[i] - out[i - 1]
        if abs(delta) > max_rate:
            out[i] = out[i - 1] + np.sign(delta) * max_rate
    return out


def _low_freq_noise(n, hz, rng, max_freq=1.0):
    """Generate low-frequency noise (fallback)."""
    t = np.arange(n) / hz
    result = np.zeros(n)
    for _ in range(4):
        f = rng.uniform(0.1, max_freq)
        phase = rng.uniform(0, 2 * np.pi)
        result += np.sin(2 * np.pi * f * t + phase)
    return result / 4.0
