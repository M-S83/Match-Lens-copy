"""A field that never varies has not been measured.

The structural agent returned defensive_line.home_height_pct = 45.0 in
nineteen windows of twenty, formation.home = "4-4-2" in twenty-one of
twenty-one, and pressing.home_intensity = 3.5 in twenty of twenty. Eighteen
further runs against an identical set of frames returned the same values
again -- so the constancy is a property of the field, not of the match.

The accumulator counts such a field as maximally consistent and the report
grades it [A], offering its consistency as evidence of a stable defensive
line. These tests pin the check that tells the two apart.
"""
import pytest

from field_variance import (
    MEASURED, NEAR_CONSTANT, NO_DATA, NOT_MEASURED, UNMEASURED,
    classify, compute, unmeasured_families,
)


def test_a_field_that_never_varies_is_not_measured():
    assert classify(["4-4-2"] * 21)["verdict"] == NOT_MEASURED


def test_one_outlier_does_not_rescue_a_stuck_field():
    """home_height_pct: 45.0 nineteen times and 55.0 once.

    Two distinct values clears a naive `distinct > 1` test, which is why the
    check is on the modal share instead.
    """
    values = [45.0] * 19 + [55.0]

    rec = classify(values)
    assert rec["verdict"] == NEAR_CONSTANT
    assert rec["dominant_share"] == 0.95
    assert rec["verdict"] in UNMEASURED


def test_a_field_that_moves_is_measured():
    """away_height_pct across the real match: 40 x13, 50 x3, 42 x2, 45, 48."""
    values = [40.0] * 13 + [50.0] * 3 + [42.0] * 2 + [45.0, 48.0]

    rec = classify(values)
    assert rec["verdict"] == MEASURED
    assert rec["distinct"] == 5


def test_a_short_run_of_the_same_value_is_not_an_accusation():
    """Three windows of 4-4-2 is a short match, not a stuck sensor."""
    assert classify(["4-4-2"] * 3)["verdict"] == NO_DATA


def test_all_null_is_reported_as_absence_not_as_a_constant():
    """pressing_by_window.avg_score is null on every window of every match.

    That is a key mismatch in the accumulator, a different defect from a
    stuck field, and collapsing the two would hide which one you have.
    """
    rec = classify([None] * 21)

    assert rec["verdict"] == NO_DATA
    assert rec["windows_with_value"] == 0


def test_nulls_do_not_count_toward_the_window_threshold():
    assert classify([45.0] * 7 + [None] * 40)["verdict"] == NO_DATA


# ── end to end over a running_summary ─────────────────────────────────────────

def _summary(n=21):
    return {
        "match": "Gorleston vs Tilbury",
        "formation_history": [
            {"home_formation": "4-4-2", "away_formation": "4-4-2",
             "home_shape": "mid", "away_shape": "mid"} for _ in range(n)],
        "line_height_m_by_window": [
            {"home_height_pct": 45.0,
             "away_height_pct": 40.0 + (i % 5) * 2} for i in range(n)],
        "pressing_by_window": [{"avg_score": None} for _ in range(n)],
        "possession_by_window": [{"focus_pct": 50.0} for _ in range(n)],
    }


def test_compute_flags_the_fields_that_never_moved(tmp_path):
    report = compute(str(tmp_path), _summary(), write=False)

    assert "formation_history.home_formation" in report["not_measured"]
    assert "line_height_m_by_window.home_height_pct" in report["not_measured"]
    assert "possession_by_window.focus_pct" in report["not_measured"]
    assert "line_height_m_by_window.away_height_pct" not in report["not_measured"]


def test_compute_names_the_families_a_grader_must_not_trust(tmp_path):
    families = unmeasured_families(compute(str(tmp_path), _summary(), write=False))

    assert "shape" in families
    assert "territory" in families


def test_match_state_is_not_monitored():
    """It comes from the operator's goal times, not from frames.

    Gorleston led from minute 6, so match_state is constant across 19 of 21
    windows -- a fact about the match. Alarming on it would train people to
    ignore the alarm.
    """
    from field_variance import MONITORED

    assert all(src != "match_state_by_window" for src, _, _ in MONITORED)


def test_compute_writes_the_report_where_the_reader_looks(tmp_path):
    import json
    compute(str(tmp_path), _summary(), write=True)

    written = json.loads((tmp_path / "field_variance.json").read_text())
    assert written["not_measured"] == compute(
        str(tmp_path), _summary(), write=False)["not_measured"]


def test_compute_refuses_to_invent_a_summary(tmp_path):
    with pytest.raises(FileNotFoundError):
        compute(str(tmp_path))
