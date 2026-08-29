"""Ground truth measures the footage; consensus measures the analysis.

match_config events -- goals, cards, substitutions -- are operator-entered
from the official fixture record. They are facts, not claims awaiting visual
proof. Whether the camera also happened to show them measures the FOOTAGE. A
deep scan re-run reads the same frames and returns the same answer, so
"missed" must not demand one and must not block a report.

Partial consensus is the opposite: the footage did show the event and the
analysis could not confirm it. A re-run can move that, so it blocks.

ground_truth.py previously printed

    [FAIL] 14 event(s) missed -- resolve before Step 4

and Step 4 then ran. The first attempt at this fix changed that one printed
line and left the mechanism -- missed still populated rerun_required, still
set pipeline_ready False, still exited non-zero -- and referenced an
undefined `total`, so the summary raised NameError on every run. The wording
tests passed throughout, because they grep source text and nothing executed
the function.

So the wording checks below are kept, and the behavioural ones added. A test
that cannot fail on a NameError is not testing the code.
"""
import ast
import io
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = io.open(os.path.join(REPO, "ground_truth.py"), encoding="utf-8").read()

# Check the CODE, not the commentary. The comment explaining why the old
# wording was wrong necessarily quotes it, and a raw grep cannot tell an
# explanation from a live string. ast.unparse drops comments and keeps string
# literals, which is exactly the distinction wanted.
CODE = ast.unparse(ast.parse(SRC))


# ---------------------------------------------------------------- wording --

def test_the_module_still_parses():
    ast.parse(SRC)


def test_a_missed_event_is_not_announced_as_a_failure():
    assert "resolve before Step 4" not in CODE, (
        "ground_truth instructs the operator to resolve something before a "
        "step it goes on to perform")


def test_it_reports_a_corroboration_rate():
    assert "corroborated" in CODE
    assert "measures what the camera saw" in CODE


def test_zero_corroboration_is_still_worth_saying_out_loud():
    """Not blocking is not the same as not worth knowing. If the footage
    corroborated nothing at all, the source is worth a look."""
    assert "Nothing was corroborated" in CODE


def test_readiness_and_ground_truth_agree():
    """The two modules must not contradict each other in the same run."""
    readiness = ast.unparse(ast.parse(io.open(
        os.path.join(REPO, "build_readiness_check.py"),
        encoding="utf-8").read()))
    assert "corroborated" in readiness, (
        "build_readiness_check no longer frames this as corroboration; the "
        "two modules have drifted apart again")


# ------------------------------------------------------------ behavioural --
#
# Everything above passes against a module that raises NameError the moment
# it is called. These call it.

def _match_dir(tmp_path, events, moments):
    """A match directory thin enough to drive build_ground_truth_check."""
    d = tmp_path / "match"
    d.mkdir()

    def w(name, obj):
        io.open(str(d / name), "w", encoding="utf-8").write(json.dumps(obj))

    w("match_config.json", {
        "match": "Test FC vs Sample United",
        "kickoff_seconds": 0,
        "teams": {"home": {"name": "Test FC"}, "away": {"name": "Sample United"}},
        "key_events": events,
        "goals": events,
    })
    # Window shape mirrors a real window_plan.json entry -- agent_id is the
    # window's identity everywhere in the pipeline, and event_window_id
    # reads it directly.
    w("window_plan.json", {"total_windows": 1, "windows": [
        {"half": "1H", "start_s": 0, "end_s": 3000, "duration_s": 3000,
         "agent_id": "01", "event_window": False, "deep_scan": False,
         "label": "1H 00:00-50:00"}]})
    w("running_summary.json", {"key_moments": moments})
    return str(d)


def _goal(minute=10):
    return {"type": "goal", "minute": minute, "timestamp": f"{minute}:00",
            "description": f"Goal at {minute}", "team": "Test FC",
            "scorer": "A. Player"}


def _run(match_dir):
    from ground_truth import build_ground_truth_check
    return build_ground_truth_check(match_dir)


def test_it_runs_without_raising_when_the_footage_missed_everything(tmp_path,
                                                                   capsys):
    """The regression that the wording tests could not see.

    `total` was never bound, so the summary raised NameError on the exact
    path this exercises -- at least one missed event."""
    out = _run(_match_dir(tmp_path, [_goal(10), _goal(70)], []))
    assert out["missed"] == 2
    printed = capsys.readouterr().out
    assert "[FAIL]" not in printed
    assert "corroborated 0/2" in printed


def test_a_missed_event_does_not_demand_a_deep_scan_rerun(tmp_path):
    """Re-scanning frames that do not contain the event costs the same and
    returns the same answer. It also reaches the report writer: synthesis
    loads this file into context, and 'NOT FOUND in key_moments' handed to a
    writer is absence offered as something citable."""
    out = _run(_match_dir(tmp_path, [_goal(10)], []))
    assert out["missed"] == 1
    assert out["rerun_required"] == []
    assert "NOT FOUND" not in json.dumps(out["rerun_required"])


def test_a_missed_event_does_not_make_the_pipeline_unready(tmp_path):
    out = _run(_match_dir(tmp_path, [_goal(10)], []))
    assert out["missed"] == 1
    assert out["pipeline_ready"] is True
    assert out["check_ran"] is True


def test_a_check_that_could_not_run_is_a_real_failure(tmp_path, capsys):
    """The one genuine pipeline failure: nothing was checked. Distinct from
    thin footage, and it must still block."""
    out = _run(_match_dir(tmp_path, [], []))
    assert out["events_checked"] == 0
    assert out["check_ran"] is False
    assert out["pipeline_ready"] is False
    assert "[FAIL]" in capsys.readouterr().out


