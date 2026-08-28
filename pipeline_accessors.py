"""Canonical accessors for pipeline data structures.

Single source of truth for reading fields that have historical name drift.
Every reader in the pipeline should route through these accessors instead
of calling `.get("foo", .get("bar"))` inline. The point is to make field
aliases a one-line change in this file rather than a hunt across the
codebase.

Conventions
-----------
- Accessor names describe the concept (e.g. ``window_id``).
- The first key tried is whatever the live producer actually writes;
  fallbacks exist only to tolerate legacy or hand-edited files.
- Each accessor documents who writes the canonical key and why other
  aliases exist.

Adding a new accessor: keep it short, declarative, and pure. No I/O,
no logging, no side effects. If you find yourself wanting to log a
warning when the fallback fires, do it once at the call site that
matters, not inside the accessor.
"""


def get_window_id(w: dict) -> str:
    """Return the canonical window identifier.

    `window_plan.py` (line ~262) writes this as ``agent_id`` — a two-digit
    zero-padded sequence number, e.g. ``"07"``. It does NOT write a
    ``window_id`` key. The ``window_id`` fallback exists only for legacy
    window dicts or hand-edited plans; no live writer in the current
    pipeline produces it.

    Returns "" if neither key is present (caller must handle).
    """
    return w.get("agent_id") or w.get("window_id") or ""


def get_source_limitations_note(profile: dict) -> str:
    """Return the source limitations note from a source_profile dict.

    `source_profiler.py` writes this as ``source_limitations_note`` —
    a one-sentence description of the main limitation of the footage type.

    Three legacy aliases are tolerated for hand-edited or older profile
    files (``notes``, ``source_limitations``, ``limitations_note``);
    no live writer in the current pipeline produces them. Two scripts
    (generate_flagged_moments, generate_pass_network) historically read
    only the legacy aliases, so their reports shipped without the source
    caveat — see AUDIT.md F3.

    Returns "" if no limitation key is present.
    """
    return (profile.get("source_limitations_note")
            or profile.get("notes")
            or profile.get("source_limitations")
            or profile.get("limitations_note")
            or "")


def get_marking(record: dict):
    """Return the set piece marking value from a set piece record.

    Canonical key is ``marking_system`` — written by both
    ``setpiece_writeback.apply_burst_to_record`` (via BURST_CONFIRMS) and,
    after F4, by ``accumulator.validate_set_piece``.

    ``marking`` is the legacy alias written by older accumulator versions
    and by some 1fps structural agents. Tolerated as a fallback so
    historical running_summary.json files still read correctly.

    Returns None if neither key is present. Callers that need a categorical
    default should do ``get_marking(sp) or "unknown"`` — this keeps the
    distinction between "field absent" and "field present, value empty".

    See AUDIT.md F4.
    """
    return record.get("marking_system") or record.get("marking") or None


def get_moment_time(moment: dict) -> str:
    """Return the time string from a ``key_moments`` entry.

    Canonical key is ``minute`` (Fix 32a schema) -- the value the current
    structural agent emits. ``timestamp`` is the legacy alias kept by older
    merged files and by set-piece records.

    Both forms parse: ``ground_truth.parse_timestamp_to_seconds`` accepts
    ``"18m47s"`` and ``"18:47"`` alike, so callers do not need to know which
    key supplied the value.

    Returns "" when neither key is present, so callers can filter falsy values
    rather than guarding every bracket access.

    See AUDIT-2026-08.md A4: ``ground_truth.py`` read ``timestamp`` only, so it
    received "" for every moment and scored every known event as missed.
    """
    return moment.get("minute") or moment.get("timestamp") or ""


