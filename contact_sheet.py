#!/usr/bin/env python3
"""
contact_sheet.py -- tile extracted frames into one image so a human can find
an event by eye.

    python contact_sheet.py "C:/path/to/match dir" --from 52m00s --to 80m00s --every 20

Writes a single PNG with every sampled frame labelled by its timestamp.

Why this exists
---------------
Step 1b's boundary detection is two-phase: a coarse scan proposes a region,
then a fine scan picks the best frame inside it. The fine scan's confidence is
relative to the region it was given -- it reports how good its best candidate
was among the frames it saw, NOT whether the true event is in that range at
all. So a coarse scan that proposes the wrong region yields a confident wrong
answer, and no amount of re-running fixes it.

When that happens the operator has to look. At 1fps a full match is ~7,000
files, which is not something anyone scrubs through in Explorer. This tiles a
range into one image: 84 frames of a 28-minute range on a single sheet.

Timestamps accept 67m00s, 67:00, 67m, or plain seconds (4020).
"""
import argparse
import os
import re
import sys

from PIL import Image, ImageDraw, ImageFont


def parse_time(text: str) -> int:
    """'1:11:09' | '67m00s' | '67:00' | '67m' | '4020' -> seconds.

    H:MM:SS is here because that is what a video player's scrubber shows, and
    it is the form an operator reads boundaries off. Two-part input stays
    MM:SS: '67:00' is 67 minutes, matching the labels window_plan prints.
    Three-part input is unambiguous, so it is the only form read as hours.
    """
    t = str(text).strip().lower()
    if re.fullmatch(r"\d+", t):
        return int(t)
    m = re.fullmatch(r"(\d+):([0-5]?\d):([0-5]?\d)", t)          # H:MM:SS
    if m:
        return int(m.group(1)) * 3600 + int(m.group(2)) * 60 + int(m.group(3))
    m = re.fullmatch(r"(?:(\d+)m)?(?:(\d+)s?)?", t)              # 67m00s / 67m
    if m and (m.group(1) or m.group(2)):
        return int(m.group(1) or 0) * 60 + int(m.group(2) or 0)
    m = re.fullmatch(r"(\d+):([0-5]?\d)", t)                     # MM:SS
    if m:
        return int(m.group(1)) * 60 + int(m.group(2))
    raise argparse.ArgumentTypeError(
        f"cannot read {text!r} as a time. Use 1:11:09, 71m09s, 71:09, or 4269.")


def frame_name(sec: int) -> str:
    m, s = divmod(int(sec), 60)
    return f"frame_{m:02d}m{s:02d}s.jpg"


def label(sec: int) -> str:
    m, s = divmod(int(sec), 60)
    return f"{m}m{s:02d}s"


def build_sheet(match_dir, start_s, end_s, every, cols, tile_w, out_path):
    frames_dir = os.path.join(match_dir, "frames")
    if not os.path.isdir(frames_dir):
        raise FileNotFoundError(f"no frames directory in {match_dir} -- run "
                                f"extract_frames.py first")

    wanted  = list(range(int(start_s), int(end_s) + 1, int(every)))
    present, missing = [], []
    for s in wanted:
        p = os.path.join(frames_dir, frame_name(s))
        (present if os.path.exists(p) else missing).append(s)

    if not present:
        raise FileNotFoundError(
            f"none of the {len(wanted)} frames in {label(start_s)}-"
            f"{label(end_s)} exist. Is the range inside the video?")
    if missing:
        # Named, not silently dropped: a gap in the sheet is a gap in the
        # evidence, and the operator is about to make a decision on it.
        print(f"  [WARN] {len(missing)} of {len(wanted)} frames absent, e.g. "
              f"{', '.join(label(s) for s in missing[:5])}")

    # Uniform tiles from the first frame's aspect ratio.
    with Image.open(os.path.join(frames_dir, frame_name(present[0]))) as probe:
        ar = probe.height / probe.width
    tile_h = int(tile_w * ar)
    bar    = 18                       # label strip under each tile
    rows   = (len(present) + cols - 1) // cols

    sheet = Image.new("RGB", (cols * tile_w, rows * (tile_h + bar)), (17, 17, 17))
    draw  = ImageDraw.Draw(sheet)
    try:
        font = ImageFont.load_default(14)
    except TypeError:              # Pillow < 10.1 takes no size argument
        font = ImageFont.load_default()

    for i, sec in enumerate(present):
        col, row = i % cols, i // cols
        x, y = col * tile_w, row * (tile_h + bar)
        with Image.open(os.path.join(frames_dir, frame_name(sec))) as im:
            sheet.paste(im.convert("RGB").resize((tile_w, tile_h),
                                                 Image.LANCZOS), (x, y))
        draw.text((x + 4, y + tile_h + 2), label(sec),
                  fill=(255, 214, 0), font=font)

    sheet.save(out_path)
    return {"written": out_path, "tiles": len(present), "missing": missing,
            "rows": rows, "cols": cols, "size": sheet.size}


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Tile 1fps frames into one image to locate an event by eye.")
    ap.add_argument("match_dir")
    ap.add_argument("--from", dest="start", required=True, type=parse_time,
                    help="start time, e.g. 52m00s")
    ap.add_argument("--to", dest="end", required=True, type=parse_time,
                    help="end time, e.g. 80m00s")
    ap.add_argument("--every", type=int, default=20,
                    help="seconds between sampled frames (default 20)")
    ap.add_argument("--cols", type=int, default=7)
    ap.add_argument("--width", type=int, default=320,
                    help="tile width in px (default 320)")
    ap.add_argument("--out", default=None,
                    help="output PNG (default: <match_dir>/sheet_<from>_<to>.png)")
    args = ap.parse_args()

    if args.end <= args.start:
        print("  [FAIL] --to must be after --from", file=sys.stderr)
        return 1
    if args.every < 1:
        print("  [FAIL] --every must be at least 1", file=sys.stderr)
        return 1

    out = args.out or os.path.join(
        args.match_dir, f"sheet_{label(args.start).replace('m', 'm')}"
                        f"_{label(args.end)}.png".replace(" ", ""))
    try:
        r = build_sheet(args.match_dir, args.start, args.end, args.every,
                        args.cols, args.width, out)
    except (FileNotFoundError, OSError) as e:
        print(f"  [FAIL] {e}", file=sys.stderr)
        return 1

    print(f"  {r['tiles']} frames, {r['rows']}x{r['cols']}, "
          f"{r['size'][0]}x{r['size'][1]}px")
    print(f"  Written: {r['written']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
