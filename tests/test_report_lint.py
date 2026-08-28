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


# ── the linter has to actually run, wherever the write lives ─────────────
#
# The first version of this wiring test asserted that pipeline_runner_v2's
# 4a/4b blocks call the linter. They do. They also never execute: the runner
# prints "3l_synthesis output is current. Skipping 4a/4b", and synthesis_agent
# is what writes the files. So the checker was wired into a dead path, the
# test was green, and a full run produced no lint output at all.
#
# The test below does not name a module. It finds every function anywhere in
# the repo that writes a report file, and requires that function to lint it.
# Move the write and the test follows it.
import ast
import glob
import io as _io
import re

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _scan_source(source: str, label: str = "<src>"):
    """(label, function, dump, lints) for each report-writing function."""
    out = []
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return out
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        dump  = ast.dump(node)
        names = re.findall(r"'([^']*report[^']*\.md)'", dump)
        names += re.findall(r"'(opposition_report_)'", dump)
        writes = "open" in dump and "'w'" in dump
        if names and writes:
            out.append((label, node.name, dump, "lint" in dump.lower()))
    return out


def _report_writing_functions():
    out = []
    for path in glob.glob(os.path.join(REPO, "*.py")):
        out += _scan_source(_io.open(path, encoding="utf-8").read(),
                            os.path.basename(path))
    return out


def test_the_wiring_scan_finds_the_report_writers():
    """Guard against a green run that scanned nothing."""
    found = _report_writing_functions()
    assert found, ("no report-writing function found anywhere in the repo; "
                   "the wiring assertion below would pass vacuously")
    assert any("synthesis" in f for f, _, _, _ in found), (
        f"synthesis_agent writes the reports on every real run; scan found "
        f"{[(f, n) for f, n, _, _ in found]}")


def test_every_function_that_writes_a_report_lints_it():
    unlinted = [(f, n) for f, n, _, lints in _report_writing_functions()
                if not lints]
    assert not unlinted, (
        "function(s) write a report without checking it: "
        + ", ".join(f"{f}:{n}" for f, n in unlinted)
        + ". A report is checked where it is written, or the findings are "
          "discovered by whoever reads it last.")


UNLINTED_WRITER = '''
def _write_tactical_report(match_dir, bundle):
    result = call_the_api()
    out_path = os.path.join(match_dir, "tactical_report.md")
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(result)
    return result
'''

LINTED_WRITER = UNLINTED_WRITER.replace(
    "    return result", "    _lint_written_report(match_dir, x)\n    return result")


def test_the_scan_recognises_a_writer_that_does_not_lint():
    """Mutation, against the predicate rather than against the repo.

    The previous version of this test compared the repo to itself after a
    string replace that could never change the answer -- it asserted nothing.
    """
    found = _scan_source(UNLINTED_WRITER)
    assert len(found) == 1, found
    assert found[0][3] is False, "a writer with no lint call read as linted"


def test_the_scan_recognises_a_writer_that_does_lint():
    found = _scan_source(LINTED_WRITER)
    assert len(found) == 1, found
    assert found[0][3] is True


def test_a_function_that_writes_something_else_is_not_in_scope():
    found = _scan_source('''
def _write_state(match_dir):
    with open(os.path.join(match_dir, "pipeline_state.json"), "w") as f:
        f.write("{}")
''')
    assert found == []


def test_lint_written_report_writes_findings_beside_the_report(tmp_path):
    from synthesis_agent import _lint_written_report
    (tmp_path / "tactical_report.md").write_text(
        "Rest defence security was measured as very secure.", encoding="utf-8")
    (tmp_path / "result_family_gates.json").write_text(
        json.dumps(GATES), encoding="utf-8")

    _lint_written_report(str(tmp_path), "tactical_report.md")

    out = tmp_path / "tactical_report.lint.txt"
    assert out.exists(), "no findings file written beside the report"
    assert "measurement_language_on_downgraded_family" in out.read_text(
        encoding="utf-8")


def test_a_clean_report_still_gets_a_findings_file(tmp_path):
    """Absence of a file and absence of findings must not look identical."""
    from synthesis_agent import _lint_written_report
    (tmp_path / "tactical_report.md").write_text(
        "Gorleston won 2-0.", encoding="utf-8")
    _lint_written_report(str(tmp_path), "tactical_report.md")
    out = tmp_path / "tactical_report.lint.txt"
    assert out.exists()
    assert "nothing to answer for" in out.read_text(encoding="utf-8")


