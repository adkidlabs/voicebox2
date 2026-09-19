"""
MOSS-TTS-Nano backend (custom macOS build, W1).

Wraps the upstream ``moss_tts_nano_runtime.NanoTTSService`` as a Voicebox
``TTSBackend``.  MOSS-TTS-Nano is a 0.1B autoregressive TTS model: CPU
realtime, 48 kHz stereo output, zero-shot cloning from a ~3 s reference
clip, and 16 built-in preset voices (of which ``assets/audio`` ships the
reference clips that are bundled in ``backend/vendor/moss``).

Integration notes
-----------------
- The runtime code is vendored under ``backend/vendor/moss/`` so the frozen
  bundle never depends on a live ``git+https`` pip install.  The adapter adds
  that directory to ``sys.path`` and imports the runtime lazily, so importing
  this module never pulls in torch/transformers.
- Both untrusted-remote-code repos (checkpoint + audio tokenizer) are
  downloaded into the HF cache by the in-app model-download flow
  (``POST /models/download``).  Once cached, the runtime loads with
  ``local_files_only=True`` and works fully offline.
- The runtime speaks stereo; the rest of Voicebox's pipeline is mono, so
  ``generate()`` downmixes to mono before returning (same reliability as all
  other engines; native stereo is preserved in the runtime's own write-out
  path).
"""

from __future__ import annotations

import asyncio
import logging
import sys
from pathlib import Path

import numpy as np

from .base import (
    combine_voice_prompts as _combine_voice_prompts,
    async_iter_from_sync,
    model_load_progress,
)

logger = logging.getLogger(__name__)

MOSS_CHECKPOINT_REPO = "OpenMOSS-Team/MOSS-TTS-Nano"
MOSS_AUDIO_TOKENIZER_REPO = "OpenMOSS-Team/MOSS-Audio-Tokenizer-Nano"
MOSS_SAMPLE_RATE = 48000
MOSS_DEFAULT_VOICE = "Junhao"

_VENDOR_ROOT = Path(__file__).resolve().parent.parent / "vendor" / "moss"


def _ensure_runtime_importable() -> None:
    """Put the vendored MOSS runtime on ``sys.path`` (idempotent)."""
    vendor_path = str(_VENDOR_ROOT)
    if vendor_path not in sys.path:
        sys.path.insert(0, vendor_path)


def _patch_torchaudio_codec() -> None:
    """torchaudio>=2.9 delegates load()/save() to torchcodec; when it's
    missing (this bundle), fall back to soundfile.

    The MOSS model's remote code (modeling_moss_tts_nano.py) calls
    torchaudio.load for reference audio and torchaudio.save for output wavs —
    on torchaudio 2.11 both raise ImportError without torchcodec. Same
    pattern as utils/dac_shim.py: patch only what the engine uses.
    """
    import torchaudio

    try:
        import torchcodec  # noqa: F401

        return  # torchcodec present — upstream path works
    except ImportError:
        pass

    if getattr(torchaudio, "_voicebox_sf_fallback", False):
        return

    import soundfile as sf
    import torch

    def _sf_load(filepath, *args, **kwargs):
        data, sample_rate = sf.read(str(filepath), dtype="float32", always_2d=True)
        # (frames, channels) → (channels, frames) — torchaudio convention
        return torch.from_numpy(data.T.copy()), int(sample_rate)

    def _sf_save(uri, src, sample_rate, channels_first=True, format=None, **kwargs):
        tensor = src.detach().cpu().numpy()
        if tensor.ndim == 2 and channels_first:
            tensor = tensor.T  # (channels, frames) → (frames, channels)
        elif tensor.ndim == 1:
            tensor = tensor[:, None]
        sf.write(str(uri), tensor.astype("float32"), int(sample_rate))

    torchaudio.load = _sf_load
    torchaudio.save = _sf_save
    torchaudio._voicebox_sf_fallback = True
    logger.info("torchaudio torchcodec missing — soundfile fallback patched for MOSS")


def _runtime():
    """Lazily import the vendored runtime (imports torch/transformers)."""
    _ensure_runtime_importable()
    import moss_tts_nano_runtime

    return moss_tts_nano_runtime


def _available_voice_presets() -> list[dict]:
    """Return the built-in preset voices whose bundled reference clips exist."""
    rt = _runtime()
    presets = rt.build_default_voice_presets()
    voices = []
    for name, preset in presets.items():
        if preset.prompt_audio_path.is_file():
            voices.append({"voice_id": name, "display_name": name, "description": preset.description})
    return voices


