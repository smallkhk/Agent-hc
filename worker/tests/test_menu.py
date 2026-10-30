import json

import numpy as np
import pytest

from worker.detect.menu import MenuClassifier, MenuRule, Prediction, flatten_screen
from worker.tests import synth


def pred(score, label="mod_menu"):
    return Prediction("normal_gameplay" if score < 0.5 else label, max(score, 1 - score), label, score)


def test_two_of_three_flags_once():
    rule = MenuRule(0.8)
    out = [rule.update(p) for p in (pred(0.9), pred(0.1), pred(0.85), pred(0.95), pred(0.9))]
    assert [o is not None for o in out] == [False, False, True, False, False]
    assert out[2].score == 0.9  # reports the strongest of the hits


def test_single_spike_does_not_flag():
    rule = MenuRule(0.8)
    assert all(rule.update(p) is None for p in (pred(0.99), pred(0.1), pred(0.2), pred(0.99), pred(0.3)))


def test_new_episode_after_menu_disappears():
    rule = MenuRule(0.8)
    flags = [rule.update(p) for p in [pred(0.9)] * 3 + [pred(0.1)] * 3 + [pred(0.9)] * 3]
    assert sum(f is not None for f in flags) == 2


def test_missing_screen_counts_as_no_hit():
    rule = MenuRule(0.8)
    assert [rule.update(p) for p in (pred(0.9), None, pred(0.9))][-1] is not None
    rule = MenuRule(0.8)
    assert all(rule.update(p) is None for p in (pred(0.9), None, None, pred(0.9)))


def test_flatten_recovers_the_screen():
    screen = synth.game_screen(np.random.default_rng(0))
    photo = synth.place(synth.desk(np.random.default_rng(1)), screen, np.float32(synth.GOOD))
    flat = flatten_screen(photo, np.float32(synth.GOOD), (400, 185))
    ref = __import__("cv2").resize(screen, (400, 185))
    assert np.abs(flat.astype(int) - ref.astype(int)).mean() < 12


def test_flatten_rotates_portrait_quads():
    tall = np.float32([[300, 40], [500, 40], [500, 440], [300, 440]])
    assert flatten_screen(np.zeros((480, 854, 3), np.uint8), tall).shape == (224, 448, 3)


def tiny_model(tmp_path, classes):
    """Linear model on mean colour: red screens → mod_menu. Enough to test the runtime wrapper."""
    onnx = pytest.importorskip("onnx")
    from onnx import TensorProto, helper

    w = np.zeros((3, len(classes)), np.float32)
    w[0, classes.index("mod_menu")] = 8.0  # R channel
    w[2, classes.index("normal_gameplay")] = 8.0  # B channel
    graph = helper.make_graph(
        [helper.make_node("GlobalAveragePool", ["image"], ["pooled"]),
         helper.make_node("Flatten", ["pooled"], ["flat"]),
         helper.make_node("MatMul", ["flat", "w"], ["logits"])],
        "tiny",
        [helper.make_tensor_value_info("image", TensorProto.FLOAT, ["batch", 3, 224, 448])],
        [helper.make_tensor_value_info("logits", TensorProto.FLOAT, ["batch", len(classes)])],
        [helper.make_tensor("w", TensorProto.FLOAT, w.shape, w.ravel())],
    )
    model = helper.make_model(graph, opset_imports=[helper.make_opsetid("", 17)])
    model.ir_version = 8
    path = tmp_path / "menu_classifier.onnx"
    onnx.save(model, str(path))
    (tmp_path / "labels.json").write_text(json.dumps({
        "classes": classes, "suspicious": ["mod_menu", "esp_overlay", "unknown_overlay"],
        "input": {"width": 448, "height": 224}, "mean": [0.5, 0.5, 0.5], "std": [0.25, 0.25, 0.25]}))
    return path


def test_classifier_runtime(tmp_path):
    classes = ["normal_gameplay", "codm_menu_ui", "mod_menu", "esp_overlay", "unknown_overlay"]
    clf = MenuClassifier.load(tiny_model(tmp_path, classes))
    red = np.zeros((224, 448, 3), np.uint8); red[..., 2] = 255  # BGR
    blue = np.zeros((224, 448, 3), np.uint8); blue[..., 0] = 255
    p = clf.predict(red)
    assert p.top == "mod_menu" and p.label == "mod_menu" and p.score > 0.9
    p = clf.predict(blue)
    assert p.top == "normal_gameplay" and p.score < 0.1


def test_no_model_means_rule_off(tmp_path):
    assert MenuClassifier.load(tmp_path / "missing.onnx") is None