def test_a_lint_failure_does_not_lose_a_paid_report(tmp_path, capsys):
    """The report has already been bought. A lint problem warns; it does not
    raise into the caller and abandon the run."""
    from synthesis_agent import _lint_written_report
    _lint_written_report(str(tmp_path), "does_not_exist.md")
    assert "report_lint could not run" in capsys.readouterr().out


# ── the citation that argues with itself ──────────────────────────────────
#
# The two-axis rule is stated as plainly as prose can manage -- "The grade is
# the LOWER of them", "Not [A] with a caveat sentence -- [B]" -- and the
# writer applied it correctly and then published the wrong letter, because it
# used the bracket to show its working. Eight in one opposition report.
#
# These are the exact strings from the 28 August run.

GORLESTON_CITATIONS = [
    "[A — accumulator: consistent, observability: downgraded]",
    "[A — accumulator: consistent, observability: downgraded → B]",
    "[A — accumulator: consistent, 11 high out of 17 appearances, "
    "observability: downgraded → B]",
    "[A — count axis consistent, observability axis downgraded = B]",
]


@pytest.mark.parametrize("citation", GORLESTON_CITATIONS)
def test_a_citation_that_resolves_to_b_is_caught(citation):
    out = RL.lint(f"Forbes ran in behind consistently {citation}.", GATES)
    assert "citation_contradicts_its_own_grade" in _checks(out), citation


def test_the_finding_names_the_grade_the_citation_reached():
    out = RL.lint("x [A — consistent, observability: downgraded → B].", GATES)
    detail = [f for f in out
              if f["check"] == "citation_contradicts_its_own_grade"][0]["detail"]
    assert "[A]" in detail and "[B]" in detail


def test_a_correctly_resolved_citation_is_left_alone():
    """What the prompt now asks for: the answer, not the working."""
    assert RL.lint(
        "Forbes ran in behind [B — 11 observations; movement downgraded on "
        "this source].", GATES) == []


def test_a_bare_letter_is_fine():
    assert RL.lint("Forbes ran in behind [B].", GATES) == []


def test_one_defect_produces_one_finding():
    """The contradiction check supersedes the consistency heuristic. Both
    firing on the same citation is noise, and noise is how a checker gets
    ignored."""
    out = RL.lint("x [A — accumulator: consistent, observability: "
                  "downgraded → B].", GATES)
    assert len(out) == 1, [f["check"] for f in out]


def test_a_lower_grade_naming_a_higher_one_is_not_a_contradiction():
    """[C - would be B if the far side were visible] is honest, not wrong."""
    out = RL.lint("x [C — would be B were the far side visible].", GATES)
    assert "citation_contradicts_its_own_grade" not in _checks(out)


# ── families are named by their fields, not only by prose ─────────────────

def test_press_trigger_summary_is_the_pressing_family():
    """A real [A] on a downgraded family went unflagged because the pattern
    demanded the words "pressing" or "pressure". Citations name fields."""
    out = RL.lint("Back pass was the top trigger "
                  "[A — press_trigger_summary: 8 observed phases].",
                  dict(GATES, gates=dict(GATES["gates"], pressing="downgraded")))
    assert "a_grade_on_downgraded_family" in _checks(out)


# ── a number has to be about the field it is matched against ──────────────

VAR_POSS = {"fields": {"possession_by_window.focus_pct": {
    "verdict": "constructed", "windows_with_value": 21,
    "values": {"50.0": 20}}}}


def test_a_line_height_percentage_is_not_a_possession_figure():
    """Both medium findings on the 28 August reports were line-height text
    matched against possession's modal value. away_height_pct is measured."""
    out = RL.lint("The defensive line settled at approximately 40–50% of the "
                  "pitch depth across the first half.", GATES, VAR_POSS)
    assert out == [], out


def test_out_of_possession_is_a_phase_of_play_not_a_statistic():
    """The idiom put every defending paragraph's numbers in scope."""
    out = RL.lint("Tilbury organised in a mid-block out of possession. The "
                  "defensive line settled at 50% of the pitch depth.",
                  GATES, VAR_POSS)
    assert out == [], out


def test_a_real_possession_figure_is_still_caught():
    out = RL.lint("The possession split was a contested 50% across the match.",
                  GATES, VAR_POSS)
    assert "value_from_unmeasured_field" in _checks(out)


def test_an_unmonitored_field_still_matches_without_a_subject():
    """A field with no SUBJECT_OF entry falls back to matching anywhere,
    rather than silently checking nothing."""
    variance = {"fields": {"some_new_list.some_field": {
        "verdict": "not_measured", "windows_with_value": 20,
        "values": {"77.0": 19}}}}
    assert "value_from_unmeasured_field" in _checks(
        RL.lint("The figure was 77% across the match.", GATES, variance))
