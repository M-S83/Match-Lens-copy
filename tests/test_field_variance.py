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


# ── derived per-entry fields fall with their sources ─────────────────────────
#
# Redacting a source leaves any average of it standing, still carrying the
# constant. pressing avg_score is the mean of a home intensity fixed at 3.5
# and an away intensity that moves: 85% dominance, under the near-constant
# threshold, so it publishes. line_height avg_pct is the same shape and was
# monitored by nothing at all.

def _sides(home, away, n=21):
    return {"pressing_by_window": [
        {"home_intensity": home, "away_intensity": away[i % len(away)],
         "avg_score": (home + away[i % len(away)]) / 2} for i in range(n)]}


def test_an_average_of_a_stuck_field_is_redacted_too(tmp_path):
    from field_variance import compute, redact

    s = _sides(3.5, [3.0, 3.5, 4.0, 4.5])
    out = redact(s, compute(str(tmp_path), s, write=False))
    e = out["pressing_by_window"][0]

    assert e["home_intensity"] == "not_measured"
    assert e["away_intensity"] != "not_measured", "away moves and must survive"
    assert e["avg_score"] == "not_measured", "the mean carries the constant"


def test_an_average_survives_when_both_sources_move(tmp_path):
    from field_variance import compute, redact

    s = {"pressing_by_window": [
        {"home_intensity": 2.0 + (i % 5) * 0.5,
         "away_intensity": 3.0 + (i % 4) * 0.5,
         "avg_score": 2.5 + (i % 3) * 0.5} for i in range(21)]}
    out = redact(s, compute(str(tmp_path), s, write=False))

    assert out["pressing_by_window"][0]["avg_score"] != "not_measured"


def test_intensity_is_monitored_per_side_not_as_an_average():
    """Averaging a constant home with a moving away gives 85% dominance, which
    slips under the threshold. The fix is monitoring what the agent emitted,
    not moving the threshold."""
    from field_variance import MONITORED

    fields = {f for src, f, _ in MONITORED if src == "pressing_by_window"}
    assert {"home_intensity", "away_intensity"} <= fields


def test_every_derived_field_names_sources_that_are_monitored():
    """A derivation pointing at an unmonitored source can never fire."""
    from field_variance import DERIVED_FIELDS, MONITORED

    monitored = {f"{src}.{f}" for src, f, _ in MONITORED}
    for derived, sources in DERIVED_FIELDS.items():
        assert any(s in monitored for s in sources), derived
