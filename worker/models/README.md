# Hack-menu model

`menu_classifier.onnx` + `labels.json` + `metrics.json`, written by `python -m training.train` (see training/README.md).

Shipped model (v1, 2026-10-30): MobileNetV3-Large, classes `normal_gameplay`, `codm_menu_ui`, `mod_menu`, `esp_overlay`.
Trained on 33 gameplay and 49 CODM menu screenshots from public gaming articles, plus 300 + 300 synthetic mod menus
and ESP overlays (`training/synth.py`). **No real hack footage yet**: keep `MENU_SHADOW=true` until it has been
retrained with real examples and checked on real matches.

Held-out check (screenshots and backgrounds never seen in training), threshold 0.8:
legit gameplay 0 / 8 flagged, CODM menus 0 / 7 flagged, synthetic mod menus 59 / 60, synthetic ESP 44 / 60.
