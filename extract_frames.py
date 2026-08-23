#!/usr/bin/env python3
"""
extract_frames.py -- Match Lens Step 1: whole-match 1fps frame extraction.

    python extract_frames.py "C:/path/to/match dir"

Writes <match_dir>/frames/frame_MMmSSs.jpg at 1fps, JPEG quality 80.

Why this file exists
--------------------
Step 1 was the only pipeline step with no script. It lived as a code block in
SKILL.md (the "Step 1 -- Frame Extraction" section), executed by an agent
reading the skill. Every other step of the head of the pipeline is a real
script -- 1a container_analyser.py, 1b detect_boundaries.py, 1c window_plan.py
-- so a terminal run could reach none of them: no frames means no boundaries,
no boundaries means no window plan, and pipeline_runner_v2.py exits on the
missing window_plan.json.

Frame selection is identical to SKILL.md's block: for each whole second, the
frame at index int(sec * fps). The difference is how that frame is reached.
SKILL.md seeks (cap.set(CAP_PROP_POS_FRAMES, n)) once per second -- ~6,000
seeks on a 100-minute match. Step 1a exists precisely because seeking is not
always reliable: SKILL.md's own container table says a keyframe interval over
4s means "higher_fps_extraction_safe=False; use ffmpeg not OpenCV", and on
long-GOP footage each seek re-decodes from the preceding keyframe.

This script decodes once, in order, with grab() to step over frames it does
not want and retrieve() only on the ones it keeps. Sequential decoding makes
seek reliability moot -- there is no seek that can land on the wrong frame --
and it does not re-decode the same GOP thousands of times.

Missing frames are counted and reported, never papered over. Downstream steps
look frames up by exact filename (detect_boundaries.get_frames_in_range builds
frame_MMmSSs.jpg by hand), so a silent gap becomes a silently shorter analysis.
"""
import argparse
import glob
import json
import os
import sys
import time

import cv2

from frame_extraction import find_source_video

JPEG_QUALITY = 80        # SKILL.md Step 1; bursts use 90 for spatial detail
PROGRESS_EVERY = 500     # frames between progress lines
MANIFEST = "extraction.json"   # written into frames/ on a completed run


def frame_name(sec: int) -> str:
    """frame_MMmSSs.jpg -- the name every downstream step reconstructs."""
    m, s = divmod(int(sec), 60)
    return f"frame_{m:02d}m{s:02d}s.jpg"


def extract_1fps(video_path: str, out_dir: str,
                 jpeg_quality: int = JPEG_QUALITY) -> dict:
    """
    Decode video_path once and write one frame per whole second to out_dir.

    Returns a dict with written/expected/missing counts. Raises on a video
    that cannot be opened or whose fps is unreadable -- an unreadable fps
    would otherwise silently select frame 0 for every second.
    """
    os.makedirs(out_dir, exist_ok=True)

    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        raise IOError(f"Cannot open video: {video_path}")

    fps = cap.get(cv2.CAP_PROP_FPS)
    if not fps or fps <= 0:
        cap.release()
        raise ValueError(
            f"Could not read fps from {video_path}. Without fps there is no "
            f"mapping from seconds to frame indices, and every extracted "
            f"frame would be wrong.")

    total    = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    duration = total / fps if total > 0 else 0.0
    print(f"  Source:   {os.path.basename(video_path)}")
    if total > 0:
        print(f"  Video:    {fps:.3f} fps, {total} frames, {duration / 60:.1f} min")
    else:
        print(f"  Video:    {fps:.3f} fps, frame count unavailable from container")
    print(f"  Writing:  {out_dir}")

    started      = time.monotonic()
    index        = 0     # index of the frame grab() is about to consume
    next_sec     = 0     # next whole second we want
    next_index   = 0     # int(next_sec * fps)
    written      = 0
    failed_reads = []

    while True:
        ok = cap.grab()
        if not ok:
            break
        if index == next_index:
            ok2, frame = cap.retrieve()
            if ok2 and frame is not None:
                cv2.imwrite(os.path.join(out_dir, frame_name(next_sec)), frame,
                            [cv2.IMWRITE_JPEG_QUALITY, jpeg_quality])
                written += 1
                if written % PROGRESS_EVERY == 0:
                    el = time.monotonic() - started
                    print(f"    {written} frames "
                          f"({next_sec // 60}m{next_sec % 60:02d}s)  "
                          f"{el:.0f}s elapsed")
            else:
                # Decoded nothing for a second we asked for. Record it; a gap
                # in the frame set must be visible, not inferred later from a
                # short window plan.
                failed_reads.append(next_sec)
            next_sec += 1
            next_index = int(next_sec * fps)
        index += 1

    cap.release()

    # Seconds we never reached at all (decode stopped early), as distinct from
    # seconds we reached and could not decode.
    expected = next_sec  # every second we attempted
    elapsed  = time.monotonic() - started
    print(f"  Done:     {written} frames in {elapsed:.0f}s")

    if failed_reads:
        head = ", ".join(frame_name(s) for s in failed_reads[:5])
        print(f"  [WARN]  {len(failed_reads)} second(s) could not be decoded "
              f"and have no frame: {head}"
              f"{' ...' if len(failed_reads) > 5 else ''}")
        print(f"          Downstream steps look frames up by exact filename, "
              f"so these seconds are simply absent from the analysis.")

    if total > 0 and duration - expected > 2:
        print(f"  [WARN]  decode stopped at {expected}s but the container "
              f"reports {duration:.0f}s. {duration - expected:.0f}s of footage "
              f"produced no frames.")

    result = {"written": written, "attempted": expected,
              "failed_seconds": failed_reads, "fps": fps,
              "duration_s": duration}

    # A manifest so a later run can tell a COMPLETE extraction from an
    # interrupted one. Without it the only available signal is "some frames
    # exist", and seconds that legitimately failed to decode are
    # indistinguishable from seconds never reached.
    try:
        with open(os.path.join(out_dir, MANIFEST), "w", encoding="utf-8") as f:
            json.dump({**result, "video": os.path.abspath(video_path),
                       "complete": True}, f, indent=2)
    except OSError as e:
        print(f"  [WARN]  could not write {MANIFEST}: {e}. A later run cannot "
              f"verify this extraction was complete.")
    return result


