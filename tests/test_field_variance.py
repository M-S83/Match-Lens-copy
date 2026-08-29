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


# ── a default two fields share ────────────────────────────────────────────
#
# Dominance alone could not catch pressing. home_intensity was 3.5 in twenty
# windows of twenty and was correctly withheld. away_intensity was 3.5 in
# seventeen of twenty -- 85%, just under the 90% threshold -- so it passed as
# measured, and the report published "away pressing intensity was
# directionally measurable at 3.5".
#
# Lowering the threshold would be a guess. The tell is not the share: it is
# that both fields keep returning the SAME number. One of them provably is
# not measuring anything, so a sibling answering with that same value is
# reading the same default.

import json

import field_variance as _FV


def _fields(**specs):
    """{'list.field': (verdict, {value: count}, share)} -> a fields dict."""
    out = {}
    for key, (verdict, values, share) in specs.items():
        out[key.replace("__", ".")] = {
            "verdict": verdict, "values": values, "dominant_share": share,
            "windows_total": 20, "windows_with_value": 20,
            "distinct": len(values), "family": key.split("__")[0]}
    return out


def test_a_sibling_that_keeps_returning_the_stuck_value_is_anchored():
    """The Gorleston pressing case."""
    fields = _fields(
        pressing_by_window__home_intensity=(_FV.NOT_MEASURED, {3.5: 20}, 1.0),
        pressing_by_window__away_intensity=(
            _FV.MEASURED, {3.5: 17, 5.5: 1, 2.5: 1, 2.0: 1}, 0.85))
    flagged = _FV.mark_shared_defaults(fields)

    assert flagged == ["pressing_by_window.away_intensity"]
    rec = fields["pressing_by_window.away_intensity"]
    assert rec["verdict"] == _FV.ANCHORED
    assert rec["anchored_on"] == "pressing_by_window.home_intensity"
    assert "3.5" in rec["reason"]


def test_a_sibling_with_a_DIFFERENT_modal_value_survives():
    """The check that this discriminates instead of flagging everything.

    home_height_pct is stuck at 45.0 while away_height_pct's modal value is
    40.0. Different numbers, so the away line is moving on its own.
    """
    fields = _fields(
        line_height_m_by_window__home_height_pct=(
            _FV.NEAR_CONSTANT, {45.0: 19, 55.0: 1}, 0.95),
        line_height_m_by_window__away_height_pct=(
            _FV.MEASURED, {40.0: 13, 50.0: 3, 42.0: 2, 45.0: 1, 48.0: 1}, 0.65))
    assert _FV.mark_shared_defaults(fields) == []
    assert (fields["line_height_m_by_window.away_height_pct"]["verdict"]
            == _FV.MEASURED)


def test_fields_in_different_lists_do_not_anchor_each_other():
    """A coincidence of value across unrelated families is not evidence."""
    fields = _fields(
        pressing_by_window__home_intensity=(_FV.NOT_MEASURED, {50.0: 20}, 1.0),
        possession_by_window__focus_pct=(_FV.MEASURED, {50.0: 15, 60.0: 5}, 0.75))
    assert _FV.mark_shared_defaults(fields) == []


def test_a_genuinely_varied_field_is_not_anchored_by_a_rare_match():
    """Below ANCHOR_SHARE the modal value is not a default, it is a mode."""
    fields = _fields(
        pressing_by_window__home_intensity=(_FV.NOT_MEASURED, {3.5: 20}, 1.0),
        pressing_by_window__away_intensity=(
            _FV.MEASURED, {3.5: 6, 5.5: 5, 2.5: 5, 2.0: 4}, 0.30))
    assert _FV.mark_shared_defaults(fields) == []


def test_anchored_counts_as_unmeasured():
    assert _FV.ANCHORED in _FV.UNMEASURED


def test_the_whole_pressing_family_is_withheld_end_to_end(tmp_path):
    rows = []
    for i, away in enumerate([3.5] * 17 + [5.5, 2.5, 2.0]):
        rows.append({"window": f"w{i:02d}", "home_intensity": 3.5,
                     "away_intensity": away, "peak": max(3.5, away),
                     "avg_score": round((3.5 + away) / 2, 2),
                     "observations": [{"trigger": "back_pass"}]})
    summary = {"match": "t", "pressing_by_window": rows}
    report  = _FV.compute(str(tmp_path), running_summary=summary, write=False)

    assert report["anchored"], "away_intensity passed the dominance test again"
    out = _FV.redact(summary, report)
    for field in ("home_intensity", "away_intensity", "avg_score", "peak"):
        assert out["pressing_by_window"][0][field] == _FV.NOT_MEASURED, field
    assert out["pressing_by_window"][0]["observations"], (
        "the press TRIGGERS vary and are the real pressing signal; only the "
        "manufactured number should go")


