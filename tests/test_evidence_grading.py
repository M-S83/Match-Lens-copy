"""The evidence grade may not exceed what the camera could see.

The synthesis prompt used to say, of a pattern the accumulator had counted:

    accumulator "consistent" -> always [A] in the report
    Never write [C] or [D] for an accumulator-classified tendency.

That rule exists for a good reason: a player observed dropping deep 14 times
should not be hedged into meaninglessness because no single observation's
prose sounds confident. But it collapses two independent questions into one.

  COUNT         -- how many observations support this. The accumulator owns
                   it, and on that axis the rule is right.
  OBSERVABILITY -- whether this camera can see the thing at all. The source
                   profile owns it, and the rule never consulted it.

On a Veo ball-tracking source, eighteen result families are downgraded --
shape, territory, pressing, rest_defence, player_positioning among them. The
tactical report nonetheless carried 28 [A] grades, 18 of them on downgraded
families, including "far-side fullback positioning was uniformly mid-depth
across all observed phases [A]" three paragraphs after its own data-quality
note called far-side positioning frequently unobservable.

The grade must be the lower of the two axes.
"""
import json
import os

import pytest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _prompt():
    with open(os.path.join(REPO_ROOT, "synthesis_agent.py"), encoding="utf-8") as f:
        return f.read()


def test_the_always_A_instruction_is_gone_not_merely_caveated():
    """Replaced, not softened. A contradicted instruction still gets followed."""
    src = _prompt()

    assert 'accumulator "consistent" → always [A] in the report' not in src
    assert "always [A]" not in src


def test_the_prompt_states_both_axes_and_which_wins():
    src = _prompt()

    assert "AXIS 1 — COUNT" in src
    assert "AXIS 2 — OBSERVABILITY" in src
    assert "the LOWER of them" in src


def test_a_downgraded_family_is_capped_at_B():
    src = _prompt()

    assert 'family "downgraded" → observability axis permits [B] at most' in src
    assert 'family "suppressed" → do not report the finding at all' in src


def test_the_prompt_forbids_reporting_a_never_measured_field():
    """Not "hedge it" -- omit it. A hedged mention still reads as a finding."""
    src = _prompt()

    assert "field_variance.not_measured" in src
    assert "Say NOTHING about any" in src


def test_the_count_axis_is_still_authoritative_for_counted_patterns():
    """The original fix solved a real problem; this must not undo it."""
    src = _prompt()

    assert "the count\nsupersedes the impression" in src
    assert "Quote-hedge" in src


# ── the grader is actually given what the rule refers to ──────────────────────

def _match_dir(tmp_path, gates=None):
    def write(name, obj):
        (tmp_path / name).write_text(json.dumps(obj), encoding="utf-8")

    write("match_config.json", {"match": "A vs B"})
    write("pass_sequences.json", [])
    write("running_summary.json", {
        "match": "A vs B",
        "formation_history": [{"home_formation": "4-4-2"} for _ in range(21)],
        "line_height_m_by_window": [
            {"home_height_pct": 45.0, "away_height_pct": 40.0 + (i % 5) * 2}
            for i in range(21)],
    })
    write("confidence_reliability_report.json",
          {"result_family_gates": gates if gates is not None
           else {"shape": "downgraded", "local_duels": "allowed"}})
    return str(tmp_path)


def test_the_bundle_carries_the_family_gates(tmp_path):
    """A rule the grader cannot evaluate is not a rule."""
    from synthesis_agent import build_input_bundle

    bundle = build_input_bundle(_match_dir(tmp_path))

    assert bundle["result_family_gates"]["shape"] == "downgraded"
    assert bundle["result_family_gates"]["local_duels"] == "allowed"


def test_the_bundle_carries_the_not_measured_field_list(tmp_path):
    from synthesis_agent import build_input_bundle

    bundle = build_input_bundle(_match_dir(tmp_path))

    assert "formation_history.home_formation" in bundle["field_variance"]["not_measured"]
    assert ("line_height_m_by_window.away_height_pct"
            not in bundle["field_variance"]["not_measured"])


def test_field_variance_is_computed_not_read(tmp_path):
    """A stale field_variance.json must not outrank the summary beside it."""
    from synthesis_agent import build_input_bundle

    md = _match_dir(tmp_path)
    (tmp_path / "field_variance.json").write_text(
        json.dumps({"not_measured": ["a_stale_lie"]}), encoding="utf-8")

    bundle = build_input_bundle(md)

    assert "a_stale_lie" not in bundle["field_variance"]["not_measured"]


def test_missing_gates_do_not_crash_synthesis(tmp_path):
    """Older matches have no reliability report; the bundle degrades to {}."""
    from synthesis_agent import build_input_bundle

    md = _match_dir(tmp_path)
    os.remove(os.path.join(md, "confidence_reliability_report.json"))

    assert build_input_bundle(md)["result_family_gates"] == {}