def expected_frame_count(video_path: str) -> int | None:
    """How many 1fps frames a complete extraction of this video yields.

    None when the container will not report fps or frame count -- in which
    case completeness cannot be checked and must not be assumed either way.
    """
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        return None
    fps = cap.get(cv2.CAP_PROP_FPS)
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    cap.release()
    if not fps or fps <= 0 or total <= 0:
        return None
    s = 0
    while int(s * fps) < total:
        s += 1
    return s


def verify_existing(out_dir: str, existing: list, video_path: str | None) -> tuple:
    """Decide whether an existing frames/ may be treated as a finished Step 1.

    Returns (ok, message). The old guard was `if existing and not --force`,
    which treats one frame and seven thousand identically: an interrupted
    extraction skipped exactly as confidently as a complete one, and the
    shortfall surfaced only as a quietly shorter analysis.
    """
    mpath = os.path.join(out_dir, MANIFEST)
    if os.path.exists(mpath):
        try:
            with open(mpath, encoding="utf-8") as f:
                man = json.load(f)
            if man.get("complete") and man.get("written") == len(existing):
                return True, (f"{len(existing)} frames, extraction recorded "
                              f"complete")
            return False, (
                f"{len(existing)} frames on disk but the manifest records "
                f"{man.get('written')} written. The directory has changed "
                f"since extraction.")
        except (OSError, json.JSONDecodeError):
            pass        # unreadable manifest -- fall through to the count check

    if not video_path or not os.path.exists(video_path):
        return True, (f"{len(existing)} frames; no manifest and the source "
                      f"video is not available, so completeness cannot be "
                      f"verified. Proceeding on the frames present.")

    expected = expected_frame_count(video_path)
    if expected is None:
        return True, (f"{len(existing)} frames; the container reports no "
                      f"usable fps or frame count, so completeness cannot be "
                      f"verified. Proceeding on the frames present.")
    if len(existing) >= expected:
        return True, f"{len(existing)} frames, matching the video's {expected}"
    return False, (
        f"{len(existing)} frames but this video yields {expected} at 1fps -- "
        f"{expected - len(existing)} missing. This looks like an interrupted "
        f"extraction.")


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Match Lens Step 1 -- extract whole-match frames at 1fps.")
    ap.add_argument("match_dir", help="match directory containing match_config.json")
    ap.add_argument("--video", default=None,
                    help="override the video path (default: resolved from "
                         "match_config.video_path, then *.mp4 in match_dir)")
    ap.add_argument("--force", action="store_true",
                    help="re-extract even if frames already exist")
    ap.add_argument("--quality", type=int, default=JPEG_QUALITY,
                    help=f"JPEG quality (default {JPEG_QUALITY}, per SKILL.md)")
    args = ap.parse_args()

    match_dir = args.match_dir
    if not os.path.isdir(match_dir):
        print(f"  [FAIL] not a directory: {match_dir}", file=sys.stderr)
        return 1

    out_dir  = os.path.join(match_dir, "frames")
    existing = glob.glob(os.path.join(out_dir, "frame_*.jpg"))

    try:
        video = args.video or find_source_video(match_dir)
    except FileNotFoundError as e:
        if not existing:
            print(f"  [FAIL] {e}", file=sys.stderr)
            return 1
        video = None            # frames exist; verify what can be verified

    if existing and not args.force:
        ok, msg = verify_existing(out_dir, existing, video)
        if ok:
            print(f"  [SKIP] {msg}")
            print(f"         Pass --force to re-extract.")
            return 0
        print(f"  [FAIL] {msg}", file=sys.stderr)
        print(f"         Re-run with --force to extract the whole match again.",
              file=sys.stderr)
        print(f"         Skipping now would hand every downstream step a "
              f"silently shorter match.", file=sys.stderr)
        return 1

    if video is None:
        print(f"  [FAIL] no source video found for {match_dir}", file=sys.stderr)
        return 1

    try:
        result = extract_1fps(video, out_dir, jpeg_quality=args.quality)
    except (IOError, ValueError) as e:
        print(f"  [FAIL] {e}", file=sys.stderr)
        return 1

    if result["written"] == 0:
        print("  [FAIL] no frames were written.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
