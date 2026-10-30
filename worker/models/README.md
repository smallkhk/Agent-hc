# Hack-menu model

`menu_classifier.onnx` + `labels.json` + `metrics.json`, written by `python -m training.train` (see training/README.md).

Shipped model (v3, 2026-10-30): MobileNetV3-Large, classes `normal_gameplay`, `codm_menu_ui`, `mod_menu`, `esp_overlay`.
Trained on 33 gameplay and 49 CODM menu screenshots from public gaming articles, 26 real hand cam frames of the
"Cloud" cheat in a match plus one real ESP screenshot, and 400 + 500 synthetic mod menus and cheat overlays
(`training/synth.py`). Keep `MENU_SHADOW=true`: it has not yet seen honest hand cam footage.

Held-out check at threshold 0.8 (nothing below was used for training):

| Test | Flagged |
|---|---|
| Real cheat menus (Cloud Engine screenshot, R6X9 camera photo) | 2 / 2 |
| Real "Cloud" overlay on lobby / MVP / victory screens, hand cam | 5 / 13 (12 / 13 top class `esp_overlay`) |
| Clean gameplay / CODM menu screenshots | 0 / 15 |
| Clean CODM menus with simulated fingers + camera wash | 0 / 28 |
| Clean gameplay with simulated fingers + camera wash | 7 / 32 (false alarms) |

Next: retrain with a few minutes of honest hand cam footage (same camera setups, no cheat) to cut the false alarms
on camera-filmed gameplay.
