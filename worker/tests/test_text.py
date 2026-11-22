import cv2
import numpy as np
import pytest

from worker.detect import text as t

# What the OCR read from real hand cam footage and screenshots (see training notes).
R6X9_MENU = ["R6X9:CODM", "Enable Hit Magic", "Save Settings", "Enable AimBot", "Player", "EnableFOV", "Enable Smooth",
             "AimFOV", "CloseAimFov", "Draw", "AimTarget:", "Legs", "Head", "Chest", "Aim Location:", "SmoothAim",
             "SizeFov", "60", "Device:iPad"]
CLOUD_IN_MATCH = ["28:51", "CLOUD", "6", "Piaver"]
CLOUD_ENGINE = ["CLOUD ENGINE", "SKINS", "Weapons", "Melee", "Operators", "Apply locally (trial)"]
HONEST_CODM_SETTINGS = ["PREVIEW", "Search and Preview", "Cloud Sensitivity Management"]
HONEST_SETTINGS_WORDS = ["Aim Assist", "Auto Fire", "FOV", "ADS", "Sensitivity", "Gyroscope", "Skins", "Loadout"]


def types(texts):
    return [f.type for f in t.classify(texts)]


def test_real_cheat_menus_are_cheat_text():
    f = t.classify(R6X9_MENU)
    assert [x.type for x in f] == [t.CHEAT_TEXT]
    assert "Enable AimBot" in f[0].words and "Enable Hit Magic" in f[0].words
    assert f[0].detail().startswith('Text on screen: "')
    assert types(CLOUD_ENGINE) == [t.CHEAT_TEXT]


def test_cloud_watermark_counts_but_cloud_sensitivity_does_not():
    assert types(CLOUD_IN_MATCH) == [t.CHEAT_TEXT]
    assert types(HONEST_CODM_SETTINGS) == []


def test_legit_codm_settings_words_are_not_cheats():
    assert types(HONEST_SETTINGS_WORDS) == []


def test_testflight_and_two_codm_apps():
    assert types(["Photos", "TestFlight", "Settings"]) == [t.TESTFLIGHT]
    assert types(["Call of Duty", "Safari", "Call of Duty"]) == [t.DUPLICATE_CODM]
    assert types(["Call of Duty", "Safari", "Discord"]) == []  # one install is normal


def test_reader_reads_a_rendered_menu():
    pytest.importorskip("rapidocr_onnxruntime")
    reader = t.TextReader.load()
    assert reader is not None
    img = np.full((480, 960, 3), 40, np.uint8)
    cv2.putText(img, "MOD MENU", (60, 110), cv2.FONT_HERSHEY_SIMPLEX, 2.0, (255, 255, 255), 4)
    cv2.putText(img, "Enable Aimbot", (60, 230), cv2.FONT_HERSHEY_SIMPLEX, 1.6, (255, 255, 255), 3)
    cv2.putText(img, "No Recoil", (60, 330), cv2.FONT_HERSHEY_SIMPLEX, 1.6, (255, 255, 255), 3)
    texts = reader.read(img)
    found = t.classify(texts)
    assert [f.type for f in found] == [t.CHEAT_TEXT], texts
    assert len(found[0].words) >= 2
