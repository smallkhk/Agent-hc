# Hack-menu classifier

Classes: `normal_gameplay`, `codm_menu_ui` (lobby, settings, loadout: allowed), `mod_menu`, `esp_overlay`, `unknown_overlay`.
The worker flags a suspicious class at ≥ `MENU_THRESHOLD` on 2 of the last 3 samples.

```bash
python3.11 -m venv .venv-train
.venv-train/bin/pip install torch torchvision --index-url https://download.pytorch.org/whl/cpu
.venv-train/bin/pip install -r training/requirements.txt
```

## 1. Collect

Every image is the **flattened game screen** (448×224), cut out of camera footage the same way the worker does it.
Plain screenshots are used as they are.

```bash
# camera footage (hand cam recordings, phone videos): one class per run
.venv-train/bin/python -m training.collect video --label normal_gameplay recordings/12/*.mp4
# screenshots / screen recordings without a camera
.venv-train/bin/python -m training.collect images --label mod_menu --raw ~/mod-menu-screenshots/
# admin-labelled alerts from the database (Confirm / False positive buttons)
.venv-train/bin/python -m training.collect db
```

Images land in `training/dataset/<class>/`. Admin **false positives** of menu alerts go to `training/dataset/_review/`:
they are not a mod menu, but whether they are gameplay or CODM's own menus has to be sorted by hand.

What to gather: normal gameplay across many maps and modes, phone and iPad, bright and dim; CODM's own menus
(lobby, settings, loadout, scoreboard); mod-menu and ESP screenshots and videos. Aim for a few hundred per class.

## 2. Train

```bash
.venv-train/bin/python -m training.train --data training/dataset --out worker/models --epochs 15
```

Pretrained MobileNetV3-Large (or `--arch efficientnet_b0`), class-balanced sampling, augmentation for perspective,
blur, glare, JPEG compression and colour. Writes `worker/models/menu_classifier.onnx`, `labels.json` and
`metrics.json` (precision / recall per class on the validation split). Restart the worker to load a new model.

## 3. Shadow mode first

With `MENU_SHADOW=true` (default) menu flags are stored as `info` events: no Discord alert. Check them on the
admin dashboard and the metrics; when false positives are rare, set `MENU_SHADOW=false` to alert.
Retrain periodically: `collect db` pulls in every new admin label.
