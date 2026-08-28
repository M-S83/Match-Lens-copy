"""
pipeline_state.py — checkpoint manager for Match Lens pipeline

Writes pipeline_state.json to the match directory after every step.
If a run is interrupted, re-running pipeline_runner_v2.py will skip
completed steps and resume from the exact failure point.

State file structure:
  {
    "match":    "Felixstowe vs Lowestoft",
    "started":  "2026-04-23T14:00:00",
    "quality":  "standard",
    "windows": {
      "1H_00-00_05-00": {
        "3a": "complete",
        "3b": "complete",
        "3d_event": "skipped",
        "3e_merge": "complete"
      },
      ...
    },
    "steps": {
      "3c_triage":    "complete",
      "3f_sequences": "complete",
      "3g_summary":   "complete",
      "3h_ground_truth": "pending",
      ...
    },
    "batch_ids": {
      "3a_batch_id": "msgbatch_abc123",
      "3b_batch_id": null
    }
  }
"""

import json, os
from datetime import datetime
from pipeline_schemas import stamp_schema_version

STATE_FILE = "pipeline_state.json"

# Steps belonging to an analysis window. A window's identity is minted by
# window_plan.json and by nothing else.
WINDOW_STEPS  = ["3a", "3b", "3d_event", "3d_recovery", "3e_merge"]

# Steps belonging to a BURST, which is not a window. A burst is a short
# high-fps re-run anchored on one queued event; its id is
# "{window_id}_{anchor_ts}" (e.g. "01_03m00s") and it is minted at run time
# by the confirmation queue, not by the plan.
#
# These two used to sit in WINDOW_STEPS. Recording a burst result through
# mark_window therefore created a full window record under the burst id with
# every window step pending -- including 3a. PHASE 1 found 3a pending and
# paid to run the structural agent against a window that does not exist:
# eight of them in the run of 2026-08-24, each silently handed minutes 0-5
# because get_window_frames defaults an absent window to start_s=0/end_s=300.
BURST_STEPS   = ["3d_setpiece", "3i_player_action"]
PIPELINE_STEPS = [
    "2b_jersey_ocr",
    "3c_triage", "3d_reruns", "3e_merge",
    # v3 port Step 4: zone-normalisation walker runs after the merge
    # step has written *_merged.json files and before pass-sequence
    # accumulation reads them.
    "3e_zone_normalise",
    "3f_shots", "3f_sequences", "3g_summary",
    "3h_ground_truth", "3i_escalation",
    # v3 port Step 1: 3i_player_escalation is the player-side sibling
    # of 3i_escalation. Reads merged windows for player-observation
    # uncertainty and queues focused confirmation passes. Output:
    # player_escalation_queue.json (separate from confirmation_queue.json).
    "3i_player_escalation",
    "3j_readiness",
    "3k_metrics",
    # v3 port Step 1: 3k2_player_cards is the player-side aggregator
    # that runs after deep skill metrics, before synthesis. Reads
    # running_summary + match_config + source_profile; writes
    # player_summary_cards.json.
    "3k2_player_cards",
    "3l_synthesis",
    "4a_tactical_report", "4b_opposition_report",
]


def load_state(match_dir: str) -> dict:
    path = os.path.join(match_dir, STATE_FILE)
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    return None


def init_state(match_dir: str, match_name: str, windows: list,
               quality: str = "standard") -> dict:
    """Create a fresh state file. Call once before starting the pipeline."""
    path = os.path.join(match_dir, STATE_FILE)
    if os.path.exists(path):
        existing = load_state(match_dir)
        # Don't overwrite a state that has completed windows
        done = sum(1 for w in existing.get("windows", {}).values()
                   if w.get("3a") == "complete")
        # ...nor one holding batch IDs. Completed windows alone was the wrong
        # test: while the first 3a batch is in flight it has been submitted and
        # PAID FOR, and nothing is complete yet, so `done` is 0 and the guard
        # did not fire. A bare re-run after an early crash then reset
        # batch_ids to {} -- and the batch ID is the only handle on that work,
        # so the money was simply gone. The hole sat exactly where the loss is
        # largest: 3a is the single biggest step of a standard run.
        batches = existing.get("batch_ids") or {}
        if done > 0 or batches:
            if done > 0:
                print(f"  [STATE] Existing state found: {done} windows complete.")
            if batches:
                print(f"  [STATE] {len(batches)} batch(es) recorded: "
                      f"{', '.join(sorted(batches))}. These are submitted and "
                      f"already paid for.")
            print(f"  [STATE] Keeping it. Re-run with --resume to continue "
                  f"from this checkpoint.")
            print(f"  [STATE] To genuinely start over, delete "
                  f"{STATE_FILE} first -- any in-flight batch is then "
                  f"unreachable and its cost is lost.")
            return existing

    state = {
        "match":     match_name,
        "started":   datetime.now().isoformat(),
        "quality":   quality,
        "windows":   {w: {s: "pending" for s in WINDOW_STEPS} for w in windows},
        "bursts":    {},
        "steps":     {s: "pending" for s in PIPELINE_STEPS},
        "batch_ids": {},
        "errors":    [],
        "last_updated": datetime.now().isoformat(),
    }
    _save(match_dir, state)
    print(f"  [STATE] Initialised: {len(windows)} windows, quality={quality}")
    return state


