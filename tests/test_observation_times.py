"""An observation timestamp has to belong to the window it came from.

WHAT THIS FOUND
---------------
The schema asks for "timestamp": "[MMmSSs]" and nowhere says which clock --
absolute video time, time since kick-off, or an offset within the window. Each
window's agent picked its own, and some picked none:

  * the window covering 10:00-15:00 returned fifteen observations stamped
    00m00s, 01m00s, 02m00s ... 14m00s -- one per player, at exactly
    one-minute intervals. An index, not a reading.
  * the window covering 45:00-48:15 returned fifteen, all stamped 00m00s.
  * other windows returned irregular values that do look observed.

Across 265 observations of a 121-minute match, not one timestamp exceeds 25
minutes, and frames[0] equals the timestamp in 264 of 265 cases -- the
filename generated from the number rather than the number read off a frame.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from accumulator import _validate_observation_times, _window_bounds


def _obs(*stamps):
    return [{"player": f"#{i}", "timestamp": t,
             "frames": [f"frame_{t}.jpg"]} for i, t in enumerate(stamps)]


def _run(observations, rng="10:00-15:00", window="1H_10-00-15-00"):
    summary = {}
    _validate_observation_times(observations, window, rng, summary)
    return summary


# ── bounds ────────────────────────────────────────────────────────────────

def test_a_range_is_read_as_seconds():
    assert _window_bounds("10:00-15:00") == (600, 900)
    assert _window_bounds("45:00-48:15") == (2700, 2895)


def test_an_unreadable_range_disables_the_check_rather_than_guessing():
    for bad in (None, "", "first half", "10:00", 42):
        assert _window_bounds(bad) is None


def test_a_window_with_no_range_leaves_observations_alone():
    obs = _obs("00m00s")
    _run(obs, rng=None)
    assert obs[0]["timestamp"] == "00m00s"


# ── the two real failures ─────────────────────────────────────────────────

def test_the_one_per_minute_index_is_rejected():
    """The 10:00-15:00 window: fifteen players, 00m00s to 14m00s."""
    obs = _obs(*[f"{i:02d}m00s" for i in range(15)])
    summary = _run(obs)

    kept = [o["timestamp"] for o in obs if o["timestamp"]]
    assert kept == ["10m00s", "11m00s", "12m00s", "13m00s", "14m00s"], (
        "only the five that happen to land inside the window survive; the "
        "other ten are indices that cannot be observations of it")
    assert summary["observation_time_rejects"][0]["rejected"] == 10


def test_a_window_of_all_zeros_loses_every_timestamp():
    """The 45:00-48:15 window."""
    obs = _obs(*["00m00s"] * 15)
    summary = _run(obs, rng="45:00-48:15")
    assert all(o["timestamp"] is None for o in obs)
    assert summary["observation_time_rejects"][0] == {
        "window": "1H_10-00-15-00", "range": "45:00-48:15",
        "rejected": 15, "of": 15}


def test_a_genuine_within_window_reading_survives_untouched():
    obs = _obs("10m30s", "12m45s", "14m59s")
    summary = _run(obs)
    assert [o["timestamp"] for o in obs] == ["10m30s", "12m45s", "14m59s"]
    assert "observation_time_rejects" not in summary
    assert all("frames" in o for o in obs)


def test_the_window_edges_are_inclusive():
    obs = _obs("10m00s", "15m00s")
    _run(obs)
    assert [o["timestamp"] for o in obs] == ["10m00s", "15m00s"]


# ── what happens to a rejected one ────────────────────────────────────────

def test_the_rejected_value_is_kept_for_diagnosis_not_for_use():
    obs = _obs("02m00s")
    _run(obs)
    assert obs[0]["timestamp"] is None, "the field a reader uses must be empty"
    assert obs[0]["timestamp_rejected"] == "02m00s"
    assert "no clock is defined" in obs[0]["timestamp_note"]


def test_the_frame_reference_goes_with_it():
    """frames[0] is generated from the timestamp in 264 of 265 cases, so it
    names footage the observation was not taken from."""
    obs = _obs("02m00s")
    _run(obs)
    assert "frames" not in obs[0]
    assert obs[0]["frames_rejected"] == ["frame_02m00s.jpg"]


def test_the_observation_itself_is_never_discarded():
    """The player and what they did are still evidence. Only the claim about
    WHEN is unsupported."""
    obs = _obs("02m00s")
    obs[0]["observation"] = "drops between the lines to receive"
    _run(obs)
    assert obs[0]["player"] == "#0"
    assert obs[0]["observation"] == "drops between the lines to receive"


def test_shifting_by_the_window_start_is_not_the_fix():
    """Adding 600s would turn 00m00s into a plausible 10m00s and legitimise
    every index and every zero. The honest offsets and the fabrications look
    identical once shifted, so nothing is reinterpreted."""
    obs = _obs("00m00s")
    _run(obs)
    assert obs[0]["timestamp"] is None
    assert obs[0].get("timestamp") != "10m00s"


def test_an_unparseable_timestamp_is_left_for_someone_else():
    obs = [{"player": "#1", "timestamp": "second half"}]
    _run(obs)
    assert obs[0]["timestamp"] == "second half"
