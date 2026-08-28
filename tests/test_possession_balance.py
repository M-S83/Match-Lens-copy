"""Possession balance must report what was measured, not what is plausible.

calc_possession_balance read focus_pct as ``(w.get("focus_pct") or 50)``.
A window with no reading became a perfectly balanced one, was divided into
by the full window count, and voted in windows_focus_dominant. Two windows,
one unreadable and one at 70%, reported 60% -- a number that describes no
window in the match.

The same expression crashed with a TypeError once field_variance began
redacting focus_pct to the string "not_measured", because a non-empty string
is truthy and went straight into sum(). Nothing in the suite covered this
function at all, in either failure.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from deep_skill_metrics import calc_possession_balance
import field_variance as FV


def _windows(*values):
    return {"possession_by_window": [
        {"window": f"w{i:02d}", "focus_pct": v, "focus_seqs": 10,
         "opp_seqs": 10, "basis": "sequence_count"}
        for i, v in enumerate(values)]}


def test_an_unmeasured_window_does_not_become_a_balanced_one():
    """The original defect, stated as an outcome rather than an expression."""
    out = calc_possession_balance(_windows(None, 70.0))
    assert out["focus_avg_pct"] == 70.0, (
        "a window with no reading was averaged in as 50%, producing a figure "
        "that describes neither window")
    assert out["windows_measured"] == 1
    assert out["windows_withheld"] == 1


def test_the_denominator_is_the_windows_that_carried_a_reading():
    out = calc_possession_balance(_windows(60.0, None, None, 60.0))
    assert out["focus_avg_pct"] == 60.0
    assert out["windows_total"] == 4
    assert out["windows_measured"] == 2
    assert out["windows_withheld"] == 2


def test_an_unmeasured_window_cannot_vote_for_dominance():
    """`or 50` never reached 55, but it still sat in the denominator.

    Here the withheld windows must neither count as dominant nor dilute the
    two that are.
    """
    out = calc_possession_balance(_windows(58.0, None, None, 62.0))
    assert out["windows_focus_dominant"] == 2
    assert out["balance"] == "dominant"


def test_redacted_values_do_not_crash():
    out = calc_possession_balance(_windows(FV.NOT_MEASURED, FV.NOT_MEASURED))
    assert out["focus_avg_pct"] is None
    assert out["windows_measured"] == 0
    assert out["windows_withheld"] == 2
    assert out["balance"] is None
    assert "basis" in out


def test_a_fully_redacted_match_reports_nothing_rather_than_fifty():
    """End to end with the redaction that now applies to this match.

    The Gorleston possession numbers are withheld because the team label they
    are built from alternates strictly. What reaches the metric is a column
    of "not_measured" strings, and the honest output is an absent figure --
    not 50%, and not an exception.
    """
    summary = _windows(*([50.0] * 10))
    report  = {"not_measured": ["possession_by_window.focus_pct",
                               "possession_by_window.focus_seqs",
                               "possession_by_window.opp_seqs"],
               "fields": {}}
    redacted = FV.redact(summary, report)
    out = calc_possession_balance(redacted)
    assert out["focus_avg_pct"] is None
    assert out["windows_withheld"] == 10


def test_a_clean_match_is_unaffected():
    out = calc_possession_balance(_windows(40.0, 45.0, 60.0, 55.0))
    assert out["focus_avg_pct"] == 50.0
    assert out["opposition_avg_pct"] == 50.0
    assert out["windows_measured"] == 4
    assert out["windows_withheld"] == 0
    assert out["balance"] == "contested"


def test_no_possession_data_at_all_returns_empty():
    assert calc_possession_balance({}) == {}
    assert calc_possession_balance({"possession_by_window": []}) == {}


def test_booleans_are_not_readings():
    """isinstance(True, int) is True in Python; a bool must not average in."""
    out = calc_possession_balance(_windows(True, 80.0))
    assert out["focus_avg_pct"] == 80.0
    assert out["windows_withheld"] == 1
