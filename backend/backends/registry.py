"""
Engine registry layer (custom macOS build, W1).

Sits *over* the existing per-engine ``TTSBackend`` implementations and the
``TTS_ENGINES`` / ``ModelConfig`` registry in :mod:`backend.backends`.
It exposes declarative ``EngineDescriptor`` metadata so the UI can render an
engine picker, clone/preset affordances, and download options without
hardcoding engine names in the frontend.

Existing engines get their descriptor from a small static metadata table here
(they already define behavioral fingerprints via ``ModelConfig``/their backend
class).  New engines (MOSS-TTS-Nano, AuK) define a full descriptor on their
backend class through the ``ENGINE_DESCRIPTOR`` class attribute.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


def _configs_for_engine(engine: str) -> list[Any]:
    """Return the ``ModelConfig`` rows for *engine* (lazy import)."""
    from . import get_tts_model_configs

    return [c for c in get_tts_model_configs() if c.engine == engine]


@dataclass(frozen=True)
class EngineDescriptor:
    """Public, UI-facing declaration of a TTS engine."""

    engine: str
    display_name: str
    description: str
    sample_rate: int
    languages: list[str] = field(default_factory=lambda: ["en"])
    supports_cloning: bool = False
    supports_presets: bool = False
    supports_streaming: bool = False
    supports_mps: bool = False
    license: str = ""
    min_ram_gb: float = 0.0
    experimental: bool = False
    models: list[dict] = field(default_factory=list)
    preset_voices: list[dict] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "engine": self.engine,
            "display_name": self.display_name,
            "description": self.description,
            "sample_rate": self.sample_rate,
            "languages": self.languages,
            "supports_cloning": self.supports_cloning,
            "supports_presets": self.supports_presets,
            "supports_streaming": self.supports_streaming,
            "supports_mps": self.supports_mps,
            "license": self.license,
            "min_ram_gb": self.min_ram_gb,
            "experimental": self.experimental,
            "models": self.models,
            "preset_voices": self.preset_voices,
        }

    def with_models(self) -> EngineDescriptor:
        """Attach the engine's downloadable model variants from the registry."""
        models = []
        for cfg in _configs_for_engine(self.engine):
            models.append(
                {
                    "model_name": cfg.model_name,
                    "display_name": cfg.display_name,
                    "model_size": cfg.model_size,
                    "hf_repo_id": cfg.hf_repo_id,
                    "size_mb": cfg.size_mb,
                }
            )
        return EngineDescriptor(
            engine=self.engine,
            display_name=self.display_name,
            description=self.description,
            sample_rate=self.sample_rate,
            languages=self.languages,
            supports_cloning=self.supports_cloning,
            supports_presets=self.supports_presets,
            supports_streaming=self.supports_streaming,
            supports_mps=self.supports_mps,
            license=self.license,
            min_ram_gb=self.min_ram_gb,
            experimental=self.experimental,
            models=models,
            preset_voices=self.preset_voices,
        )


# Static metadata for the pre-existing engines.  The two new engines
# (MOSS-TTS-Nano, AuK) declare ``ENGINE_DESCRIPTOR`` on their backend class.
_ENGINE_META: dict[str, dict] = {
    "qwen": {
        "description": "Multilingual Qwen3-TTS, two sizes.",
        "sample_rate": 24000,
        "languages": ["zh", "en", "ja", "ko", "de", "fr", "ru", "pt", "es", "it"],
        "supports_cloning": True,
        "supports_presets": False,
        "supports_streaming": True,
        "supports_mps": True,
        "license": "Apache-2.0",
        "min_ram_gb": 6.0,
    },
    "qwen_custom_voice": {
        "description": "Qwen3-TTS with fixed preset voices and instruct control.",
        "sample_rate": 24000,
        "languages": ["zh", "en", "ja", "ko", "de", "fr", "ru", "pt", "es", "it"],
        "supports_cloning": False,
        "supports_presets": True,
        "supports_streaming": False,
        "supports_mps": True,
        "license": "Apache-2.0",
        "min_ram_gb": 6.0,
    },
    "luxtts": {
        "description": "Fast, English-focused voice cloning.",
        "sample_rate": 22050,
        "languages": ["en"],
        "supports_cloning": True,
        "supports_presets": False,
        "supports_streaming": False,
        "supports_mps": False,
        "license": "MIT",
        "min_ram_gb": 2.0,
    },
    "chatterbox": {
        "description": "Multilingual voice cloning in 23 languages.",
        "sample_rate": 16000,
        "languages": ["zh", "en", "ja", "ko", "de", "fr", "ru", "pt", "es", "it", "he", "ar", "da", "el", "fi", "hi", "ms", "nl", "no", "pl", "sv", "sw", "tr"],
        "supports_cloning": True,
        "supports_presets": False,
        "supports_streaming": False,
        "supports_mps": False,
        "license": "MIT",
        "min_ram_gb": 8.0,
    },
    "chatterbox_turbo": {
        "description": "English-focused Chatterbox with para tags ([laugh]).",
        "sample_rate": 16000,
        "languages": ["en"],
        "supports_cloning": True,
        "supports_presets": False,
        "supports_streaming": False,
        "supports_mps": False,
        "license": "MIT",
        "min_ram_gb": 4.0,
    },
    "kokoro": {
        "description": "82M-param CPU-realtime engine with preset voices.",
        "sample_rate": 24000,
        "languages": ["en", "es", "fr", "hi", "it", "pt", "ja", "zh"],
        "supports_cloning": False,
        "supports_presets": True,
        "supports_streaming": False,
        "supports_mps": True,
        "license": "Apache-2.0",
        "min_ram_gb": 0.5,
    },
}


