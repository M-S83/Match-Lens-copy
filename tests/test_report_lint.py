"""The report is the last artefact and the only one anybody reads.

result_family_gates and field_variance shape the bundle the writer is handed.
Neither can tell whether the writer obeyed them, and prose is where the
discipline is actually lost. These tests hold the two failures found on the
Gorleston report, plus the two bugs the linter itself shipped with.
"""
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import report_lint as RL

GATES = {"gates": {"rest_defence": "downgraded", "territory": "downgraded",
                   "pressing": "downgraded", "player_positioning": "downgraded",
                   "player_movement": "allowed", "local_duels": "allowed"}}


def _checks(findings):
    return sorted({f["check"] for f in findings})


# ── grades ────────────────────────────────────────────────────────────────

def test_the_em_dash_grade_form_is_counted():
    """"zero [A] grades" was measured by searching for the literal "[A]".

    The report writes "[A - reason]". Seven of them were reported as none.
    """
    grades = RL.grades_in("a [A] b [A — run_type consistent] c [B - x] d [C]")
    assert [g["grade"] for g in grades] == ["A", "A", "B", "C"]
    assert grades[1]["reason"] == "run_type consistent"


def test_an_a_grade_on_a_downgraded_family_is_flagged():
    out = RL.lint("Held a high line [A — positioning_confidence stable].", GATES)
    assert "a_grade_on_downgraded_family" in _checks(out)


def test_an_a_grade_earned_by_consistency_alone_is_flagged():
    out = RL.lint("Forbes ran in behind [A — run_type consistent across 11].",
                  GATES)
    assert "a_grade_justified_by_consistency" in _checks(out)


def test_an_a_grade_on_an_allowed_family_with_a_real_reason_is_left_alone():
    out = RL.lint("Won the header [A — 14 duels logged from 9 frames].", GATES)
    assert out == []


def test_lower_grades_are_not_policed():
    """The rule is about [A]. A downgraded family may be discussed at [B]."""
    out = RL.lint("Rest defence looked compact [B — downgraded family].", GATES)
    assert "a_grade_on_downgraded_family" not in _checks(out)


# ── measurement and absence language ──────────────────────────────────────

def test_measurement_language_about_a_downgraded_family_is_flagged():
    out = RL.lint("Rest defence security was measured as very secure.", GATES)
    assert "measurement_language_on_downgraded_family" in _checks(out)


def test_absence_is_not_a_finding():
    """The Gorleston sentence, verbatim in shape.

    Shifts were not registered because a ball-following camera cannot see
    far-side structure. Reading that as security inverts the evidence.
    """
    out = RL.lint(
        "Rest defence security was measured as very secure - minimal backward "
        "line shifts from possession changes were registered across both "
        "teams [B - downgraded family].", GATES)
    assert "absence_read_as_evidence" in _checks(out)


def test_the_absence_pattern_covers_a_real_noun_phrase():
    """The first version allowed 30 characters and missed the sentence it
    was written for, which puts 44 between the quantifier and the verb."""
    assert RL.lint("Minimal backward line shifts from possession changes "
                   "were registered for rest defence.", GATES)


def test_an_allowed_family_may_be_described_as_measured():
    out = RL.lint("Duels were measured across 197 frames.", GATES)
    assert out == []


# ── values that were never readings ───────────────────────────────────────

VARIANCE = {"fields": {"line_height_m_by_window.home_height_pct": {
    "verdict": "not_measured", "windows_with_value": 20,
    "values": {"45.0": 19, "55.0": 1}}}}


def test_a_value_from_a_stuck_field_is_flagged():
    out = RL.lint("The defensive line sat at roughly 45% of pitch length.",
                  GATES, VARIANCE)
    assert "value_from_unmeasured_field" in _checks(out)


def test_values_survive_a_round_trip_through_json():
    """json.load returns object keys as strings.

    The first version tested isinstance(value, float), so every field was
    skipped once the report was linted from disk -- which is the only way
    this is ever run. It passed in memory and did nothing in production.
    """
    round_tripped = json.loads(json.dumps(VARIANCE))
    out = RL.lint("The line sat at roughly 45% of pitch length.",
                  GATES, round_tripped)
    assert "value_from_unmeasured_field" in _checks(out), (
        "the check works in memory but not on the file it reads")


def test_an_unrelated_percentage_is_not_flagged():
    out = RL.lint("He completed 78% of his passes.", GATES, VARIANCE)
    assert out == []


def test_a_measured_field_is_not_policed():
    variance = {"fields": {"line_height_m_by_window.away_height_pct": {
        "verdict": "measured", "windows_with_value": 20,
        "values": {"40.0": 13, "50.0": 3}}}}
    assert RL.lint("Their line sat at 40% of pitch length.",
                   GATES, variance) == []


