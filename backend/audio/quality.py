"""
Reference-audio quality scoring for voice cloning (W2, additive).

``score_reference_audio`` inspects a candidate clone sample and returns a
0-100 score plus a list of non-blocking warnings. It is *pure-warning*:
callers (the pre-flight ``POST /profiles/quality-check`` endpoint, the
profile-creation UI badge) surface the result but never reject the sample —
hard validation stays in ``utils.audio.validate_and_load_reference_audio``.

Metrics are computed on the raw loaded waveform (no preprocessing), so
clipping and noise stay visible. Only numpy + librosa are used — both are
already in the frozen bundle.
"""

from __future__ import annotations

import numpy as np

from ..utils.audio import load_audio

_FRAME_MS = 20.0
_SILENCE_THRESHOLD_DB = -40.0


def _frame_rms(audio: np.ndarray, frame_len: int) -> np.ndarray:
    n_frames = len(audio) // frame_len
    if n_frames == 0:
        return np.array([np.sqrt(np.mean(audio**2))], dtype=np.float64)
    frames = audio[: n_frames * frame_len].reshape(n_frames, frame_len)
    return np.sqrt(np.mean(frames**2, axis=1))


def score_reference_audio(audio_path: str) -> dict:
    """Score a reference-audio file for cloning suitability.

    Returns a dict with:
      - ``score``: int 0-100 (higher is better; clean speech ≈ 90+).
      - ``warnings``: list of ``{"code", "message", "severity"}`` where
        severity is ``"warn"`` or ``"error"`` (errors still don't block —
        they flag samples that will clone badly).
      - ``metrics``: raw numbers (duration_s, rms_db, peak, clipping_ratio,
        silence_ratio, snr_db, dc_offset) for UI tooltips/debugging.
    """
    warnings: list[dict] = []

    def warn(code: str, message: str, severity: str = "warn") -> None:
        warnings.append({"code": code, "message": message, "severity": severity})

    try:
        audio, sr = load_audio(audio_path)
    except Exception as e:
        return {
            "score": 0,
            "warnings": [
                {
                    "code": "unreadable",
                    "message": f"Could not read audio file: {e}",
                    "severity": "error",
                }
            ],
            "metrics": {},
        }

    audio = np.asarray(audio, dtype=np.float64).ravel()
    duration_s = len(audio) / float(sr) if sr else 0.0
    if audio.size == 0 or duration_s <= 0:
        return {
            "score": 0,
            "warnings": [
                {"code": "empty", "message": "Audio file contains no samples.", "severity": "error"}
            ],
            "metrics": {"duration_s": 0.0},
        }

    peak = float(np.abs(audio).max())
    rms = float(np.sqrt(np.mean(audio**2)))
    rms_db = 20.0 * np.log10(rms) if rms > 0 else -120.0
    dc_offset = float(abs(np.mean(audio)))
    clipping_ratio = float(np.mean(np.abs(audio) >= 0.99))

    frame_len = max(1, int(sr * _FRAME_MS / 1000))
    frame_energies = _frame_rms(audio, frame_len)
    silence_threshold = 10 ** (_SILENCE_THRESHOLD_DB / 20)
    is_silence = frame_energies < silence_threshold
    silence_ratio = float(np.mean(is_silence)) if is_silence.size else 1.0

    speech_energy = frame_energies[~is_silence]
    # Noise floor from the 10th percentile of frame energy: robust even when
    # loud background noise means no frame falls below the silence threshold.
    floor = float(np.percentile(frame_energies, 10)) if frame_energies.size else 0.0
    speech_level = float(np.percentile(speech_energy, 90)) if speech_energy.size else 0.0
    if speech_level > 0 and floor > 0:
        snr_db = float(20.0 * np.log10(speech_level / floor))
        snr_db = max(-10.0, min(60.0, snr_db))
    elif speech_level > 0:
        snr_db = 60.0  # no measurable floor — treat as clean
    else:
        snr_db = -10.0  # all silence

    score = 100

    # — Duration (clone needs enough phonetic coverage) —
    if duration_s < 3.0:
        score -= 30
        warn("too_short", f"Only {duration_s:.1f}s of audio — aim for 6-20s for a reliable clone.", "error")
    elif duration_s < 6.0:
        score -= 10
        warn("short_sample", f"{duration_s:.1f}s is usable but 6-20s clones noticeably better.")
    elif duration_s > 30.0:
        score -= 5
        warn("long_sample", f"{duration_s:.1f}s exceeds 30s — only the most useful part may be used.")

    # — Level —
    if rms_db < -40.0:
        score -= 20
        warn("too_quiet", f"Very quiet (RMS {rms_db:.1f} dBFS) — record closer to the mic.", "error")
    elif rms_db < -30.0:
        score -= 8
        warn("quiet", f"Quiet recording (RMS {rms_db:.1f} dBFS) — a louder take clones better.")

    # — Clipping —
    if clipping_ratio > 0.01:
        score -= 25
        warn(
            "clipping",
            f"{clipping_ratio * 100:.1f}% of samples are clipped — lower the input gain and re-record.",
            "error",
        )
    elif clipping_ratio > 0.001:
        score -= 10
        warn("near_clipping", "Some samples near full scale — watch the input gain.")

    # — Noise (speech energy vs silence-floor energy) —
    if snr_db < 10.0:
        score -= 25
        warn("noisy", f"Low signal-to-noise ratio (~{snr_db:.0f} dB) — record in a quieter room.", "error")
    elif snr_db < 20.0:
        score -= 10
        warn("some_noise", f"Audible background noise (~{snr_db:.0f} dB SNR) — quieter is better.")

    # — Silence fraction —
    if silence_ratio > 0.8:
        score -= 30
        warn("mostly_silence", "Mostly silence — trim dead air before cloning.", "error")
    elif silence_ratio > 0.5:
        score -= 15
        warn("much_silence", "Over half is silence — trim it for a tighter clone.")

    # — DC offset —
    if dc_offset > 0.05:
        score -= 5
        warn("dc_offset", "Noticeable DC offset — usually harmless, a high-pass fixes it.")

    score = max(0, min(100, round(score)))

    return {
        "score": score,
        "warnings": warnings,
        "metrics": {
            "duration_s": round(duration_s, 2),
            "rms_db": round(rms_db, 1),
            "peak": round(peak, 3),
            "clipping_ratio": round(clipping_ratio, 4),
            "silence_ratio": round(silence_ratio, 3),
            "snr_db": round(snr_db, 1),
            "dc_offset": round(dc_offset, 4),
        },
    }