def _backend_descriptor_attr(engine: str, attr: str, default: Any = None) -> Any:
    """Look up ``__dict__``/class ``ENGINE_DESCRIPTOR`` -- not used yet; kept for new engines."""
    return default


def build_descriptor(engine: str) -> EngineDescriptor | None:
    """Build the engine descriptor for *engine*.

    Order of precedence:
      1. An ``engine_descriptor()`` classmethod on the backend class (new
         engines can lazily inspect the runtime, e.g. bundled preset voices).
      2. A class-level ``ENGINE_DESCRIPTOR`` attribute on the backend class.
      3. The static metadata table for pre-existing engines.
    """
    from . import get_tts_backend_for_engine

    backend = None
    try:
        backend = get_tts_backend_for_engine(engine)
    except Exception:
        backend = None

    descriptor: EngineDescriptor | None = None
    if backend is not None:
        descriptor_ctor = getattr(backend, "engine_descriptor", None)
        if callable(descriptor_ctor):
            try:
                candidate = descriptor_ctor()
                if isinstance(candidate, EngineDescriptor):
                    descriptor = candidate
            except Exception:
                descriptor = None

        if descriptor is None:
            descriptor = getattr(backend, "ENGINE_DESCRIPTOR", None)

    if isinstance(descriptor, EngineDescriptor):
        return descriptor.with_models()

    meta = _ENGINE_META.get(engine)
    if meta is None:
        return None

    preset_voices: list[dict] = []
    if meta.get("supports_presets"):
        from .kokoro_backend import KOKORO_VOICES
        from .qwen_custom_voice_backend import QWEN_CUSTOM_VOICES

        if engine == "kokoro":
            preset_voices = [{"voice_id": v[0], "display_name": v[1]} for v in KOKORO_VOICES]
        elif engine == "qwen_custom_voice":
            preset_voices = [{"voice_id": v[0], "display_name": v[1]} for v in QWEN_CUSTOM_VOICES]

    descriptor = EngineDescriptor(
        engine=engine,
        display_name=_display_name(engine),
        description=meta["description"],
        sample_rate=meta["sample_rate"],
        languages=meta["languages"],
        supports_cloning=meta.get("supports_cloning", False),
        supports_presets=meta.get("supports_presets", False),
        supports_streaming=meta.get("supports_streaming", False),
        supports_mps=meta.get("supports_mps", False),
        license=meta["license"],
        min_ram_gb=meta["min_ram_gb"],
        experimental=meta.get("experimental", False),
        preset_voices=preset_voices,
    )
    return descriptor.with_models()


def _display_name(engine: str) -> str:
    from . import TTS_ENGINES

    return TTS_ENGINES.get(engine, engine.replace("_", " ").title())


def list_engine_descriptors() -> list[dict]:
    """Return serialized descriptors for every registered TTS engine."""
    from . import TTS_ENGINES

    descriptors: list[dict] = []
    for engine in TTS_ENGINES:
        descriptor = build_descriptor(engine)
        if descriptor is not None:
            descriptors.append(descriptor.to_dict())
    return descriptors


def get_engine_descriptor(engine: str) -> dict | None:
    """Return the serialized descriptor for a single engine, if registered."""
    descriptor = build_descriptor(engine)
    return descriptor.to_dict() if descriptor is not None else None
