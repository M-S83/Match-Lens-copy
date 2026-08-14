#!/usr/bin/env python3
"""
prepare_match.py -- run the head of the pipeline: Steps 1a, 1, 1b, 1c.

    python prepare_match.py "C:/Users/dbmux/Desktop/Grays Analysis"

pipeline_runner_v2.py is the BACK half of the pipeline. It opens with

    ERROR: window_plan.json not found. Run window_plan.py first.

because it assumes the head has already run. The head is four steps with a
strict order, each consuming the one before:

    1a  container_analyser.py   video          -> container_profile.json
    1   extract_frames.py       video          -> frames/frame_MMmSSs.jpg
    1b  detect_boundaries.py    frames/        -> match_boundaries.json   (paid)
    1c  window_plan.py          boundaries +   -> window_plan.json
                                container_profile

Step 1b calls the Claude API (Haiku, two scan phases). It is the only paid
step here and it is cheap relative to the main run, but it is not free, so it
is named as paid in the output rather than run silently.

Every step is skipped if its output already exists, so re-running after a
failure resumes rather than repeating. --force re-runs everything.

Stops at the first failure. A half-built head is worse than none: window_plan
generated from a failed boundary detection produces windows over the wrong
minutes of footage, and nothing downstream would flag it.
"""
import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent


def rule(n, title):
    print(f"\n{'=' * 64}\n  Step {n} -- {title}\n{'=' * 64}")


def run(cmd) -> int:
    print(f"  $ {' '.join(str(c) for c in cmd)}\n")
    return subprocess.run(cmd).returncode


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Run Match Lens Steps 1a/1/1b/1c for a match directory.")
    ap.add_argument("match_dir")
    ap.add_argument("--force", action="store_true",
                    help="re-run every step even if its output exists")
    ap.add_argument("--override-boundaries", action="store_true",
                    help="pass --override to Step 1b: accept boundaries even "
                         "if its own validation fails")
    args = ap.parse_args()

    py        = sys.executable
    match_dir = os.path.abspath(args.match_dir)
    if not os.path.isdir(match_dir):
        print(f"  [FAIL] not a directory: {match_dir}", file=sys.stderr)
        return 1

    cfg_path = os.path.join(match_dir, "match_config.json")
    if not os.path.exists(cfg_path):
        print(f"  [FAIL] no match_config.json in {match_dir}", file=sys.stderr)
        print(f"         Create one with new_match.py, or copy yours in.",
              file=sys.stderr)
        return 1

    # Resolve the video the same way every other step does, so a broken
    # video_path is reported here rather than three steps in.
    sys.path.insert(0, str(REPO))
    try:
        from frame_extraction import find_source_video
        video = find_source_video(match_dir)
    except FileNotFoundError as e:
        print(f"  [FAIL] {e}", file=sys.stderr)
        return 1

    with open(cfg_path, encoding="utf-8") as f:
        mc = json.load(f)
    print(f"\n  Match:    {mc.get('match', '(unnamed)')}")
    print(f"  Dir:      {match_dir}")
    print(f"  Video:    {video}")

    def done(name):
        return (not args.force) and os.path.exists(os.path.join(match_dir, name))

    # ── 1a  container profile ────────────────────────────────────────────────
    rule("1a", "Container analysis (ffprobe, seconds, free)")
    if done("container_profile.json"):
        print("  [SKIP] container_profile.json exists.")
    elif run([py, str(REPO / "container_analyser.py"), match_dir, video]) != 0:
        print("\n  [FAIL] Step 1a failed.", file=sys.stderr)
        return 1

    # ── 1   frame extraction ─────────────────────────────────────────────────
    rule("1", "Frame extraction at 1fps (minutes, free)")
    cmd = [py, str(REPO / "extract_frames.py"), match_dir]
    if args.force:
        cmd.append("--force")
    if run(cmd) != 0:
        print("\n  [FAIL] Step 1 failed.", file=sys.stderr)
        return 1

    # ── 1b  boundary detection ───────────────────────────────────────────────
    rule("1b", "Boundary detection -- KO1/HT/KO2/FT (Claude Haiku, PAID)")
    if done("match_boundaries.json"):
        print("  [SKIP] match_boundaries.json exists.")
    else:
        cmd = [py, str(REPO / "detect_boundaries.py"), match_dir]
        if args.override_boundaries:
            cmd.append("--override")
        if run(cmd) != 0:
            print("\n  [FAIL] Step 1b failed. Nothing downstream can run: the",
                  file=sys.stderr)
            print("         window plan is built from these four timestamps.",
                  file=sys.stderr)
            return 1

    # ── 1c  window plan ──────────────────────────────────────────────────────
    rule("1c", "Window plan (free)")
    if done("window_plan.json"):
        print("  [SKIP] window_plan.json exists.")
    elif run([py, str(REPO / "window_plan.py"), match_dir]) != 0:
        print("\n  [FAIL] Step 1c failed.", file=sys.stderr)
        return 1

    # ── Report what was actually produced ────────────────────────────────────
    wp_path = os.path.join(match_dir, "window_plan.json")
    try:
        with open(wp_path, encoding="utf-8") as f:
            wp = json.load(f)
        n_windows = len(wp.get("windows", []))
    except (OSError, json.JSONDecodeError) as e:
        print(f"\n  [FAIL] window_plan.json is unreadable: {e}", file=sys.stderr)
        return 1

    frames = len([p for p in os.listdir(os.path.join(match_dir, "frames"))
                  if p.startswith("frame_") and p.endswith(".jpg")])

    print(f"\n{'=' * 64}")
    print(f"  Head complete: {frames} frames, {n_windows} analysis windows.")
    print(f"{'=' * 64}")
    if n_windows == 0:
        print("\n  [FAIL] zero windows. The boundaries produced no live play,")
        print("         so there is nothing to analyse. Check "
              "match_boundaries.json", file=sys.stderr)
        print("         before spending anything on the main run.",
              file=sys.stderr)
        return 1
    print(f"\n  Next:\n    {py} pipeline_runner_v2.py \"{match_dir}\" "
          f"--quality standard\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
