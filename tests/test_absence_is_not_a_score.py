"""Nothing observed must not become a number.

THE DEFECT
----------
calc_rest_defence_security read the `shifts` list on every window, counted
the backward ones, and divided by the window count. On the Gorleston match
that list was empty in all 21 windows -- the agent recorded no line movement
anywhere -- so the function computed 0 backward shifts, 0.0 per window, and
a score of 1.0 - (0.0 * 0.25) = 1.0.

A perfect rating, from no observations. It fed rest_defence_category, which
returns "very_secure" below 0.5, which fed REST_DEFENCE_PROSE, which says
"the back line holds its position almost completely after possession
changes" -- and the report published exactly that, as a finding, twelve
lines above a note saying rest-defence structure is what this source cannot
show.

The inversion matters as much as the value: rest_defence is a DOWNGRADED
family on a ball-following camera precisely because a far-side line shift is
not in frame. Zero recorded can only mean unobserved. It can never mean
stationary.

Four more functions had the same shape -- `if not sequences: return 0.0` --
including calc_width_usage, which returned the method string "none" and a
score of 0.0, quotable as "made no use of the width".
"""
import inspect
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import deep_skill_metrics as D


def _windows(*shift_lists):
    return {"line_height_by_window": [{"shifts": list(s)} for s in shift_lists]}


BACK = {"from_pct": 50, "to_pct": 40}      # line dropped
FWD  = {"from_pct": 40, "to_pct": 50}      # line pushed up


# ── rest defence ──────────────────────────────────────────────────────────

def test_no_shifts_recorded_anywhere_is_withheld_not_perfect():
    """The Gorleston case: 21 windows, every shifts list empty."""
    score, per_window, windows, tiers = D.calc_rest_defence_security(
        _windows(*([[]] * 21)))
    assert score is None, (
        f"21 windows with no recorded shift produced a security score of "
        f"{score}; absence was scored as excellence")
    assert per_window is None
    assert windows == 21, "the window count is still worth reporting"
    assert tiers == ["no_data"]


def test_the_withheld_result_cannot_become_a_category():
    assert D.rest_defence_category(None) == "unknown"


def test_no_prose_is_emitted_for_a_withheld_rest_defence():
    """The prose path is what reached the report, so it is what must go
    quiet -- not merely the number."""
    assert D.build_prose_interpretation(
        "rest_defence_security_score",
        {"avg_backward_shifts_per_window": None, "category": "unknown"}) is None


def test_a_match_that_did_record_shifts_is_unaffected():
    score, per_window, windows, tiers = D.calc_rest_defence_security(
        _windows([BACK], [], [FWD], []))
    assert per_window == 0.25
    assert score == 0.94
    assert tiers == ["repeated_pattern"]


def test_forward_shifts_alone_still_count_as_observation():
    """A line that only ever pushed UP was observed, and scores as secure --
    which is a finding. It must not be confused with never having been seen.
    """
    score, per_window, _, tiers = D.calc_rest_defence_security(
        _windows([FWD], [FWD], [FWD]))
    assert score is not None, "shifts were observed; this is real data"
    assert per_window == 0.0
    assert tiers == ["repeated_pattern"]


def test_zero_backward_from_real_sightings_differs_from_zero_sightings():
    """The two cases the old code could not tell apart, side by side."""
    seen     = D.calc_rest_defence_security(_windows([FWD], [FWD], [FWD]))
    not_seen = D.calc_rest_defence_security(_windows([], [], []))
    assert seen[1] == 0.0 and not_seen[1] is None
    assert seen[0] is not None and not_seen[0] is None


# ── the other four, and the next one ──────────────────────────────────────

def test_no_sequences_is_not_zero_width_usage():
    score, n, tiers, method = D.calc_width_usage({"sequences": []})
    assert score is None
    assert method is None, (
        'the method string was literally "none", which a report can quote as '
        '"made no use of the width"')


def test_no_sequences_is_not_zero_route_diversity():
    assert D.calc_build_up_route_diversity({"sequences": []})[0] is None


def test_no_sequences_is_not_perfect_pattern_reliability():
    assert D.calc_pattern_reliability({"sequences": []})[0] is None


def test_no_pressing_readings_is_not_zero_pressing():
    assert D.calc_pressing_intensity({"pressing_by_window": []})[0] is None


EMPTY_SUMMARY = dict(
    {k: [] for k in ("line_height_by_window", "line_height_m_by_window",
                     "possession_by_window", "pressing_by_window", "duels",
                     "formation_history", "key_moments", "shots",
                     "individual_observations", "transitions", "set_pieces",
                     "sequences")},
    match="t")


def _single_arg_calcs():
    for name in sorted(n for n in dir(D) if n.startswith("calc_")):
        fn = getattr(D, name)
        try:
            sig = inspect.signature(fn)
        except (TypeError, ValueError):
            continue
        required = [p for p in sig.parameters.values()
                    if p.default is inspect._empty]
        if len(required) == 1:
            yield name, fn


def test_the_sweep_finds_the_functions_it_claims_to_check():
    """Guard against a green run that checked nothing."""
    names = [n for n, _ in _single_arg_calcs()]
    assert len(names) >= 12, f"only {len(names)} calc_ functions discovered"
    for expected in ("calc_rest_defence_security", "calc_width_usage",
                     "calc_pressing_intensity"):
        assert expected in names


def test_no_metric_returns_a_number_when_given_nothing():
    """The rule, applied to every metric including ones added later.

    Given empty input a metric must return an empty container, or a sequence
    whose leading value -- the score -- is None. A number in that position is
    a claim about a match nobody observed.
    """
    offenders = {}
    for name, fn in _single_arg_calcs():
        try:
            out = fn(EMPTY_SUMMARY)
        except Exception:
            continue          # a raise is not a false claim
        if isinstance(out, dict):
            if out:
                offenders[name] = out
        elif isinstance(out, (list, tuple)) and out:
            head = out[0]
            if isinstance(head, (int, float)) and not isinstance(head, bool):
                offenders[name] = out
    assert not offenders, (
        "metric(s) produced a value from no observations:\n  "
        + "\n  ".join(f"{k}: {v}" for k, v in offenders.items())
        + "\n\nReturn None for the score instead. A rate over nothing is not "
          "zero, it is absent -- and on a downgraded family the absence is "
          "the camera, not the match.")


def test_the_sweep_would_catch_a_regression(monkeypatch):
    """Mutation: put the old shape back and the sweep must fail."""
    monkeypatch.setattr(D, "calc_width_usage",
                        lambda passes: (0.0, 0, ["suggestive"], "none"))
    with pytest.raises(AssertionError):
        test_no_metric_returns_a_number_when_given_nothing()
