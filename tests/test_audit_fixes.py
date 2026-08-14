"""Regression tests for the AUDIT-2026-08 fixes.

Each test names the finding it guards. They are written to fail loudly if the
original defect returns, so the fix cannot be silently undone by a later edit.

Scope note: these cover pure logic only. See tests/conftest.py — video, image
and API paths are stubbed, not exercised.
"""
import json
import os
import tempfile

import pytest


# ── A1: the readiness gate must actually gate ────────────────────────────────

def _gate(payload, override=False):
    from pipeline_runner_v2 import _report_gate_open
    d = tempfile.mkdtemp()
    if payload is not None:
        with open(os.path.join(d, "report_readiness.json"), "w") as f:
            f.write(payload)
    return _report_gate_open(d, override=override), d


def test_a1_gate_open_when_ready():
    ok, _ = _gate(json.dumps({"report_ready": True}))
    assert ok is True


def test_a1_gate_closed_when_not_ready():
    """The original defect: report_ready was computed and ignored."""
    ok, _ = _gate(json.dumps({"report_ready": False,
                              "blocking_issues": ["boundary confidence 0.4"]}))
    assert ok is False


def test_a1_gate_fails_closed_when_file_missing():
    """The gate not having run is not evidence the pipeline is healthy."""
    ok, _ = _gate(None)
    assert ok is False


def test_a1_gate_fails_closed_on_corrupt_json():
    ok, _ = _gate("{not json")
    assert ok is False


def test_a1_override_opens_gate_and_records_the_decision():
    ok, d = _gate(json.dumps({"report_ready": False, "blocking_issues": ["x"]}),
                  override=True)
    assert ok is True
    with open(os.path.join(d, "report_readiness.json")) as f:
        assert json.load(f)["readiness_overridden"] is True


def test_a1_report_ready_has_a_reader_outside_the_writer():
    """Guards the shape of the bug: the flag existed but nothing consumed it."""
    import pipeline_runner_v2 as p
    src = open(p.__file__, encoding="utf-8").read()
    assert "report_ready" in src, "the runner must consult report_ready"


# ── A3: player metrics must not be fabricated from a forbidden field ─────────

def test_a3_metrics_unavailable_when_no_ratings():
    """SKILL.md forbids agents emitting `rating`; the default fabricated a 3,
    making both metrics constants (1.00 / 0.60) for every player."""
    from deep_skill_metrics import calc_player_metrics
    summary = {"individual_observations": [
        {"player": "#10", "observation": "drops between lines"},
        {"player": "#10", "observation": "switches play"},
    ]}
    (pm,) = calc_player_metrics(summary, {"items": []})
    assert pm["player_role_consistency"] is None
    assert pm["player_positioning_stability"] is None
    assert pm["observations_count"] == 2, "must count observations, not ratings"
    assert pm["ratings_count"] == 0


def test_a3_metrics_still_compute_when_ratings_are_real():
    from deep_skill_metrics import calc_player_metrics
    summary = {"individual_observations": [
        {"player": "#7", "observation": "a", "rating": 4},
        {"player": "#7", "observation": "b", "rating": 2},
    ]}
    (pm,) = calc_player_metrics(summary, {"items": []})
    # mean 3.0, variance 1.0 -> 1 - 1/4 = 0.75 ; 3.0/5 = 0.6
    assert pm["player_role_consistency"] == 0.75
    assert pm["player_positioning_stability"] == 0.6


def test_a3_no_fabricated_rating_default_remains():
    """Checked via AST, not text search: the fix's own explanatory comment
    quotes the old expression, so a substring check would match the comment."""
    import ast
    import deep_skill_metrics as d
    tree = ast.parse(open(d.__file__, encoding="utf-8").read())
    for node in ast.walk(tree):
        if (isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "get"
                and len(node.args) == 2
                and isinstance(node.args[0], ast.Constant)
                and node.args[0].value == "rating"):
            pytest.fail(f"fabricated rating default is back at line {node.lineno}")


# ── A5/A6: published provenance must match the arithmetic ────────────────────

