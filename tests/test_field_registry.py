"""The registry that stops an unmeasurable field reaching a report.

WHY THIS FILE EXISTS
--------------------
field_variance decides which fields a report may quote. Its tables --
MONITORED, DERIVED_FIELDS, INDEPENDENT -- are maintained by hand, and a hand
maintained table fails silently: nothing goes red when a field is added to the
accumulator and nobody classifies it.

That is not hypothetical. pressing_by_window.peak is max(home_intensity,
away_intensity). home_intensity was 3.5 on twenty windows of twenty and was
correctly redacted; peak was in no table, so the redacted record read
{"avg_score": "not_measured", "peak": 3.5}. The mechanism built to suppress a
stuck value published it one key to the right, and the suite was green.

So these tests read the dict literals accumulator.py actually appends, rather
than a fixture that would drift out of date without failing. A new field in
the accumulator turns this file red until someone decides what it is.
"""
import ast
import io
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import field_variance as FV

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _appended_keys(source_path: str) -> dict:
    """{list name: {key, ...}} for every summary["<list>"].append({...})."""
    tree  = ast.parse(io.open(source_path, encoding="utf-8").read())
    found = {}
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "append"):
            continue
        target = node.func.value
        if not (isinstance(target, ast.Subscript)
                and isinstance(target.value, ast.Name)
                and target.value.id == "summary"):
            continue
        sl   = target.slice
        name = sl.value if isinstance(sl, ast.Constant) else None
        if name not in FV.MONITORED_LISTS:
            continue
        for arg in node.args:
            if isinstance(arg, ast.Dict):
                found.setdefault(name, set()).update(
                    k.value for k in arg.keys if isinstance(k, ast.Constant))
    return found


# --------------------------------------------------------------------------
# The registry check, and proof that it is not vacuous
# --------------------------------------------------------------------------

def test_append_sites_are_discoverable():
    """Guard against a green run that checked nothing.

    If the accumulator is refactored so the append sites stop matching the
    shape this file parses, every later assertion here passes over an empty
    set. That is the failure mode this test exists to prevent: it demands
    that each monitored list was actually found, with fields in it.
    """
    found = _appended_keys(os.path.join(REPO, "accumulator.py"))
    for list_name in FV.MONITORED_LISTS:
        assert list_name in found, (
            f"no summary[{list_name!r}].append({{...}}) site found in "
            f"accumulator.py -- the registry check below would pass "
            f"vacuously")
        assert len(found[list_name]) >= 3, (
            f"{list_name}: only {len(found[list_name])} key(s) recovered; "
            f"the parser is probably not seeing the real append site")


def test_every_accumulator_field_is_classified():
    """No field reaches a monitored list without a decision about it."""
    found   = _appended_keys(os.path.join(REPO, "accumulator.py"))
    missing = {}
    for list_name, keys in found.items():
        gaps = FV.unclassified_fields(list_name, keys)
        if gaps:
            missing[list_name] = gaps
    assert not missing, (
        "field(s) in a monitored list are in none of MONITORED, "
        "DERIVED_FIELDS or INDEPENDENT:\n  "
        + "\n  ".join(f"{k}: {v}" for k, v in missing.items())
        + "\n\nAdd each to field_variance.py. If it is a measurement, "
          "MONITORED. If it is computed from other fields, DERIVED_FIELDS, "
          "so it falls when they do. If it is neither, INDEPENDENT with a "
          "reason.")


def test_registry_check_catches_an_unclassified_field():
    """Mutation: the check above must fail when a field is genuinely missing.

    Without this, test_every_accumulator_field_is_classified could be
    asserting nothing at all and would look identical.
    """
    gaps = FV.unclassified_fields(
        "pressing_by_window", ["avg_score", "peak", "a_brand_new_field"])
    assert gaps == ["pressing_by_window.a_brand_new_field"]


def test_peak_is_declared_derived_from_the_intensities():
    assert "pressing_by_window.peak" in FV.DERIVED_FIELDS
    assert set(FV.DERIVED_FIELDS["pressing_by_window.peak"]) == {
        "pressing_by_window.home_intensity",
        "pressing_by_window.away_intensity"}


# --------------------------------------------------------------------------
# The defect the registry was written for, tested behaviourally
# --------------------------------------------------------------------------

