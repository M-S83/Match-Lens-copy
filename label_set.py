"""Build and score a hand-labelled frame set for the team classifier.

WHY
---
Every tuning decision made so far rests on ONE hand-counted frame. That is not
a validation set, and it shows: three separate changes in one session each
improved some frames while quietly breaking that one, and each was only caught
because it existed. Adding shorts and socks to the kit sampling looked like an
improvement everywhere until it moved the labelled frame from 6 home to 8.

A number that cannot be scored is a number nobody can defend. This makes
scoring cheap enough that it happens before a change ships rather than after.

    python label_set.py MATCH_DIR --prepare 8     # writes frames to count
    ...fill in label_set/labels.json by eye...
    python label_set.py MATCH_DIR --score         # accuracy, per frame

The prepared frames are CLEAN, not annotated. Showing someone the classifier's
answer while asking them to produce the truth is how you get agreement instead
of measurement.
"""
import argparse
import json
import os
import shutil

import cv2
import numpy as np

from team_detect import frame_seconds, in_play, live_play_spans

LABEL_DIR = "label_set"
LABEL_FILE = "labels.json"

# Sentinel: the detector is unavailable, so stop trying for the rest of the run
# rather than raising the same import error once per frame.
_NO_MODEL = object()


def _spread(picked, n):
    """Evenly spaced across live play, so a set is not all one camera angle.

    Sampling at random clusters by chance, and the failure modes are positional
    -- a dugout in view, a goal in view, the far touchline in view. A set that
    misses those measures nothing about them.
    """
    if len(picked) <= n:
        return picked
    # Inset from both ends. linspace over the full range lands exactly on the
    # kickoff whistle and the full-time whistle -- frames where players are
    # walking on or walking off, which are the two least representative
    # moments in the match and both got picked on the first run.
    lo, hi = 0.04, 0.96
    idx = (np.linspace(lo, hi, n) * (len(picked) - 1)).round().astype(int)
    return [picked[i] for i in sorted(set(idx.tolist()))]


def _write_zoom(src, dst, model):
    """A crop tight on the players, upscaled, for counting by eye.

    Counting from a 1920x1080 wide shot where a distant player is thirty pixels
    tall is slow and error-prone. This crops to the detections and enlarges,
    which makes kit colour obvious without changing what is in the picture --
    it is a magnifying glass, not an annotation. No labels are drawn: showing
    someone the classifier's answer while asking for the truth produces
    agreement, not measurement.
    """
    img = cv2.imread(src)
    if img is None:
        return model
    if model is None:
        try:
            from ultralytics import YOLO
            model = YOLO("yolov8n-seg.pt")
        except Exception as e:
            # The zoom is a magnifying glass, not the deliverable. Losing it
            # must not cost the clean frames and the labels file, which are
            # what the human actually needs and which require no model at all.
            print(f"  [WARN] no detector available ({e}); writing frames "
                  f"without enlarged copies")
            return _NO_MODEL
    if model is _NO_MODEL:
        return model
    H, W = img.shape[:2]
    try:
        r = model.predict(src, classes=[0], conf=0.25, imgsz=1920,
                          verbose=False)[0]
        b = r.boxes.xyxy.cpu().numpy()
    except Exception as e:
        print(f"  [WARN] detector failed on {os.path.basename(src)}: {e}")
        return model
    if len(b) == 0:
        cv2.imwrite(dst, img)
        return model
    x1 = max(0, int(b[:, 0].min()) - 70)
    y1 = max(0, int(b[:, 1].min()) - 40)
    x2 = min(W, int(b[:, 2].max()) + 70)
    y2 = min(H, int(b[:, 3].max()) + 50)
    crop = img[y1:y2, x1:x2]
    sc = min(2.4, 1900 / max(1, crop.shape[1]))
    cv2.imwrite(dst, cv2.resize(crop, None, fx=sc, fy=sc,
                                interpolation=cv2.INTER_CUBIC))
    return model


