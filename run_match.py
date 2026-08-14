#!/usr/bin/env python3
"""
run_match.py -- one command from a bare clone to a running analysis.

    python run_match.py --video "C:/Users/dbmux/Desktop/Grays Analysis/69ca....mp4" ^
                        --home "Grays Athletic" --away "Opponent FC" ^
                        --date 2026-08-09 ^
                        --dir "C:/Users/dbmux/Desktop/Grays Analysis"

It performs, in order, stopping at the first failure:

  1. writes .env if absent (prompting for the key, never echoing it)
  2. runs check_setup.py and aborts unless it exits 0
  3. scaffolds match_config.json via new_match.py
  4. runs the pipeline head (prepare_match.py: Steps 1a, 1, 1b, 1c)
  5. runs the pipeline

Written in Python rather than PowerShell on purpose. `.env` encoding is the
single most common way setup fails on Windows -- PowerShell's `>` writes UTF-16
and its 5.1 `-Encoding utf8` writes a BOM that becomes part of the first key
name. Python's open(..., encoding="utf-8") writes neither, so the whole class of
problem disappears.

    --dry-run    do everything except the paid pipeline run
    --force-env  overwrite an existing .env
    --force      overwrite an existing match_config.json
"""
import argparse
import getpass
import os
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent


def step(n, title):
    print(f"\n{'=' * 64}\n  {n}. {title}\n{'=' * 64}")


def run(cmd, **kw):
    """Run a subprocess with this interpreter, streaming output."""
    print(f"  $ {' '.join(str(c) for c in cmd)}")
    return subprocess.run(cmd, **kw).returncode


def ensure_env(force: bool, key_arg: str | None) -> bool:
    env_path = REPO / ".env"

    if env_path.exists() and not force:
        raw = env_path.read_bytes()
        if raw[:2] in (b"\xff\xfe", b"\xfe\xff"):
            print("  [FAIL] existing .env is UTF-16 (PowerShell `>` writes this).")
            print("         Re-run with --force-env to rewrite it correctly.")
            return False
        if raw[:3] == b"\xef\xbb\xbf":
            print("  [WARN] existing .env starts with a UTF-8 BOM. The runner")
            print("         tolerates it, but --force-env would rewrite it clean.")
        print(f"  [OK]   .env already exists: {env_path}")
        return True

    key = key_arg or os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        print("  No .env and no ANTHROPIC_API_KEY in the environment.")
        try:
            # getpass so the key is not echoed to the terminal or shell history
            key = getpass.getpass("  Paste your Anthropic API key (hidden): ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n  [FAIL] no key supplied.")
            return False
    if not key:
        print("  [FAIL] no key supplied.")
        return False

    # UTF-8, no BOM, LF. This is the whole reason the script is Python.
    with open(env_path, "w", encoding="utf-8", newline="\n") as f:
        f.write(f"ANTHROPIC_API_KEY={key}\n")
    print(f"  [OK]   wrote {env_path} (UTF-8, no BOM, key ends ...{key[-4:]})")
    print("         .env is gitignored -- it will not be committed.")
    return True


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Set up and run a Match Lens analysis end to end.")
    ap.add_argument("--video", required=True)
    ap.add_argument("--home",  required=True)
    ap.add_argument("--away",  required=True)
    ap.add_argument("--dir",   required=True, dest="directory")
    ap.add_argument("--date",  default="")
    ap.add_argument("--quality", default="standard",
                    choices=["economy", "standard", "full", "high_density", "full_1fps"])
    ap.add_argument("--api-key", default=None,
                    help="avoid on shared machines; prompts if omitted")
    ap.add_argument("--home-kit", default="")
    ap.add_argument("--away-kit", default="")
    ap.add_argument("--force-env", action="store_true")
    ap.add_argument("--force",     action="store_true")
    ap.add_argument("--dry-run",   action="store_true",
                    help="everything except the paid pipeline run")
    args = ap.parse_args()

    py = sys.executable

    step(1, "API key")
    if not ensure_env(args.force_env, args.api_key):
        return 1

    step(2, "Preflight")
    if run([py, str(REPO / "check_setup.py")]) != 0:
        print("\n  Preflight failed. Fix the [FAIL] items above and re-run.")
        return 1

    step(3, "Match directory")
    cmd = [py, str(REPO / "new_match.py"),
           "--video", args.video, "--home", args.home, "--away", args.away,
           "--dir", args.directory]
    for flag, val in (("--date", args.date), ("--home-kit", args.home_kit),
                      ("--away-kit", args.away_kit)):
        if val:
            cmd += [flag, val]
    if args.force:
        cmd.append("--force")
    rc = run(cmd)
    if rc != 0:
        cfg = Path(args.directory) / "match_config.json"
        if cfg.exists() and not args.force:
            print(f"\n  {cfg} already exists — keeping it.")
            print("  Pass --force to regenerate (this discards any lineups or")
            print("  goals you have filled in).")
        else:
            return 1

    step(4, "Pipeline head -- Steps 1a/1/1b/1c")
    # pipeline_runner_v2.py is the back half and exits without window_plan.json.
    # Step 1b inside here calls the API, so --dry-run stops before it.
    if args.dry_run:
        print("  --dry-run: stopping before Step 1b, the first paid step.\n")
        print("  When ready:")
        print(f'    {py} prepare_match.py "{args.directory}"')
        print(f'    {py} pipeline_runner_v2.py "{args.directory}" '
              f'--quality {args.quality}')
        return 0
    if run([py, str(REPO / "prepare_match.py"), args.directory]) != 0:
        print("\n  Pipeline head failed -- not starting the main run.")
        return 1

    step(5, "Pipeline")

    print("  Fill in `lineups` and `goals` in match_config.json first if you")
    print("  can — both materially improve output. Ctrl-C now if you want to.\n")
    return run([py, str(REPO / "pipeline_runner_v2.py"),
                args.directory, "--quality", args.quality])


if __name__ == "__main__":
    sys.exit(main())