class MossTtsNanoBackend:
    """MOSS-TTS-Nano zero-shot cloning backend (48 kHz)."""

    def __init__(self):
        self._service = None
        self.model_size = "default"

    def is_loaded(self) -> bool:
        return self._service is not None and self._service._model is not None

    def _get_model_path(self, model_size: str) -> str:
        return MOSS_CHECKPOINT_REPO

    def _is_model_cached(self, model_size: str = "default") -> bool:
        from .base import is_model_cached

        return is_model_cached(MOSS_CHECKPOINT_REPO) and is_model_cached(MOSS_AUDIO_TOKENIZER_REPO)

    @classmethod
    def engine_descriptor(cls):
        """Build the EngineDescriptor for the registry (see backends/registry.py)."""
        from . import TTS_ENGINES
        from .registry import EngineDescriptor

        return EngineDescriptor(
            engine="moss_tts_nano",
            display_name=TTS_ENGINES["moss_tts_nano"],
            description=(
                "MOSS-TTS-Nano: 0.1B, CPU-realtime, 48 kHz, zero-shot cloning "
                "and 8 bundled preset voices across zh/en/jp (Apache-2.0)."
            ),
            sample_rate=MOSS_SAMPLE_RATE,
            languages=["zh", "en", "ja", "de", "fr", "ko", "ru", "pt", "es", "it"],
            supports_cloning=True,
            supports_presets=True,
            supports_streaming=False,
            supports_mps=False,
            license="Apache-2.0",
            min_ram_gb=1.0,
            preset_voices=_available_voice_presets(),
        )

    async def load_model(self, model_size: str = "default") -> None:
        if self.is_loaded():
            return
        await asyncio.to_thread(self._load_model_sync)

    def _load_model_sync(self) -> None:
        rt = _runtime()
        _patch_torchaudio_codec()
        is_cached = self._is_model_cached()

        with model_load_progress("moss-tts-nano", is_cached):
            logger.info("Loading MOSS-TTS-Nano on CPU (fp32)...")
            self._service = rt.NanoTTSService(
                checkpoint_path=MOSS_CHECKPOINT_REPO,
                audio_tokenizer_path=MOSS_AUDIO_TOKENIZER_REPO,
                device="cpu",
                dtype="float32",
                output_dir=str(self._service_output_dir()),
                voice_presets=None,
            )
            self._service.get_model()
            # Warm the audio tokenizer inside the tracked load too — it would
            # otherwise download silently (outside any progress patch) at the
            # first synthesize() call.
            self._service._load_audio_tokenizer_locked(tts_attn_implementation="sdpa")
            logger.info("MOSS-TTS-Nano loaded successfully")

    def _service_output_dir(self) -> Path:
        from ..config import get_cache_dir

        cache = Path(get_cache_dir())
        out_dir = cache / "moss-nano"
        out_dir.mkdir(parents=True, exist_ok=True)
        return out_dir

    def unload_model(self) -> None:
        if self._service is not None:
            self._service = None
            logger.info("MOSS-TTS-Nano unloaded")

    async def create_voice_prompt(
        self,
        audio_path: str,
        reference_text: str,
        use_cache: bool = True,
    ) -> tuple[dict, bool]:
        # The runtime reads the reference clip directly during synthesis, so
        # the "prompt" is just a deferred reference to the sample file — cheap.
        return {
            "voice_type": "cloned",
            "prompt_audio_path": str(Path(audio_path).resolve()),
            "reference_text": reference_text or "",
        }, False

    async def combine_voice_prompts(
        self,
        audio_paths: list[str],
        reference_texts: list[str],
    ) -> tuple[np.ndarray, str]:
        return await _combine_voice_prompts(
            audio_paths, reference_texts, sample_rate=MOSS_SAMPLE_RATE
        )

    async def generate(
        self,
        text: str,
        voice_prompt: dict,
        language: str = "en",
        seed: int | None = None,
        instruct: str | None = None,
    ) -> tuple[np.ndarray, int]:
        await self.load_model()
        return await asyncio.to_thread(self._generate_sync, text, voice_prompt, seed)

    async def stream_generate(
        self,
        text: str,
        voice_prompt: dict,
        language: str = "en",
        seed: int | None = None,
        instruct: str | None = None,
    ):
        """Yield (audio_chunk, sample_rate) per segment as generated (W3).

        Wraps the runtime's ``synthesize_stream`` — it emits one audio event
        per voice-clone text segment plus a final full result (skipped; the
        caller's pipeline concatenates the segments itself).
        """
        await self.load_model()
        kwargs = self._build_synthesize_kwargs(text, voice_prompt, seed)
        async for item in async_iter_from_sync(self._stream_chunks_sync, kwargs):
            yield item

    def _stream_chunks_sync(self, kwargs: dict):
        service = self._service
        if service is None:
            raise RuntimeError("MOSS-TTS-Nano model is not loaded")

        for event in service.synthesize_stream(**kwargs):
            if str(event.get("type", "")) != "audio":
                continue
            waveform = np.asarray(event["waveform_numpy"], dtype=np.float32)
            if waveform.ndim == 2:
                waveform = waveform.mean(axis=1).astype(np.float32)
            yield waveform, int(event["sample_rate"]) or MOSS_SAMPLE_RATE

    def _build_synthesize_kwargs(
        self,
        text: str,
        voice_prompt: dict,
        seed: int | None,
    ) -> dict:
        voice_type = voice_prompt.get("voice_type", "cloned")
        prompt_path = voice_prompt.get("prompt_audio_path") or voice_prompt.get("audio_path")

        kwargs = {
            "text": str(text).strip(),
            "mode": "voice_clone",
        }
        if voice_type == "preset":
            preset_name = voice_prompt.get("preset_voice_id")
            if not preset_name:
                raise ValueError("MOSS preset profile is missing preset_voice_id")
            kwargs["voice"] = str(preset_name)
        else:
            if not prompt_path or not Path(prompt_path).is_file():
                raise ValueError("MOSS cloned profile requires a reference audio sample")
            kwargs["voice"] = None
            kwargs["prompt_audio_path"] = str(prompt_path)

        if seed is not None:
            kwargs["seed"] = int(seed)
        return kwargs

    def _generate_sync(
        self,
        text: str,
        voice_prompt: dict,
        seed: int | None,
    ) -> tuple[np.ndarray, int]:
        service = self._service
        if service is None:
            raise RuntimeError("MOSS-TTS-Nano model is not loaded")

        kwargs = self._build_synthesize_kwargs(text, voice_prompt, seed)

        result = service.synthesize(**kwargs)

        waveform = np.asarray(result["waveform_numpy"], dtype=np.float32)
        # waveform_to_numpy guarantees (frames, channels) — mix to mono over
        # the channel axis. (axis=0 would collapse time!)
        if waveform.ndim == 2:
            waveform = waveform.mean(axis=1).astype(np.float32)

        return waveform, int(result["sample_rate"]) or MOSS_SAMPLE_RATE