def _pressing_summary():
    """Ten windows: home stuck at 3.5, away moving, peak = max of the two."""
    rows = []
    for i, away in enumerate([3.5, 3.5, 3.5, 5.5, 2.5, 2.0, 3.5, 3.5, 3.5, 3.5]):
        rows.append({"window": f"w{i:02d}", "agent_id": f"{i:02d}",
                     "home_intensity": 3.5, "away_intensity": away,
                     "avg_score": round((3.5 + away) / 2, 2),
                     "peak": max(3.5, away), "peak_ts": None,
                     "observations": []})
    return {"match": "t", "pressing_by_window": rows}


def test_peak_does_not_survive_the_redaction_of_its_source():
    """The Gorleston leak, as a behaviour rather than a table lookup."""
    summary = _pressing_summary()
    report  = FV.compute("", running_summary=summary, write=False)

    assert report["fields"]["pressing_by_window.home_intensity"]["verdict"] \
        == FV.NOT_MEASURED

    out = FV.redact(summary, report)
    peaks = [r["peak"] for r in out["pressing_by_window"]]
    assert set(peaks) == {FV.NOT_MEASURED}, (
        f"peak survived redaction as {sorted(set(peaks))} while the "
        f"home_intensity it is computed from was withheld")


def test_a_measured_sibling_still_survives():
    """Redaction is per field: a sibling that moves on its own is kept.

    This used to be demonstrated with _pressing_summary(), where away
    intensity varies around a home value stuck at 3.5. That fixture is the
    real Gorleston defect, and mark_shared_defaults now correctly withholds
    the away field too -- its modal value IS the value home is stuck on.

    The per-field property is still worth holding, so it is shown with line
    height, where the away modal value (40.0) genuinely differs from the
    stuck home one (45.0). That is the case the anchor rule must not touch.
    """
    rows = []
    for i, away in enumerate([40.0, 40.0, 50.0, 42.0, 40.0, 48.0,
                              40.0, 50.0, 40.0, 45.0]):
        rows.append({"window": f"w{i:02d}", "agent_id": f"{i:02d}",
                     "home_height_pct": 45.0, "away_height_pct": away,
                     "avg_pct": round((45.0 + away) / 2, 1),
                     "avg_m_approx": None, "line_width_m_approx": None,
                     "space_behind_m": None, "shifts": []})
    summary = {"match": "t", "line_height_m_by_window": rows}
    report  = FV.compute("", running_summary=summary, write=False)

    assert report["fields"][
        "line_height_m_by_window.home_height_pct"]["verdict"] \
        == FV.NOT_MEASURED
    assert report["fields"][
        "line_height_m_by_window.away_height_pct"]["verdict"] == FV.MEASURED

    out   = FV.redact(summary, report)
    aways = [r["away_height_pct"] for r in out["line_height_m_by_window"]]
    assert FV.NOT_MEASURED not in aways
    assert len(set(aways)) > 1


def test_the_pressing_sibling_is_now_withheld_with_its_stuck_twin():
    """The behaviour that replaced it, stated explicitly rather than left as
    a silent change to the test above."""
    summary = _pressing_summary()
    report  = FV.compute("", running_summary=summary, write=False)
    assert report["fields"]["pressing_by_window.away_intensity"]["verdict"] \
        == FV.ANCHORED
    out   = FV.redact(summary, report)
    aways = [r["away_intensity"] for r in out["pressing_by_window"]]
    assert set(aways) == {FV.NOT_MEASURED}


# --------------------------------------------------------------------------
# Alternating team attribution
# --------------------------------------------------------------------------

def _seqs(per_window):
    """per_window: {window: [team, ...]} -> flat sequence records."""
    out = []
    for window, teams in per_window.items():
        for t in teams:
            out.append({"window": window, "team": t, "passes": 3})
    return out


def test_strict_alternation_is_reported_as_constructed():
    alt = ["home_kit", "away_kit"] * 5
    res = FV.check_team_attribution(
        sequences=_seqs({f"w{i}": list(alt) for i in range(8)}))
    assert res["verdict"] == FV.CONSTRUCTED
    assert res["windows_alternating"] == 8
    assert res["share"] == 1.0


