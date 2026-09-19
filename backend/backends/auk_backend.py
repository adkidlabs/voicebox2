"""
AuK backend adapter (custom macOS build, W1) — EXPERIMENTAL.

Wraps the upstream ``AukInfer`` (AuK / AuK-Flash, a 1.5B speech generation +
editing foundation model) as a Voicebox ``TTSBackend`` for zero-shot cloning.

Status: experimental.  AuK needs ~14 GB of weights (``tencent/AuK-Flash``
plus the ``Qwen/Qwen2.5-Omni-3B`` text encoder), its upstream pins
``torch>=2.7,<2.8`` (Voicebox ships torch 2.14 — we do NOT downgrade), and
coverage is zh/en only.  It is therefore registered with
``experimental=True``; runtime verification against torch 2.14 on the M1 Pro
is a planned follow-up once the weights are cached.

Integration notes
-----------------
- All AuK imports are lazy (load/generate only) so importing this module is
  safe even when the ``auk`` package or its heavy deps aren't installed.
- The ``auk`` python package is pip-installed into the venv with --no-deps
  (its requirements would otherwise force a torch downgrade).  The Frozen
  build bundles it via ``--collect-all auk``.
- Weights and the Qwen text encoder are pulled into the HF cache by the
  in-app model-download flow; ``snapshot_download`` is used at load time so
  nothing runs until both repos are actually cached.
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path

import numpy as np

from .base import (
    combine_voice_prompts as _combine_voice_prompts,
    model_load_progress,
)

logger = logging.getLogger(__name__)

AUK_FLASH_REPO = "tencent/AuK-Flash"
AUK_BASE_REPO = "tencent/AuK"
AUK_QWEN_REPO = "Qwen/Qwen2.5-Omni-3B"
AUK_SAMPLE_RATE = 24000

# AuK-Flash ships config.yaml + auk_flash.safetensors + vae.safetensors in
# the same snapshot.  We default to Flash (4-step / CFG-off distilled recipe)
# as the sensible CPU/M1 variant.
AUK_DEFAULT_REPO = AUK_FLASH_REPO
AUK_CKPT_BASENAME = "auk_flash.safetensors"


def _download_repo(repo_id: str) -> Path:
    """Snapshot *repo_id* into the HF cache and return its snapshot dir."""
    from huggingface_hub import snapshot_download

    snapshot = snapshot_download(repo_id)
    return Path(snapshot)


class AukBackend:
    """AuK-Flash zero-shot cloning backend (experimental, zh/en)."""

    def __init__(self):
        self._engine = None
        self.model_size = "default"

    def is_loaded(self) -> bool:
        return self._engine is not None

    def _get_model_path(self, model_size: str) -> str:
        return AUK_DEFAULT_REPO

    def _is_model_cached(self, model_size: str = "default") -> bool:
        from .base import is_model_cached

        return is_model_cached(AUK_DEFAULT_REPO) and is_model_cached(AUK_QWEN_REPO)

    @classmethod
    def engine_descriptor(cls):
        from . import TTS_ENGINES
        from .registry import EngineDescriptor

        return EngineDescriptor(
            engine="auk",
            display_name=TTS_ENGINES["auk"],
            description=(
                "AuK-Flash: 1.5B speech generation foundation model, zero-shot "
                "cloning, zh/en only, ~14GB with the Qwen2.5-Omni text encoder "
                "(MIT). Experimental on this build."
            ),
            sample_rate=AUK_SAMPLE_RATE,
            languages=["zh", "en"],
            supports_cloning=True,
            supports_presets=False,
            supports_streaming=False,
            supports_mps=False,
            license="MIT",
            min_ram_gb=16.0,
            experimental=True,
            preset_voices=[],
        )

    async def load_model(self, model_size: str = "default") -> None:
        if self.is_loaded():
            return
        await asyncio.to_thread(self._load_model_sync)

    def _load_model_sync(self) -> None:

        is_cached = self._is_model_cached()

        with model_load_progress("auk", is_cached):
            logger.info("Loading AuK-Flash (experimental) on CPU...")

            # 1. Ensure both weight repos are in the HF cache.
            auk_dir = _download_repo(AUK_DEFAULT_REPO)
            qwen_dir = _download_repo(AUK_QWEN_REPO)

            ckpt = auk_dir / AUK_CKPT_BASENAME
            if not ckpt.is_file():
                candidates = [p for p in auk_dir.glob("*.safetensors") if p.name != "vae.safetensors"]
                if not candidates:
                    raise FileNotFoundError(f"No AuK checkpoint found under {auk_dir}")
                ckpt = candidates[0]

            config_path = auk_dir / "config.yaml"
            if not config_path.is_file():
                raise FileNotFoundError(f"config.yaml not found next to checkpoint: {auk_dir}")

            # 2. Build the inference engine (lazy heavy imports).
            try:
                from auk.infer.infer_auk import AukInfer
            except ImportError as e:
                raise RuntimeError(
                    "AuK runtime is not installed in this build. "
                    "Install it with: pip install --no-deps <auk-checkout> "
                    "plus qwen-omni-utils, omegaconf, torchdiffeq, x_transformers."
                ) from e

            self._engine = AukInfer(
                config_path=str(config_path),
                ckpt_path=str(ckpt),
                device="cpu",
                dtype="fp32",
                qwen_path=str(qwen_dir),
                cpu_offload=False,
            )
            logger.info("AuK-Flash loaded successfully")

    def unload_model(self) -> None:
        if self._engine is not None:
            self._engine = None
            logger.info("AuK unloaded")

    async def create_voice_prompt(
        self,
        audio_path: str,
        reference_text: str,
        use_cache: bool = True,
    ) -> tuple[dict, bool]:
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
            audio_paths, reference_texts, sample_rate=AUK_SAMPLE_RATE
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

    def _generate_sync(
        self,
        text: str,
        voice_prompt: dict,
        seed: int | None,
    ) -> tuple[np.ndarray, int]:
        engine = self._engine
        if engine is None:
            raise RuntimeError("AuK model is not loaded")

        prompt_path = voice_prompt.get("prompt_audio_path") or voice_prompt.get("audio_path")
        if not prompt_path or not Path(prompt_path).is_file():
            raise ValueError("AuK cloned profile requires a reference audio sample")
        prompt_path = str(Path(prompt_path).resolve())
        ref_text = voice_prompt.get("reference_text") or ""

        target_text = str(text).strip()
        if not target_text:
            raise ValueError("text is required")

        # AuK is instruction-driven: the target text lives in the instruction.
        instruction = f"Say the following with the same voice: '{target_text}'"

        try:
            from auk.infer.infer_auk import get_gen_duration
        except ImportError as e:
            raise RuntimeError("AuK runtime is not installed in this build.") from e

        gen_seconds = get_gen_duration(
            audio=prompt_path,
            ref_text=ref_text,
            gen_text=target_text,
            gen_seconds=None,
        ) or max(3.0, min(len(target_text) / 10.0, 30.0))

        messages = [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": instruction},
                    {"type": "audio", "audio": prompt_path},
                ],
            }
        ]

        audio_tensor, sample_rate = engine.generate(
            messages,
            audio=prompt_path,
            gen_seconds=gen_seconds,
            seed=int(seed) if seed is not None else None,
        )

        waveform = audio_tensor.detach().cpu().numpy()
        if waveform.ndim > 1:
            waveform = waveform.squeeze(0)
        return waveform.astype(np.float32), int(sample_rate) or AUK_SAMPLE_RATE
