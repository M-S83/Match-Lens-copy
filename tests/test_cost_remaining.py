"""What THIS run costs, not what the match would cost from scratch.

The runner printed "Estimated cost: $8.46 / API calls: 57" before four
consecutive --resume --force-reports runs whose real work was three synthesis
calls costing about $0.17. The line sits directly above "Check balance", so it
reads as a spend warning.

That is not a harmless over-estimate. A warning that is wrong every time is one
the operator learns to skip, and the run where the number matters is the run
they skip it on.
"""
import json

import pytest

from cost_estimator import (
    REPORT_CALLS, calculate_cost, estimate_remaining, load_match_data,
)


def _match(tmp_path, windows=21, event_windows=9, complete=True):
    (tmp_path / "window_plan.json").write_text(json.dumps({
        "windows": [{"agent_id": f"{i:02d}", "start_s": i * 300,
                     "end_s": (i + 1) * 300, "half": "1H",
                     "event_window": i < event_windows,
                     "label": f"w{i}"} for i in range(windows)]}), encoding="utf-8")
    (tmp_path / "match_config.json").write_text(json.dumps({
        "match": "A vs B", "goals": [], "home_team": "A", "away_team": "B"}),
        encoding="utf-8")
    st = "complete" if complete else "pending"
    (tmp_path / "pipeline_state.json").write_text(json.dumps({
        "windows": {f"{i:02d}": {"3a": st, "3b": st,
                                 "3d_event": st if i < event_windows else "pending"}
                    for i in range(windows)},
        "steps": {"3l_synthesis": "complete"}}), encoding="utf-8")
    return str(tmp_path)


def _set(md, **steps):
    p = f"{md}/pipeline_state.json"
    with open(p) as f:
        s = json.load(f)
    s["steps"].update(steps)
    with open(p, "w") as f:
        json.dump(s, f)


def test_a_finished_match_costs_nothing_to_resume(tmp_path):
    md = _match(tmp_path)
    assert estimate_remaining(md, load_match_data(md), "full")["cost_usd"] == 0.0


def test_force_reports_is_priced_as_three_calls_not_the_whole_match(tmp_path):
    """The exact case that was quoted $8.46 four times."""
    md = _match(tmp_path)
    _set(md, **{"3l_synthesis": "pending"})
    r = estimate_remaining(md, load_match_data(md), "full")
    full = calculate_cost(load_match_data(md), "full")

    assert r["api_calls"] == REPORT_CALLS
    assert r["cost_usd"] < 0.05 * full["total_cost_usd"]


def test_a_cold_match_returns_none_so_the_full_figure_is_shown(tmp_path):
    """With no state, the whole match genuinely is still to pay for."""
    md = _match(tmp_path)
    (tmp_path / "pipeline_state.json").unlink()

    assert estimate_remaining(md, load_match_data(md), "full") is None


def test_only_planned_event_windows_are_priced(tmp_path):
    """3d_event runs on the nine windows the plan flagged. The other twelve sit
    at 'pending' forever and counting them restores the over-estimate."""
    md = _match(tmp_path, complete=False)
    r = estimate_remaining(md, load_match_data(md), "full")

    assert r["breakdown"]["3d_event"]["calls"] == 9


def test_a_partially_done_match_charges_only_for_the_rest(tmp_path):
    md = _match(tmp_path, complete=False)
    p = f"{md}/pipeline_state.json"
    with open(p) as f:
        s = json.load(f)
    for i in range(15):
        s["windows"][f"{i:02d}"]["3a"] = "complete"
    with open(p, "w") as f:
        json.dump(s, f)

    assert estimate_remaining(md, load_match_data(md), "full")[
        "breakdown"]["3a_structural"]["calls"] == 6


def test_skipped_and_failed_windows_are_not_re_charged(tmp_path):
    """A window the gate skipped will not be submitted, and a failed one is not
    retried by default -- charging for either quotes work that will not happen."""
    md = _match(tmp_path, complete=False)
    p = f"{md}/pipeline_state.json"
    with open(p) as f:
        s = json.load(f)
    s["windows"]["00"]["3a"] = "skipped"
    s["windows"]["01"]["3a"] = "failed"
    with open(p, "w") as f:
        json.dump(s, f)

    assert estimate_remaining(md, load_match_data(md), "full")[
        "breakdown"]["3a_structural"]["calls"] == 19


