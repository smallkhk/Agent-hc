# Hack-menu model

`menu_classifier.onnx` + `labels.json` + `metrics.json`, written by `python -m training.train` (see training/README.md).

Shipped model (v5, 2026-11-21): MobileNetV3-Large, classes `normal_gameplay`, `codm_menu_ui`, `mod_menu`, `esp_overlay`.
Trained on: 16 minutes of honest hand cam footage (CODM matches with the device held and moving, lobby, settings,
iOS screens), screenshots from public gaming articles, real hand cam footage of the "Cloud" cheat in a match,
and synthetic mod menus / cheat overlays drawn on clean screenshots and on the honest hand cam frames.
Augmentation: fingers, camera wash, glare, blur, perspective, upside-down.

Held-out check (nothing below was used for training):

| Test | at 0.8 | at 0.9 |
|---|---|---|
| Honest hand cam gameplay, false alarms | 0 / 157 | 0 / 157 |
| Honest hand cam menus, false alarms | 0 / 116 | 0 / 116 |
| Real cheat menus (Cloud Engine, R6X9) | 2 / 2 | 2 / 2 |
| Real "Cloud" overlay (watermark + FOV circle) on lobby / MVP screens, hand cam | 9 / 21 | 4 / 21 |

Recommended: `MENU_THRESHOLD=0.8`. The thin FOV circle alone is the weak spot; more real footage of it will help.
