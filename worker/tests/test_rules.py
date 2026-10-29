import numpy as np

from worker.detect.integrity import FreezeDetector
from worker.rules import EscalatingRule
from worker.tests import synth


def run(rule, samples, fps=2, event_type="X"):
    out = []
    for i, failing in enumerate(samples):
        for e in rule.update(failing, i / fps, event_type):
            out.append((i / fps, e.severity))
    return out


def test_warning_then_violation_once_per_episode():
    rule = EscalatingRule(10, 30)
    events = run(rule, [True] * 100)  # 50 s of failure at 2 fps
    assert events == [(10.0, "warning"), (30.0, "violation")]


def test_pass_resets_grace_period():
    rule = EscalatingRule(10, 30)
    samples = [True] * 18 + [False] + [True] * 18  # 9 s, blip, 9 s
    assert run(rule, samples) == []


def test_new_episode_warns_again():
    rule = EscalatingRule(2, None)
    events = run(rule, [True] * 6 + [False] + [True] * 6)
    assert [s for _, s in events] == ["warning", "warning"]


def test_violation_only_rule():
    rule = EscalatingRule(None, 8)
    assert run(rule, [True] * 20) == [(8.0, "violation")]


def test_threshold_change_applies_to_running_episode():
    rule = EscalatingRule(10, 30)
    rule.update(True, 0, "X")
    rule.violation_sec = 5
    assert [e.severity for e in rule.update(True, 6, "X")] == ["violation"]


def test_freeze_detector():
    rng = np.random.default_rng(0)
    frame = synth.scene(synth.GOOD)
    fd = FreezeDetector(diff_threshold=0.3)
    fd.update(frame)
    assert fd.is_static(fd.update(frame))  # identical frame → frozen
    noisy = (frame.astype(np.int16) + rng.normal(0, 3, frame.shape)).clip(0, 255).astype(np.uint8)
    assert not fd.is_static(fd.update(noisy))  # camera noise → live
    moved = synth.scene([[x + 6, y + 3] for x, y in synth.GOOD])
    assert not fd.is_static(fd.update(moved))