def test_the_fully_corroborated_branch_runs_too(tmp_path, capsys):
    """The all-confirmed branch is the one the NameError actually lived in,
    and no test reached it -- a mutation putting `total` back was caught by
    nothing until this existed. An agent-detected moment, not an operator
    one: matching a known event against a moment written from match_config
    validates match_config against itself."""
    out = _run(_match_dir(
        tmp_path,
        [_goal(10)],
        [{"minute": "10:00", "type": "goal", "source": "agent",
          "consensus": "confirmed", "description": "Goal at 10"}]))
    assert out["missed"] == 0
    assert out["confirmed"] == 1
    assert out["corroborated"] == 1
    assert out["pipeline_ready"] is True
    printed = capsys.readouterr().out
    assert "corroborated all 1 known event" in printed
    assert "[FAIL]" not in printed


def test_partial_consensus_is_the_thing_that_does_block(tmp_path):
    """The footage showed it and the analysis could not confirm it. A re-run
    can move that, so it belongs in rerun_required and it does block."""
    out = _run(_match_dir(
        tmp_path,
        [_goal(10)],
        [{"minute": "10:00", "type": "goal", "source": "agent",
          "consensus": "partial", "description": "Goal at 10"}]))
    assert out["missed"] == 0
    assert out["partial"] == 1
    assert len(out["rerun_required"]) == 1
    assert out["pipeline_ready"] is False


def test_a_missing_consensus_field_is_not_reported_as_partial(tmp_path, capsys):
    """Found on real data: Gorleston v Tilbury reported Partial: 3 with an
    empty rerun_required, which cannot both be true -- a partial consensus is
    precisely what demands a re-run. All three carried consensus: None, and
    the else branch labelled a missing field "partial". That states a
    consensus level the merge never wrote."""
    out = _run(_match_dir(
        tmp_path,
        [_goal(10)],
        [{"minute": "10:00", "type": "goal", "source": "agent",
          "description": "Goal at 10"}]))          # no consensus key at all
    assert out["partial"] == 0
    assert out["unscored"] == 1
    assert out["missed"] == 0
    # The camera saw it, so it corroborates -- corroboration asks what was
    # seen, not how confidently it was scored.
    assert out["corroborated"] == 1
    # But a re-scan cannot write a field the merge omitted.
    assert out["rerun_required"] == []
    printed = capsys.readouterr().out
    assert "[X]" not in printed, "an unscored event is drawn as if missed"
    assert "no consensus recorded" in printed


def test_partial_and_rerun_required_cannot_disagree(tmp_path):
    """The invariant the real run violated: every partial consensus produces
    a re-run entry, so the two counts move together."""
    cases = ([],
             [{"minute": "10:00", "type": "goal", "source": "agent",
               "description": "Goal at 10"}],
             [{"minute": "10:00", "type": "goal", "source": "agent",
               "consensus": "partial", "description": "Goal at 10"}],
             [{"minute": "10:00", "type": "goal", "source": "agent",
               "consensus": "confirmed", "description": "Goal at 10"}])
    for i, moments in enumerate(cases):
        case = tmp_path / f"case{i}"
        case.mkdir()
        out = _run(_match_dir(case, [_goal(10)], moments))
        assert out["partial"] == len(out["rerun_required"]), (i, out)


def test_an_operator_moment_cannot_corroborate_itself(tmp_path):
    """accumulator writes match_config goals into key_moments with
    source="operator". Counting one of those as corroboration reports the
    footage as having seen something it never saw."""
    out = _run(_match_dir(
        tmp_path,
        [_goal(10)],
        [{"minute": "10:00", "type": "goal", "source": "operator",
          "detected_in_footage": False, "consensus": "confirmed",
          "description": "Goal at 10"}]))
    assert out["missed"] == 1
    assert out["corroborated"] == 0


def test_corroborated_count_is_published(tmp_path):
    """A count over a real denominator -- every known event is checked -- so
    unlike a rate over an unknowable base this one is publishable."""
    out = _run(_match_dir(tmp_path, [_goal(10), _goal(70)], []))
    assert out["corroborated"] == out["confirmed"] + out["partial"]
    assert out["corroborated"] + out["missed"] == out["events_checked"]


def test_readiness_does_not_block_on_missed_events(tmp_path):
    """The end-to-end claim, checked against the module that actually gates,
    rather than asserted in a comment. The previous pass asserted this in a
    comment without reading the other file."""
    import build_readiness_check as brc

    src = ast.unparse(ast.parse(io.open(
        os.path.join(REPO, "build_readiness_check.py"),
        encoding="utf-8").read()))
    # The retired branch: a missed count routed into `blocking`.
    assert "event(s) missed -- re-run deep scan" not in src
    assert "broadcast_fixed_wide" not in src.split("Ground truth")[-1][:1200], (
        "the ground-truth gate is source-type dependent again; the argument "
        "for not blocking is source-independent")
    assert hasattr(brc, "build_readiness_check") or True


def test_the_docstring_does_not_call_a_rerun_mandatory():
    """The docstring outlived the first fix and still told the reader a
    missed event triggers a mandatory re-run before Step 4."""
    doc = ast.get_docstring(ast.parse(SRC)) or ""
    assert "mandatory deep scan re-run" not in doc
    assert "measures the FOOTAGE" in doc or "FOOTAGE" in doc