def get_formation_home(record: dict):
    """Return the home team's formation string from a structural agent dict.

    Canonical: ``formation.home`` (Fix 32a schema, written by current
    structural agents). Legacy fallback: ``formation.shape_in_possession``
    — pre-Fix-32a Veo runs wrote a single shape string here, usually
    describing the focus/home team's in-possession shape. This fallback
    is approximate on legacy single-side data.

    Returns None if neither key is present.
    """
    f = record.get("formation") or {}
    return f.get("home") or f.get("shape_in_possession") or None


def get_formation_away(record: dict):
    """Return the away team's formation string from a structural agent dict.

    Canonical: ``formation.away``. Legacy fallback:
    ``formation.shape_out_of_possession`` — pre-Fix-32a Veo runs sometimes
    wrote the opposition shape here. The mapping IP→home / OOP→away is
    approximate; legacy files often won't have OOP populated at all.

    Returns None if neither key is present.
    """
    f = record.get("formation") or {}
    return f.get("away") or f.get("shape_out_of_possession") or None


def get_window_start_seconds(w: dict) -> float:
    """Return the canonical window start time in seconds.

    `window_plan.py` writes this as ``start_s``. The legacy ``start_seconds``
    alias is tolerated for any historical window_plan.json files written
    under the old schema; no live writer in the current pipeline produces it.

    Returns 0.0 if neither key is present (caller must handle).
    """
    v = w.get("start_s")
    if v is None:
        v = w.get("start_seconds", 0.0)
    return float(v)


def get_window_end_seconds(w: dict) -> float:
    """Return the canonical window end time in seconds.

    `window_plan.py` writes this as ``end_s``. The legacy ``end_seconds``
    alias is tolerated for any historical window_plan.json files written
    under the old schema; no live writer in the current pipeline produces it.

    Returns 0.0 if neither key is present (caller must handle).
    """
    v = w.get("end_s")
    if v is None:
        v = w.get("end_seconds", 0.0)
    return float(v)


def get_match_id(match_dir: str, mc: dict | None = None) -> str:
    """Return the canonical match identifier.

    Reads ``mc["match"]`` if available, otherwise falls back to
    ``os.path.basename(match_dir)``. The fallback exists for two
    legitimate cases:

    1. ``match_config.json`` has been written but its ``match`` key is
       missing or empty (data problem — caller should log a WARNING).
    2. ``match_config.json`` does not yet exist on disk because the
       caller runs early in the pipeline, before extract_match_details.py
       has produced it (expected — caller should log INFO).

    Callers are responsible for logging if and how the fallback firing
    should be surfaced; this accessor stays pure (no I/O, no logging,
    no side effects) per the module's stated principles.

    Returns the basename of match_dir if mc is None or mc["match"] is
    missing/empty.
    """
    import os
    if mc and mc.get("match"):
        return mc["match"]
    return os.path.basename(match_dir)


# ── Team side ────────────────────────────────────────────────────────────────
#
# Historically this was read as `lineup.get("team_side", "")` in four places.
# NOTHING in the pipeline has ever written that key: match_config lineups carry
# {"team": {"name": ...}, "startXI", "substitutes"} and no more. The silent ""
# default meant `side == "home"` was never true, so on 2026-08-14 the Gorleston
# vs Tilbury run put all 32 players from both squads into the AWAY roster shown
# to the 3b player agent, and 176 of 223 observations were attributed to the
# wrong team -- in the prose as well as the label.
#
# These accessors therefore RAISE rather than default. The module principle is
# "no side effects"; raising is not a side effect, it is a pure function
# declining to invent an answer. A run that cannot tell the teams apart must
# stop, not produce fluent analysis of the wrong side.

_HOME_ALIASES = ("home", "home_kit", "home_team")
_AWAY_ALIASES = ("away", "away_kit", "away_team")


