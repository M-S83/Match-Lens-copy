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

def test_recovery_is_not_charged_because_it_cannot_run(tmp_path):
    """3d_recovery has no phase in the runner. Nothing submits it, and pricing
    it inflated every estimate this tool has produced."""
    est = calculate_cost(load_match_data(_match(tmp_path)), "full")

    assert est["steps"]["3d_recovery"]["cost_usd"] == 0.0
    assert "no runner phase" in est["steps"]["3d_recovery"]["note"]


def test_synthesis_is_three_calls_not_two():
    """One tactical report plus one opposition report per team."""
    assert REPORT_CALLS == 3
