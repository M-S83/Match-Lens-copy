"""Tests for the head of the pipeline -- Steps 1a, 1, 1b, 1c.

These guard a gap found running the pipeline from a terminal for the first
time: Step 1 (whole-match 1fps frame extraction) had no script. It existed
only as a code block inside SKILL.md, executed by an agent reading the skill.
pipeline_runner_v2.py is the back half and exits immediately without
window_plan.json, which cannot exist without match_boundaries.json, which
cannot exist without frames/.

Unlike the rest of the suite, the extraction tests here exercise cv2 for real
against a synthetic video written by cv2.VideoWriter. They are skipped when
cv2 is the conftest stub, so a bare checkout still runs green.
"""
import ast
import os
import subprocess
import sys

import pytest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

cv2 = pytest.importorskip("cv2")
np = pytest.importorskip("numpy")

# conftest registers a bare stub when the real package is absent; the stub has
# no VideoWriter, so real-video tests must not run against it.
_REAL_CV2 = hasattr(cv2, "VideoWriter") and hasattr(cv2, "VideoCapture")
needs_cv2 = pytest.mark.skipif(not _REAL_CV2,
                               reason="cv2 is stubbed; no real video codec")

SYNTH_FPS = 25.0
SYNTH_FRAMES = 250          # 10 seconds


def _grey(i):
    """Grey value for source frame i.

    97 is coprime with 256, so the sequence visits every value once per 256
    frames -- globally near-unique -- while consecutive frames differ by ~97.
    A step of 1 is useless here: it falls below the codec's quantisation, so
    neighbouring frames decode to identical means and an off-by-one would go
    undetected.
    """
    return (i * 97) % 256


def _write_synthetic_video(path, fps=SYNTH_FPS, n=SYNTH_FRAMES, w=160, h=120):
    """A video whose frame N is a solid colour identifying N.

    Solid colours survive the encode/JPEG round trip well enough that a frame
    can be identified from its pixels, which is what makes "did it pick the
    right frame?" testable rather than merely "did it pick some frame?".
    """
    vw = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"mp4v"), fps, (w, h))
    if not vw.isOpened():
        pytest.skip("no mp4v encoder available in this environment")
    for i in range(n):
        vw.write(np.full((h, w, 3), _grey(i), dtype=np.uint8))
    vw.release()
    return str(path)


def _expected_seconds(n=SYNTH_FRAMES, fps=SYNTH_FPS):
    """Seconds that map to a real source frame index."""
    s = 0
    while int(s * fps) < n:
        s += 1
    return s


# ── Step 1 exists at all ─────────────────────────────────────────────────────

def test_step1_has_a_script():
    """The original gap: every head step but Step 1 had a script.

    Checked by importing the callable rather than by looking for a file, so
    renaming the file without providing the entry point still fails.
    """
    from extract_frames import extract_1fps
    assert callable(extract_1fps)


def test_head_steps_are_all_runnable_scripts():
    for name in ("container_analyser.py", "extract_frames.py",
                 "detect_boundaries.py", "window_plan.py", "prepare_match.py"):
        path = os.path.join(REPO, name)
        assert os.path.exists(path), f"{name} missing from the repo"
        src = open(path, encoding="utf-8").read()
        tree = ast.parse(src)
        has_main = any(
            isinstance(n, ast.If)
            and isinstance(n.test, ast.Compare)
            and isinstance(n.test.left, ast.Name)
            and n.test.left.id == "__name__"
            for n in tree.body)
        assert has_main, f"{name} has no __main__ entry point"


# ── Frame naming is the contract downstream steps reconstruct ────────────────

def test_frame_name_matches_downstream_reconstruction():
    """detect_boundaries.get_frames_in_range builds these names by hand.

    Any divergence means frames exist on disk but are looked up under a name
    that is not there, and the boundary scan silently sees fewer frames.
    """
    from extract_frames import frame_name
    assert frame_name(0) == "frame_00m00s.jpg"
    assert frame_name(9) == "frame_00m09s.jpg"
    assert frame_name(69) == "frame_01m09s.jpg"
    assert frame_name(1029) == "frame_17m09s.jpg"     # SKILL.md's own example


def test_frame_name_does_not_wrap_past_99_minutes():
    """A full match plus stoppage exceeds 99 minutes; MM must widen, not wrap."""
    from extract_frames import frame_name
    assert frame_name(100 * 60 + 5) == "frame_100m05s.jpg"
    assert frame_name(115 * 60) == "frame_115m00s.jpg"


def test_frame_names_sort_chronologically_with_frame_sort_key():
    from extract_frames import frame_name
    from pipeline_paths import frame_sort_key
    secs = [0, 59, 60, 599, 600, 3600, 6000, 6900]
    names = [frame_name(s) for s in secs]
    assert sorted(names, key=frame_sort_key) == names


# ── Frame selection is identical to SKILL.md's Step 1 ────────────────────────

