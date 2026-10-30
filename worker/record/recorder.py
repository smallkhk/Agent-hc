"""Chunked session recording: raw frames piped into FFmpeg's segment muxer.

Files: STORAGE_DIR/recordings/<session>/<UTC start>.mp4, 10-min chunks, fragmented MP4 so a
crash or power loss only costs the last fragment, not the whole chunk.
"""

from __future__ import annotations

import asyncio
import logging
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

log = logging.getLogger("worker.record")

CHUNK_SEC = 600
NAME_FORMAT = "%Y%m%dT%H%M%SZ"


@dataclass(frozen=True)
class Chunk:
    path: Path
    started_at: datetime
    ended_at: datetime  # last write; still growing while the chunk is active
    size_bytes: int


def chunk_start(path: Path) -> datetime | None:
    try:
        return datetime.strptime(path.stem, NAME_FORMAT).replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def list_chunks(directory: Path) -> list[Chunk]:
    out = []
    for p in directory.glob("*.mp4"):
        start = chunk_start(p)
        if start is None:
            continue
        st = p.stat()
        out.append(Chunk(p, start, datetime.fromtimestamp(st.st_mtime, timezone.utc), st.st_size))
    return sorted(out, key=lambda c: c.started_at)


class Recorder:
    def __init__(self, directory: Path, fps: float, chunk_sec: int = CHUNK_SEC) -> None:
        self.dir = directory
        self.fps = fps
        self.chunk_sec = chunk_sec
        self.proc: asyncio.subprocess.Process | None = None
        self.size: tuple[int, int] | None = None

    @property
    def running(self) -> bool:
        return self.proc is not None and self.proc.returncode is None

    async def start(self, width: int, height: int) -> None:
        self.dir.mkdir(parents=True, exist_ok=True)
        cmd = [
            "ffmpeg", "-hide_banner", "-loglevel", "error", "-nostdin",
            # Frames arrive irregularly: stamp each with its arrival time so clips line up with events.
            "-use_wallclock_as_timestamps", "1",
            "-f", "rawvideo", "-pix_fmt", "yuv420p", "-s", f"{width}x{height}", "-i", "pipe:0",
            "-an", "-vf", "crop=trunc(iw/2)*2:trunc(ih/2)*2",  # x264 needs even dimensions
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "28", "-pix_fmt", "yuv420p",
            "-g", str(int(self.fps * 2)), "-fps_mode", "passthrough",
            "-f", "segment", "-segment_time", str(self.chunk_sec), "-reset_timestamps", "1",
            "-strftime", "1", "-segment_format", "mp4",
            # Fragmented MP4 written as it goes, so clips can be cut from the active chunk.
            # flush_packets: without it the segment muxer holds the whole chunk in memory until close.
            "-segment_format_options", "movflags=+frag_keyframe+empty_moov+default_base_moof:flush_packets=1",
            str(self.dir / f"{NAME_FORMAT}.mp4"),
        ]
        self.proc = await asyncio.create_subprocess_exec(
            *cmd, stdin=asyncio.subprocess.PIPE, env={**os.environ, "TZ": "UTC"},
        )
        self.size = (width, height)
        log.info("recording %s at %dx%d", self.dir, width, height)

    async def write(self, i420: bytes, width: int, height: int) -> None:
        if self.size != (width, height) or not self.running:
            await self.stop()  # resolution changed (quality switch) or FFmpeg died: new chunk
            await self.start(width, height)
        assert self.proc and self.proc.stdin
        try:
            self.proc.stdin.write(i420)
            await self.proc.stdin.drain()
        except (BrokenPipeError, ConnectionResetError):
            log.error("ffmpeg for %s exited (code %s)", self.dir, self.proc.returncode)
            await self.stop()

    async def stop(self) -> None:
        proc, self.proc, self.size = self.proc, None, None
        if proc is None:
            return
        if proc.stdin and not proc.stdin.is_closing():
            proc.stdin.close()
        try:
            await asyncio.wait_for(proc.wait(), timeout=10)
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()


async def cut_clip(chunks: list[Chunk], start: datetime, end: datetime, out: Path) -> bool:
    """Copies [start, end] out of the chunks (spanning two if needed) without re-encoding."""
    parts = [c for c in chunks if c.started_at <= end and c.ended_at >= start]
    if not parts:
        return False
    out.parent.mkdir(parents=True, exist_ok=True)
    lines = []
    for c in parts:
        lines.append(f"file '{c.path.as_posix()}'")
        if c.started_at < start:
            lines.append(f"inpoint {(start - c.started_at).total_seconds():.2f}")
        if c.ended_at > end:
            lines.append(f"outpoint {(end - c.started_at).total_seconds():.2f}")
    listing = out.with_suffix(".txt")
    listing.write_text("\n".join(lines) + "\n")
    proc = await asyncio.create_subprocess_exec(
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-nostdin", "-y",
        "-f", "concat", "-safe", "0", "-i", str(listing), "-c", "copy", "-movflags", "+faststart", str(out),
    )
    code = await proc.wait()
    listing.unlink(missing_ok=True)
    return code == 0 and out.exists() and out.stat().st_size > 0
