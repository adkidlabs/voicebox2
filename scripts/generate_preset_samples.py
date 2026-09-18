"""Generate static preset-voice preview samples for the offline custom build.

Writes one short WAV per Kokoro preset voice into
``backend/static/preset_samples/kokoro/<voice_id>.wav``. The samples are
bundled with the frozen app and served by the backend at
``/preset-samples`` so preset rows can show a play button without loading
the model at runtime.

Run once at build/dev time (requires the Kokoro weights cached):

    backend/venv/bin/python scripts/generate_preset_samples.py

Skips voices whose sample already exists unless ``--force`` is passed.
"""

import argparse
import asyncio
import sys
from pathlib import Path

BACKEND_STATIC = Path(__file__).resolve().parent.parent / "backend" / "static"
OUT_DIR = BACKEND_STATIC / "preset_samples" / "kokoro"

SAMPLE_TEXT = {
    "en": "This is a custom build of Voicebox, running entirely offline.",
    "es": "Este es un ejemplo de voz para Voicebox.",
    "fr": "Voici un échantillon de voix pour Voicebox.",
    "hi": "यह Voicebox के लिए एक नमूना आवाज़ है।",
    "it": "Questo è un esempio di voce per Voicebox.",
    "pt": "Este é um exemplo de voz para o Voicebox.",
    "ja": "これはVoicebox用の音声サンプルです。",
    "zh": "这是Voicebox的语音示例。",
}


async def generate() -> int:
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

    from backend.utils.audio import normalize_audio, save_audio
    from backend.backends.kokoro_backend import KOKORO_VOICES, KokoroTTSBackend

    backend = KokoroTTSBackend()

    total = 0
    failed = []

    await backend.load_model()

    for voice_id, name, gender, lang in KOKORO_VOICES:
        out = OUT_DIR / f"{voice_id}.wav"
        if out.exists() and not ARGS.force:
            continue

        text = SAMPLE_TEXT.get(lang, SAMPLE_TEXT["en"])
        voice_prompt = {
            "voice_type": "preset",
            "preset_engine": "kokoro",
            "preset_voice_id": voice_id,
        }

        try:
            audio, sample_rate = await backend.generate(text, voice_prompt, language=lang)
        except Exception as exc:  # misaki lang pack (e.g. ja) may be missing
            try:
                audio, sample_rate = await backend.generate(
                    SAMPLE_TEXT["en"], voice_prompt, language="en"
                )
            except Exception:
                failed.append(voice_id)
                print(f"  skip {voice_id}: {exc}", file=sys.stderr)
                continue
        try:
            audio = normalize_audio(audio, target_db=-18.0)
            out.parent.mkdir(parents=True, exist_ok=True)
            save_audio(audio, str(out), sample_rate=sample_rate)
            total += 1
            print(f"  ok  {voice_id} ({name}, {lang}) -> {out.name}")
        except Exception as exc:
            failed.append(voice_id)
            print(f"  skip {voice_id}: {exc}", file=sys.stderr)

    backend.unload_model()
    print(f"generated {total} fresh samples; {len(failed)} skipped")
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--force", action="store_true", help="regenerate existing samples")
    ARGS = parser.parse_args()
    sys.exit(asyncio.run(generate()))