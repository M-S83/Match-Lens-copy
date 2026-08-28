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


# ── the audit reaches the writer, it does not merely report ──────────────────

def test_a_withheld_metric_is_removed_not_annotated(tmp_path):
    """Absent beats forbidden, for the fourth time in this project."""
    from metric_audit import apply

    md = _match(
        tmp_path,
        [_metric("shape_thing", family="shape", status="downgraded"),
         _metric("keeper", family="chance_patterns")],
        variance={"not_measured": ["f.x"], "fields": {"f.x": {"family": "shape"}}})
    names = [m["metric_name"] for m in apply(
        [_metric("shape_thing", family="shape", status="downgraded"),
         _metric("keeper", family="chance_patterns")], md)]

    assert "shape_thing" not in names
    assert "keeper" in names


def test_counts_survive_and_proportions_do_not(tmp_path):
    from metric_audit import apply

    src = [{"metric_name": "duel_effectiveness",
            "supporting_result_families": ["player_duels"],
            "result_family_status": "allowed",
            "value": {"#4 home_kit": {"total": 11, "won": 9,
                                      "win_rate": 0.82,
                                      "retention_rate": 0.78}}}]
    # apply() reads its verdicts from the file, so the metric has to be in it.
    m = apply(src, _match(tmp_path, src))[0]
    rec = m["value"]["#4 home_kit"]

    assert rec == {"total": 11, "won": 9}, "counts kept, rates gone"
    assert m["audit"]["verdict"] == "counts_only"


def test_a_rate_hidden_in_a_prose_summary_is_also_removed(tmp_path):
    """width_usage carried the figure twice: score 0.05 and a summary string
    reading '5% of sequences used wide channels'. Removing only the number
    leaves the sentence to be quoted."""
    from metric_audit import apply

    src = [{"metric_name": "width_usage_score",
            "supporting_result_families": ["spacing"],
            "result_family_status": "downgraded",
            "value": {"score": 0.05, "method": "zone_labels",
                      "summary": "5% of sequences used wide channels"}}]
    m = apply(src, _match(tmp_path, src))[0]

    assert m["value"] == {"method": "zone_labels"}


def test_a_sound_metric_passes_through_untouched(tmp_path):
    """publish means publish -- nothing is stripped from a clean metric.

    This used to be shown with a value carrying conversion_rate_pct and no
    key _n_of recognises. That is now counts_only: a rate whose sample size
    the tool cannot state is not one it can certify. The property here is
    about pass-through, so it is shown with counts, which need no n.
    """
    from metric_audit import apply

    src = {"metric_name": "chance_creation_profile",
           "supporting_result_families": ["chance_patterns"],
           "result_family_status": "allowed",
           "value": {"threat_sequences": 17, "ending_in_cross": 16,
                     "ending_in_shot": 1}}

    m = apply([src], _match(tmp_path, [src]))[0]
    assert m["value"] == src["value"], "publish means publish"


def test_a_rate_with_no_statable_sample_size_is_not_published(tmp_path):
    """The behaviour that replaced it, stated rather than left implicit.

    between_lines_receiving_rate published a per-player rate over one to six
    receptions. It was marked publish because _n_of cannot see inside a dict
    keyed by player, so the minimum-n rule never ran -- the metric was not
    judged safe, it was simply not judged.
    """
    from metric_audit import apply

    src = {"metric_name": "chance_creation_profile",
           "supporting_result_families": ["chance_patterns"],
           "result_family_status": "allowed",
           "value": {"threat_sequences": 17, "conversion_rate_pct": 4.0}}

    m = apply([src], _match(tmp_path, [src]))[0]
    assert m["value"] == {"threat_sequences": 17}, (
        "the rate survived although its denominator cannot be stated")


def test_a_bare_rate_field_is_stripped(tmp_path):
    """RATE_KEYS listed "_rate" as a substring, which does not match a field
    named plainly "rate" -- so a per-player rate went straight through."""
    from metric_audit import apply

    src = {"metric_name": "between_lines_receiving_rate",
           "supporting_result_families": ["player_movement"],
           "result_family_status": "allowed",
           "value": {"A (#1)": {"total_receiving": 2, "between_lines": 0,
                                "rate": 0.0}}}

    m = apply([src], _match(tmp_path, [src]))[0]
    assert m["value"]["A (#1)"] == {"total_receiving": 2, "between_lines": 0}


def test_a_count_whose_name_contains_a_rate_word_survives():
    """The opposite failure of a substring test: "rate" sits inside
    "accurate_passes", which is a count."""
    from metric_audit import _looks_like_a_rate
    assert _looks_like_a_rate("accurate_passes", 12) is False
    assert _looks_like_a_rate("top_route_count", 135) is False
    assert _looks_like_a_rate("rate", 0.0) is True
    assert _looks_like_a_rate("final_third_rate_pct", 31.5) is True


def test_an_unaudited_metric_is_left_alone(tmp_path):
    """A metric the audit has no opinion on must not be silently dropped."""
    from metric_audit import apply

    md = _match(tmp_path, [])
    m = apply([{"metric_name": "brand_new_thing", "value": {"n": 5}}], md)[0]
    assert m["value"] == {"n": 5}
