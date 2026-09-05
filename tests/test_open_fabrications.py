"""Regression tests for the open fabrications fixed on 2026-09-05.

Each names its ledger id in FABRICATION-AUDIT.md. They are written to fail if
the original defect returns, so a later edit cannot quietly restore it.

The shared shape: absent input must never arrive as a number that reads like a
measurement. A missing coverage score is not 0.0 and not 1.0; an unclassified
source is not "confidence 0.5"; a pitch nobody measured is not 105 m stated as
fact; and one team's defensive line is not the other's.
"""
import ast
import json
import os

import pytest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


# Structural helpers. Text search is wrong for these checks: every fix below
# carries a comment quoting the defect it removed, so grepping for the defect
# finds the explanation of its own absence.

def _tree(filename):
    return ast.parse(open(os.path.join(REPO, filename), encoding="utf-8").read())


def _get_calls_with_default(filename, key):
    """Every `.get("<key>", <default>)` in the file, as unparsed source."""
    out = []
    for node in ast.walk(_tree(filename)):
        if (isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "get"
                and len(node.args) == 2
                and isinstance(node.args[0], ast.Constant)
                and node.args[0].value == key):
            out.append(ast.unparse(node))
    return out


def _assignments_to(filename, name):
    """Unparsed right-hand sides of every assignment to `name`."""
    out = []
    for node in ast.walk(_tree(filename)):
        if isinstance(node, ast.Assign):
            for t in node.targets:
                if isinstance(t, ast.Name) and t.id == name:
                    out.append(ast.unparse(node.value))
    return out


# ── O1: suppressed families must be read, not asserted ───────────────────────

def test_o1_suppressed_families_are_computed_from_the_gates():
    """Was `suppressed_families = []  # no suppressed families in this pipeline`.

    source_profiler assigns "suppressed" (source_profiler.py:165, :196) and
    reads it back at :212, so the comment was false. The one artefact whose
    job is to state what could NOT be measured asserted that nothing was
    suppressed, on every run, without looking.
    """
    rhs = _assignments_to("build_readiness_check.py", "suppressed_families")
    assert rhs, "suppressed_families is no longer assigned at all"
    assert "[]" not in rhs, "suppressed_families is still hardcoded empty"
    assert any("suppressed" in r and "gates" in r for r in rhs), (
        f"suppressed_families is not read from the gates: {rhs}")


def test_o1_source_profiler_really_does_emit_suppressed():
    """Guards the premise: if no gate can be "suppressed", the fix is pointless."""
    src = open(os.path.join(REPO, "source_profiler.py"), encoding="utf-8").read()
    assert '"suppressed"' in src


# ── O17: absent confidence is not zero confidence ────────────────────────────

def test_o17_absent_source_confidence_is_none_not_zero():
    for key in ("classification_confidence", "avg_confidence"):
        calls = _get_calls_with_default("build_readiness_check.py", key)
        assert not calls, (
            f"{key} still has a default, so an unmeasured confidence is "
            f"published as a number: {calls}")


def test_o17_unknown_confidence_blocks_the_report():
    """A confidence nobody read is not evidence the classification was good."""
    literals = [n.value for n in ast.walk(_tree("build_readiness_check.py"))
                if isinstance(n, ast.Constant) and isinstance(n.value, str)]
    assert any("records no classification_confidence" in s for s in literals)


# ── O16: an unrecognised source must not look measured ───────────────────────

def test_o16_unknown_source_is_capped_and_says_so():
    from deep_skill_metrics import compute_metric_confidence, SOURCE_GLOBAL_CAP

    conf, status, limitation = compute_metric_confidence(
        base=0.9, required_families=[], gates={"gates": {}},
        evidence_tiers=["direct"], windows_contributing=10,
        source_type="a_source_nobody_has_ever_heard_of")
    assert conf <= min(SOURCE_GLOBAL_CAP.values())
    assert status == "downgraded"
    assert limitation and "not in the source-cap table" in limitation


def test_o16_known_source_carries_no_defaulting_note():
    from deep_skill_metrics import compute_metric_confidence

    conf, status, limitation = compute_metric_confidence(
        base=0.9, required_families=[], gates={"gates": {}},
        evidence_tiers=["direct"], windows_contributing=10,
        source_type="tactical_wide_static")
    assert status == "allowed"
    assert limitation is None
    assert conf > 0.5


def test_o16_fallback_tracks_the_table_rather_than_a_literal():
    """The conservative cap must be derived from the table, not hardcoded.

    A literal 0.5 silently stops being the most conservative value the moment
    someone adds a lower cap.
    """
    import deep_skill_metrics as dsm

    original = dict(dsm.SOURCE_GLOBAL_CAP)
    try:
        dsm.SOURCE_GLOBAL_CAP["a_very_limited_source"] = 0.2
        cap, recognised = dsm.source_global_cap("still_unknown")
        assert recognised is False
        assert cap == 0.2
    finally:
        dsm.SOURCE_GLOBAL_CAP.clear()
        dsm.SOURCE_GLOBAL_CAP.update(original)


# ── O10: absent coverage is unknown, not zero and not one ────────────────────

def test_o10_absent_coverage_does_not_claim_a_measured_zero():
    """Was `.get("off_ball_coverage_score", 0)`, which then reported
    "off_ball_coverage_score 0.00 below 0.4" -- a measurement never taken."""
    from zone_helpers import validate_between_lines

    r = validate_between_lines({"between_lines": "between_def_mid"}, {"visibility_scores": {}})
    assert r["between_lines_kept"] is False          # downgrade is still right
    assert "0.00" not in (r["downgrade_reason"] or "")
    assert "unknown" in r["downgrade_reason"]
    assert "not measured as poor" in r["downgrade_reason"]