def prepare(match_dir, n):
    spans = live_play_spans(match_dir)
    frames_dir = os.path.join(match_dir, "frames")
    picked = sorted(
        (t, os.path.join(frames_dir, f))
        for f in os.listdir(frames_dir)
        for t in [frame_seconds(f)]
        if t is not None and in_play(t, spans))
    if not picked:
        raise SystemExit("No in-play frames found.")
    chosen = _spread(picked, n)

    out = os.path.join(match_dir, LABEL_DIR)
    zoom = os.path.join(out, "zoom")
    os.makedirs(out, exist_ok=True)
    os.makedirs(zoom, exist_ok=True)
    model = None
    rows = []
    for t, fp in chosen:
        name = os.path.basename(fp)
        shutil.copyfile(fp, os.path.join(out, name))
        model = _write_zoom(fp, os.path.join(zoom, name), model)
        rows.append({"frame": name, "video_s": t,
                     "home": None, "away": None, "keeper": None,
                     "note": ""})
    path = os.path.join(out, LABEL_FILE)
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            old = {r["frame"]: r for r in json.load(f).get("labels", [])}
        for r in rows:                      # never discard counts already done
            if old.get(r["frame"], {}).get("home") is not None:
                r.update(old[r["frame"]])
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"match_dir": match_dir, "labels": rows}, f, indent=2)

    print(f"  {len(rows)} frames written to {out}")
    print(f"  Enlarged copies for counting in {os.path.join(out, 'zoom')} -- "
          f"count from those, they are the same picture.")
    print(f"  Count players by team in each, then fill home/away/keeper in "
          f"{LABEL_FILE}.")
    print(f"  Count only players ON the pitch. Leave a frame's counts null to "
          f"skip it.")


def score(match_dir, model, conf):
    path = os.path.join(match_dir, LABEL_DIR, LABEL_FILE)
    if not os.path.exists(path):
        raise SystemExit(f"No {path}. Run --prepare first.")
    with open(path, encoding="utf-8") as f:
        rows = json.load(f)["labels"]
    done = [r for r in rows if r.get("home") is not None
            and r.get("away") is not None]
    if not done:
        raise SystemExit("No frames counted yet.")

    from ultralytics import YOLO
    from team_classifier import classify_frame
    with open(os.path.join(match_dir, "match_config.json"), encoding="utf-8") as f:
        mc = json.load(f)
    m = YOLO(model)

    print(f"  {'frame':18} {'truth h/a/k':>12} {'got h/a/k':>12} "
          f"{'err':>5}  coverage")
    eh, ea, exact, tot = [], [], 0, 0
    for r in done:
        fp = os.path.join(match_dir, "frames", r["frame"])
        img = cv2.imread(fp)
        if img is None:
            continue
        H, W = img.shape[:2]
        res_y = m.predict(fp, classes=[0], conf=conf, imgsz=1920, verbose=False)[0]
        dets = []
        if res_y.masks is not None:
            for b, mk in zip(res_y.boxes.xyxy.cpu().numpy(),
                             res_y.masks.data.cpu().numpy()):
                dets.append((b, cv2.resize(mk, (W, H),
                                           interpolation=cv2.INTER_NEAREST) > 0.5))
        c = classify_frame(img, dets, mc).counts
        gh, ga = c.get("home", 0), c.get("away", 0)
        gk = c.get("keeper", 0)
        dh, da = gh - r["home"], ga - r["away"]
        eh.append(abs(dh)); ea.append(abs(da)); tot += 1
        if dh == 0 and da == 0:
            exact += 1
        cov = classify_frame(img, dets, mc).coverage
        print(f"  {r['frame']:18} {str(r['home'])+'/'+str(r['away'])+'/'+str(r.get('keeper')):>12} "
              f"{f'{gh}/{ga}/{gk}':>12} {f'{dh:+d}/{da:+d}':>7}  {cov:.0%}")

    print(f"\n  frames scored      {tot}")
    print(f"  exact on both      {exact}/{tot}")
    print(f"  mean abs error     home {np.mean(eh):.2f}   away {np.mean(ea):.2f}")
    print(f"  worst frame        home {max(eh)}   away {max(ea)}")
    print(f"\n  Compare this against the same line from before a change. A "
          f"change that improves the mean while worsening the worst frame is "
          f"usually trading one error for another, not fixing anything.")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("match_dir")
    ap.add_argument("--prepare", type=int, metavar="N")
    ap.add_argument("--score", action="store_true")
    ap.add_argument("--model", default="yolov8n-seg.pt")
    ap.add_argument("--conf", type=float, default=0.25)
    a = ap.parse_args()
    if a.prepare:
        prepare(a.match_dir, a.prepare)
    elif a.score:
        score(a.match_dir, a.model, a.conf)
    else:
        ap.error("give --prepare N or --score")
