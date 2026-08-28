"""Window identity has exactly one source: window_plan.json.

THE DEFECT THESE TESTS PIN
--------------------------
``mark_window`` used to mint a window record for any id it was handed::

    if window_id not in state["windows"]:
        state["windows"][window_id] = {s: "pending" for s in WINDOW_STEPS}

A set-piece burst is submitted under the id ``"{window_id}_{anchor_ts}"``
(e.g. ``"01_03m00s"``), and ``collect_results`` recorded every batch result
through ``mark_window``. So finishing a burst created a *window* under the
burst's id, carrying every window step as pending -- including ``3a``.

``pending_windows(state, "3a")`` then reported that window as work to do.
PHASE 1 duly paid for it. Because the burst id is absent from
window_plan.json the window lookup returned ``{}``, and
``get_window_frames`` defaults an absent window to ``start_s=0`` /
``end_s=300`` -- so eight paid structural agents in the run of 2026-08-24
each analysed minutes 0-5 and stamped the output ``00:00-00:00``.

The repair is structural, not a guard: bursts have their own namespace,
``mark_window`` raises on an unknown id, and ``reconcile_with_plan`` moves
records written by earlier builds.
"""
import json
import os
import re

import pytest

import pipeline_state as ps
from pipeline_state import (
    BURST_STEPS, WINDOW_STEPS, init_state, mark_burst, mark_result,
    mark_window, pending_windows, reconcile_with_plan,
)

PLAN_IDS = ["01", "02", "03"]
BURST_ID = "01_03m00s"

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


@pytest.fixture()
def match_dir(tmp_path):
    return str(tmp_path)


@pytest.fixture()
def state(match_dir):
    return init_state(match_dir, "Test vs Test", PLAN_IDS)


# ── the namespaces are distinct ───────────────────────────────────────────────

def test_window_and_burst_steps_are_disjoint():
    """A step is per-window or per-burst, never both.

    3d_setpiece and 3i_player_action sat in WINDOW_STEPS, which is what made
    a burst look like a window in the first place.
    """
    assert set(WINDOW_STEPS) & set(BURST_STEPS) == set()
    assert "3d_setpiece" in BURST_STEPS
    assert "3i_player_action" in BURST_STEPS


def test_a_fresh_window_record_carries_no_burst_steps(state):
    for rec in state["windows"].values():
        assert set(rec) == set(WINDOW_STEPS)


# ── mark_window no longer mints identity ──────────────────────────────────────

def test_mark_window_refuses_an_id_the_plan_never_named(match_dir, state):
    """The exact call that used to cost money.

    3a is a genuine window step, so nothing but the unknown id can raise
    here -- this pins identity, not step routing.
    """
    with pytest.raises(KeyError):
        mark_window(match_dir, state, BURST_ID, "3a", "complete")
    assert BURST_ID not in state["windows"]


def test_mark_window_refuses_a_burst_step(match_dir, state):
    with pytest.raises(ValueError):
        mark_window(match_dir, state, "01", "3d_setpiece", "complete")


def test_mark_burst_refuses_a_window_step(match_dir, state):
    with pytest.raises(ValueError):
        mark_burst(match_dir, state, BURST_ID, "3a", "complete")


def test_a_recorded_burst_does_not_become_a_pending_window(match_dir, state):
    """End-to-end shape of the defect: finish a burst, then ask what 3a owes.

    Goes through mark_result -- the same routing collect_results uses -- so
    this fails if that decision is ever removed, not just if mark_window
    starts minting again. Before the fix, pending_windows returned
    [BURST_ID] and PHASE 1 submitted a paid structural request for it.
    """
    mark_result(match_dir, state, BURST_ID, "3d_setpiece", "complete")

    assert sorted(pending_windows(state, "3a")) == PLAN_IDS
    assert BURST_ID not in pending_windows(state, "3a")
    assert BURST_ID not in state["windows"]
    assert state["bursts"][BURST_ID]["3d_setpiece"] == "complete"


