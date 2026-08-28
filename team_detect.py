"""Count players per team, per frame, using local CV only. No API calls.

    python team_detect.py "C:\\Users\\dbmux\\Desktop\\Grays Analysis" --stride 30

Writes team_counts.json to the match directory. Frames outside live play are
never sampled: match_boundaries puts half-time at 3245-4269s on this match,
and three of the first ten frames I tested by hand sat inside it -- one
returned 13 "home" players, which is more than can be on a pitch. A dead-time
frame does not fail loudly, it returns a confident meaningless split, so the
boundary check is not an optimisation, it is a correctness requirement.

Requires: ultralytics (torch is already present for easyocr).
    pip install ultralytics
"""
import argparse
import json
import os
import re
import sys

import cv2
import numpy as np

from team_classifier import classify_frame

FRAME_RE = re.compile(r"frame_(\d+)m(\d+)s\.(?:jpg|jpeg|png)$", re.I)
# A team cannot have more than eleven players on the pitch. A frame claiming
# more is not noisy, it is provably wrong, and averaging it in launders a
# known error into a plausible-looking median. Counted and reported instead.
MAX_ON_PITCH = 11
MAX_INVALID_RATE = 0.10   # above this the medians are withheld entirely

LABEL_COLOURS = {"home": (0, 255, 0), "away": (0, 0, 255), "keeper": (0, 255, 255),
                 "other": (255, 0, 255), "off_field": (255, 140, 0),
                 "off_pitch": (160, 160, 160), "too_small": (140, 140, 140)}


def frame_seconds(name):
    """Video-clock seconds from a frame filename, or None.

    Minutes are not zero-padded to a fixed width past 99, and this video runs
    to 121 minutes, so parse the number rather than slicing the string.
    """
    m = FRAME_RE.search(os.path.basename(name))
    return int(m.group(1)) * 60 + int(m.group(2)) if m else None


def live_play_spans(match_dir):
    """[(start_s, end_s), ...] of actual football. Raises if unknown.

    Refuses to default to "the whole video": pre-match, half-time and
    post-match together are 1478 seconds here, and every one of those frames
    would produce a team count that looks exactly like a real one.
    """
    path = os.path.join(match_dir, "match_boundaries.json")
    if not os.path.exists(path):
        raise FileNotFoundError(
            f"team_detect: no match_boundaries.json in {match_dir}. Without it "
            f"there is no way to tell football from half-time, and a "
            f"half-time frame returns a confident, meaningless split.")
    with open(path, encoding="utf-8") as f:
        b = (json.load(f).get("boundaries") or {})
    need = ("ko_1h", "ht_whistle", "ko_2h", "ft_whistle")
    missing = [k for k in need if not isinstance(b.get(k), dict)
               or b[k].get("seconds") is None]
    if missing:
        raise ValueError(f"team_detect: match_boundaries.json is missing "
                         f"{', '.join(missing)}.")
    s = {k: float(b[k]["seconds"]) for k in need}
    return [(s["ko_1h"], s["ht_whistle"]), (s["ko_2h"], s["ft_whistle"])]