def normalise_side(value) -> str | None:
    """Map any home/away spelling used in the pipeline to 'home' or 'away'.

    Accepts the kit forms the vision agents emit ("home_kit"/"away_kit"), the
    bare forms ("home"/"away") and the team-name forms ("home_team"). Returns
    None for anything else, including None -- callers that require an answer
    should use resolve_side_from_team_name or resolve_team_side instead.
    """
    if not isinstance(value, str):
        return None
    v = value.strip().lower()
    if v in _HOME_ALIASES:
        return "home"
    if v in _AWAY_ALIASES:
        return "away"
    return None


def resolve_side_from_team_name(team_name: str, mc: dict) -> str:
    """Return 'home' or 'away' for a literal team name.

    Compares against mc["home_team"] / mc["away_team"], case- and
    whitespace-insensitively. Raises ValueError when the name matches neither,
    because guessing here is how an entire match gets attributed to the wrong
    side.
    """
    side = normalise_side(team_name)
    if side:
        return side
    name = (team_name or "").strip().lower()
    home = (mc.get("home_team") or "").strip().lower()
    away = (mc.get("away_team") or "").strip().lower()
    if name and name == home:
        return "home"
    if name and name == away:
        return "away"
    raise ValueError(
        f"Cannot resolve team side for {team_name!r}: it matches neither "
        f"home_team {mc.get('home_team')!r} nor away_team {mc.get('away_team')!r}."
    )


def resolve_team_side(lineup: dict, mc: dict) -> str:
    """Return 'home' or 'away' for a match_config lineup block.

    Prefers an explicit ``team_side`` when one is present and valid (no live
    writer produces it, but hand-authored configs may), otherwise derives the
    side from the team name. Raises ValueError when neither resolves.
    """
    explicit = normalise_side((lineup or {}).get("team_side"))
    if explicit:
        return explicit
    team = (lineup or {}).get("team")
    name = team.get("name", "") if isinstance(team, dict) else (team or "")
    return resolve_side_from_team_name(name, mc)


# ── Match clock vs video clock ───────────────────────────────────────────────
#
# The other recurring defect family. A match minute (match_config "elapsed",
# key_moments "minute") and a video second (window start_s/end_s, frame
# filenames) are different coordinate systems separated by the pre-match
# footage and the half-time break. Comparing one to the other without
# conversion has produced at least four separate bugs: calc_match_state
# (window_plan), the ground-truth check, the cost estimator's event-window
# count, and the event-window flag. Every comparison between an event time and
# a window time must route through here.

_BOUNDARY_KEYS = {
    "ko_1h":      ("ko_1h",      "ko_1h_seconds",      "ko_1h_s"),
    "ht_whistle": ("ht_whistle", "ht_whistle_seconds", "ht_s", "ht_whistle_s"),
    "ko_2h":      ("ko_2h",      "ko_2h_seconds",      "ko_2h_s"),
    "ft_whistle": ("ft_whistle", "ft_whistle_seconds", "ft_s", "ft_whistle_s"),
    "ko_et1":     ("ko_et1",     "ko_et1_seconds",     "ko_et1_s"),
    "ko_et2":     ("ko_et2",     "ko_et2_seconds",     "ko_et2_s"),
}


def get_kickoff_seconds(source: dict) -> dict:
    """Extract kickoff/whistle video-seconds from any boundary shape we write.

    Three shapes exist in the wild and all are read here:
      * match_boundaries.json  -> {"boundaries": {"ko_1h": {"seconds": N}, ...}}
      * set_boundaries.py      -> {"ko_1h_seconds": N, ...} (boundaries_override)
      * detect_boundaries.py   -> {"ko_1h_s": N, ...}

    Returns a dict with keys ko_1h / ht_whistle / ko_2h / ft_whistle / ko_et1 /
    ko_et2; values are floats, or None when that boundary is absent. Missing
    extra-time boundaries are normal; missing ko_1h is not, and callers that
    need it should check.
    """
    src = source or {}
    nested = src.get("boundaries") if isinstance(src.get("boundaries"), dict) else {}
    out = {}
    for canon, aliases in _BOUNDARY_KEYS.items():
        val = None
        entry = nested.get(canon)
        if isinstance(entry, dict) and entry.get("seconds") is not None:
            val = entry["seconds"]
        elif isinstance(entry, (int, float)):
            val = entry
        if val is None:
            for a in aliases:
                cand = src.get(a)
                if isinstance(cand, dict) and cand.get("seconds") is not None:
                    val = cand["seconds"]; break
                if isinstance(cand, (int, float)):
                    val = cand; break
        out[canon] = float(val) if val is not None else None
    return out