# ── reconcile_with_plan repairs state written by earlier builds ───────────────

def _legacy_state(match_dir):
    """State in the shape pipeline_state.json actually had on 2026-08-24."""
    legacy = {
        "match": "Gorleston vs Tilbury",
        "started": "2026-08-24T20:00:00",
        "quality": "full",
        "windows": {
            **{wid: {"3a": "complete", "3b": "complete", "3d_event": "pending",
                     "3d_setpiece": "pending", "3d_recovery": "pending",
                     "3e_merge": "pending", "3i_player_action": "pending"}
               for wid in PLAN_IDS},
            # burst records that mark_window minted in the window namespace
            BURST_ID: {"3a": "pending", "3b": "pending", "3d_event": "skipped",
                       "3d_setpiece": "complete", "3d_recovery": "skipped",
                       "3e_merge": "skipped", "3i_player_action": "pending"},
            "02_05m30s": {"3a": "skipped", "3b": "skipped",
                          "3d_event": "skipped", "3d_setpiece": "complete",
                          "3d_recovery": "skipped", "3e_merge": "skipped",
                          "3i_player_action": "pending"},
        },
        "steps": {}, "batch_ids": {}, "errors": [],
        "last_updated": "2026-08-24T21:30:00",
    }
    with open(os.path.join(match_dir, ps.STATE_FILE), "w", encoding="utf-8") as f:
        json.dump(legacy, f)
    return legacy


def test_reconcile_moves_orphans_out_of_the_window_namespace(match_dir):
    legacy = _legacy_state(match_dir)
    assert pending_windows(legacy, "3a") == [BURST_ID], "precondition: the leak"

    out = reconcile_with_plan(match_dir, legacy, PLAN_IDS)

    assert sorted(out["windows"]) == PLAN_IDS
    assert sorted(out["bursts"]) == [BURST_ID, "02_05m30s"]
    assert pending_windows(out, "3a") == []


def test_reconcile_preserves_completed_burst_work(match_dir):
    """Burst results are paid for. Migrating them must not re-queue them."""
    out = reconcile_with_plan(match_dir, _legacy_state(match_dir), PLAN_IDS)

    for bid in (BURST_ID, "02_05m30s"):
        assert out["bursts"][bid]["3d_setpiece"] == "complete"


def test_reconcile_strips_burst_steps_from_genuine_windows(match_dir):
    out = reconcile_with_plan(match_dir, _legacy_state(match_dir), PLAN_IDS)

    for rec in out["windows"].values():
        assert set(rec) == set(WINDOW_STEPS)


def test_reconcile_adds_plan_windows_absent_from_state(match_dir):
    out = reconcile_with_plan(match_dir, _legacy_state(match_dir),
                              PLAN_IDS + ["04"])

    assert out["windows"]["04"] == {s: "pending" for s in WINDOW_STEPS}


def test_reconcile_refuses_an_empty_plan(match_dir):
    """An unreadable plan must not silently orphan every real window.

    The superseded workaround in --force-structural did exactly that: it
    fell back to ``_plan_ids = set()`` on OSError, and only a truthiness
    check downstream kept it from treating all 21 windows as pseudo-windows.
    """
    with pytest.raises(ValueError):
        reconcile_with_plan(match_dir, _legacy_state(match_dir), [])


def test_reconcile_is_idempotent(match_dir):
    once = reconcile_with_plan(match_dir, _legacy_state(match_dir), PLAN_IDS)
    shape = (sorted(once["windows"]), sorted(once["bursts"]))
    twice = reconcile_with_plan(match_dir, once, PLAN_IDS)

    assert (sorted(twice["windows"]), sorted(twice["bursts"])) == shape


# ── enforcement: the callers cannot regrow the old behaviour ──────────────────

def _source(name):
    with open(os.path.join(REPO_ROOT, name), encoding="utf-8") as f:
        return f.read()


