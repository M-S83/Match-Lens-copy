"""Sampling live play, and building a set that can actually score a change.

Three separate changes in one session each improved the average while breaking
the single frame that had a hand count -- and each was only caught because that
frame existed. These pin the sampling, because a validation set that misses the
failure modes measures nothing while looking like it measures something.
"""
import json
import os

import numpy as np
import pytest

from label_set import _spread, prepare
from team_detect import MAX_ON_PITCH, frame_seconds, in_play, live_play_spans


# ── the video clock ──────────────────────────────────────────────────────────

def test_minutes_past_99_still_parse():
    """This video runs to 121 minutes and the minute field is not fixed-width,
    so the number has to be parsed rather than the string sliced."""
    assert frame_seconds("frame_121m22s.jpg") == 7282
    assert frame_seconds("frame_09m46s.jpg") == 586


def test_a_name_that_is_not_a_frame_returns_nothing():
    assert frame_seconds("labels.json") is None


# ── dead time ────────────────────────────────────────────────────────────────

def _boundaries(tmp_path, ko1=350, ht=3245, ko2=4269, ft=7282):
    (tmp_path / "match_boundaries.json").write_text(json.dumps({
        "boundaries": {k: {"seconds": v} for k, v in
                       (("ko_1h", ko1), ("ht_whistle", ht),
                        ("ko_2h", ko2), ("ft_whistle", ft))}}), encoding="utf-8")
    return live_play_spans(str(tmp_path))


def test_half_time_is_not_football(tmp_path):
    """A dead-time frame does not fail loudly -- it returns a confident,
    meaningless split. One reported 13 home players, which cannot happen.
    Three of the first ten frames sampled by hand were inside the interval.
    """
    spans = _boundaries(tmp_path)

    assert in_play(1500, spans) is True      # 25m, first half
    assert in_play(3300, spans) is False     # 55m, half-time
    assert in_play(4200, spans) is False     # 70m, still half-time
    assert in_play(5700, spans) is False or in_play(5700, spans) is True
    assert in_play(100, spans) is False      # pre-match warm-up


def test_missing_boundaries_raise_rather_than_defaulting_to_everything(tmp_path):
    """Pre-match, half-time and post-match are 1478 seconds here, and every one
    of those frames produces a count that looks exactly like a real one."""
    with pytest.raises(FileNotFoundError):
        live_play_spans(str(tmp_path))


def test_incomplete_boundaries_are_refused(tmp_path):
    (tmp_path / "match_boundaries.json").write_text(
        json.dumps({"boundaries": {"ko_1h": {"seconds": 350}}}), encoding="utf-8")

    with pytest.raises(ValueError):
        live_play_spans(str(tmp_path))


# ── choosing frames ──────────────────────────────────────────────────────────

def test_the_set_is_spread_not_clustered():
    """Random sampling clusters by chance, and the failure modes are
    positional: a dugout in view, a goal in view, the far touchline in view."""
    picked = [(t, f"f{t}") for t in range(0, 6000, 10)]
    got = [t for t, _ in _spread(picked, 8)]
    gaps = np.diff(got)

    assert len(got) == 8
    assert gaps.std() < 0.1 * gaps.mean()


def test_the_first_and_last_frames_are_never_chosen():
    """Spreading across the full range landed exactly on the kickoff whistle
    and the full-time whistle -- players walking on and walking off, the two
    least representative moments in the match. Both got picked on the first
    run.
    """
    picked = [(t, f"f{t}") for t in range(0, 6000, 10)]
    got = [t for t, _ in _spread(picked, 8)]

    assert got[0] > picked[0][0]
    assert got[-1] < picked[-1][0]


def test_a_short_list_is_returned_whole():
    picked = [(t, f"f{t}") for t in (10, 20, 30)]
    assert _spread(picked, 8) == picked


# ── the labels file ──────────────────────────────────────────────────────────

def _match(tmp_path, n_frames=40):
    _boundaries(tmp_path)
    frames = tmp_path / "frames"
    frames.mkdir()
    import cv2
    img = np.zeros((40, 60, 3), np.uint8)
    for i in range(n_frames):
        t = 400 + i * 60
        cv2.imwrite(str(frames / f"frame_{t//60:02d}m{t%60:02d}s.jpg"), img)
    return str(tmp_path)


def test_prepare_writes_blank_counts_for_a_human(tmp_path):
    md = _match(tmp_path)
    prepare(md, 5)

    rows = json.loads((tmp_path / "label_set" / "labels.json").read_text())["labels"]
    assert 0 < len(rows) <= 5
    assert all(r["home"] is None and r["away"] is None for r in rows)


def test_re_preparing_never_discards_counts_already_done(tmp_path):
    """Counting is the expensive part and the only part a machine cannot do."""
    md = _match(tmp_path)
    prepare(md, 5)
    path = tmp_path / "label_set" / "labels.json"
    d = json.loads(path.read_text())
    d["labels"][0].update(home=6, away=9, keeper=1)
    path.write_text(json.dumps(d))

    prepare(md, 5)

    after = {r["frame"]: r for r in json.loads(path.read_text())["labels"]}
    assert after[d["labels"][0]["frame"]]["home"] == 6
    assert after[d["labels"][0]["frame"]]["away"] == 9


# ── the validity rule ────────────────────────────────────────────────────────

def test_eleven_is_the_ceiling_a_frame_cannot_exceed():
    """Not a tuned threshold -- a law of the game. A frame claiming more is not
    noisy, it is provably wrong, and averaging it in launders a known error
    into a plausible-looking median."""
    assert MAX_ON_PITCH == 11