def test_realistic_possession_is_not_flagged():
    """A team wins the ball and keeps it, so runs of the same label occur."""
    runs = ["home_kit", "home_kit", "away_kit", "home_kit",
            "away_kit", "away_kit", "away_kit", "home_kit",
            "home_kit", "away_kit"]
    res = FV.check_team_attribution(
        sequences=_seqs({f"w{i}": list(runs) for i in range(8)}))
    assert res["verdict"] == FV.MEASURED
    assert res["windows_alternating"] == 0


def test_one_alternating_window_among_many_is_not_enough():
    alt  = ["home_kit", "away_kit"] * 5
    runs = ["home_kit", "home_kit", "away_kit", "away_kit",
            "home_kit", "away_kit", "away_kit", "home_kit"]
    per  = {f"w{i}": list(runs) for i in range(9)}
    per["w9"] = list(alt)
    res = FV.check_team_attribution(sequences=_seqs(per))
    assert res["verdict"] == FV.MEASURED
    assert res["windows_alternating"] == 1


def test_short_windows_do_not_count_towards_the_verdict():
    """Three sequences alternate by chance often enough to prove nothing."""
    res = FV.check_team_attribution(
        sequences=_seqs({f"w{i}": ["home_kit", "away_kit", "home_kit"]
                         for i in range(20)}))
    assert res["verdict"] == FV.NO_DATA
    assert res["windows_checked"] == 0


def test_missing_pass_sequences_file_is_not_an_error(tmp_path):
    assert FV.check_team_attribution(str(tmp_path)) is None


# --------------------------------------------------------------------------
# End to end: a constructed label withholds the possession numbers
# --------------------------------------------------------------------------

def _match_with_alternating_sequences(tmp_path):
    alt  = ["home_kit", "away_kit"] * 5
    rows = [{"window": f"w{i:02d}", "focus_pct": 50.0, "focus_seqs": 10,
             "opp_seqs": 10, "basis": "sequence_count"} for i in range(10)]
    summary = {"match": "t", "possession_by_window": rows}
    (tmp_path / "pass_sequences.json").write_text(json.dumps(
        {"sequences": _seqs({f"w{i:02d}": list(alt) for i in range(10)})}),
        encoding="utf-8")
    (tmp_path / "running_summary.json").write_text(
        json.dumps(summary), encoding="utf-8")
    return summary


def test_constructed_attribution_withholds_every_possession_number(tmp_path):
    summary = _match_with_alternating_sequences(tmp_path)
    report  = FV.compute(str(tmp_path), write=False)

    assert report["team_attribution"]["verdict"] == FV.CONSTRUCTED
    for f in ("focus_pct", "focus_seqs", "opp_seqs"):
        key = f"possession_by_window.{f}"
        assert key in report["not_measured"], f"{key} was published"

    out = FV.redact(summary, report)
    for row in out["possession_by_window"]:
        for f in ("focus_pct", "focus_seqs", "opp_seqs"):
            assert row[f] == FV.NOT_MEASURED, (
                f"{f} survived as {row[f]!r} although the team label it is "
                f"built from carries no information")
        assert row["basis"] == "sequence_count"


def test_focus_seqs_would_pass_variance_testing_on_its_own(tmp_path):
    """Why the alternation check has to exist as a separate test.

    focus_seqs took four distinct values across the Gorleston match with a
    62% modal share -- comfortably 'measured' by distinct-value counting.
    Nothing about its own distribution reveals that the split it encodes was
    manufactured, so a variance-only pipeline publishes it.
    """
    rows = [{"window": f"w{i:02d}", "focus_pct": 50.0,
             "focus_seqs": v, "opp_seqs": v, "basis": "sequence_count"}
            for i, v in enumerate([10, 10, 11, 12, 10, 11, 5, 12, 10, 11])]
    verdict = FV.classify([r["focus_seqs"] for r in rows])["verdict"]
    assert verdict == FV.MEASURED

    summary = {"match": "t", "possession_by_window": rows}
    alt = ["home_kit", "away_kit"] * 5
    (tmp_path / "pass_sequences.json").write_text(json.dumps(
        {"sequences": _seqs({f"w{i:02d}": list(alt) for i in range(10)})}),
        encoding="utf-8")
    report = FV.compute(str(tmp_path), running_summary=summary, write=False)
    assert report["fields"]["possession_by_window.focus_seqs"]["verdict"] \
        == FV.CONSTRUCTED


def test_constructed_counts_as_unmeasured_for_family_gating():
    assert FV.CONSTRUCTED in FV.UNMEASURED
