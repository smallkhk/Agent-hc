import cv2
import numpy as np

from worker.detect.integrity import LoopDetector, SceneChangeDetector, hamming, phash
from worker.tests import synth


def gameplay(n, seed=0, speed=6):
    """Camera frames of a device showing moving game content (a random walk that never repeats)."""
    rng = np.random.default_rng(seed)
    desk = synth.desk(rng)
    blobs = [(rng.uniform(50, 750), rng.uniform(40, 330), rng.uniform(15, 50),
              tuple(int(c) for c in rng.integers(60, 250, 3))) for _ in range(12)]
    vel = rng.normal(0, speed, (12, 2))
    frames = []
    for _ in range(n):
        screen = np.full((370, 800, 3), (100, 130, 140), np.uint8)
        vel += rng.normal(0, 1.5, vel.shape)
        blobs = [((x + vx) % 800, (y + vy) % 370, r, c) for (x, y, r, c), (vx, vy) in zip(blobs, vel)]
        for x, y, r, c in blobs:
            cv2.circle(screen, (int(x), int(y)), int(r), c, -1)
        frames.append(synth.place(desk, synth.device(screen), np.float32(synth.GOOD)))
    return frames


def camera(frame, rng, sigma=3.0):
    return (frame.astype(np.int16) + rng.normal(0, sigma, frame.shape)).clip(0, 255).astype(np.uint8)


def first_hit(det, frames, seed=1):
    rng = np.random.default_rng(seed)
    for i, f in enumerate(frames):
        if det.update(camera(f, rng)):
            return i
    return None


def test_phash_is_noise_robust():
    f = gameplay(1)[0]
    rng = np.random.default_rng(0)
    g = lambda x: cv2.cvtColor(x, cv2.COLOR_BGR2GRAY)  # noqa: E731
    assert int(hamming(phash(g(camera(f, rng))), phash(g(camera(f, rng))))) <= 4


def test_looped_clip_detected_on_second_pass():
    clip = gameplay(40)
    hit = first_hit(LoopDetector(capacity=1200), clip + clip + clip)
    assert hit is not None and 40 + 18 <= hit <= 40 + 25  # ~one match run into the replay


def test_replay_sampled_out_of_phase_is_detected():
    fine = gameplay(160, speed=3)  # 4 "fps" source
    first, replay = fine[0::2], fine[1::2]  # second pass sampled half a frame later
    hit = first_hit(LoopDetector(capacity=1200), first + replay)
    assert hit is not None and hit < 80 + 30


def test_live_gameplay_never_loops():
    assert first_hit(LoopDetector(capacity=1200), gameplay(400, seed=5)) is None


def test_static_scene_is_not_a_loop():
    frame = gameplay(1)[0]
    assert first_hit(LoopDetector(capacity=1200), [frame] * 300) is None


def test_loop_state_holds_then_clears():
    clip = gameplay(40)
    det = LoopDetector(capacity=1200, hold=10)
    rng = np.random.default_rng(2)
    states = [det.update(camera(f, rng)) for f in clip + clip + gameplay(60, seed=9)]
    assert any(states[60:80]) and not any(states[-30:])


def test_scene_change():
    det = SceneChangeDetector()
    rng = np.random.default_rng(0)
    corners = np.float32(synth.GOOD)
    room_a = [camera(f, rng) for f in gameplay(20, seed=1)]
    rng_b = np.random.default_rng(42)
    other_desk = synth.desk(rng_b, level=150)
    room_b = [camera(synth.place(other_desk, synth.device(np.full((370, 800, 3), 120, np.uint8)), corners), rng)
              for _ in range(10)]
    hits = [det.update(f, corners) for f in room_a + room_b]
    assert not any(hits[:20])  # game content changing inside the screen doesn't count
    assert sum(hits) == 1 and hits.index(True) >= 20