def mark_window(match_dir: str, state: dict, window_id: str,
                step: str, status: str, error: str = None) -> dict:
    """Mark a step on an EXISTING window as complete/failed/skipped.

    An unknown window id is a bug, not a window. This function used to mint
    one -- a full WINDOW_STEPS skeleton -- as a side effect of recording a
    status, which is how burst ids ("01_03m00s") became windows carrying a
    pending 3a that PHASE 1 then paid to run. Burst-keyed steps belong in
    mark_burst(); reconcile_with_plan() repairs state written before this.
    """
    if step in BURST_STEPS:
        raise ValueError(
            f"mark_window: {step!r} is a burst step; use mark_burst()."
        )
    if window_id not in state.get("windows", {}):
        raise KeyError(
            f"mark_window: {window_id!r} is not a window in window_plan.json "
            f"(known: {sorted(state.get('windows', {}))}). If this is a burst "
            f"id, the caller should be using mark_burst()."
        )
    state["windows"][window_id][step] = status
    state["last_updated"] = datetime.now().isoformat()
    if error:
        state["errors"].append({
            "window": window_id, "step": step,
            "error": error, "time": datetime.now().isoformat()
        })
    _save(match_dir, state)
    return state


def mark_burst(match_dir: str, state: dict, burst_id: str,
               step: str, status: str, error: str = None) -> dict:
    """Mark a burst step as complete/failed/skipped.

    Unlike windows, bursts ARE minted here: the confirmation queue decides at
    run time which events get a high-fps re-run, so the id cannot come from
    the plan. They live in their own namespace so nothing that walks
    state["windows"] -- pending_windows, print_progress, the --force resets --
    can mistake one for an analysis window.
    """
    if step not in BURST_STEPS:
        raise ValueError(
            f"mark_burst: {step!r} is not a burst step {BURST_STEPS}."
        )
    bursts = state.setdefault("bursts", {})
    if burst_id not in bursts:
        bursts[burst_id] = {s: "pending" for s in BURST_STEPS}
    bursts[burst_id][step] = status
    state["last_updated"] = datetime.now().isoformat()
    if error:
        state["errors"].append({
            "burst": burst_id, "step": step,
            "error": error, "time": datetime.now().isoformat()
        })
    _save(match_dir, state)
    return state


def mark_result(match_dir: str, state: dict, item_id: str,
                step: str, status: str, error: str = None) -> dict:
    """Record a batch result in the namespace its step belongs to.

    The single place that decides whether a batch custom_id names a window or
    a burst. collect_results used to assume "window" for everything, which is
    how burst ids reached mark_window and became windows carrying a pending,
    payable 3a. Keep this the only implementation of that decision.
    """
    fn = mark_burst if step in BURST_STEPS else mark_window
    return fn(match_dir, state, item_id, step, status, error)


def reconcile_with_plan(match_dir: str, state: dict, plan_window_ids) -> dict:
    """Make state["windows"] hold exactly the windows window_plan.json names.

    Call once per run, immediately after the state is loaded. Three repairs,
    all of state written by builds where mark_window minted identity:

      * entries absent from the plan are burst records in the wrong
        namespace -- moved to state["bursts"] with their burst-step statuses
        intact, so completed burst work is never re-paid;
      * burst-only steps left on genuine window records are dropped;
      * plan windows missing from state are added as pending.
    """
    plan_ids = [str(w) for w in plan_window_ids]
    if not plan_ids:
        raise ValueError(
            "reconcile_with_plan: window_plan.json named no windows. Refusing "
            "to reconcile -- every existing window would be treated as an "
            "orphan and moved out of the analysis namespace."
        )
    known   = set(plan_ids)
    windows = state.setdefault("windows", {})
    bursts  = state.setdefault("bursts", {})

    orphans = [wid for wid in list(windows) if wid not in known]
    for wid in orphans:
        rec    = windows.pop(wid)
        merged = bursts.get(wid, {})
        for s in BURST_STEPS:
            if merged.get(s) in (None, "pending") and rec.get(s):
                merged[s] = rec[s]
            merged.setdefault(s, "pending")
        bursts[wid] = merged

    stripped = 0
    for rec in windows.values():
        for s in BURST_STEPS:
            if rec.pop(s, None) is not None:
                stripped += 1

    missing = [wid for wid in plan_ids if wid not in windows]
    for wid in missing:
        windows[wid] = {s: "pending" for s in WINDOW_STEPS}

    if orphans or missing or stripped:
        if orphans:
            print(f"  [STATE] Reconciled with window_plan.json: moved "
                  f"{len(orphans)} burst record(s) out of the window "
                  f"namespace ({', '.join(sorted(orphans)[:4])}"
                  f"{'...' if len(orphans) > 4 else ''}).")
        if stripped:
            print(f"  [STATE] Dropped {stripped} burst-only step entr(ies) "
                  f"from window records.")
        if missing:
            print(f"  [STATE] Added {len(missing)} plan window(s) absent from "
                  f"state: {', '.join(missing[:6])}"
                  f"{'...' if len(missing) > 6 else ''}.")
        _save(match_dir, state)
    return state


