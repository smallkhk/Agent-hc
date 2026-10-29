import numpy as np
import pytest

from worker.detect import screen as s
from worker.tests import synth


def shifted(quad, dx=0, dy=0):
    return [[x + dx, y + dy] for x, y in quad]


def scaled(quad, k, cx=427, cy=240):
    return [[cx + (x - cx) * k, cy + (y - cy) * k] for x, y in quad]


@pytest.mark.parametrize("seed", range(5))
def test_screen_fully_inside_passes(seed):
    r = s.detect_screen(synth.scene(synth.GOOD, seed=seed))
    assert r.ok, r
    assert r.area_frac > 0.4
    assert 1.3 <= r.aspect <= 2.3


def test_corners_are_close_to_the_real_device():
    r = s.detect_screen(synth.scene(synth.GOOD))
    # The detector may lock onto the bezel or the screen inside it: within ~25px either way.
    assert np.abs(r.corners - np.float32(synth.GOOD)).max() < 30


def test_ipad_aspect_passes():
    ipad = [[200, 40], [660, 50], [670, 440], [190, 430]]  # ~1.2-1.4 incl. bezel
    r = s.detect_screen(synth.scene(ipad))
    assert r.ok or r.reason == s.NOT_FOUND  # iPad 4:3 sits at the low edge of the default range
    r = s.detect_screen(synth.scene(ipad), s.ScreenParams(aspect_min=1.15))
    assert r.ok, r


@pytest.mark.parametrize("dx", [180, -200])
def test_screen_partly_out_of_frame_is_cut_off(dx):
    r = s.detect_screen(synth.scene(shifted(synth.GOOD, dx=dx)))
    assert not r.ok
    assert r.reason == s.CUT_OFF, r


def test_screen_out_the_bottom_is_cut_off():
    r = s.detect_screen(synth.scene(shifted(synth.GOOD, dy=150)))
    assert r.reason == s.CUT_OFF, r


def test_small_screen():
    r = s.detect_screen(synth.scene(scaled(synth.GOOD, 0.35)))
    assert r.reason == s.TOO_SMALL, r


def test_dark_screen():
    r = s.detect_screen(synth.scene(synth.GOOD, brightness=12, with_thumbs=False))
    assert r.reason in (s.DARK, s.NOT_FOUND), r


def test_glare():
    r = s.detect_screen(synth.scene(synth.GOOD, glare=True))
    assert r.reason == s.GLARE, r


def test_no_screen():
    rng = np.random.default_rng(3)
    r = s.detect_screen(synth.desk(rng))
    assert r.reason == s.NOT_FOUND, r


def test_covered_camera():
    r = s.detect_screen(np.random.default_rng(0).normal(4, 2, (480, 854, 3)).clip(0, 255).astype(np.uint8))
    assert not r.ok
    assert r.reason in (s.NOT_FOUND, s.DARK)


def test_smoother_follows_and_resets():
    sm = s.CornerSmoother(alpha=0.5, reset_px=50)
    a = np.float32(synth.GOOD)
    assert np.allclose(sm.update(a), a)
    assert np.allclose(sm.update(a + 10), a + 5)
    assert np.allclose(sm.update(a + 200), a + 200)
    assert sm.update(None) is None
