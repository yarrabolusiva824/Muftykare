import asyncio
from livekit import rtc
from livekit.agents.utils.audio import audio_frames_from_file

_cache: dict[str, list[rtc.AudioFrame]] = {}
_lock = asyncio.Lock()

async def _get_cached_frames(file_path: str) -> list[rtc.AudioFrame]:
    if file_path not in _cache:
        async with _lock:
            if file_path not in _cache:  # re-check after acquiring lock
                frames = []
                async for frame in audio_frames_from_file(file_path):
                    frames.append(frame)
                _cache[file_path] = frames
    return _cache[file_path]

async def looping_cached_audio(file_path: str):
    """Infinite generator that replays pre-decoded frames — no decode work per call."""
    frames = await _get_cached_frames(file_path)
    if not frames:
        return
    while True:
        for frame in frames:
            yield frame

async def warm_ambience_cache(file_path: str) -> None:
    """Decode and cache the file ahead of time so playback never blocks on it."""
    await _get_cached_frames(file_path)


async def make_ambient_generator(file_path: str):
    """
    Decode audio into memory, return an infinite in-memory async generator.
    The returned generator has ZERO awaits inside — pure list iteration only.
    Decode happens here, before the generator is created.
    """
    frames = await _get_cached_frames(file_path)

    async def _loop():
        if not frames:
            return
        while True:
            for frame in frames:
                yield frame

    return _loop()