def mark_step(match_dir: str, state: dict, step: str,
              status: str, error: str = None) -> dict:
    """Mark a pipeline step as complete/failed/skipped."""
    state["steps"][step] = status
    state["last_updated"] = datetime.now().isoformat()
    if error:
        state["errors"].append({
            "step": step, "error": error,
            "time": datetime.now().isoformat()
        })
    _save(match_dir, state)
    return state


def is_window_done(state: dict, window_id: str, step: str) -> bool:
    return state.get("windows", {}).get(window_id, {}).get(step) == "complete"


def is_step_done(state: dict, step: str) -> bool:
    return state.get("steps", {}).get(step) == "complete"


def pending_windows(state: dict, step: str, include_failed: bool = False) -> list:
    """Return window IDs that still need a given step."""
    done = {"complete", "skipped"}
    if not include_failed:
        done.add("failed")
    return [wid for wid, steps in state.get("windows", {}).items()
            if steps.get(step) not in done]


def failed_windows(state: dict, step: str) -> list:
    """Return window IDs where a given step has failed."""
    return [wid for wid, steps in state.get("windows", {}).items()
            if steps.get(step) == "failed"]


def print_progress(state: dict):
    """Print a summary of pipeline progress."""
    windows  = state.get("windows", {})
    total    = len(windows)
    print(f"\n  Pipeline: {state.get('match','?')} ({state.get('quality','?')})")
    print(f"  Started:  {state.get('started','?')[:19]}")
    print()
    for step in WINDOW_STEPS:
        done    = sum(1 for w in windows.values() if w.get(step) == "complete")
        skipped = sum(1 for w in windows.values() if w.get(step) == "skipped")
        failed  = sum(1 for w in windows.values() if w.get(step) == "failed")
        pending = total - done - skipped - failed
        bar     = "#" * done + "." * pending
        print(f"  {step:<14} {bar} {done}/{total} "
              + (f"[{skipped} skipped] " if skipped else "")
              + (f"[{failed} FAILED] " if failed else ""))
    print()
    for step in PIPELINE_STEPS:
        status = state.get("steps", {}).get(step, "pending")
        icon   = "[OK]" if status == "complete" else "[FAIL]" if status == "failed" else "-"
        print(f"  {icon} {step}")
    bursts = state.get("bursts", {})
    if bursts:
        print()
        for step in BURST_STEPS:
            done   = sum(1 for b in bursts.values() if b.get(step) == "complete")
            failed = sum(1 for b in bursts.values() if b.get(step) == "failed")
            print(f"  {step:<14} {done}/{len(bursts)} bursts"
                  + (f" [{failed} FAILED]" if failed else ""))
    if state.get("errors"):
        print(f"\n  Errors: {len(state['errors'])}")
        for e in state["errors"][-3:]:
            print(f"    {e.get('window','?')}/{e.get('step','?')}: {e.get('error','?')[:60]}")


def store_batch_id(match_dir: str, state: dict, key: str, batch_id: str) -> dict:
    state["batch_ids"][key] = batch_id
    state["last_updated"] = datetime.now().isoformat()
    _save(match_dir, state)
    return state


def _save(match_dir: str, state: dict):
    path = os.path.join(match_dir, STATE_FILE)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(stamp_schema_version(state, "pipeline_state"), f, indent=2)


if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        print("Usage: python pipeline_state.py [MATCH_DIR]")
        sys.exit(1)
    state = load_state(sys.argv[1])
    if state:
        print_progress(state)
    else:
        print("No pipeline_state.json found in this directory.")
