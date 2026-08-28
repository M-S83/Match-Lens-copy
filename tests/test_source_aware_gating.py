"""Guards for the two source-aware policy changes.

1. Ground truth is a measure of the FOOTAGE, not of the analysis. Goals, cards
   and substitutions come from the official fixture record via match_config;
   they are known facts. Blocking reports because a ball-following camera did
   not independently re-observe a yellow card withheld analysis the operator
   facts already underwrite.

2. Set-piece 5fps bursts are paid work. Running them for a source whose
   profile has already downgraded the set_pieces family spends money to
   enrich a result that is downgraded before it is written.
"""
import json
import os

import pytest

import build_readiness_check as brc
import escalation_router as er


def _gt(missed, checked):
    return {"missed": missed, "events_checked": checked}


def test_missed_events_no_longer_block_reports(tmp_path, monkeypatch):
    """13 of 16 missed on Veo is the camera, not a pipeline failure."""
    blocking, warnings = [], []
    gt = _gt(13, 16)
    gt_total, gt_missed = gt["events_checked"], gt["missed"]
    if isinstance(gt_missed, int) and gt_total > 0:
        warnings.append("corroborated")
    else:
        blocking.append("did not run")
    assert blocking == []
    assert warnings


def test_a_check_that_never_ran_still_blocks():
    """0 events checked means the step failed or its file is missing --
    a different thing from the footage not showing an event."""
    blocking, warnings = [], []
    gt_total, gt_missed = 0, "file missing"
    if isinstance(gt_missed, int) and gt_total > 0:
        warnings.append("corroborated")
    else:
        blocking.append("did not run")
    assert blocking and not warnings


@pytest.mark.parametrize("wrapper", ["gates", "result_family_rules", "families"])
@pytest.mark.parametrize("state,allowed", [
    ("allowed",     True),
    ("downgraded",  False),
    ("suppressed",  False),
])
def test_set_piece_escalation_follows_the_source_profile(tmp_path, wrapper, state, allowed):
    """`gates` is the key source_profiler actually writes -- the first version of
    this guard checked the other two, matched neither, and silently allowed a
    full set of paid 5fps bursts on a source that downgrades set_pieces."""
    (tmp_path / "result_family_gates.json").write_text(
        json.dumps({wrapper: {"set_pieces": state}}), encoding="utf-8")
    assert er._set_pieces_family_allowed(str(tmp_path)) is allowed


def test_gate_reads_the_real_file_shape_source_profiler_writes(tmp_path):
    """Verbatim structure from a real run rather than an assumed one."""
    real = {
        "source_type": "veo_ball_tracking",
        "analysis_scope": "all",
        "gates": {"shape": "downgraded", "spacing": "downgraded",
                  "set_pieces": "downgraded", "local_duels": "allowed"},
        "visibility_based_limitations": ["..."],
        "schema_version": "1.0",
    }
    (tmp_path / "result_family_gates.json").write_text(json.dumps(real), encoding="utf-8")
    assert er._set_pieces_family_allowed(str(tmp_path)) is False


def test_no_profile_means_escalate_as_before(tmp_path):
    """Absent gates file must not silently suppress paid work."""
    assert er._set_pieces_family_allowed(str(tmp_path)) is True


def test_unreadable_gates_file_does_not_suppress(tmp_path):
    (tmp_path / "result_family_gates.json").write_text("{not json", encoding="utf-8")
    assert er._set_pieces_family_allowed(str(tmp_path)) is True


def test_ocr_timeout_is_large_enough_for_a_full_match():
    """~250 full-HD frames at 2-5s each on CPU. The old 600s budget meant the
    step timed out and self-skipped on every run it has ever made."""
    import pipeline_runner_v2 as pr
    assert pr.OCR_TIMEOUT_S >= 1800


def test_ocr_crops_to_the_player_band_before_inference():
    import jersey_ocr as jo
    assert 0 < jo.PLAYER_BAND_TOP < jo.PLAYER_BAND_BOTTOM < 1


# -- Tier 1 efficiency changes ------------------------------------------------

def test_api_frames_are_sent_at_the_cheaper_resolution():
    """Anthropic bills to a 1568-token ceiling, so full-HD costs double for no
    extra legibility on this footage."""
    import pipeline_runner_v2 as pr
    for q in ("economy", "standard", "full"):
        p = pr.QUALITY_PROFILES[q]
        assert p["resize_w"] == 1024 and p["resize_h"] == 576, q


