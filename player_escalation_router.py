"""
player_escalation_router.py

Builds the player-action escalation queue. This is SEPARATE from the main
confirmation_queue.json (which handles goals, transitions, GK actions, etc).

Player-action escalations confirm individual technical details that cannot
be resolved at 1fps:
    receiving_orientation
    pre_receive_scan
    first_touch_direction
    foot_used
    aerial_duel_contact

Cap: 5 items per match. Independent from the main 10-item cap.

Run order:
    After Step 3e (programmatic merge) writes all *_merged.json files
    Before Step 3i (hybrid frame-rate confirmation) main escalation run
    Before Step 3k (deep skill metrics)

The confirmation prompts use prompts/05_player_action_confirmation.md.
Use the same extract_segment() function from the main escalation pipeline
(it already reads container_profile.json and handles seek/ffmpeg routing).
"""

import json
import os
import glob


ELIGIBLE_CATEGORIES = {
    "receiving_orientation",
    "pre_receive_scan",
    "first_touch_direction",
    "foot_used",
    "aerial_duel_contact",
}

FPS_BY_CATEGORY = {
    "receiving_orientation": 3,
    "pre_receive_scan":      3,
    "foot_used":             3,
    "first_touch_direction": 5,
    "aerial_duel_contact":   5,
}

CAP_PLAYER_ACTIONS = 5

# Where the confirmation prompt template lives, relative to this file.
PROMPT_TEMPLATE = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "prompts", "05_player_action_confirmation.md")


def escalation_is_available(match_dir: str) -> tuple:
    """(can this step do anything, why not).

    Step 3i has never produced a confirmation on any run, and nothing said
    so: the phase is wrapped in `except Exception: print(... non-blocking,
    continuing)`, so a fatal misconfiguration reads as one warning line in a
    long log. Three things are wrong with it, and each is checkable.

    1. PROMPT_TEMPLATE does not exist. build_player_action_confirmation_prompt
       opens it unconditionally, so the phase raises on its first item. The
       path it used also resolved to <repo>/../prompts, outside the repo
       entirely, so creating the directory in the obvious place would not
       have helped.

    2. ELIGIBLE_CATEGORIES accepted 1 of 45 queued items on the Gorleston
       match. The player agent writes its own vocabulary -- movement_off_ball,
       hold_up_play, aerial_ability -- and the five categories here appear
       almost never.

    3. Worse, and fatal: merge_player_confirmation_into_window writes back
       into individual_observations, matching on player + timestamp +
       action_category. Not one of the 265 individual_observations on that
       match used an eligible category. The overlap between the two
       vocabularies is empty, so even a confirmation that came back
       "confirmed" would match no observation and be discarded.

    Until 1 and 3 are fixed the step cannot succeed, so it is gated off here
    rather than left to fail quietly inside a broad except.
    """
    if not os.path.exists(PROMPT_TEMPLATE):
        return (False, "confirmation prompt template is missing: %s"
                       % PROMPT_TEMPLATE)

    present = observed_categories(match_dir)
    if present and not (present & ELIGIBLE_CATEGORIES):
        return (False,
                "no individual_observation uses an eligible category, so a "
                "confirmation could never be written back. observed: %s; "
                "eligible: %s"
                % (", ".join(sorted(present)[:6]),
                   ", ".join(sorted(ELIGIBLE_CATEGORIES))))
    return (True, "")


def observed_categories(match_dir: str) -> set:
    """Every action_category present in individual_observations."""
    found = set()
    for path in sorted(glob.glob(os.path.join(
            match_dir, "agent_logs", "*_merged.json"))):
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, ValueError):
            continue
        for obs in data.get("individual_observations") or []:
            cat = obs.get("action_category")
            if cat:
                found.add(cat)
    return found


def _parse_mmss(s):
    """'34m12s' -> 2052 seconds. Returns None on parse failure."""
    if not s or "m" not in s:
        return None
    try:
        mm, rest = s.split("m", 1)
        ss = rest.rstrip("s")
        return int(mm) * 60 + int(ss)
    except (ValueError, AttributeError):
        return None


def _seconds_to_mmss(sec):
    if sec is None or sec < 0:
        return None
    m, s = divmod(int(sec), 60)
    return f"{m:02d}m{s:02d}s"


