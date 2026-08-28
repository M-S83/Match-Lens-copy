"""Every published figure, traced back to what it was counted over.

The report's most concrete-looking numbers were its most wrong: "82% win rate
across 11 contested duels" for a player whose record was 9-0-2, computed as
wins over times-VISIBLE, across a sample holding half the match's duels. Prose
gets hedged and figures get quoted, so figures need the mechanical check.
"""
import json

import pytest

from metric_audit import MIN_N_FOR_RATE, UNKNOWABLE_DENOMINATOR, audit


def _match(tmp_path, metrics, variance=None):
    (tmp_path / "deep_skill_metrics.json").write_text(
        json.dumps({"metrics": metrics}), encoding="utf-8")
    if variance is not None:
        (tmp_path / "field_variance.json").write_text(
            json.dumps(variance), encoding="utf-8")
    return str(tmp_path)


def _metric(name, family="build_up", status="allowed", value=None, conf=0.6):
    return {"metric_name": name, "supporting_result_families": [family],
            "result_family_status": status, "confidence": conf,
            "value": value if value is not None else {"total_sequences": 400}}


def _verdicts(r):
    return {row["metric"]: row["verdict"] for row in r["rows"]}


def test_a_sound_figure_is_publishable(tmp_path):
    r = audit(_match(tmp_path, [_metric("chance_creation_profile",
                                        family="chance_patterns")]))
    assert _verdicts(r)["chance_creation_profile"] == "publish"


def test_a_downgraded_family_caps_at_B(tmp_path):
    r = audit(_match(tmp_path, [_metric("x", family="pressing",
                                        status="downgraded")]))
    assert _verdicts(r)["x"] == "cap_at_B"


def test_an_unknowable_denominator_is_counts_only(tmp_path):
    """duel_effectiveness divided by times-visible and called it a win rate."""
    r = audit(_match(tmp_path, [_metric("duel_effectiveness",
                                        family="player_duels")]))
    row = next(x for x in r["rows"] if x["metric"] == "duel_effectiveness")

    assert row["verdict"] == "counts_only"
    assert "players_visible" in row["note"]


def test_a_small_sample_is_withheld(tmp_path):
    """At n=9 a single event moves the figure eleven points."""
    r = audit(_match(tmp_path, [_metric("x", value={"total_sequences": 9})]))
    row = next(x for x in r["rows"] if x["metric"] == "x")

    assert row["verdict"] == "withhold"
    assert "one event moves this" in row["note"]


def test_a_never_measured_family_is_withheld_before_anything_else(tmp_path):
    """A field that returned the same value in every window is not evidence,
    whatever its sample size or family gate says."""
    r = audit(_match(
        tmp_path,
        [_metric("shape_thing", family="shape", status="downgraded",
                 value={"total_sequences": 900})],
        variance={"not_measured": ["formation_history.home_formation"],
                  "fields": {"formation_history.home_formation":
                             {"family": "shape", "verdict": "not_measured"}}}))
    row = next(x for x in r["rows"] if x["metric"] == "shape_thing")

    assert row["verdict"] == "withhold"
    assert "never varied" in row["note"]


def test_withhold_outranks_a_merely_downgraded_family(tmp_path):
    """Order matters: the harsher verdict has to win, or a downgraded family
    would mask a field that is not measured at all."""
    r = audit(_match(
        tmp_path,
        [_metric("a", family="shape", status="downgraded"),
         _metric("b", family="shape", status="downgraded")],
        variance={"not_measured": ["f.x"],
                  "fields": {"f.x": {"family": "shape"}}}))

    assert set(_verdicts(r).values()) == {"withhold"}


def test_the_worst_verdicts_are_listed_first(tmp_path):
    r = audit(_match(tmp_path, [
        _metric("ok", family="chance_patterns"),
        _metric("duel_effectiveness", family="player_duels"),
        _metric("dg", family="pressing", status="downgraded")]))

    assert [x["verdict"] for x in r["rows"]] == [
        "counts_only", "cap_at_B", "publish"]


def test_every_flagged_metric_says_what_is_actually_counted():
    """A note saying 'unreliable' teaches nothing. Each has to name the
    quantity, so the label cannot drift back to the convenient reading."""
    for name, note in UNKNOWABLE_DENOMINATOR.items():
        assert len(note) > 40, name
        assert "not" in note or "rather than" in note, name


def test_the_rate_threshold_is_not_below_ten(tmp_path):
    """Below about ten, a percentage is arithmetic rather than evidence."""
    assert MIN_N_FOR_RATE >= 10


def test_a_missing_metrics_file_audits_nothing_rather_than_failing(tmp_path):
    r = audit(str(tmp_path))
    assert r["metrics_audited"] == 0
