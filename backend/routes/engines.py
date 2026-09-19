"""Engine registry endpoints."""

from fastapi import APIRouter

router = APIRouter()


@router.get("/engines")
async def list_engines():
    """List all registered TTS engines with picker + download metadata."""
    from ..backends.registry import list_engine_descriptors

    return {"engines": list_engine_descriptors()}
