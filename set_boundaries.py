#!/usr/bin/env python3
"""
set_boundaries.py -- write operator-confirmed boundaries into match_config.json.

    python set_boundaries.py "C:/path/to/match dir" ^
        --ko1 4m00s --ht 51m45s --ko2 67m10s --ft 115m30s

Writes `boundaries_override` into match_config.json. detect_boundaries.py
already honours that block (detect_boundaries.py:471) and skips detection
entirely, so Step 1b becomes free and deterministic on the next run.

Why this exists
---------------
Two reasons, both learned the hard way.

1. Hand-editing JSON on Windows goes wrong. Pasting a `"key": {...}` fragment
   into PowerShell makes PowerShell try to *execute* it, and the config is left
   untouched -- so the next run silently repeats the paid detection it was
   meant to skip.

2. The numbers should be checked BEFORE they are used, not after. This applies
   the same rules detect_boundaries validates against and refuses to write a
   set that fails them, so an impossible half-length is caught here rather than
   after a window plan has been built on it.

--check reports without writing. --force writes despite failed rules, and
records that it did so, because a run that ignored its own checks must stay
identifiable afterwards.
"""
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from contact_sheet import parse_time                       # noqa: E402


def _label(s):
    m, sec = divmod(int(s), 60)
    return f"{m}m{sec:02d}s"


def check(ko1, ht, ko2, ft, duration_s=None):
    """Apply detect_boundaries' own rules. Returns a list of failure strings."""
    from detect_boundaries import (MIN_KO1H_S, MIN_HALF_S, MAX_HALF_S,
                                   MIN_HT_BREAK, MAX_HT_BREAK,
                                   MIN_TOTAL_S, MAX_TOTAL_S)
    out = []
    if not (ko1 < ht < ko2 < ft):
        out.append(f"not in order: ko1 {_label(ko1)} < ht {_label(ht)} "
                   f"< ko2 {_label(ko2)} < ft {_label(ft)}")
        return out                       # every other rule is meaningless now

    fh, htb, sh, tot = ht - ko1, ko2 - ht, ft - ko2, ft - ko1
    if ko1 <= MIN_KO1H_S:
        out.append(f"ko_1h at {ko1}s is <= {MIN_KO1H_S}s -- likely a pre-match frame")
    if fh < MIN_HALF_S:
        out.append(f"1H {fh // 60}m -- minimum is {MIN_HALF_S // 60}m")
    if fh > MAX_HALF_S:
        out.append(f"1H {fh // 60}m -- maximum is {MAX_HALF_S // 60}m")
    if htb < MIN_HT_BREAK:
        out.append(f"HT break {htb // 60}m -- minimum is {MIN_HT_BREAK // 60}m")
    if htb > MAX_HT_BREAK:
        out.append(f"HT break {htb // 60}m -- maximum is {MAX_HT_BREAK // 60}m")
    if sh < MIN_HALF_S:
        out.append(f"2H {sh // 60}m -- minimum is {MIN_HALF_S // 60}m")
    if sh > MAX_HALF_S:
        out.append(f"2H {sh // 60}m -- maximum is {MAX_HALF_S // 60}m")
    if tot < MIN_TOTAL_S or tot > MAX_TOTAL_S:
        out.append(f"total {tot // 60}m -- expected "
                   f"{MIN_TOTAL_S // 60}-{MAX_TOTAL_S // 60}m")
    if duration_s is not None and ft > duration_s:
        out.append(f"ft {_label(ft)} is past the end of the video "
                   f"({_label(duration_s)})")
    return out


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Write operator-confirmed boundaries into match_config.json.")
    ap.add_argument("match_dir")
    ap.add_argument("--ko1", required=True, type=parse_time, help="1H kickoff")
    ap.add_argument("--ht",  required=True, type=parse_time, help="HT whistle")
    ap.add_argument("--ko2", required=True, type=parse_time, help="2H kickoff")
    ap.add_argument("--ft",  required=True, type=parse_time, help="FT whistle")
    ap.add_argument("--check", action="store_true",
                    help="report only; do not write")
    ap.add_argument("--force", action="store_true",
                    help="write even if the checks fail (recorded in the file)")
    args = ap.parse_args()

    cfg_path = os.path.join(args.match_dir, "match_config.json")
    if not os.path.exists(cfg_path):
        print(f"  [FAIL] no match_config.json in {args.match_dir}", file=sys.stderr)
        return 1

    # Frame count is the video duration at 1fps -- used only to catch an ft
    # past the end of the footage.
    frames_dir = os.path.join(args.match_dir, "frames")
    duration_s = None
    if os.path.isdir(frames_dir):
        n = len([p for p in os.listdir(frames_dir)
                 if p.startswith("frame_") and p.endswith(".jpg")])
        duration_s = n - 1 if n else None

    ko1, ht, ko2, ft = args.ko1, args.ht, args.ko2, args.ft
    print(f"\n  KO 1H: {_label(ko1):>9}")
    print(f"  HT:    {_label(ht):>9}    1H play    {(ht - ko1) // 60}m"
          f"{(ht - ko1) % 60:02d}s")
    print(f"  KO 2H: {_label(ko2):>9}    HT break   {(ko2 - ht) // 60}m"
          f"{(ko2 - ht) % 60:02d}s")
    print(f"  FT:    {_label(ft):>9}    2H play    {(ft - ko2) // 60}m"
          f"{(ft - ko2) % 60:02d}s")
    if duration_s:
        print(f"  Video: {_label(duration_s):>9}    post-match "
              f"{max(0, duration_s - ft) // 60}m"
              f"{max(0, duration_s - ft) % 60:02d}s")

    failures = check(ko1, ht, ko2, ft, duration_s)
    if failures:
        print(f"\n  {len(failures)} check(s) failed:")
        for f in failures:
            print(f"    [!] {f}")
    else:
        print(f"\n  All checks passed.")

    if args.check:
        print("  --check: nothing written.\n")
        return 1 if failures else 0

    if failures and not args.force:
        print("\n  Not written. Re-read the frames around the failing boundary,")
        print("  or pass --force if you are certain the footage really is "
              "this shape.\n")
        return 1

    with open(cfg_path, encoding="utf-8") as f:
        cfg = json.load(f)

    cfg["boundaries_override"] = {
        "ko_1h_seconds":      int(ko1),
        "ht_whistle_seconds": int(ht),
        "ko_2h_seconds":      int(ko2),
        "ft_whistle_seconds": int(ft),
        # Provenance: these are operator assertions from reading frames, not
        # detections. Anything downstream reading this file can tell which.
        "source": "operator",
    }
    if failures:
        cfg["boundaries_override"]["checks_failed"] = failures
        cfg["boundaries_override"]["forced"] = True

    with open(cfg_path, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2, ensure_ascii=False)

    print(f"\n  Written to {cfg_path}")
    if failures:
        print("  [!] --force used: the failed checks are recorded in the file.")
    print(f"\n  Next:\n    python prepare_match.py \"{args.match_dir}\"")
    print("  Step 1b will read the override and skip detection (free).\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