def build_player_escalation_queue(match_dir):
    """
    Reads every *_merged.json from agent_logs/, collects player_escalation_queue
    entries, validates and prioritises, applies cap, writes
    player_escalation_queue.json at match_dir.

    Returns the queue list.
    """
    logs_dir = os.path.join(match_dir, "agent_logs")
    merged_files = sorted(glob.glob(os.path.join(logs_dir, "*_merged.json")))

    all_items = []
    skipped_ineligible = []

    for path in merged_files:
        with open(path) as f:
            data = json.load(f)
        items = data.get("player_escalation_queue", [])
        for item in items:
            cat = item.get("action_category")
            if cat not in ELIGIBLE_CATEGORIES:
                skipped_ineligible.append({
                    "source_file":     os.path.basename(path),
                    "action_category": cat,
                    "reason":          "ineligible category",
                })
                continue

            # Default fps if agent didn't specify
            if not item.get("escalation_target_fps"):
                item["escalation_target_fps"] = FPS_BY_CATEGORY.get(cat, 3)

            # Default rerun window if agent didn't specify
            if not item.get("rerun_window_start") or not item.get("rerun_window_end"):
                ts_sec = _parse_mmss(item.get("timestamp"))
                if ts_sec is not None:
                    # Clamp at the start of the match. _seconds_to_mmss
                    # returns None for a negative value, so an observation at
                    # 00m00s -- 45% of them on the Gorleston match, because
                    # the player agent stamps that when it cannot place the
                    # moment -- produced rerun_window_start: null and a burst
                    # extraction with no start.
                    item["rerun_window_start"] = _seconds_to_mmss(max(0, ts_sec - 2))
                    item["rerun_window_end"]   = _seconds_to_mmss(ts_sec + 2)

            item["source_window"] = data.get("window")
            item["source_file"]   = os.path.basename(path)
            all_items.append(item)

    # Sort: high priority first, then by source_window order
    priority_rank = {"high": 0, "medium": 1, "low": 2}
    all_items.sort(key=lambda i: (
        priority_rank.get(i.get("priority", "medium"), 1),
        i.get("source_window") or "",
    ))

    # Apply cap
    accepted = all_items[:CAP_PLAYER_ACTIONS]
    skipped_cap = all_items[CAP_PLAYER_ACTIONS:]

    output = {
        "cap":                          CAP_PLAYER_ACTIONS,
        "total_collected":              len(all_items),
        "accepted_count":               len(accepted),
        "skipped_count_cap":            len(skipped_cap),
        "skipped_count_ineligible":     len(skipped_ineligible),
        "accepted":                     accepted,
        "skipped_cap":                  [
            {**i, "skip_reason": "cap_exceeded"} for i in skipped_cap
        ],
        "skipped_ineligible":           skipped_ineligible,
    }

    out_path = os.path.join(match_dir, "player_escalation_queue.json")
    with open(out_path, "w") as f:
        json.dump(output, f, indent=2)

    print(f"[player_escalation_router] Wrote {out_path}")
    print(f"  Collected: {len(all_items)}")
    print(f"  Accepted:  {len(accepted)} (cap {CAP_PLAYER_ACTIONS})")
    print(f"  Skipped by cap:        {len(skipped_cap)}")
    print(f"  Skipped as ineligible: {len(skipped_ineligible)}")

    return accepted


def merge_player_confirmation_into_window(match_dir, confirmation_result):
    """
    After a player-action confirmation prompt returns, merge the result
    back into the appropriate merged window JSON. Updates the matching
    individual_observation entry by timestamp + player.

    confirmation_result should be the parsed JSON from the prompt response.
    """
    if confirmation_result.get("status") != "confirmed":
        # Inconclusive -- leave the original 1fps observation untouched
        return False

    timestamp = confirmation_result.get("timestamp")
    player = confirmation_result.get("player")
    action_category = confirmation_result.get("action_category")

    logs_dir = os.path.join(match_dir, "agent_logs")
    merged_files = sorted(glob.glob(os.path.join(logs_dir, "*_merged.json")))

    for path in merged_files:
        with open(path) as f:
            data = json.load(f)
        updated = False
        for obs in data.get("individual_observations", []):
            if (
                obs.get("timestamp") == timestamp
                and obs.get("player") == player
                and obs.get("action_category") == action_category
            ):
                obs["evidence_tier"] = "escalated_confirmation"
                obs["confidence"] = "high" if confirmation_result.get("confidence_after_rerun", 0) >= 0.75 else "medium"
                obs["confirmed_detail"] = confirmation_result.get("confirmed_detail")
                obs["recommended_report_wording"] = confirmation_result.get("recommended_report_wording")
                updated = True
        if updated:
            with open(path, "w") as f:
                json.dump(data, f, indent=2)
            return True
    return False


if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        print("Usage: python player_escalation_router.py [MATCH_DIR]")
        sys.exit(1)
    build_player_escalation_queue(sys.argv[1])
