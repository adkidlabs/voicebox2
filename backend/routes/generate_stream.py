"""WebSocket streaming generation (W3).

Net-new transport: streams engine-native audio chunks to the client as they
are generated instead of generate-then-play. Rest of the pipeline
(persistence, history, SSE status tracking) behaves exactly like ``POST
/generate`` — the streamed generation lands in history when it completes.

Protocol (JSON messages):
  Client → server: one request (``GenerationRequest`` fields).
  Server → client:
    ``{"type": "started", "generation_id", "text"}``
    ``{"type": "status", "status": "loading_model"|"generating"}``
    ``{"type": "audio", "data": <base64 float32 PCM>, "sample_rate": N}``
    ``{"type": "done", "generation_id", "duration", "sample_rate", "audio_path"}``
    ``{"type": "error", "message"}``

Disconnect handling: a receiver task waits for the client's frames; on
``WebSocketDisconnect`` the generation is cancelled through the existing
task-queue cancellation (no zombie inference continues).
"""

import asyncio
import base64
import logging
import uuid

import numpy as np
from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from .. import models
from ..database import get_db
from ..services import history, profiles
from ..services.task_queue import cancel_generation as cancel_generation_job, enqueue_generation
from ..utils.tasks import get_task_manager

logger = logging.getLogger(__name__)

router = APIRouter()


def _resolve_generation_engine(data: models.GenerationRequest, profile) -> str:
    return data.engine or getattr(profile, "default_engine", None) or getattr(profile, "preset_engine", None) or "qwen"


