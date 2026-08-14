#!/usr/bin/env python3
"""
check_setup.py -- preflight for a Match Lens run.

Run this before spending anything. It checks every prerequisite the pipeline
needs and tells you exactly what is missing and how to fix it, rather than
letting you discover it as a stack trace forty minutes in.

    python check_setup.py

Exit codes:
    0  ready to run
    1  something blocking is missing (each one is named)

Why this exists: step 1a shells out to ffprobe, and a missing ffprobe used to
surface on Windows as "[WinError 2] The system cannot find the file specified",
naming neither ffprobe nor ffmpeg. The most common cause is entirely mundane --
winget updates PATH but not shells that are already open.
"""
import importlib
import os
import shutil
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent

OK, WARN, FAIL = "  [OK]  ", "  [WARN]", "  [FAIL]"

# import name -> (pip name, why the pipeline needs it)
REQUIRED = {
    "anthropic":  ("anthropic",      "Claude API + Message Batches"),
    "cv2":        ("opencv-python",  "video decode, frame extraction"),
    "PIL":        ("Pillow",         "frame image handling"),
    "numpy":      ("numpy",          "frame preprocessing"),
    "dotenv":     ("python-dotenv",  "loading ANTHROPIC_API_KEY"),
    "docx":       ("python-docx",    "Step 5 Word conversion"),
}
OPTIONAL = {
    "easyocr":    ("easyocr",    "requirements-ocr.txt",     "jersey-number OCR (Step 2b self-skips without it)"),
    "weasyprint": ("weasyprint", "requirements-reports.txt", "branded PDF reports"),
    "pytest":     ("pytest",     "requirements-dev.txt",     "the regression suite"),
}


def _v(mod):
    return getattr(mod, "__version__", "(no __version__)")


def check_python():
    print("\nPython")
    major, minor = sys.version_info[:2]
    if (major, minor) >= (3, 10):
        print(f"{OK} {sys.version.split()[0]}  ({sys.executable})")
        return True
    print(f"{FAIL} {sys.version.split()[0]} -- 3.10+ required "
          f"(the code uses PEP 604 unions, e.g. `str | None`)")
    return False


def check_packages():
    print("\nRequired packages")
    missing = []
    for imp, (pip_name, why) in REQUIRED.items():
        try:
            mod = importlib.import_module(imp)
            print(f"{OK} {pip_name:16} {_v(mod):12} {why}")
        except ImportError:
            print(f"{FAIL} {pip_name:16} {'MISSING':12} {why}")
            missing.append(pip_name)
    if missing:
        print(f"\n       Fix: pip install -r requirements.txt")
    return not missing


def check_optional():
    print("\nOptional packages")
    for imp, (pip_name, req_file, why) in OPTIONAL.items():
        try:
            mod = importlib.import_module(imp)
            print(f"{OK} {pip_name:16} {_v(mod):12} {why}")
        except ImportError:
            print(f"{WARN} {pip_name:16} {'absent':12} {why}")
            print(f"         -> pip install -r {req_file}")


def check_ffprobe():
    print("\nffmpeg / ffprobe")
    path = shutil.which("ffprobe")
    if not path:
        print(f"{FAIL} ffprobe not on PATH -- step 1a cannot run")
        print( "         Windows: winget install Gyan.FFmpeg")
        print( "         macOS:   brew install ffmpeg")
        print( "         Linux:   sudo apt install ffmpeg")
        print( "         Then OPEN A NEW TERMINAL -- a PATH update does not reach")
        print( "         shells that are already running. This is the most common")
        print( "         cause of step 1a failing.")
        return False
    try:
        out = subprocess.run(["ffprobe", "-version"], capture_output=True,
                             text=True, timeout=15)
        ver = out.stdout.splitlines()[0] if out.stdout else "(no version output)"
        print(f"{OK} {ver}")
        print(f"         {path}")
        return True
    except Exception as e:
        print(f"{FAIL} ffprobe found at {path} but would not run: {e}")
        return False