def _function_body(src, name):
    m = re.search(rf"^def {name}\(.*?(?=^def |\Z)", src, re.M | re.S)
    assert m, f"{name} not found"
    return m.group(0)


def test_collect_results_routes_burst_steps_by_step():
    """A batch result must be filed by what the step is, not assumed a window.

    Any bare mark_window call in collect_results is the old routing back.
    """
    body = _function_body(_source("batch_runner.py"), "collect_results")

    assert "mark_result(" in body
    direct = [ln for ln in body.splitlines()
              if re.search(r"(?<![\w.])mark_(window|burst)\(", ln)]
    assert direct == [], (
        f"collect_results bypasses mark_result and picks a namespace "
        f"itself: {direct}")


def test_the_runner_reconciles_before_reading_pending_windows():
    """Order matters: reconcile has to happen before any phase asks for work."""
    src = _source("pipeline_runner_v2.py")
    recon = src.index("state = reconcile_with_plan(")
    first_pending = src.index('pending_windows(state, "3a")')

    assert recon < first_pending


def test_force_structural_no_longer_re_reads_the_plan_to_skip_pseudo_windows():
    """The workaround is replaced, not left standing beside the real fix.

    state["windows"] is plan-only now, so a filter inside the reset loop
    would be dead code that reads as if it were load-bearing.
    """
    src = _source("pipeline_runner_v2.py")

    assert "_skipped_pseudo" not in src
    assert "set-piece pseudo-window, not an analysis window" not in src


# ── the same defect, reaching the accumulator ─────────────────────────────────
#
# Stopping burst records from becoming windows stops NEW ghost files. The 18
# already on disk keep polluting every accumulation run, because the
# accumulator found its structural inputs with a bare glob for
# "*structural*.json" in eight separate places -- so agent_01_03m00s_structural
# .json counted as a window everywhere. On the Gorleston match that inflated
# the formation vote to 39 and supplied the far-side sample observations,
# with 18 of the 39 being the same five minutes analysed over and over.

def _fake_logs(tmp_path, window_ids, burst_ids):
    import json as _json
    (tmp_path / "window_plan.json").write_text(_json.dumps(
        {"windows": [{"agent_id": w} for w in window_ids]}), encoding="utf-8")
    logs = tmp_path / "agent_logs"
    logs.mkdir()
    for i in list(window_ids) + list(burst_ids):
        (logs / f"agent_{i}_structural.json").write_text("{}", encoding="utf-8")
        (logs / f"agent_{i}_player.json").write_text("{}", encoding="utf-8")
    return str(logs)


def test_structural_files_excludes_burst_output(tmp_path):
    from pipeline_paths import structural_files

    logs = _fake_logs(tmp_path, ["01", "02"], ["01_03m00s", "02_05m30s"])

    got = [os.path.basename(p) for p in structural_files(logs)]
    assert got == ["agent_01_structural.json", "agent_02_structural.json"]


def test_structural_files_returns_plan_order_not_lexical(tmp_path):
    """Plan order is what the callers mean; lexical order only coincides."""
    from pipeline_paths import structural_files

    logs = _fake_logs(tmp_path, ["03", "01", "02"], [])

    got = [os.path.basename(p)[6:8] for p in structural_files(logs)]
    assert got == ["03", "01", "02"]


def test_structural_files_refuses_to_guess_without_a_plan(tmp_path):
    """No plan means no way to tell a window from a burst. Say so."""
    from pipeline_paths import structural_files

    logs = tmp_path / "agent_logs"
    logs.mkdir()
    (logs / "agent_01_structural.json").write_text("{}", encoding="utf-8")

    with pytest.raises(FileNotFoundError):
        structural_files(str(logs))


def test_the_accumulator_never_globs_structural_files_itself():
    """Eight bare globs were eight chances to disagree about what a window is."""
    src = _source("accumulator.py")

    stray = [ln.strip() for ln in src.splitlines()
             if "glob.glob" in ln and "structural" in ln]
    assert stray == [], f"accumulator bypasses structural_files(): {stray}"