# ── the whole thing ───────────────────────────────────────────────────────

def test_a_disciplined_report_produces_nothing():
    clean = (
        "# Match report\n\n"
        "Gorleston won 2-0.\n\n"
        "- Curtis scored from a diagonal run in behind [B — 7 runs logged].\n"
        "- Duels were counted, not rated: 14 contested, 6 won [B].\n"
        "- Rest defence is not reportable from this source.\n")
    assert RL.lint(clean, GATES, VARIANCE) == []


def test_findings_are_ordered_worst_first():
    out = RL.lint(
        "The line sat at 45% of pitch length. "
        "Rest defence security was measured as very secure.",
        GATES, VARIANCE)
    assert [f["severity"] for f in out] == sorted(
        [f["severity"] for f in out], key=lambda s: {"high": 0, "medium": 1}[s])


def test_a_missing_report_is_an_explicit_error(tmp_path):
    with pytest.raises(FileNotFoundError):
        RL.lint_match(str(tmp_path))


def test_lint_match_reads_both_config_files(tmp_path):
    (tmp_path / "tactical_report.md").write_text(
        "Rest defence security was measured as very secure.", encoding="utf-8")
    (tmp_path / "result_family_gates.json").write_text(
        json.dumps(GATES), encoding="utf-8")
    (tmp_path / "field_variance.json").write_text(
        json.dumps(VARIANCE), encoding="utf-8")
    out = RL.lint_match(str(tmp_path))
    assert "measurement_language_on_downgraded_family" in _checks(out)


def test_missing_config_files_do_not_crash_the_lint(tmp_path):
    (tmp_path / "tactical_report.md").write_text("Anything.", encoding="utf-8")
    assert RL.lint_match(str(tmp_path)) == []


# ── the linter has to actually run ────────────────────────────────────────
#
# report_filter.py has sat in this repo defining report levels and a prompt
# builder that nothing imports. A checker nobody calls is worse than no
# checker: it reads as coverage that does not exist. These tests hold the
# wiring, not just the logic.

import ast
import io

RUNNER = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "pipeline_runner_v2.py")


def _calls_after(source: str, marker_step: str) -> bool:
    """Is _lint_report called in the same block that marks this step done?"""
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if not isinstance(node, ast.Try):
            continue
        body = ast.dump(ast.Module(body=node.body, type_ignores=[]))
        if marker_step in body and "_lint_report" in body:
            return True
    return False


def test_both_report_write_sites_lint_what_they_wrote():
    src = io.open(RUNNER, encoding="utf-8").read()
    for step in ("4a_tactical_report", "4b_opposition_report"):
        assert _calls_after(src, step), (
            f"the block that writes and marks {step} does not call "
            f"_lint_report. A report is checked at the moment it is "
            f"produced, or the findings are discovered by whoever reads it "
            f"last.")


def test_the_wiring_check_would_notice_its_absence():
    """Mutation: the test above must fail if the call is removed."""
    src = io.open(RUNNER, encoding="utf-8").read()
    stripped = "\n".join(l for l in src.splitlines()
                         if "_lint_report(" not in l)
    assert not _calls_after(stripped, "4a_tactical_report")


def test_lint_report_writes_findings_beside_the_report(tmp_path):
    from pipeline_runner_v2 import _lint_report
    (tmp_path / "tactical_report.md").write_text(
        "Rest defence security was measured as very secure.", encoding="utf-8")
    (tmp_path / "result_family_gates.json").write_text(
        json.dumps(GATES), encoding="utf-8")

    _lint_report(str(tmp_path), "tactical_report.md")

    out = tmp_path / "tactical_report.lint.txt"
    assert out.exists(), "no findings file written beside the report"
    assert "measurement_language_on_downgraded_family" in out.read_text(
        encoding="utf-8")


def test_a_clean_report_still_gets_a_findings_file(tmp_path):
    """Absence of a file and absence of findings must not look identical."""
    from pipeline_runner_v2 import _lint_report
    (tmp_path / "tactical_report.md").write_text(
        "Gorleston won 2-0.", encoding="utf-8")
    _lint_report(str(tmp_path), "tactical_report.md")
    out = tmp_path / "tactical_report.lint.txt"
    assert out.exists()
    assert "nothing to answer for" in out.read_text(encoding="utf-8")


def test_a_lint_failure_does_not_lose_a_paid_report(tmp_path, capsys):
    """The report has already been bought. A lint problem warns; it does not
    raise into the caller and abandon the run."""
    from pipeline_runner_v2 import _lint_report
    _lint_report(str(tmp_path), "does_not_exist.md")
    assert "report_lint could not run" in capsys.readouterr().out