def check_api_key():
    """Mirror the runner's own search order (pipeline_runner_v2.py:39-41)."""
    print("\nAnthropic API key")
    # Deduplicate: when the repo sits directly in the home directory --
    # C:\Users\<name>\Match-Lens-copy -- REPO.parent and Path.home() are the
    # same path, and the list printed it twice.
    searched, _seen = [], set()
    for _p in (REPO / ".env", REPO.parent / ".env", Path.home() / ".env"):
        _r = _p.resolve()
        if _r not in _seen:
            _seen.add(_r)
            searched.append(_p)
    found_env = next((p for p in searched if p.exists()), None)

    key = None
    if found_env:
        print(f"{OK} .env found: {found_env}")
        try:
            from dotenv import dotenv_values
        except ImportError:
            print(f"{WARN} python-dotenv is not installed, cannot read it")
        else:
            # Encoding is the single most common way a .env silently fails on
            # Windows, and the two failure modes need different messages.
            raw = found_env.read_bytes()
            if raw[:2] in (b"\xff\xfe", b"\xfe\xff"):
                print(f"{FAIL} .env is UTF-16, not UTF-8 -- python-dotenv cannot read it")
                print( "         PowerShell's `>` redirection writes UTF-16 by default.")
                print( "         Rewrite it as UTF-8 without a BOM:")
                print( '           [IO.File]::WriteAllText("$PWD\\.env", "ANTHROPIC_API_KEY=sk-ant-...")')
                return False
            try:
                vals = dotenv_values(found_env)
            except UnicodeDecodeError as e:
                print(f"{FAIL} .env is not valid UTF-8: {e}")
                print( "         Rewrite it as UTF-8 without a BOM:")
                print( '           [IO.File]::WriteAllText("$PWD\\.env", "ANTHROPIC_API_KEY=sk-ant-...")')
                return False
            key = vals.get("ANTHROPIC_API_KEY")
            if key is None and any(k.lstrip("\ufeff") == "ANTHROPIC_API_KEY"
                                   for k in vals if k):
                # The quiet one: PowerShell 5.1's `-Encoding utf8` writes a BOM,
                # which becomes part of the FIRST key name. Nothing errors; the
                # lookup just returns None while the file plainly contains it.
                print(f"{FAIL} .env begins with a UTF-8 BOM, so the first key is read as")
                print( "         '\\ufeffANTHROPIC_API_KEY' and the lookup silently misses it.")
                print( "         Rewrite it as UTF-8 without a BOM:")
                print( '           [IO.File]::WriteAllText("$PWD\\.env", "ANTHROPIC_API_KEY=sk-ant-...")')
                return False
    else:
        print(f"{WARN} no .env in any of:")
        for p in searched:
            print(f"         {p}")

    key = key or os.environ.get("ANTHROPIC_API_KEY")
    if key:
        src = ".env" if found_env and key else "environment"
        print(f"{OK} ANTHROPIC_API_KEY present via {src} (ends ...{key[-4:]})")
        return True

    print(f"{FAIL} ANTHROPIC_API_KEY not set")
    print(f"         Create {REPO / '.env'} containing:")
    print( "           ANTHROPIC_API_KEY=sk-ant-...")
    print( "         (.env is gitignored -- it will not be committed)")
    return False


def check_repo():
    print("\nRepository")
    ok = True
    for name in ("pipeline_runner_v2.py", "requirements.txt", "SKILL.md"):
        if (REPO / name).exists():
            print(f"{OK} {name}")
        else:
            print(f"{FAIL} {name} missing -- are you in the repo root?")
            ok = False
    return ok


def main():
    print("=" * 64)
    print("  Match Lens -- preflight")
    print("=" * 64)

    results = [
        check_python(),
        check_repo(),
        check_packages(),
        check_ffprobe(),
        check_api_key(),
    ]
    check_optional()   # never blocking

    print("\n" + "=" * 64)
    if all(results):
        print("  READY -- all prerequisites satisfied.")
        print("\n  Next:")
        print('    python new_match.py --video "<path to .mp4>" \\')
        print('                        --home "Home Team" --away "Away Team" \\')
        print('                        --dir "<match dir>"')
        print('    python prepare_match.py "<match dir>"          # Steps 1a/1/1b/1c')
        print('    python pipeline_runner_v2.py "<match dir>" --quality standard')
        print("=" * 64)
        return 0

    print("  NOT READY -- fix the [FAIL] items above, then re-run this check.")
    print("=" * 64)
    return 1


if __name__ == "__main__":
    sys.exit(main())
