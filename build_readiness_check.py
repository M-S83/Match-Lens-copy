"""
build_readiness_check.py -- Match Lens pipeline gate before Step 4.

Reads all pipeline output files and determines whether the pipeline
is ready to write reports. Writes report_readiness.json.

Step 4 must not run if report_ready is false.

Usage:
    python build_readiness_check.py [MATCH_DIR]
"""

import json
import os
import sys
from pipeline_accessors import (get_source_limitations_note,
                                resolve_side_from_team_name)
from pipeline_schemas import stamp_schema_version


def build_readiness_check(match_dir: str) -> bool:

    def load(fname):
        p = os.path.join(match_dir, fname)
        if not os.path.exists(p):
            return None
        with open(p, encoding="utf-8") as f:
            return json.load(f)

    boundaries    = load("match_boundaries.json")
    config        = load("match_config.json")
    window_plan   = load("window_plan.json")
    ground_truth  = load("ground_truth_check.json")
    summary       = load("running_summary.json")
    rerun_q       = load("rerun_queue.json")
    cq            = load("confirmation_queue.json") or {"total": 0, "skipped": 0}
    source_prof   = load("source_profile.json")
    result_gates  = load("result_family_gates.json")
    deep_metrics  = load("deep_skill_metrics.json")

    blocking = []
    warnings = []

    # Source type is read here (not just in the source-profile section below)
    # so the ground-truth check can apply a source-aware relaxation.
    source_type_early = (source_prof or {}).get("source_type", "unknown")

    # -- Boundary confidence ---------------------------------------------------
    bc = {}
    if boundaries:
        for k, v in boundaries.get("boundaries", {}).items():
            bc[k] = v.get("confidence", 0)
    boundary_ok = bool(bc) and all(v >= 0.8 for v in bc.values())
    if not boundary_ok:
        low = [k for k, v in bc.items() if v < 0.8] if bc else ["boundaries file missing"]
        blocking.append(f"Low boundary confidence: {low}")

    # -- Config verification ---------------------------------------------------
    config_verified   = bool(config and config.get("verified"))
    enrichment_level  = (config or {}).get("enrichment_level", "identity_only")
    player_id_ceiling = (config or {}).get("player_id_ceiling", "tentative")
    if not config_verified:
        blocking.append("match_config.json not verified -- complete Step 1d")

    # -- Windows ---------------------------------------------------------------
    planned  = (window_plan or {}).get("total_windows", 0)
    complete = (summary or {}).get("windows_complete", 0)
    windows_ok = planned > 0 and complete == planned
    if not windows_ok:
        blocking.append(f"Windows incomplete: {complete}/{planned}")

    # -- Ground truth ----------------------------------------------------------
    # A missed event never blocks, on any source type. The reasoning is in
    # the block below and it is source-independent: at 1fps a ball-following
    # camera misses touchline events whether it is Veo or broadcast.
    #
    # This comment previously ended "Veo runs keep the strict gate", which
    # described the earlier source_type_early == "broadcast_fixed_wide"
    # branch. The code was corrected and the header was not, so it spent a
    # while asserting a gate that had already been removed, directly above
    # the code that does not implement it.
    #
    # The one blocking case is events_checked == 0: the check did not run.
    gt_total  = (ground_truth or {}).get("total",
                  (ground_truth or {}).get("events_checked", 0))
    gt_missed = (ground_truth or {}).get("missed", "file missing")

    gt_passed = bool(ground_truth and isinstance(gt_missed, int) and gt_missed == 0)

    if not gt_passed:
        # Goals, cards and substitutions come from match_config, which is
        # operator-entered from the official fixture record. They are known
        # facts, not claims requiring visual proof. Whether the footage also
        # happened to show them is a measure of the FOOTAGE, not of the
        # analysis -- and on a ball-following camera at 1fps the answer is
        # usually "no", by design rather than by failure.
        #
        # Blocking reports on it was the wrong shape twice over: it withheld
        # analysis the operator facts already underwrite, and it spent event-
        # agent money re-deriving a timeline that was never in doubt. It is
        # now recorded as a corroboration rate, which is genuinely useful --
        # it tells you how much of the discrete-event layer the camera can
        # see -- and it never blocks.
        #
        # The genuine pipeline failure remains blocking: events_checked == 0
        # means the check never ran or its file is missing, which is a
        # different thing from the footage not showing an event.
        if isinstance(gt_missed, int) and gt_total > 0:
            _seen = gt_total - gt_missed
            warnings.append(
                f"Ground truth: footage independently corroborated "
                f"{_seen}/{gt_total} known event(s). Operator facts remain "
                f"authoritative; this is a measure of what the camera saw, "
                f"not of analysis quality."
            )
        else:
            blocking.append(
                f"Ground truth check did not run (events_checked={gt_total}) "
                f"-- the file is missing or the step failed."
            )

    # -- Data gaps (warning, not blocking) ------------------------------------
    data_gap_windows = (summary or {}).get("data_gap_windows", [])
    if data_gap_windows:
        blocking.append(
            f"Data gap windows detected: {data_gap_windows} "
            f"-- review before reporting or accept reduced confidence"
        )

    # -- Unresolvable frames ---------------------------------------------------
    unresolvable = sum(
        1 for i in (rerun_q or {}).get("rerun_queue", [])
        if i.get("status") == "unresolvable"
    )

    # -- Source profile --------------------------------------------------------
    source_profile_present   = bool(source_prof)
    source_type              = (source_prof or {}).get("source_type", "unknown")
    # O17: None, not 0.0. A missing profile or a profile with no confidence
    # field has not been measured, and 0.0 reads as a genuine zero-confidence
    # classification -- published alongside report_ready: true.
    source_confidence        = (source_prof or {}).get("classification_confidence")
    source_profile_confident = (source_confidence is not None
                                and source_confidence >= 0.6)
    split_aware              = (source_prof or {}).get("split_aware", False)
    # Fix 38: broadcast source_profile.json stores the limitation under "notes",
    # not "source_limitations_note". Prefer either-key so broadcast runs no longer
    # write an empty source-limitation string into report_readiness.json.
    sp = source_prof or {}
    source_limitations       = get_source_limitations_note(sp)
    downgraded_families      = [
        f for f, s in (result_gates or {}).get("gates", {}).items()
        if s == "downgraded"
    ]
    # O1: this was `suppressed_families = []` with the comment "no suppressed
    # families in this pipeline". That comment is false -- source_profiler
    # assigns "suppressed" (source_profiler.py:165, :196) and reads it back at
    # :212. So the one artefact whose job is to state what could NOT be
    # measured asserted that nothing was suppressed, on every run, without
    # looking. Computed the same way as downgraded_families directly above.
    suppressed_families = [
        f for f, s in (result_gates or {}).get("gates", {}).items()
        if s == "suppressed"
    ]

    # O17: an absent source profile gave classification_confidence 0.0, which
    # is indistinguishable from a real zero-confidence classification and was
    # published as a number. None means "not measured"; the guard below now
    # blocks on unknown as well as low, because a confidence nobody read is
    # not evidence the classification was good.
    if source_prof and source_confidence is None:
        blocking.append(
            "source_profile.json records no classification_confidence -- "
            "cannot tell whether source_type "
            f"{source_type!r} was classified or defaulted. "
            "Review source_profile.json before reporting."
        )
    elif source_prof and not source_profile_confident:
        blocking.append(
            f"Source classification confidence low ({source_confidence:.2f}) "
            f"-- source_type defaulted to {source_type}. "
            f"Review source_profile.json before reporting."
        )

    report_ready = len(blocking) == 0

    # -- Report modules available ----------------------------------------------
    # All three are always available -- which ones to generate is a per-job decision
    modules = {
        "tactical":   True,
        "opposition": True,
        "moments":    True,
    }

    readiness = {
        "report_ready":             report_ready,
        "boundary_confidence":      bc,
        "boundary_confidence_ok":   boundary_ok,
        "team_config_verified":     config_verified,
        "enrichment_level":         enrichment_level,
        "player_id_ceiling":        player_id_ceiling,
        "event_validation_passed":  gt_passed,
        "windows_planned":          planned,
        "windows_complete":         complete,
        "windows_ok":               windows_ok,
        "unresolvable_frames":      unresolvable,
        "data_gap_windows":         data_gap_windows,
        "source_type":              source_type,
        "source_classification_confidence": source_confidence,
        "source_profile_present":   source_profile_present,
        "source_profile_confident": source_profile_confident,
        "split_aware":              split_aware,
        "suppressed_families":      suppressed_families,
        "downgraded_families":      downgraded_families,
        "source_limitations":       source_limitations,
        "confirmation_total":       cq.get("total", 0),
        "confirmation_skipped":     cq.get("skipped_by_cap", cq.get("skipped", 0)),
        "confirmation_goals":       cq.get("goals", 0),
        "goals_uncapped":           cq.get("goals_uncapped", False),
        "report_modules_available": modules,
        "blocking_issues":          blocking,
        "warnings":                 warnings,
    }

    out_path = os.path.join(match_dir, "report_readiness.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(stamp_schema_version(readiness, "report_readiness"), f, indent=2)

    # -- Terminal output -------------------------------------------------------
    status = "[OK] READY" if report_ready else "[X]  NOT READY"
    print(f"\n{'-'*55}")
    print(f"  {status} -- report_readiness.json written")
    print(f"{'-'*55}")

    if blocking:
        print("  Blocking issues:")
        for issue in blocking:
            print(f"    [FAIL] {issue}")
    else:
        print(f"  Enrichment level : {enrichment_level}")
        print(f"  Player ID ceiling: {player_id_ceiling}")
        print(f"  Windows          : {complete}/{planned}")
        print(f"  Unresolvable     : {unresolvable} frames")
        print(f"  Confirmation     : {cq.get('total',0)} items | {cq.get('skipped_by_cap', cq.get('skipped',0))} skipped")
        if data_gap_windows:
            print(f"  [!]  Data gap windows: {data_gap_windows}")

    print(f"{'-'*55}\n")

    # Write confidence_reliability_report.json
    cq_data = cq or {}
    reliability = {
        "match":                     (config or {}).get("match", "unknown"),
        "source_type":               source_type,
        "classification_confidence": source_confidence,
        "split_aware":               split_aware,
        "visibility_scores":         (source_prof or {}).get("visibility_scores", {}),
        # Fix 38: see line ~122 for rationale.
        "source_limitations_note":   get_source_limitations_note(source_prof or {}),
        "visibility_based_limitations": source_limitations,
        "suppressed_families":       suppressed_families,
        "downgraded_families":       downgraded_families,
        "result_family_gates":       (result_gates or {}).get("gates", {}),
        "escalation_summary": {
            "total_tagged":        cq_data.get("total", 0),
            "goals":               cq_data.get("goals", 0),
            "goals_uncapped":      cq_data.get("goals_uncapped", False),
            "high_priority_other": cq_data.get("high_priority_other", 0),
            "medium_priority":     cq_data.get("medium_priority", 0),
            "skipped_by_cap":      cq_data.get("skipped_by_cap", 0),
            "skipped_ineligible":  cq_data.get("skipped_ineligible", 0),
        },
        "data_gap_windows":   data_gap_windows,
        "unresolvable_frames": unresolvable,
        "report_ready":        report_ready,
        "blocking_issues":     blocking,
        "generated_at":        __import__("datetime").datetime.now().isoformat(),
        "deep_skill_metrics_summary": {
            "available":           deep_metrics is not None,
            "total_metrics":       (deep_metrics or {}).get("total_metrics", 0),
            "active_metrics":      (deep_metrics or {}).get("active_metrics", 0),
            # O17: None when there are no metrics. 0.0 here reported "every
            # metric came back at zero confidence" for a step that had not
            # run, in the file whose entire subject is confidence.
            "suppressed_metrics":  (deep_metrics or {}).get("suppressed_metrics", []),
            "avg_confidence":      (deep_metrics or {}).get("avg_confidence"),
        },
    }
    rel_path = os.path.join(match_dir, "confidence_reliability_report.json")
    with open(rel_path, "w", encoding="utf-8") as f:
        json.dump(stamp_schema_version(reliability, "confidence_reliability_report"), f, indent=2)
    print(f"  confidence_reliability_report.json written")

    if deep_metrics:
        dm = deep_metrics
        _avg = dm.get("avg_confidence")
        print(f"  Metrics:         {dm.get('active_metrics',0)} active | "
              f"{len(dm.get('suppressed_metrics',[]))} suppressed | avg conf: "
              f"{'unavailable' if _avg is None else _avg}")
    else:
        print("  [!]  deep_skill_metrics.json not found -- run Step 3k before Step 4")

    if not report_ready:
        print("  Step 4 is blocked. Resolve issues above and re-run this script.")

    return report_ready



def validate_shirt_numbers(match_dir: str) -> dict:
    """
    Cross-check individual_observation shirt numbers against confirmed lineups.
    Flags any #-numbers that don't appear in either team's lineup.
    Returns dict with: unmatched, home_shirts, away_shirts, obs_numbers.
    """
    mc_path  = os.path.join(match_dir, "match_config.json")
    rs_path  = os.path.join(match_dir, "running_summary.json")
    if not os.path.exists(mc_path) or not os.path.exists(rs_path):
        return {"skipped": True, "reason": "match_config or running_summary missing"}

    with open(mc_path, encoding="utf-8") as f:  mc = json.load(f)
    with open(rs_path, encoding="utf-8")  as f: rs = json.load(f)

    # Build confirmed shirt sets from lineups
    home_shirts, away_shirts = set(), set()
    for lineup in mc.get("lineups", []):
        _t = lineup.get("team", {})
        team_name = _t.get("name", "") if isinstance(_t, dict) else str(_t)
        for player in lineup.get("startXI", []) + lineup.get("substitutes", []):
            num = player.get("player", {}).get("number")
            if num:
                # Inline name comparison replaced by the canonical accessor, so
                # there is one implementation of "which side is this team".
                try:
                    _side = resolve_side_from_team_name(team_name, mc)
                except ValueError:
                    _side = "away"
                if _side == "home":
                    home_shirts.add(str(num))
                else:
                    away_shirts.add(str(num))

    all_shirts = home_shirts | away_shirts

    # Check shirt numbers in individual_observations
    import re as _re
    obs_numbers = set()
    unmatched = []
    for obs in rs.get("individual_observations", []):
        player = obs.get("player", "") or ""
        nums = _re.findall(r"#(\d+)", player)
        for n in nums:
            obs_numbers.add(n)
            if all_shirts and n not in all_shirts:
                unmatched.append({"player": player, "number": n,
                                   "obs": obs.get("observation", "")[:50]})

    return {
        "skipped":      False,
        "home_shirts":  sorted(home_shirts),
        "away_shirts":  sorted(away_shirts),
        "obs_numbers":  sorted(obs_numbers),
        "unmatched":    unmatched,
        "unmatched_count": len(unmatched),
        "note": ("Pass network sequences use free-text chain notation (#N) which "
                 "may have misread multi-digit shirt numbers at 1fps. "
                 f"Unmatched: {sorted(set(u['number'] for u in unmatched))}")
                 if unmatched else "All observed shirt numbers match confirmed lineups.",
    }


if __name__ == "__main__":
    match_dir = sys.argv[1] if len(sys.argv) > 1 else input("Match directory path: ").strip()
    if not os.path.isdir(match_dir):
        print(f"Error: '{match_dir}' is not a valid directory.")
        sys.exit(1)
    ready = build_readiness_check(match_dir)
    sys.exit(0 if ready else 1)