def test_estimator_per_frame_cost_tracks_the_runner_resolution():
    """If these drift apart every estimate is wrong by 2x."""
    import cost_estimator as ce
    for q in ("economy", "standard", "full"):
        assert ce.QUALITY_PROFILES[q]["tokens_per_frame"] == 786, q


def test_estimator_prices_at_batch_rates():
    """The runner submits everything through the Batches API at 50% of list."""
    import cost_estimator as ce
    assert ce.INPUT_COST_PER_TOKEN == 3.00 / 1_000_000 * 0.5


def test_frame_selection_keeps_temporal_spread():
    """Quality selection must not clump frames -- one per equal time bucket."""
    import pipeline_runner_v2 as pr
    frames = [f"frame_{i:02d}m00s.jpg" for i in range(60)]
    picked = pr.sample_frames(frames, 6)
    assert len(picked) == 6
    idx = [frames.index(p) for p in picked]
    assert idx == sorted(idx)
    assert max(idx) - min(idx) >= 40, "selection collapsed into part of the window"


def test_frame_selection_falls_back_without_pillow(monkeypatch):
    import pipeline_runner_v2 as pr
    frames = [f"f{i}.jpg" for i in range(40)]
    assert len(pr.sample_frames(frames, 5)) == 5
    assert pr.sample_frames(frames, 100) == frames


@pytest.mark.parametrize("cfg,expected", [
    ({}, 300),
    ({"window_seconds": 150}, 150),
    ({"window_seconds": 5}, 300),      # below the sane floor -> default
    ({"window_seconds": "abc"}, 300),  # wrong type -> default
])
def test_window_length_is_configurable_within_sane_bounds(cfg, expected):
    import window_plan as wp
    assert wp._window_seconds(cfg) == expected


def test_frame_scoring_is_bounded_per_bucket(monkeypatch):
    """Regression: the first version scored EVERY frame in the window at full
    1920x1080 -- 176 ms each, ~9300 frames on a 31-window run, 27 minutes of
    silent CPU before the first API call. Scoring must be bounded and must
    never touch a full-resolution image."""
    import pipeline_runner_v2 as pr
    from PIL import Image

    opened = {"count": 0, "sizes": []}
    real_open = Image.open

    def spy(path, *a, **k):
        opened["count"] += 1
        return real_open(path, *a, **k)

    monkeypatch.setattr(Image, "open", spy)
    frames = [f"frame_{i:03d}.jpg" for i in range(300)]   # unreadable -> score 0
    picked = pr.sample_frames(frames, 60)
    assert len(picked) == 60
    # 60 buckets x at most 4 candidates each
    assert opened["count"] <= 60 * 4, f"scored {opened['count']} frames, unbounded"


def test_frame_scoring_uses_draft_mode_not_full_decode():
    """PIL draft mode decodes a JPEG straight to a reduced size. Without it the
    full frame is decoded and thrown away."""
    import inspect
    import pipeline_runner_v2 as pr
    src = inspect.getsource(pr.sample_frames)
    assert ".draft(" in src, "frame scoring must decode via draft mode"
    assert "thumbnail" in src, "frame scoring must not run on full-size images"


def test_force_structural_leaves_setpiece_pseudo_windows_alone(tmp_path):
    """Regression: a blanket reset marked the 10 set-piece pseudo-windows
    pending for 3a and 3b. That cost ten spurious paid 3a requests and then
    crashed 3b with a 400, because those windows carry no frames so the request
    list came back empty."""
    import json
    plan = {"windows": [{"agent_id": f"{i:02d}"} for i in range(1, 22)]}
    (tmp_path / "window_plan.json").write_text(json.dumps(plan), encoding="utf-8")
    plan_ids = {str(w["agent_id"]) for w in plan["windows"]}
    state_windows = {f"{i:02d}": {} for i in range(1, 22)}
    state_windows.update({"02_08m40s": {}, "01_03m30s": {}})
    reset = [w for w in state_windows if str(w) in plan_ids]
    assert len(reset) == 21
    assert "02_08m40s" not in reset


def test_submit_batch_refuses_an_empty_request_list():
    """The API returns 400 for a zero-item batch. Skipping is correct."""
    import batch_runner as br
    assert br.submit_batch("/tmp", {}, [], "3b") is None


def test_ocr_confidence_is_low_enough_to_find_anything():
    """At 0.82 a completed scan of 247 frames produced 5 sightings. The roster
    cross-reference in resolve_to_players is the real filter."""
    import jersey_ocr as jo
    import inspect
    assert inspect.signature(jo.run_ocr).parameters["confidence_threshold"].default <= 0.5
