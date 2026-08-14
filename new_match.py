#!/usr/bin/env python3
"""
new_match.py -- scaffold a match directory and its match_config.json.

    python new_match.py --video "C:/path/to/match.mp4" \
                        --home "Grays Athletic" --away "Opponent FC" \
                        --dir "C:/path/to/Grays Analysis"

Writes <dir>/match_config.json with an ABSOLUTE video_path, so the video can
stay where it is. That matters: frame_extraction falls back to globbing
<match_dir>/*.mp4 and, with several videos present, picks the LARGEST and only
warns -- on a folder holding a 3.76 GB drone clip beside a 1.84 GB match file,
the drone clip wins silently. Setting video_path removes the ambiguity.

Refuses to overwrite an existing match_config.json unless --force is given.
"""
import argparse
import json
import os
import sys
from pathlib import Path


def build_config(args) -> dict:
    return {
        "match":      args.match or f"{args.home} vs {args.away}",
        "date":       args.date or "",
        "home_team":  args.home,
        "away_team":  args.away,
        "focus_team": args.focus,
        # Absolute, so the video need not be copied into the match directory.
        "video_path": str(Path(args.video).resolve()),
        "home_kit":    args.home_kit or "",
        "away_kit":    args.away_kit or "",
        "home_gk_kit": args.home_gk_kit or "",
        # Fill these in for materially better output -- see the notes printed
        # after this file is written.
        #
        # lineups is a LIST of team objects, not a dict. Every consumer iterates
        # it -- build_readiness_check.py:277, deep_skill_metrics.py:354 -- so a
        # {"home": [], "away": []} dict yields bare key strings and silently
        # contributes nothing to player identification.
        "lineups": [
            {"team": {"name": args.home}, "startXI": [], "substitutes": []},
            {"team": {"name": args.away}, "startXI": [], "substitutes": []},
        ],
        "goals":         [],
        "cards":         [],
        "substitutions": [],
    }


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Scaffold a Match Lens match directory.")
    ap.add_argument("--video", required=True, help="path to the source .mp4")
    ap.add_argument("--home",  required=True, help="home team name")
    ap.add_argument("--away",  required=True, help="away team name")
    ap.add_argument("--dir",   required=True, dest="directory",
                    help="match directory to create (video may live elsewhere)")
    ap.add_argument("--date",  default="", help="YYYY-MM-DD")
    ap.add_argument("--match", default="", help="match label (default: 'Home vs Away')")
    ap.add_argument("--focus", default="home", choices=["home", "away"],
                    help="which team the analysis centres on (default: home)")
    ap.add_argument("--home-kit",    default="", dest="home_kit")
    ap.add_argument("--away-kit",    default="", dest="away_kit")
    ap.add_argument("--home-gk-kit", default="", dest="home_gk_kit")
    ap.add_argument("--force", action="store_true",
                    help="overwrite an existing match_config.json")
    args = ap.parse_args()

    video = Path(args.video)
    if not video.exists():
        print(f"  [FAIL] video not found: {video}", file=sys.stderr)
        return 1
    if video.suffix.lower() != ".mp4":
        print(f"  [WARN] {video.name} is not a .mp4 -- continuing, but the "
              f"pipeline is only exercised against mp4.")

    match_dir = Path(args.directory)
    match_dir.mkdir(parents=True, exist_ok=True)

    cfg_path = match_dir / "match_config.json"
    if cfg_path.exists() and not args.force:
        print(f"  [FAIL] {cfg_path} already exists. Pass --force to overwrite.",
              file=sys.stderr)
        return 1

    cfg = build_config(args)
    with open(cfg_path, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2, ensure_ascii=False)

    size_gb = video.stat().st_size / (1024 ** 3)
    print(f"\n  Written: {cfg_path}")
    print(f"  Video:   {cfg['video_path']}  ({size_gb:.2f} GB)")

    # Warn about the exact trap this script exists to avoid.
    # Case-insensitive on purpose: the real decoy is DJI_..._D.MP4, and a
    # lowercase-only glob misses it on Linux/macOS while Windows would match.
    # A check for a case-sensitivity trap must not itself be case-sensitive.
    siblings = sorted(p for p in match_dir.iterdir()
                      if p.is_file() and p.suffix.lower() == ".mp4")
    if len(siblings) > 1:
        print(f"\n  [NOTE] {len(siblings)} .mp4 files sit in the match directory. "
              f"video_path is set explicitly, so the glob is not consulted and "
              f"the largest-file rule cannot pick the wrong one.")

    print("\n  Fill these in before running -- both materially change output quality:")
    print("    lineups  -- drives player identification. Left empty, players are")
    print("                named by shirt number and the player-ID confidence")
    print("                ceiling drops.")
    print("    goals    -- your ground truth. ground_truth.py validates the")
    print("                pipeline's detections against it; with an empty list")
    print("                there is nothing to validate against.")
    print("\n  Then:")
    print(f'    python check_setup.py')
    print(f'    python prepare_match.py "{match_dir}"')
    print(f'    python pipeline_runner_v2.py "{match_dir}" --quality standard')
    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
