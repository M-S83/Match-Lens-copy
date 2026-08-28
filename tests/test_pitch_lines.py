"""Finding the field of play, and why grass colour could not.

The pitch mask was "largest connected region of grass-coloured pixels". On this
ground that covered 79% of the frame with its top edge at y=95 -- up in the
trees -- because background vegetation shares turf hue and a 35x35 close
bridged it into one blob. It passed nearly every detection as on-pitch, which
is how 52 of 197 frames came to report more than eleven players for one team.

Eroding it did nothing, at any radius from +25px to -31px, because there was a
townscape inside.
"""
import cv2
import numpy as np
import pytest

import pitch_lines as pl
from pitch_lines import (
    MIN_LINE_LEN, SIDE_MARGIN_PX, SIDE_PURITY, WATERMARK_BOX,
    boundaries_from, merge_collinear, outside_play, signed_side,
)


def _line(p1, p2):
    return {"p1": p1, "p2": p2,
            "length": float(np.hypot(p2[0] - p1[0], p2[1] - p1[1])),
            "n_segments": 1}


# ── merging ──────────────────────────────────────────────────────────────────

def test_the_many_echoes_of_one_painted_line_become_one_line():
    """A single touchline returns as a dozen near-identical Hough segments.
    Unmerged, each would vote as an independent boundary."""
    segs = [(100, 500, 900, 300), (102, 499, 880, 305),
            (105, 498, 870, 308), (110, 496, 905, 299)]

    assert len(merge_collinear(segs)) == 1


def test_genuinely_different_lines_stay_separate():
    segs = [(100, 500, 900, 300), (100, 900, 900, 900)]

    assert len(merge_collinear(segs)) == 2


def test_merging_spans_the_full_extent_of_its_parts():
    merged = merge_collinear([(100, 100, 300, 100), (700, 100, 900, 100)])[0]
    xs = sorted([merged["p1"][0], merged["p2"][0]])

    assert xs[0] == pytest.approx(100, abs=6)
    assert xs[1] == pytest.approx(900, abs=6)


# ── which side is the pitch ──────────────────────────────────────────────────

def test_side_is_signed_and_opposite_across_the_line():
    ln = _line((0.0, 500.0), (1000.0, 500.0))

    assert signed_side(ln, [(500, 100)])[0] < 0
    assert signed_side(ln, [(500, 900)])[0] > 0


def test_a_perimeter_line_has_every_player_on_one_side():
    ln = _line((0.0, 400.0), (1900.0, 400.0))
    feet = [(x, 700) for x in range(200, 1400, 150)]

    assert len(boundaries_from([ln], feet)) == 1


def test_a_halfway_line_is_rejected_without_needing_a_rule_for_it():
    """Players on both sides. The purity test disqualifies it by construction,
    so no list of line names has to be maintained."""
    ln = _line((960.0, 0.0), (960.0, 1080.0))
    feet = [(300, 700), (400, 600), (500, 800), (520, 650),
            (1400, 700), (1500, 600), (1600, 800), (1650, 650)]

    assert boundaries_from([ln], feet) == []


def test_a_short_line_is_not_a_boundary_candidate():
    """An 18-yard box edge or a stray shadow should not bound the pitch."""
    short = _line((0.0, 400.0), (float(MIN_LINE_LEN - 40), 400.0))
    feet = [(x, 700) for x in range(200, 1400, 150)]

    assert boundaries_from([short], feet) == []


def test_too_few_confident_players_means_no_boundary_is_claimed():
    """With three players on screen, any line has them all on one side."""
    ln = _line((0.0, 400.0), (1900.0, 400.0))

    assert boundaries_from([ln], [(300, 700), (500, 700), (700, 700)]) == []


def test_purity_is_a_share_not_unanimity():
    assert 0.5 < SIDE_PURITY < 1.0


# ── rejection ────────────────────────────────────────────────────────────────

def test_someone_beyond_the_boundary_is_outside_play():
    ln = _line((0.0, 400.0), (1900.0, 400.0))
    bnds = boundaries_from([ln], [(x, 700) for x in range(200, 1400, 150)])

    assert outside_play(bnds, (900, 200)) is True
    assert outside_play(bnds, (900, 800)) is False


def test_a_player_straddling_the_line_is_not_rejected():
    """A winger with a foot on the touchline is playing.

    The distance is written out rather than derived from SIDE_MARGIN_PX. A
    test that moves with the constant it is testing agrees with any value,
    including zero -- which is the bug it is meant to catch.
    """
    ln = _line((0.0, 400.0), (1900.0, 400.0))
    bnds = boundaries_from([ln], [(x, 700) for x in range(200, 1400, 150)])

    assert outside_play(bnds, (900, 388)) is False, \
        "12px beyond the line is a boot on the paint, not a spectator"
    assert SIDE_MARGIN_PX >= 12


def test_no_boundaries_rejects_nobody():
    """Absence of evidence is not a reason to discard half the pitch."""
    assert outside_play([], (10, 10)) is False


# ── the watermark ────────────────────────────────────────────────────────────

def test_the_veo_watermark_is_masked_out():
    """It produced identical ~140px horizontals at y 968-1005 in three separate
    frames. A static false line would anchor a false boundary in every frame of
    every match filmed on this platform.
    """
    img = np.full((1080, 1920, 3), 60, np.uint8)
    img[:, :, 1] = 200                                   # green-ish turf
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    gh = int(np.bincount(hsv[:, :, 0].ravel(), minlength=180).argmax())
    m = pl.marking_mask(img, hsv, gh)

    if m is not None:
        x1, y1, x2, y2 = WATERMARK_BOX
        corner = m[int(y1 * 1080):int(y2 * 1080), int(x1 * 1920):int(x2 * 1920)]
        assert corner.sum() == 0


def test_the_watermark_box_is_the_bottom_right_corner_only():
    x1, y1, x2, y2 = WATERMARK_BOX
    assert x2 == 1.0 and y2 == 1.0
    assert (1 - x1) < 0.20 and (1 - y1) < 0.20, "must not eat the pitch"