@needs_cv2
def test_extraction_selects_the_same_frames_as_skillmd(tmp_path):
    """Sequential decode must land on the frames SKILL.md's seek lands on.

    SKILL.md Step 1 seeks to int(sec * fps) once per second. This script
    decodes in order to avoid ~6,000 seeks on a full match, which is only a
    safe substitution if it selects the identical frames.
    """
    from extract_frames import extract_1fps, frame_name

    video = _write_synthetic_video(tmp_path / "synth.mp4")
    mine = tmp_path / "mine"
    extract_1fps(video, str(mine))

    # SKILL.md Step 1, verbatim.
    theirs = tmp_path / "theirs"
    theirs.mkdir()
    cap = cv2.VideoCapture(video)
    fps = cap.get(cv2.CAP_PROP_FPS)
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    for sec in range(int(total / fps) + 1):
        fn = int(sec * fps)
        if fn >= total:
            break
        cap.set(cv2.CAP_PROP_POS_FRAMES, fn)
        ret, frame = cap.read()
        if ret:
            cv2.imwrite(os.path.join(str(theirs), frame_name(sec)), frame,
                        [cv2.IMWRITE_JPEG_QUALITY, 80])
    cap.release()

    a = sorted(os.listdir(str(mine)))
    b = sorted(os.listdir(str(theirs)))
    assert a == b and a, f"filename sets differ: {a} vs {b}"
    for n in a:
        x = cv2.imread(os.path.join(str(mine), n))
        y = cv2.imread(os.path.join(str(theirs), n))
        assert np.array_equal(x, y), f"{n} differs from SKILL.md's selection"


@needs_cv2
def test_extraction_is_not_off_by_one(tmp_path):
    """Guards the failure the previous test would still pass under.

    If both implementations were off by the same frame they would agree with
    each other and both be wrong, so pin the absolute mapping: the frame
    written for second S must be source frame int(S * fps), and must be
    distinguishable from its neighbour.
    """
    from extract_frames import extract_1fps, frame_name

    video = _write_synthetic_video(tmp_path / "synth.mp4")
    out = tmp_path / "out"
    extract_1fps(video, str(out))

    cap = cv2.VideoCapture(video)
    truth, i = {}, 0
    while True:
        ok, f = cap.read()
        if not ok:
            break
        truth[i] = float(f.mean())
        i += 1
    cap.release()

    for sec in range(_expected_seconds()):
        idx = int(sec * SYNTH_FPS)
        got = float(cv2.imread(os.path.join(str(out), frame_name(sec))).mean())
        assert abs(got - truth[idx]) < 2.0, (
            f"second {sec}: expected source frame {idx} "
            f"(mean {truth[idx]:.2f}) but got mean {got:.2f}")
        # Neighbours must be far apart, or the assertion above proves nothing
        # about *which* frame was chosen.
        for off in (-1, 1):
            if idx + off in truth:
                assert abs(got - truth[idx + off]) > 20.0, (
                    f"second {sec}: frame {idx} is indistinguishable from "
                    f"{idx + off}; this test cannot detect an off-by-one")


@needs_cv2
def test_extraction_writes_one_frame_per_second(tmp_path):
    from extract_frames import extract_1fps
    video = _write_synthetic_video(tmp_path / "synth.mp4")
    result = extract_1fps(video, str(tmp_path / "out"))
    assert result["written"] == _expected_seconds()
    assert result["failed_seconds"] == []
    assert result["fps"] == pytest.approx(SYNTH_FPS)


# ── Absent input must fail, never default ────────────────────────────────────

@needs_cv2
def test_unopenable_video_raises(tmp_path):
    """A missing video must not produce an empty-but-successful frame set."""
    from extract_frames import extract_1fps
    bad = tmp_path / "nope.mp4"
    bad.write_bytes(b"not a video")
    with pytest.raises((IOError, ValueError)):
        extract_1fps(str(bad), str(tmp_path / "out"))


def test_unreadable_fps_raises_rather_than_defaulting(monkeypatch, tmp_path):
    """fps of 0 must raise.

    Defaulting to any fps would map every second to frame 0 and yield a full
    set of identical frames -- a frame set that looks complete and is entirely
    wrong. This is the exact fabrication shape the pipeline forbids.
    """
    import extract_frames

    class _FakeCap:
        def __init__(self, *a):
            pass

        def isOpened(self):
            return True

        def get(self, prop):
            return 0.0          # fps and frame count both unreadable

        def release(self):
            pass

    monkeypatch.setattr(extract_frames.cv2, "VideoCapture", _FakeCap)
    with pytest.raises(ValueError):
        extract_frames.extract_1fps("whatever.mp4", str(tmp_path / "out"))


# ── prepare_match runs the head in the one order that works ──────────────────

def _script_call_order(path):
    """Filenames of the scripts prepare_match shells out to, in source order."""
    tree = ast.parse(open(path, encoding="utf-8").read())
    seen = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str) \
                and node.value.endswith(".py"):
            seen.append((node.lineno, node.col_offset, node.value))
    return [v for _, _, v in sorted(seen)]


def test_prepare_match_runs_head_steps_in_dependency_order():
    """1a -> 1 -> 1b -> 1c. Each step consumes the previous step's output.

    Out of order, window_plan.py reads a match_boundaries.json that is absent
    or stale and produces windows over the wrong minutes of footage, which
    nothing downstream detects.
    """
    order = _script_call_order(os.path.join(REPO, "prepare_match.py"))
    wanted = ["container_analyser.py", "extract_frames.py",
              "detect_boundaries.py", "window_plan.py"]
    got = [s for s in order if s in wanted]
    assert got == wanted, f"head steps invoked in the wrong order: {got}"


def test_prepare_match_rejects_a_directory_without_config():
    """Refuse early rather than failing three steps in."""
    r = subprocess.run(
        [sys.executable, os.path.join(REPO, "prepare_match.py"),
         os.path.dirname(os.path.abspath(__file__))],
        capture_output=True, text=True)
    assert r.returncode != 0
    assert "match_config.json" in (r.stdout + r.stderr)


def test_prepare_match_rejects_a_missing_directory():
    r = subprocess.run(
        [sys.executable, os.path.join(REPO, "prepare_match.py"),
         os.path.join(REPO, "definitely-not-here")],
        capture_output=True, text=True)
    assert r.returncode != 0