def test_a5_a6_calculation_basis_is_generated_from_the_constants():
    """The durable guard: basis strings are rendered from the same constants the
    computation uses, so they cannot drift apart again."""
    import deep_skill_metrics as d
    assert f"{d.COMPACTNESS_W_HEIGHT:.0%}" in d.COMPACTNESS_BASIS
    assert f"{d.COMPACTNESS_W_PRESSING:.0%}" in d.COMPACTNESS_BASIS
    assert str(d.ROUTE_DIVERSITY_CEILING) in d.ROUTE_DIVERSITY_BASIS


def test_a5_a6_weights_sum_to_one():
    # Plain float comparison rather than pytest.approx: conftest stubs numpy,
    # and approx introspects sys.modules["numpy"] when it is present.
    import deep_skill_metrics as d
    assert abs((d.COMPACTNESS_W_HEIGHT + d.COMPACTNESS_W_PRESSING) - 1.0) < 1e-9


def test_a5_a6_no_hardcoded_formula_strings_remain():
    import deep_skill_metrics as d
    src = open(d.__file__, encoding="utf-8").read()
    assert "Line height stability (60%)" not in src
    assert "pairs / 12" not in src


def test_a6_compactness_arithmetic_unchanged():
    """Provenance was corrected; the values were deliberately NOT changed."""
    from deep_skill_metrics import calc_compactness
    score, _, n, _, _ = calc_compactness({
        "line_height_by_window": [{"avg_pct": 40.0}, {"avg_pct": 50.0}],
        "pressing_by_window": [{"avg_score": 6.0}]})
    # height_score = 1 - 0.45 = 0.55 ; press = 0.6 ; .55*.8 + .6*.2 = 0.56
    assert score == 0.56
    assert n == 2


# ── A7: high-danger share must classify on the row vocabulary ────────────────

def test_a7_high_danger_uses_row_not_column():
    """`shot_zone` held origin_column (lateral) but was tested against row
    values, so the share was structurally always 0%."""
    from deep_skill_metrics import calc_chance_creation_profile
    shots = [{"timestamp": "10m00s", "origin_column": "central",
              "origin_row": "six_yard_box"},
             {"timestamp": "20m00s", "origin_column": "left_channel",
              "origin_row": "penalty_spot"},
             {"timestamp": "30m00s", "origin_column": "central",
              "origin_row": "outside_box"}]
    prof, _, _ = calc_chance_creation_profile({"shots_for": shots},
                                              {"sequences": []})
    assert prof["high_danger_chances"] == 2
    assert prof["low_danger_chances"] == 1
    assert prof["high_danger_pct"] == 67
    assert prof["chances_with_known_row"] == 3


def test_a7_unavailable_rather_than_zero_when_row_absent():
    from deep_skill_metrics import calc_chance_creation_profile
    prof, _, _ = calc_chance_creation_profile(
        {"shots_for": [{"timestamp": "10m00s", "origin_column": "central"}]},
        {"sequences": []})
    assert prof["high_danger_pct"] is None, "absent data must not read as 0%"
    assert prof["chances_with_known_row"] == 0


# ── A4: moment time must resolve either key ──────────────────────────────────

def test_a4_moment_time_prefers_canonical_minute():
    from pipeline_accessors import get_moment_time
    assert get_moment_time({"minute": "38:00"}) == "38:00"
    assert get_moment_time({"timestamp": "12m30s"}) == "12m30s"
    assert get_moment_time({"minute": "38:00", "timestamp": "99m99s"}) == "38:00"
    assert get_moment_time({}) == ""


def test_a4_ground_truth_matches_moments_carrying_minute():
    """The defect: ground_truth read `timestamp` only, so every known event
    scored as missed."""
    from ground_truth import find_event_in_moments
    moments = [{"minute": "38:00", "type": "goal"},
               {"timestamp": "12m30s", "type": "substitution"}]
    assert find_event_in_moments({"type": "goal", "minute": 38}, moments)
    assert find_event_in_moments({"type": "sub", "minute": 12}, moments)