def test_o10_measured_low_coverage_still_says_measured():
    from zone_helpers import validate_between_lines

    r = validate_between_lines({"between_lines": "between_def_mid"},
                               {"visibility_scores": {"off_ball_coverage_score": 0.2}})
    assert r["between_lines_kept"] is False
    assert "0.20" in r["downgrade_reason"]


def test_o10_good_coverage_keeps_the_finding():
    from zone_helpers import validate_between_lines

    r = validate_between_lines({"between_lines": "between_def_mid"},
                               {"visibility_scores": {"off_ball_coverage_score": 0.9}})
    assert r["between_lines_kept"] is True
    assert r["downgrade_reason"] is None


def test_o10_the_two_files_no_longer_disagree_about_absence():
    """zone_helpers defaulted absent to 0, player_aggregator to 1.

    The same missing field meant "not observable at all" in one file and
    "fully observable" in the other -- a disagreement across the whole range,
    each asserting a figure nobody had measured.
    """
    for f in ("zone_helpers.py", "player_aggregator.py"):
        calls = _get_calls_with_default(f, "off_ball_coverage_score")
        assert not calls, (
            f"{f} still supplies a coverage figure nobody measured: {calls}")


# ── O6: the pitch length must be looked up, not assumed silently ─────────────

def test_o6_explicit_pitch_length_is_used(tmp_path):
    from accumulator import _resolve_pitch_length

    d = tmp_path / "match" / "merged"
    d.mkdir(parents=True)
    (tmp_path / "match" / "match_config.json").write_text(
        json.dumps({"pitch_length_m": 100, "venue": "Somewhere"}), encoding="utf-8")

    length, basis = _resolve_pitch_length(str(d / "w01_merged.json"), {})
    assert length == 100.0
    assert "match_config" in basis


def test_o6_unknown_pitch_is_labelled_as_assumed(tmp_path):
    """105 m is still used, but never presented as measured."""
    from accumulator import _resolve_pitch_length, DEFAULT_PITCH_LENGTH_M

    d = tmp_path / "match" / "merged"
    d.mkdir(parents=True)
    (tmp_path / "match" / "match_config.json").write_text(
        json.dumps({"venue": "An Unlisted Ground"}), encoding="utf-8")

    summary = {}
    length, basis = _resolve_pitch_length(str(d / "w01_merged.json"), summary)
    assert length == DEFAULT_PITCH_LENGTH_M
    assert "assumed" in basis and "unverified" in basis
    assert summary["pitch_length_assumed"] is True


def test_o6_absurd_pitch_length_is_rejected(tmp_path):
    """A typo must not silently become the conversion constant."""
    from accumulator import _resolve_pitch_length, DEFAULT_PITCH_LENGTH_M

    d = tmp_path / "match" / "merged"
    d.mkdir(parents=True)
    (tmp_path / "match" / "match_config.json").write_text(
        json.dumps({"pitch_length_m": 1050}), encoding="utf-8")

    length, _ = _resolve_pitch_length(str(d / "w01_merged.json"), {})
    assert length == DEFAULT_PITCH_LENGTH_M


def test_o6_venue_table_is_consulted_when_populated(tmp_path, monkeypatch):
    """The table existed and was never read; a populated entry must now win."""
    import pitch_validation
    from accumulator import _resolve_pitch_length

    monkeypatch.setitem(pitch_validation.KNOWN_NON_STANDARD_VENUES,
                        "crown meadow", {"length_m": 100, "width_m": 64})
    d = tmp_path / "match" / "merged"
    d.mkdir(parents=True)
    (tmp_path / "match" / "match_config.json").write_text(
        json.dumps({"venue": "Crown Meadow, Lowestoft"}), encoding="utf-8")

    length, basis = _resolve_pitch_length(str(d / "w01_merged.json"), {})
    assert length == 100.0
    assert "venue table" in basis


# ── O7: one team's defensive line is not the other's ─────────────────────────

def _compactness(rows, **kw):
    from deep_skill_metrics import _metric_compactness_geometry
    summary = {"line_height_m_by_window": rows}
    return _metric_compactness_geometry(summary, "tactical_wide_static")


def test_o7_compactness_uses_the_focus_line_not_the_both_teams_mean():
    """The published number must be the focus team's own line.

    A focus side defending at 31.5 m was reported at 47.3 m -- "high line" --
    whenever the opponent pressed high. Not absent data: data belonging to
    somebody else, which is worse, because it reads as a reading and is one.
    """
    rows = [{"avg_m_approx": 47.3, "focus_m_approx": 31.5,
             "line_width_m_approx": 30.0} for _ in range(5)]
    m = _compactness(rows)
    assert m["value"]["avg_line_height_m"] == 31.5
    assert m["subject_team"] == "focus"


def test_o7_falls_back_to_the_mean_but_relabels_the_subject():
    """Without a per-team split the figure is a match figure, and says so."""
    rows = [{"avg_m_approx": 47.3, "line_width_m_approx": 30.0} for _ in range(5)]
    m = _compactness(rows)
    assert m["value"]["avg_line_height_m"] == 47.3
    assert m["subject_team"] == "both"
    assert "not the focus team's own line" in (m["limitation_note"] or "")


def test_o7_accumulator_records_the_focus_line_separately():
    src = open(os.path.join(REPO, "accumulator.py"), encoding="utf-8").read()
    assert '"focus_height_pct"' in src
    assert '"focus_m_approx"' in src
