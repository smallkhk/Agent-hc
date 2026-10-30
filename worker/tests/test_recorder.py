import asyncio
import json
import subprocess
import time
from datetime import timedelta

import cv2
import numpy as np

from worker.record.recorder import Recorder, cut_clip, list_chunks
from worker.tests import synth


def duration(path):
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "json", str(path)],
                         capture_output=True, text=True, check=True)
    return float(json.loads(out.stdout)["format"]["duration"])


def test_chunks_and_clip_across_boundary(tmp_path):
    async def go():
        rec = Recorder(tmp_path / "rec", fps=10, chunk_sec=3)
        frame = cv2.resize(synth.scene(synth.GOOD), (480, 270))
        rng = np.random.default_rng(0)
        t0 = time.monotonic()
        while time.monotonic() - t0 < 7.5:
            noisy = (frame.astype(np.int16) + rng.normal(0, 3, frame.shape)).clip(0, 255).astype(np.uint8)
            await rec.write(cv2.cvtColor(noisy, cv2.COLOR_BGR2YUV_I420).tobytes(), 480, 270)
            await asyncio.sleep(0.1)
        await rec.stop()
        chunks = list_chunks(tmp_path / "rec")
        assert sum(duration(c.path) for c in chunks) > 6.5

        # 4 s clip straddling the first chunk boundary
        boundary = chunks[1].started_at
        out = tmp_path / "clip.mp4"
        assert await cut_clip(chunks, boundary - timedelta(seconds=2), boundary + timedelta(seconds=2), out)
        assert 3.0 <= duration(out) <= 6.5  # stream copy starts at the keyframe before the cut

    asyncio.run(go())


def test_clip_from_chunk_still_being_written(tmp_path):
    async def go():
        rec = Recorder(tmp_path / "rec", fps=10)
        frame = cv2.resize(synth.scene(synth.GOOD), (480, 270))
        rng = np.random.default_rng(1)
        t0 = time.monotonic()
        while time.monotonic() - t0 < 6:
            noisy = (frame.astype(np.int16) + rng.normal(0, 3, frame.shape)).clip(0, 255).astype(np.uint8)
            await rec.write(cv2.cvtColor(noisy, cv2.COLOR_BGR2YUV_I420).tobytes(), 480, 270)
            await asyncio.sleep(0.1)
        [chunk] = list_chunks(tmp_path / "rec")  # recorder still running
        assert chunk.size_bytes > 10_000  # fragments are on disk, not buffered until the chunk closes
        out = tmp_path / "clip.mp4"
        assert await cut_clip([chunk], chunk.ended_at - timedelta(seconds=4), chunk.ended_at, out)
        assert duration(out) >= 2.0
        await rec.stop()

    asyncio.run(go())


def test_resolution_change_starts_new_chunk(tmp_path):
    async def go():
        rec = Recorder(tmp_path / "rec", fps=10)
        for w, h in ((480, 270), (640, 360)):
            img = np.full((h, w, 3), 90, np.uint8)
            for _ in range(15):
                await rec.write(cv2.cvtColor(img, cv2.COLOR_BGR2YUV_I420).tobytes(), w, h)
                await asyncio.sleep(0.07)
            await asyncio.sleep(1.1)  # chunk names have 1 s resolution
        await rec.stop()
        assert len(list_chunks(tmp_path / "rec")) == 2

    asyncio.run(go())