# ── the full-match figure itself was also wrong ──────────────────────────────

def test_recovery_is_not_a_step_at_all(tmp_path):
    """3d_recovery had an entry in WINDOW_STEPS, a suffix in batch_runner and a
    line here -- and no phase in the runner. Nothing ever submitted it, so it
    showed as 0/21 pending forever and inflated every estimate."""
    from pipeline_state import WINDOW_STEPS

    est = calculate_cost(load_match_data(_match(tmp_path)), "full")

    assert "3d_recovery" not in est["steps"]
    assert "3d_recovery" not in WINDOW_STEPS


def test_synthesis_is_three_calls_not_two():
    """One tactical report plus one opposition report per team."""
    assert REPORT_CALLS == 3


# ── pricing the invocation, not the match ─────────────────────────────────
#
# --estimate-only exited before the --force flags were applied and printed
# the full-match table for every quality profile. Asked what --force-player
# would cost, it answered $5.09 including $1.64 of 3a_structural -- a step
# that flag does not touch. The real figure is $1.34.
#
# That is the same over-estimate estimate_remaining was written to replace,
# printed directly above "Check balance", where it reads as a spend warning.

from cost_estimator import state_after_force


def _state(**steps):
    windows = {f"{i:02d}": {"3a": "complete", "3b": "complete",
                            "3d_event": "complete", "3e_merge": "complete"}
               for i in range(1, 22)}
    base = {"3e_merge": "complete", "3l_synthesis": "complete"}
    base.update(steps)
    return {"windows": windows, "steps": base}


def test_force_player_resets_only_the_player_windows():
    out = state_after_force(_state(), force_player=True)
    assert all(w["3b"] == "pending" for w in out["windows"].values())
    assert all(w["3a"] == "complete" for w in out["windows"].values()), (
        "--force-player reset the structural windows, which is the cost it "
        "exists to avoid")


def test_force_structural_resets_both():
    out = state_after_force(_state(), force_structural=True)
    assert all(w["3a"] == "pending" for w in out["windows"].values())
    assert all(w["3b"] == "pending" for w in out["windows"].values())


def test_force_reports_touches_no_window():
    out = state_after_force(_state(), force_reports=True)
    assert all(w["3a"] == "complete" and w["3b"] == "complete"
               for w in out["windows"].values())
    assert out["steps"]["3l_synthesis"] == "pending"


def test_the_original_state_is_not_mutated():
    """--estimate-only must not write anything, including in memory."""
    src = _state()
    state_after_force(src, force_structural=True)
    assert all(w["3a"] == "complete" for w in src["windows"].values())


def test_a_forced_estimate_prices_only_what_that_flag_reruns(tmp_path):
    md = load_match_data(_match(tmp_path))
    (tmp_path / "pipeline_state.json").write_text(
        json.dumps(_state()), encoding="utf-8")

    player = estimate_remaining(str(tmp_path), md, "standard",
                                state=state_after_force(_state(),
                                                        force_player=True))
    struct = estimate_remaining(str(tmp_path), md, "standard",
                                state=state_after_force(_state(),
                                                        force_structural=True))

    assert player["breakdown"]["3a_structural"]["calls"] == 0, (
        "a player rerun was quoted for structural calls it will not make")
    assert player["breakdown"]["3b_player"]["calls"] == 21
    assert player["cost_usd"] < struct["cost_usd"], (
        "the narrower flag must cost less, or there is no reason for it")


def test_without_a_force_flag_a_finished_match_costs_nothing(tmp_path):
    md = load_match_data(_match(tmp_path))
    (tmp_path / "pipeline_state.json").write_text(
        json.dumps(_state()), encoding="utf-8")
    rem = estimate_remaining(str(tmp_path), md, "standard")
    assert rem["cost_usd"] == 0.0
    assert rem["api_calls"] == 0


def test_estimate_only_uses_the_remaining_path_when_forced():
    """The wiring, not just the arithmetic."""
    import ast
    import io as _io
    import os as _os
    repo = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))
    src = _io.open(_os.path.join(repo, "pipeline_runner_v2.py"),
                   encoding="utf-8").read()
    ast.parse(src)
    block = src[src.index("if args.estimate_only:"):]
    block = block[:block.index("sys.exit(0 if _est_ok else 2)")]
    assert "state_after_force" in block
    assert "estimate_remaining" in block
    assert "Nothing has been submitted" in block