def match_minute_to_video_s(minute, ko: dict) -> float:
    """Convert a match-clock minute to a position in video seconds.

    ``ko`` is the dict returned by get_kickoff_seconds. Four-branch mapping so
    that second-half and extra-time minutes land on the right footage:

      minute <= 45   -> ko_1h + minute*60 (first-half stoppage folds forward
                        into the second half only if it would overshoot the
                        half-time whistle)
      minute <= 90   -> ko_2h + (minute-45)*60
      minute <= 105  -> ko_et1 + (minute-90)*60   (when ko_et1 is known)
      otherwise      -> ko_et2 + (minute-105)*60  (when ko_et2 is known)

    Raises TypeError for a non-numeric minute and ValueError when ko_1h is
    unknown, because a silent 0 here means every event lands on pre-match
    footage -- which is exactly how this family of bug has bitten before.
    """
    if isinstance(minute, bool) or not isinstance(minute, (int, float)):
        raise TypeError(f"match minute must be numeric, got {minute!r}")
    ko_1h = (ko or {}).get("ko_1h")
    if ko_1h is None:
        raise ValueError(
            "Cannot convert a match minute without ko_1h. Falling back to 0 "
            "would place every event in the pre-match footage."
        )
    ht    = (ko or {}).get("ht_whistle")
    ko_2h = (ko or {}).get("ko_2h")
    et1   = (ko or {}).get("ko_et1")
    et2   = (ko or {}).get("ko_et2")
    if ko_2h is None:
        ko_2h = ko_1h + 45 * 60

    if minute <= 45:
        vs = ko_1h + minute * 60
        if ht is not None and vs > ht:
            # First-half stoppage past the whistle: the footage for it is the
            # second half, not the break.
            return ko_2h + (minute - 45) * 60
        return vs
    if minute <= 90:
        return ko_2h + (minute - 45) * 60
    if minute <= 105 and et1 is not None:
        return et1 + (minute - 90) * 60
    if et2 is not None:
        return et2 + (minute - 105) * 60
    return ko_2h + (minute - 45) * 60


def video_s_to_match_minute(video_s, ko: dict) -> float:
    """Inverse of match_minute_to_video_s, to the nearest whole second.

    Returns match-clock minutes as a float. Positions inside the half-time
    break map to the half-time whistle's match minute, since no match clock
    runs there. Raises ValueError when ko_1h is unknown.
    """
    if isinstance(video_s, bool) or not isinstance(video_s, (int, float)):
        raise TypeError(f"video seconds must be numeric, got {video_s!r}")
    ko_1h = (ko or {}).get("ko_1h")
    if ko_1h is None:
        raise ValueError("Cannot convert video seconds without ko_1h.")
    ht    = (ko or {}).get("ht_whistle")
    ko_2h = (ko or {}).get("ko_2h")
    et1   = (ko or {}).get("ko_et1")
    et2   = (ko or {}).get("ko_et2")
    if et2 is not None and video_s >= et2:
        return 105 + (video_s - et2) / 60
    if et1 is not None and video_s >= et1:
        return 90 + (video_s - et1) / 60
    if ko_2h is not None and video_s >= ko_2h:
        return 45 + (video_s - ko_2h) / 60
    if ht is not None and video_s > ht:
        return (ht - ko_1h) / 60          # inside the break: clock is stopped
    return max(0.0, (video_s - ko_1h) / 60)