def test_a4_unrelated_event_still_misses():
    """Guards against 'fixing' the match by making it match everything."""
    from ground_truth import find_event_in_moments
    moments = [{"minute": "38:00", "type": "goal"}]
    assert find_event_in_moments({"type": "goal", "minute": 80}, moments) is None


# ── A13: the dual-agent merge must not drop schema fields ────────────────────

DUAL_MERGE_DROPPED = ["timestamp_range", "half", "match_state", "score_home",
                      "score_away", "confidence", "source_limitations"]


def test_a13_event_window_merge_preserves_all_schema_fields():
    import merge_utils as mu
    d = tempfile.mkdtemp()
    a = {"timestamp_range": "30:00-35:00", "half": "1H",
         "match_state": "away_winning", "score_home": 0, "score_away": 1,
         "confidence": 0.85, "source_limitations": "far side occluded",
         "formation": {"home": "4-2-3-1", "away": "4-4-2"},
         "defensive_line": {"avg_pct": 42}, "pressing": {"avg_score": 6},
         "key_moments": [{"minute": "32:00", "type": "goal"}],
         "pass_sequences": [], "set_pieces": []}
    b = {"event_agent": True, "events": [{"type": "goal"}]}
    ap = os.path.join(d, "agent_07_structural.json")
    bp = os.path.join(d, "agent_07_event.json")
    op = os.path.join(d, "agent_07_1H_30-00-35-00_merged.json")
    for path, obj in ((ap, a), (bp, b)):
        with open(path, "w") as f:
            json.dump(obj, f)

    mu.merge_dual_agents(ap, bp, op, "07", d)
    with open(op) as f:
        merged = json.load(f)

    missing = [k for k in DUAL_MERGE_DROPPED if k not in merged]
    assert not missing, f"dual merge dropped: {missing}"
    # match_state specifically: accumulator skips the window on a falsy value,
    # leaving holes at exactly the goal windows.
    assert merged["match_state"] == "away_winning"
    # computed keys must still win over the spread
    assert merged["merge_type"] == "dual_agent"


# ── A14: frames must order chronologically past minute 99 ────────────────────

def test_a14_frame_sort_key_orders_past_minute_99():
    from pipeline_paths import frame_sort_key
    names = ["frame_100m00s.jpg", "frame_97m30s.jpg",
             "frame_99m00s.jpg", "frame_102m00s.jpg"]
    assert [os.path.basename(p) for p in sorted(names, key=frame_sort_key)] == [
        "frame_97m30s.jpg", "frame_99m00s.jpg",
        "frame_100m00s.jpg", "frame_102m00s.jpg"]


def test_a14_unparseable_names_sort_deterministically_not_raise():
    from pipeline_paths import frame_sort_key
    got = sorted(["odd.jpg", "frame_01m00s.jpg", "another.png"],
                 key=frame_sort_key)
    assert got == ["another.png", "odd.jpg", "frame_01m00s.jpg"]


def test_a14_window_frames_are_chronological():
    from pipeline_paths import frame_sort_key
    from pipeline_runner_v2 import get_window_frames
    d = tempfile.mkdtemp()
    fr = os.path.join(d, "frames", "07")
    os.makedirs(fr)
    for m in (97, 98, 99, 100, 101, 102):
        open(os.path.join(fr, f"frame_{m:02d}m00s.jpg"), "w").close()
    got = get_window_frames(d, {"agent_id": "07"}, 6)
    assert got == sorted(got, key=frame_sort_key)
    assert os.path.basename(got[0]) == "frame_97m00s.jpg"


def test_a14_all_frame_sorts_use_the_canonical_key():
    """Four modules sort frame lists; all must use frame_sort_key."""
    for mod in ("pipeline_runner_v2", "jersey_ocr",
                "frame_extraction", "frame_preprocessor"):
        src = open(os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            f"{mod}.py"), encoding="utf-8").read()
        assert "frame_sort_key" in src, f"{mod} does not use the canonical key"