def in_play(t, spans):
    return any(a <= t <= z for a, z in spans)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("match_dir")
    ap.add_argument("--stride", type=int, default=30,
                    help="sample one frame every N seconds of video (default 30)")
    ap.add_argument("--annotate", type=int, default=0,
                    help="also write this many labelled frames to team_debug/")
    ap.add_argument("--model", default="yolov8n-seg.pt")
    ap.add_argument("--conf", type=float, default=0.25)
    args = ap.parse_args()

    md = args.match_dir
    with open(os.path.join(md, "match_config.json"), encoding="utf-8") as f:
        mc = json.load(f)
    spans = live_play_spans(md)
    frames_dir = os.path.join(md, "frames")

    picked = []
    for name in os.listdir(frames_dir):
        t = frame_seconds(name)
        if t is None or not in_play(t, spans) or t % args.stride:
            continue
        picked.append((t, os.path.join(frames_dir, name)))
    picked.sort()
    if not picked:
        print("  No in-play frames matched. Check --stride and the boundaries.")
        sys.exit(2)

    total_s = sum(z - a for a, z in spans)
    print(f"  Live play: {total_s/60:.0f} min in {len(spans)} spans; "
          f"sampling every {args.stride}s -> {len(picked)} frames")
    print(f"  Skipped as dead time: "
          f"{len(os.listdir(frames_dir)) - len(picked)} frames\n")

    from ultralytics import YOLO
    model = YOLO(args.model)

    dbg = os.path.join(md, "team_debug")
    if args.annotate:
        os.makedirs(dbg, exist_ok=True)

    rows, caveats, disabled, annotated = [], [], {}, 0
    for i, (t, fp) in enumerate(picked):
        img = cv2.imread(fp)
        if img is None:
            continue
        r = model.predict(fp, classes=[0], conf=args.conf, imgsz=1920,
                          verbose=False)[0]
        dets = []
        if r.masks is not None:
            H0, W0 = img.shape[:2]
            for box, mk in zip(r.boxes.xyxy.cpu().numpy(),
                               r.masks.data.cpu().numpy()):
                m = cv2.resize(mk, (W0, H0), interpolation=cv2.INTER_NEAREST) > 0.5
                dets.append((box, m))
        res = classify_frame(img, dets, mc)
        c = res.counts
        valid = (c.get("home", 0) <= MAX_ON_PITCH
                 and c.get("away", 0) <= MAX_ON_PITCH)
        rows.append({
            "video_s": t,
            "valid": valid,
            "home": c.get("home", 0), "away": c.get("away", 0),
            "keeper": c.get("keeper", 0), "unidentified": c.get("other", 0),
            "rejected_off_field": c.get("off_field", 0) + c.get("off_pitch", 0),
            "coverage": round(res.coverage, 3),
        })
        if not caveats:
            caveats, disabled = res.caveats, res.disabled
        if annotated < args.annotate:
            for (x1, y1, x2, y2), lab, v in res.labels:
                col = LABEL_COLOURS.get(lab, (255, 255, 255))
                cv2.rectangle(img, (x1, y1), (x2, y2), col, 2)
                cv2.putText(img, lab[:2], (x1, y1 - 4),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.45, col, 2, cv2.LINE_AA)
            cv2.imwrite(os.path.join(dbg, os.path.basename(fp)), img)
            annotated += 1
        if (i + 1) % 25 == 0:
            print(f"    {i+1}/{len(picked)} frames")

    cov = [r["coverage"] for r in rows]
    bad = [r for r in rows if not r["valid"]]
    rate = len(bad) / max(1, len(rows))
    usable = rate <= MAX_INVALID_RATE
    out = {
        "match": mc.get("match", ""),
        "frames_sampled": len(rows),
        "stride_seconds": args.stride,
        "median_coverage": round(float(np.median(cov)), 3) if cov else 0.0,
        "frames_invalid": len(bad),
        "invalid_rate": round(rate, 3),
        "counts_usable": usable,
        "disabled_kits": disabled,
        "caveats": list(caveats),
        "frames": rows,
    }
    if usable:
        ok = [r for r in rows if r["valid"]]
        out["median_home_in_view"] = float(np.median([r["home"] for r in ok]))
        out["median_away_in_view"] = float(np.median([r["away"] for r in ok]))
    else:
        # Withhold rather than qualify. A median printed beside a warning gets
        # quoted without the warning; a median that is absent cannot be.
        out["median_home_in_view"] = None
        out["median_away_in_view"] = None
        out["caveats"].append(
            f"{len(bad)} of {len(rows)} frames ({rate:.0%}) report more than "
            f"{MAX_ON_PITCH} players for one team, which cannot happen. The "
            f"per-frame counts are published but no match-level figure is, "
            f"because the error is systematic and one-sided -- almost all the "
            f"excess is on one team. Cause: people standing beyond the "
            f"touchline are counted as players. The pitch boundary is a line, "
            f"not a colour change, so grass masking cannot exclude them; this "
            f"needs touchline detection.")
    dest = os.path.join(md, "team_counts.json")
    with open(dest, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2)

    print(f"\n  team_counts.json written -- {len(rows)} frames")
    if usable:
        print(f"  Median in view: home {out['median_home_in_view']:.0f}  "
              f"away {out['median_away_in_view']:.0f}  "
              f"coverage {out['median_coverage']:.0%}")
    else:
        print(f"  [WITHHELD] No match-level count published: {len(bad)} of "
              f"{len(rows)} frames ({rate:.0%}) exceed {MAX_ON_PITCH} for a "
              f"team. Coverage {out['median_coverage']:.0%}.")
    for k, why in disabled.items():
        print(f"  [KIT] {k} disabled: {why}")
    for c in caveats:
        print(f"  [CAVEAT] {c}")
    if args.annotate:
        print(f"  {annotated} labelled frames in team_debug/ -- look at these "
              f"before trusting any number above.")


if __name__ == "__main__":
    main()