# ── absent beats forbidden ────────────────────────────────────────────────────
#
# The first version of this fix added a prompt rule saying not to report a
# never-measured field, and left canonical_formation = "4-4-2" in the bundle
# alongside a FORMATION RULE telling the writer to use that label. The report
# that came back said "Both teams operated in a 4-4-2 throughout the match,
# confirmed across all observed phases [A]" and, one sentence later, "no
# meaningful formation variation" -- offering the very absence of variation
# that disqualified the field as evidence that the shape was settled.
#
# A rule cannot beat a value sitting in the data. The value has to go.

def test_a_never_measured_field_is_removed_from_the_bundle(tmp_path):
    from synthesis_agent import build_input_bundle

    rs = build_input_bundle(_match_dir(tmp_path))["running_summary"]

    assert all(w["home_formation"] == "not_measured"
               for w in rs["formation_history"])


def test_the_derived_label_goes_too(tmp_path):
    """canonical_formation carries no trace of what it was computed from."""
    from synthesis_agent import build_input_bundle

    md = _match_dir(tmp_path)
    import json as _j
    summary = _j.loads((tmp_path / "running_summary.json").read_text())
    summary["canonical_formation"] = {"home": "4-4-2", "away": "4-4-2"}
    summary["formation_distribution"] = {"home": {"4-4-2": 21}}
    (tmp_path / "running_summary.json").write_text(_j.dumps(summary),
                                                   encoding="utf-8")

    rs = build_input_bundle(md)["running_summary"]

    assert rs["canonical_formation"] == "not_measured"
    assert rs["formation_distribution"] == "not_measured"


def test_redaction_is_per_field_not_per_list(tmp_path):
    """away_height_pct varies and must survive its stuck neighbour."""
    from synthesis_agent import build_input_bundle

    rs = build_input_bundle(_match_dir(tmp_path))["running_summary"]
    entry = rs["line_height_m_by_window"][0]

    assert entry["home_height_pct"] == "not_measured"
    assert entry["away_height_pct"] == 40.0


def test_the_prompt_tells_the_writer_what_to_do_with_a_redacted_formation():
    """The rule and the data must now agree instead of contradicting."""
    src = _prompt()

    assert 'If canonical_formation is "not_measured"' in src
    assert "do not write that the shape was settled" in src


def test_a_measured_summary_is_left_alone(tmp_path):
    """Redaction must not fire on a match where the fields actually moved."""
    import json as _j
    from field_variance import compute, redact

    summary = {
        "formation_history": [{"home_formation": f} for f in
                              ["4-4-2"] * 10 + ["4-3-3"] * 11],
        "canonical_formation": {"home": "4-4-2"},
    }
    out = redact(summary, compute(str(tmp_path), summary, write=False))

    assert out["canonical_formation"] == {"home": "4-4-2"}
    assert out["formation_history"][0]["home_formation"] == "4-4-2"


# ── examples beat rules ───────────────────────────────────────────────────────
#
# Third instance of one pattern. A rule was added and a contradicting
# instruction left standing, so the contradiction won:
#
#   1. "accumulator consistent -> always [A]"  vs the family gate
#   2. FORMATION RULE "use canonical_formation" vs the not-measured list
#   3. worked examples ending in a literal [A] vs the two-axis rule
#
# After (1) and (2) were fixed the report still carried four [A] grades, all
# on downgraded families, and two of them were fullback positioning -- the
# subject of a prompt example reading "Reid pushed consistently high
# throughout the first half [A]". player_positioning is downgraded for a
# ball-tracking source, so that example demonstrates the wrong answer.
#
# A demonstration outweighs a rule. The examples carry a placeholder now.

def test_no_worked_example_ends_in_a_literal_grade():
    """A literal grade belongs only in a sentence about the two axes.

    Anywhere else it is a demonstration, and a demonstration of the wrong
    answer is what produced the four surviving [A] grades.
    """
    import re

    offenders = [
        (i + 1, ln.strip())
        for i, ln in enumerate(_prompt().split("\n"))
        if re.search(r"\[(A|B|C|D)\]", ln)
        and "axis" not in ln
        and not ln.strip().startswith("#")
    ]
    assert offenders == [], (
        f"worked example(s) demonstrate a hard-coded grade: {offenders}")


def test_the_fullback_example_no_longer_demonstrates_an_A():
    """The specific example behind two of the four surviving [A] grades."""
    assert "first half [A]" not in _prompt()


def test_examples_use_the_placeholder():
    src = _prompt()

    assert src.count("[grade]") >= 18
    assert "Never emit the word" in src


def test_no_single_axis_mapping_survives_anywhere():
    """between_lines and gk_zone had their own 'confidence -> [A]' tables."""
    src = _prompt()

    assert "-> [A]:" not in src
    assert "→ [A] in the report" not in src
    assert src.count("count axis permits") >= 5


def test_the_two_axis_rule_is_shown_worked_through_once():
    """A rule stated is weaker than a rule demonstrated."""
    src = _prompt()

    assert "the lower of the two is [B]. Write [B]." in src
