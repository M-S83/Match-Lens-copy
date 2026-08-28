"""Step 3i must not look like it ran when it cannot run.

3i_player_action has never produced a single confirmation on any run, and
nothing said so. The phase is wrapped in

    except Exception as _pa_e:
        print(f"  PHASE 3b-player: Error - {_pa_e} (non-blocking, continuing)")

so a fatal misconfiguration reads as one line in a long log and the run
reports success. Three separate faults were hiding behind it:

  * the confirmation prompt template does not exist, and the path that
    looked for it resolved to <repo>/../prompts -- outside the repository;
  * ELIGIBLE_CATEGORIES matched 1 of 45 queued items on the Gorleston match;
  * fatally, merge_player_confirmation_into_window writes back into
    individual_observations matching on action_category, and not one of the
    265 observations on that match used an eligible category. The two
    vocabularies do not overlap, so a confirmed result would match nothing.

These tests hold each fault in place as a checkable condition, so the step
turns itself back on when they are fixed rather than staying dark by habit.
"""
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import player_escalation_router as R


def _match(tmp_path, obs_categories, queue=()):
    logs = tmp_path / "agent_logs"
    logs.mkdir()
    (logs / "agent_01_1H_00-00-05-00_merged.json").write_text(json.dumps({
        "window": "1H_00-00-05-00",
        "individual_observations": [
            {"player": "A (#1)", "action_category": c, "timestamp": "01m00s"}
            for c in obs_categories],
        "player_escalation_queue": list(queue),
    }), encoding="utf-8")
    return str(tmp_path)


# ── the gate ───────────────────────────────────────────────────────────────

def test_missing_prompt_template_disables_the_step(tmp_path, monkeypatch):
    monkeypatch.setattr(R, "PROMPT_TEMPLATE", str(tmp_path / "nope.md"))
    ok, why = R.escalation_is_available(
        _match(tmp_path, ["receiving_orientation"]))
    assert ok is False
    assert "template is missing" in why


def test_disjoint_vocabularies_disable_the_step(tmp_path, monkeypatch):
    """The Gorleston condition: the write-back could never match."""
    template = tmp_path / "t.md"
    template.write_text("x", encoding="utf-8")
    monkeypatch.setattr(R, "PROMPT_TEMPLATE", str(template))

    ok, why = R.escalation_is_available(
        _match(tmp_path, ["movement_off_ball", "hold_up_play",
                          "aerial_ability", "drop deep"]))
    assert ok is False
    assert "could never be written back" in why
    assert "movement_off_ball" in why


def test_the_step_enables_itself_once_both_faults_are_fixed(tmp_path,
                                                            monkeypatch):
    """Not dark by habit: one overlapping category is enough to turn it on."""
    template = tmp_path / "t.md"
    template.write_text("x", encoding="utf-8")
    monkeypatch.setattr(R, "PROMPT_TEMPLATE", str(template))

    ok, why = R.escalation_is_available(
        _match(tmp_path, ["movement_off_ball", "receiving_orientation"]))
    assert ok is True, why


def test_a_match_with_no_observations_is_not_treated_as_a_fault(tmp_path,
                                                                monkeypatch):
    """Absence of evidence is not the vocabulary fault, and must not read
    as one -- otherwise the reason printed to the operator is wrong."""
    template = tmp_path / "t.md"
    template.write_text("x", encoding="utf-8")
    monkeypatch.setattr(R, "PROMPT_TEMPLATE", str(template))
    ok, why = R.escalation_is_available(_match(tmp_path, []))
    assert ok is True, why


def test_the_prompt_template_path_is_inside_the_repo():
    """The original path was <repo>/../prompts, which no install could satisfy."""
    repo = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    assert os.path.commonpath([repo, R.PROMPT_TEMPLATE]) == repo
    assert ".." not in R.PROMPT_TEMPLATE.split(os.sep)


# ── the clamp ──────────────────────────────────────────────────────────────

def test_an_observation_at_the_start_of_the_match_still_gets_a_window(tmp_path):
    """timestamp 00m00s gave rerun_window_start: null.

    _seconds_to_mmss returns None below zero, and 45% of observations on the
    Gorleston match are stamped 00m00s, so the burst extraction downstream
    was handed a window with no start.
    """
    item = {"player": "A (#1)", "action_category": "receiving_orientation",
            "timestamp": "00m00s", "priority": "low"}
    R.build_player_escalation_queue(
        _match(tmp_path, ["receiving_orientation"], queue=[item]))

    out = json.loads((tmp_path / "player_escalation_queue.json")
                     .read_text(encoding="utf-8"))
    accepted = out["accepted"]
    assert len(accepted) == 1
    assert accepted[0]["rerun_window_start"] == "00m00s", (
        "an observation at the start of the match produced a null rerun "
        "window start")
    assert accepted[0]["rerun_window_end"] == "00m02s"


def test_a_mid_match_observation_is_unchanged(tmp_path):
    item = {"player": "A (#1)", "action_category": "foot_used",
            "timestamp": "12m30s", "priority": "high"}
    R.build_player_escalation_queue(
        _match(tmp_path, ["foot_used"], queue=[item]))
    out = json.loads((tmp_path / "player_escalation_queue.json")
                     .read_text(encoding="utf-8"))
    assert out["accepted"][0]["rerun_window_start"] == "12m28s"
    assert out["accepted"][0]["rerun_window_end"] == "12m32s"


# ── the write-back contract the gate is protecting ─────────────────────────

def test_writeback_needs_all_three_fields_to_match(tmp_path):
    """Why a disjoint vocabulary is fatal rather than merely wasteful."""
    md = _match(tmp_path, ["receiving_orientation"])
    confirmation = {"status": "confirmed", "player": "A (#1)",
                    "timestamp": "01m00s",
                    "action_category": "receiving_orientation",
                    "confidence_after_rerun": 0.8,
                    "confirmed_detail": "half-turned onto his right",
                    "recommended_report_wording": "receives half-turned"}
    assert R.merge_player_confirmation_into_window(md, confirmation) is True

    wrong = dict(confirmation, action_category="movement_off_ball")
    assert R.merge_player_confirmation_into_window(md, wrong) is False, (
        "a category the observations do not use must not merge -- this is "
        "the failure the gate exists to prevent happening silently")


def test_an_inconclusive_confirmation_leaves_the_observation_alone(tmp_path):
    md = _match(tmp_path, ["foot_used"])
    assert R.merge_player_confirmation_into_window(
        md, {"status": "inconclusive", "player": "A (#1)",
             "timestamp": "01m00s", "action_category": "foot_used"}) is False