def test_json_round_tripped_values_still_compare():
    """values keys are floats in memory and strings once read back from
    field_variance.json, which is the only way this is ever run."""
    fields = _fields(
        pressing_by_window__home_intensity=(_FV.NOT_MEASURED, {3.5: 20}, 1.0),
        pressing_by_window__away_intensity=(_FV.MEASURED, {3.5: 17, 2.0: 3}, 0.85))
    round_tripped = json.loads(json.dumps(fields))
    assert _FV.mark_shared_defaults(round_tripped) == [
        "pressing_by_window.away_intensity"]


# ── a withheld label hiding in prose ──────────────────────────────────────
#
# formation_history.home_formation was not_measured and correctly redacted,
# and the regenerated report still said "operating from a compact 4-4-2
# mid-block". Two key_moments descriptions mention 4-4-2, and free text is
# out of scope for a distinct-value count, so nothing removed it.

def _formation_match(descriptions):
    return {"match": "t",
            "formation_history": [{"window": f"w{i:02d}",
                                   "home_formation": "4-4-2",
                                   "away_formation": "4-4-2"}
                                  for i in range(21)],
            "key_moments": [{"description": d} for d in descriptions]}


def test_a_withheld_formation_is_scrubbed_from_free_text():
    summary = _formation_match([
        "Gorleston settle into a compact 4-4-2 mid-block to absorb pressure."])
    report = _FV.compute("", running_summary=summary, write=False)
    out    = _FV.redact(summary, report)
    assert "4-4-2" not in json.dumps(out)
    assert _FV.PROSE_REPLACEMENT in out["key_moments"][0]["description"]


def test_the_rest_of_the_sentence_survives():
    summary = _formation_match([
        "Gorleston settle into a compact 4-4-2 mid-block to absorb pressure."])
    out = _FV.redact(summary, _FV.compute("", running_summary=summary,
                                          write=False))
    text = out["key_moments"][0]["description"]
    assert text.startswith("Gorleston settle into a compact")
    assert text.endswith("mid-block to absorb pressure.")


def test_only_formation_shaped_values_are_scrubbed():
    """home_shape is stuck on "mid". Removing "mid" from prose would destroy
    every description in the file, so an ordinary word is never scrubbed."""
    summary = {"match": "t",
               "formation_history": [{"home_shape": "mid", "away_shape": "mid"}
                                     for _ in range(21)],
               "key_moments": [{"description": "A compact mid-block, "
                                               "defending in midfield."}]}
    report = _FV.compute("", running_summary=summary, write=False)
    assert _FV.withheld_prose_tokens(report) == []
    out = _FV.redact(summary, report)
    assert out["key_moments"][0]["description"] == (
        "A compact mid-block, defending in midfield.")


def test_a_measured_formation_is_left_in_the_prose():
    """A team that genuinely changed shape has a reportable formation, and
    the label must survive in the descriptions that discuss it."""
    rows = [{"home_formation": f, "away_formation": f} for f in
            ["4-4-2"] * 7 + ["4-3-3"] * 7 + ["3-5-2"] * 7]
    summary = {"match": "t", "formation_history": rows,
               "key_moments": [{"description": "They switched to 4-3-3."}]}
    out = _FV.redact(summary, _FV.compute("", running_summary=summary,
                                          write=False))
    assert out["key_moments"][0]["description"] == "They switched to 4-3-3."


def test_a_scoreline_is_not_mistaken_for_a_formation():
    """"2-0" is digits joined by a dash. It must never be scrubbed, and the
    guard is that it is not a value any withheld field returned."""
    summary = _formation_match(["Gorleston led 2-0 at the interval."])
    out = _FV.redact(summary, _FV.compute("", running_summary=summary,
                                          write=False))
    assert "2-0" in out["key_moments"][0]["description"]