@router.websocket("/generate/stream-ws")
async def stream_generate_ws(websocket: WebSocket):
    await websocket.accept()

    try:
        raw = await websocket.receive_text()
        data = models.GenerationRequest.model_validate_json(raw)
    except WebSocketDisconnect:
        return
    except Exception as e:
        await websocket.send_json({"type": "error", "message": f"Invalid request: {e}"})
        await websocket.close()
        return

    db = next(get_db())
    generation_id = str(uuid.uuid4())
    done_event = asyncio.Event()

    try:
        profile = await profiles.get_profile(data.profile_id, db)
        if not profile:
            await websocket.send_json({"type": "error", "message": "Profile not found"})
            await websocket.close()
            return

        engine = _resolve_generation_engine(data, profile)
        try:
            profiles.validate_profile_engine(profile, engine)
        except ValueError as e:
            await websocket.send_json({"type": "error", "message": str(e)})
            await websocket.close()
            return

        from ..backends import engine_has_model_sizes

        model_size = (data.model_size or "1.7B") if engine_has_model_sizes(engine) else None

        text = data.text
        source = "manual"
        if data.personality and getattr(profile, "personality", None):
            from ..services import personality as personality_mod

            try:
                llm_result = await personality_mod.rewrite_as_profile(profile.personality, data.text)
            except ValueError as e:
                await websocket.send_json({"type": "error", "message": str(e)})
                await websocket.close()
                return
            text = llm_result.text.strip()
            if not text:
                await websocket.send_json({"type": "error", "message": "LLM produced empty output."})
                await websocket.close()
                return
            source = "personality_speak"

        await history.create_generation(
            profile_id=data.profile_id,
            text=text,
            language=data.language,
            audio_path="",
            duration=0,
            seed=data.seed,
            db=db,
            instruct=data.instruct,
            generation_id=generation_id,
            status="generating",
            engine=engine,
            model_size=model_size if engine_has_model_sizes(engine) else None,
            source=source,
        )

        get_task_manager().start_generation(
            task_id=generation_id,
            profile_id=data.profile_id,
            text=text,
        )

        # Tell the client the id up-front so it can track the row (history
        # "Generating..." + SSE status) exactly like the REST flow.
        try:
            await websocket.send_json(
                {"type": "started", "generation_id": generation_id, "text": text}
            )
        except Exception:
            return

        effects_chain_config = None
        if data.effects_chain is not None:
            effects_chain_config = [e.model_dump() for e in data.effects_chain]
        else:
            import json as _json

            from ..database import VoiceProfile as DBVoiceProfile

            row = db.query(DBVoiceProfile).filter_by(id=data.profile_id).first()
            if row and row.effects_chain:
                try:
                    effects_chain_config = _json.loads(row.effects_chain)
                except Exception:
                    pass

        async def run_streaming() -> None:
            bg_db = next(get_db())
            try:
                from ..backends import (
                    engine_needs_trim,
                    engine_retries_runaway,
                    get_tts_backend_for_engine,
                    load_engine_model,
                )
                from ..utils.audio import has_tts_runaway, normalize_audio, save_audio, trim_tts_output
                from ..utils.chunked_tts import generate_chunked_streaming

                tts_model = get_tts_backend_for_engine(engine)
                if not tts_model.is_loaded():
                    await history.update_generation_status(generation_id, "loading_model", bg_db)
                    try:
                        await websocket.send_json({"type": "status", "status": "loading_model"})
                    except Exception:
                        return

                await load_engine_model(engine, model_size)

                voice_prompt = await profiles.create_voice_prompt_for_profile(
                    data.profile_id,
                    bg_db,
                    engine=engine,
                )

                await history.update_generation_status(generation_id, "generating", bg_db)
                try:
                    await websocket.send_json({"type": "status", "status": "generating"})
                except Exception:
                    return

                async def on_chunk(audio: np.ndarray, sr: int) -> None:
                    payload = base64.b64encode(
                        np.asarray(audio, dtype=np.float32).tobytes()
                    ).decode("ascii")
                    await websocket.send_json(
                        {"type": "audio", "data": payload, "sample_rate": int(sr)}
                    )

                audio, sample_rate = await generate_chunked_streaming(
                    tts_model,
                    text,
                    voice_prompt,
                    on_chunk,
                    language=data.language,
                    seed=data.seed,
                    max_chunk_chars=data.max_chunk_chars,
                    crossfade_ms=data.crossfade_ms,
                    trim_fn=trim_tts_output if engine_needs_trim(engine) else None,
                    runaway_detector=has_tts_runaway if engine_retries_runaway(engine) else None,
                )

                if data.normalize:
                    audio = normalize_audio(audio)

                duration = len(audio) / sample_rate

                from ..services.generation import _save_generate

                final_path = _save_generate(
                    generation_id=generation_id,
                    audio=audio,
                    sample_rate=sample_rate,
                    effects_chain=effects_chain_config,
                    save_audio=save_audio,
                    db=bg_db,
                )

                await history.update_generation_status(
                    generation_id=generation_id,
                    status="completed",
                    db=bg_db,
                    audio_path=final_path,
                    duration=duration,
                )
                try:
                    await websocket.send_json(
                        {
                            "type": "done",
                            "generation_id": generation_id,
                            "duration": duration,
                            "sample_rate": int(sample_rate),
                            "audio_path": final_path,
                        }
                    )
                except Exception:
                    pass
            except asyncio.CancelledError:
                await history.update_generation_status(
                    generation_id=generation_id,
                    status="failed",
                    db=bg_db,
                    error="Generation cancelled",
                )
            except Exception as e:
                logger.exception("WS generation %s failed", generation_id)
                await history.update_generation_status(
                    generation_id=generation_id,
                    status="failed",
                    db=bg_db,
                    error=str(e),
                )
                try:
                    await websocket.send_json({"type": "error", "message": str(e)})
                except Exception:
                    pass
            finally:
                get_task_manager().complete_generation(generation_id)
                bg_db.close()
                done_event.set()

        async def receive_loop() -> None:
            """Block until the client disconnects; then cancel the generation."""
            try:
                while True:
                    # Ignore client frames; disconnect raises WebSocketDisconnect.
                    await websocket.receive_text()
            except WebSocketDisconnect:
                cancelled = cancel_generation_job(generation_id)
                if cancelled:
                    logger.info("WS client disconnected — cancelled generation %s", generation_id)

        enqueue_generation(generation_id, run_streaming())

        receiver = asyncio.create_task(receive_loop())
        await done_event.wait()
        receiver.cancel()
        try:
            await receiver
        except (asyncio.CancelledError, Exception):
            pass

    except WebSocketDisconnect:
        cancel_generation_job(generation_id)
    finally:
        db.close()
