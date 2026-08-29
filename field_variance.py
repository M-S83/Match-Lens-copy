"""Does a field respond to its input?

WHY THIS EXISTS
---------------
On the Gorleston match the structural agent returned
``defensive_line.home_height_pct = 45.0`` in nineteen of twenty windows,
``formation.home = "4-4-2"`` in twenty-one of twenty-one, and
``pressing.home_intensity = 3.5`` in twenty of twenty. Eighteen further runs
against an identical set of frames returned those same values every time.

A field that answers the same thing whether it is shown minute 3 or minute 87
is not measuring anything. It is the model's prior for English non-league
football, formatted as a reading.

The accumulator counts such a field as maximally consistent, and the report
grades it [A] and offers its consistency as evidence of a stable defensive
line. That is backwards: the consistency IS the evidence that nothing is
being measured. Nobody catches it by reading the report, because a stuck
sensor and a genuinely stable pattern read identically in prose.

They are trivially distinguishable in the data, which is what this module
does. It is a smoke alarm, not an analysis: cheap, mechanical, and pointed at
the one failure that a fluent report cannot show you.

WHAT COUNTS AS EVIDENCE OF MEASUREMENT
--------------------------------------
Variation, and enough of it. A field with one distinct value across enough
windows is ``not_measured``. A field whose modal value covers almost every
window is ``near_constant`` and gets the same treatment: on this match
``home_height_pct`` was 45.0 in nineteen windows of twenty, which is a stuck
field with one blip, not a reading. Downstream consumers must not present
either as a finding.

WHAT THIS DOES NOT TELL YOU
---------------------------
Anything about free text. Every prose field differs from every other, so a
distinct-value count would rank the noisiest description field as the best
measured one. Prose is handled by declaration instead -- see DERIVED_FROM --
and that list has to be maintained by hand.


That a ``measured`` field is trustworthy. The same control experiment showed
``away_height_pct`` producing four distinct values from *identical* frames,
so variation on its own can be pure run-to-run noise. This module rules
things out; it never rules them in. Deciding whether a varying field carries
signal needs a repeatability run, not a distinct-value count.

A genuinely stable phenomenon is indistinguishable from a stuck field by this
test, and that is the correct trade: a team really can hold one formation for
ninety minutes, but a pipeline cannot tell you so from a source that would
have said the same thing either way. Silence is the honest answer.
"""
import json
import os
import re
import sys
from collections import Counter

SCHEMA_VERSION = "1.0"

# Windows needed before a single distinct value means anything. Below this a
# constant is unremarkable -- three windows of 4-4-2 is just a short match.
MIN_WINDOWS = 8

# Share of windows the modal value may cover before the field is treated as
# constant. At 20 windows, 0.9 means a field must differ in at least two of
# them: one lone outlier is a blip, not evidence that the field responds.
DOMINANT_SHARE = 0.9

# (running_summary list, field within each entry, result family it feeds)
MONITORED = [
    ("formation_history",      "home_formation",  "shape"),
    ("formation_history",      "away_formation",  "shape"),
    ("formation_history",      "home_shape",      "shape"),
    ("formation_history",      "away_shape",      "shape"),
    ("line_height_m_by_window", "home_height_pct", "territory"),
    ("line_height_m_by_window", "away_height_pct", "territory"),
    # Per side, not the average. home_intensity is 3.5 on twenty windows of
    # twenty while away_intensity moves -- averaging them produces 0.85
    # dominance, which slips under the near-constant threshold and publishes a
    # stuck field. Line height failed the same way: home constant, away real.
    # Monitor what the agent emitted, not a figure derived from it.
    ("pressing_by_window",     "home_intensity",  "pressing"),
    ("pressing_by_window",     "away_intensity",  "pressing"),
    ("pressing_by_window",     "avg_score",       "pressing"),
    ("possession_by_window",   "focus_pct",       "territory"),
]

# Deliberately NOT monitored: match_state_by_window.match_state. It is derived
# from match_config (the operator's goal times), not read from frames, so a
# constant there is a fact about the match rather than a stuck sensor -- this
# match really was home_winning in 19 windows of 21. Only fields the vision
# layer produces belong above; anything derived from operator facts would
# generate false alarms and teach people to ignore the alarm.

# Summary keys the accumulator DERIVES from monitored fields. Redacting the
# per-window field alone is not enough: canonical_formation says "4-4-2" with
# no trace of what it was computed from, so a reader -- human or agent -- has
# no way to tell that every vote came from a field that never varied. The
# derived value has to go too, or the constant simply reappears one layer up.
DERIVED_FROM = {
    "canonical_formation":    ["formation_history.home_formation",
                               "formation_history.away_formation"],
    "formation_distribution": ["formation_history.home_formation",
                               "formation_history.away_formation"],
    # Prose siblings of the same formation object. The variance test cannot
    # judge free text -- every string differs, so distinct-value counting
    # would call the noisiest field the best measured one. This entry is a
    # DECLARED derivation, not a computed one: ip_shape_summary collects
    # formation.home_variation / away_variation, which describe the very
    # label that was rejected. It is also the field that produced sixteen
    # different descriptions of the same five minutes across the eighteen
    # identical-input runs.
    "ip_shape_summary":       ["formation_history.home_formation",
                               "formation_history.away_formation"],
}

# Per-ENTRY fields computed from other per-entry fields. Redacting a source
# leaves any average of it standing, still carrying the constant: pressing
# avg_score is the mean of a home intensity fixed at 3.5 and an away intensity
# that moves, and scores 85% dominance -- under the near-constant threshold, so
# it publishes. line_height avg_pct is the same shape and was monitored by
# nothing at all. The mean of a measurement and a non-measurement is not a
# measurement.
DERIVED_FIELDS = {
    "pressing_by_window.avg_score": [
        "pressing_by_window.home_intensity",
        "pressing_by_window.away_intensity"],
    # peak is max(home_intensity, away_intensity). It was missed when this
    # table was written by hand, so on the Gorleston match the redacted
    # record read {"avg_score": "not_measured", "peak": 3.5} -- the
    # mechanism built to suppress a stuck value publishing it one key to the
    # right. INDEPENDENT below plus test_registry_is_complete now fail the
    # suite when a field reaches one of these lists unclassified, so the
    # next one cannot be missed the same way.
    "pressing_by_window.peak": [
        "pressing_by_window.home_intensity",
        "pressing_by_window.away_intensity"],
    "line_height_m_by_window.avg_pct": [
        "line_height_m_by_window.home_height_pct",
        "line_height_m_by_window.away_height_pct"],
    "line_height_m_by_window.avg_m_approx": [
        "line_height_m_by_window.home_height_pct",
        "line_height_m_by_window.away_height_pct"],
}

# Fields that live in a monitored list and are deliberately neither monitored
# nor derived. Each needs a reason, because "not listed" and "considered and
# excluded" look identical otherwise -- which is how pressing peak survived
# for as long as it did.
#
# This is not documentation. test_registry_is_complete reads the dict
# literals that accumulator.py appends to each of these lists and fails if a
# key appears in none of MONITORED, DERIVED_FIELDS or INDEPENDENT. Adding a
# field to the accumulator therefore forces a decision here at the moment it
# is added, rather than after a report has published it.
INDEPENDENT = {
    # Identity, not a reading.
    "formation_history.window":              "window label",
    "formation_history.window_id":           "window ordinal",
    "formation_history.agent_id":            "which agent produced the record",
    "line_height_m_by_window.window":        "window label",
    "line_height_m_by_window.agent_id":      "which agent produced the record",
    "possession_by_window.window":           "window label",
    "pressing_by_window.window":             "window label",
    "pressing_by_window.agent_id":           "which agent produced the record",
    "pressing_by_window.peak_ts":            "timestamp of the peak, not a magnitude",

    # Free text or nested lists. Distinct-value counting ranks the noisiest
    # description as the best measured field, so prose is excluded by
    # declaration -- see WHAT THIS DOES NOT TELL YOU in the module docstring.
    "formation_history.shape":               "free text",
    "formation_history.shape_oop":           "free text",
    "line_height_m_by_window.shifts":        "list of shift descriptions",
    "pressing_by_window.observations":       "list of press-trigger observations; "
                                             "triggers vary (other/back_pass/"
                                             "gk_in_possession) and carry the real "
                                             "pressing signal",
    "possession_by_window.basis":            "provenance label for focus_pct",

    # Never populated by any agent on this source. Null everywhere is caught
    # by the NO_DATA verdict if they are ever monitored; listing them here
    # records that their absence is known rather than unnoticed.
    "line_height_m_by_window.line_width_m_approx": "null on every window observed",
    "line_height_m_by_window.space_behind_m":      "null on every window observed",

    # Sequence counts. Their distinct-value spread is healthy (10, 11, 12, 5)
    # so variance testing passes them, but the split between the two is an
    # artefact of the team label -- see check_team_attribution, which is what
    # actually judges these.
    "possession_by_window.focus_seqs":       "judged by check_team_attribution",
    "possession_by_window.opp_seqs":         "judged by check_team_attribution",
    # Not a reading: it counts the sequences that carry no reading. It is the
    # denominator disclosure for the two counts above, and a rising value is
    # the honest signal that attribution is getting harder -- exactly the
    # thing a variance test would misread as a field going stale.
    "possession_by_window.unclear_seqs":     "count of unattributable sequences; "
                                             "denominator disclosure, not a measurement",
}

# The lists this module claims to cover. Anything appended to one of these by
# the accumulator is in scope for the registry check.
MONITORED_LISTS = sorted({ln for ln, _, _ in MONITORED})

NOT_MEASURED  = "not_measured"
NEAR_CONSTANT = "near_constant"
MEASURED      = "measured"
NO_DATA       = "no_data"
# A value the pipeline computed from its own construction rather than read
# from the match. It is not a stuck sensor -- it varies -- but the variation
# comes from how the data was assembled, so it carries no information about
# what happened. See check_team_attribution.
CONSTRUCTED   = "constructed"
# A field that mostly returns the SAME value a stuck sibling is stuck on. It
# varies enough to pass the dominance test, but the value it keeps returning
# is the one the model falls back to when it cannot judge. See
# mark_shared_defaults.
ANCHORED      = "anchored"

# Verdicts that mean "do not report this as an observed pattern".
UNMEASURED = (NOT_MEASURED, NEAR_CONSTANT, CONSTRUCTED, ANCHORED)

# Share of windows a field's modal value must cover before that value counts
# as its default. Deliberately below DOMINANT_SHARE: the whole point is to
# catch fields that PASSED the dominance test.
ANCHOR_SHARE = 0.6


def _modal(rec):
    """The value a field returned most often, or None."""
    values = rec.get("values") or {}
    if not values:
        return None
    top = max(values, key=values.get)
    try:
        return float(top)          # json.load turns object keys into strings
    except (TypeError, ValueError):
        return str(top)


def mark_shared_defaults(fields: dict) -> list:
    """Fields whose modal value is a stuck sibling's stuck value.

    Dominance alone could not catch pressing on the Gorleston match.
    home_intensity was 3.5 in twenty windows of twenty and was correctly
    withheld. away_intensity was 3.5 in seventeen of twenty -- 85%, just
    under the 90% threshold -- so it passed as measured, and the report
    published "away pressing intensity was directionally measurable at 3.5".

    The tell is not the share. It is that BOTH fields return the same
    number. One of them provably is not measuring; a sibling that keeps
    answering with that same value is reading the same default, and its
    three excursions are the exception rather than the signal.

    This does not fire on line height, which is the check that it
    discriminates rather than simply flagging everything: home_height_pct is
    stuck at 45.0 while away_height_pct's modal value is 40.0. Different
    numbers, so the away line is moving on its own and survives.
    """
    stuck = {}
    for key, rec in fields.items():
        if rec.get("verdict") in (NOT_MEASURED, NEAR_CONSTANT):
            value = _modal(rec)
            if value is not None:
                stuck.setdefault(key.partition(".")[0], {})[key] = value

    flagged = []
    for key, rec in fields.items():
        if rec.get("verdict") != MEASURED:
            continue
        siblings = stuck.get(key.partition(".")[0], {})
        if not siblings:
            continue
        value = _modal(rec)
        if value is None or rec.get("dominant_share", 0) < ANCHOR_SHARE:
            continue
        for other_key, other_value in siblings.items():
            if other_key != key and other_value == value:
                rec["verdict"] = ANCHORED
                rec["anchored_on"] = other_key
                rec["reason"] = (
                    "modal value %s is the value %s is stuck on; the same "
                    "default, not an independent reading"
                    % (value, other_key))
                flagged.append(key)
                break
    return flagged


def unclassified_fields(list_name: str, keys) -> list:
    """Keys in a monitored list that no declaration accounts for."""
    monitored = {"%s.%s" % (ln, f) for ln, f, _ in MONITORED}
    missing   = []
    for k in keys:
        full = "%s.%s" % (list_name, k)
        if full in monitored or full in DERIVED_FIELDS or full in INDEPENDENT:
            continue
        missing.append(full)
    return sorted(missing)


def classify(values, min_windows: int = MIN_WINDOWS,
             dominant_share: float = DOMINANT_SHARE) -> dict:
    """Verdict for one field, given its per-window values.

    None is absence, not a value: a field that is null everywhere has not
    been measured either, but for a different reason, and conflating the two
    hides which one you are looking at.
    """
    present = [v for v in values if v is not None]
    counts  = Counter(present)
    share   = (counts.most_common(1)[0][1] / len(present)) if present else 0.0
    if len(present) < min_windows:
        verdict = NO_DATA
    elif len(counts) == 1:
        verdict = NOT_MEASURED
    elif share >= dominant_share:
        verdict = NEAR_CONSTANT
    else:
        verdict = MEASURED
    return {
        "verdict":       verdict,
        "windows_total": len(values),
        "windows_with_value": len(present),
        "distinct":      len(counts),
        "dominant_share": round(share, 3),
        "values":        dict(counts.most_common(6)),
    }


# A window needs this many attributed sequences before its ordering means
# anything; three sequences alternate by chance often enough to be useless.
ALTERNATION_MIN_SEQS    = 6
# ...and this many such windows before the match-level share means anything.
ALTERNATION_MIN_WINDOWS = 5
# Share of qualifying windows that must alternate strictly before the label is
# called constructed. Real possession does not alternate: a team wins the ball
# back and keeps it, so consecutive same-team sequences are the normal case.
ALTERNATION_SHARE       = 0.9


def check_team_attribution(match_dir: str = "", sequences: list = None) -> dict:
    """Does the team label on a pass sequence carry information?

    Variance testing cannot see this failure. The team field takes two
    distinct values in every window, in healthy proportion, and passes. What
    gives it away is the ORDER: on the Gorleston match the label ran
    home, away, home, away without a single exception across 429 sequences
    and 21 separately-run agents.

    Possession does not behave that way. A side wins the ball and keeps it;
    consecutive sequences by the same team are ordinary. Perfect alternation
    across independent agents is not an observation, it is the schema line
    "Log sequences for BOTH teams, not just the focus team" being satisfied
    by a model that cannot tell at 1fps who has the ball -- so it takes turns.

    Everything downstream of the label inherits the artefact: focus_seqs and
    opp_seqs came out equal in twenty windows of twenty-one, and focus_pct
    was therefore 50.0 by construction. A reader sees a balanced game.
    """
    if sequences is None:
        path = os.path.join(match_dir, "pass_sequences.json")
        if not os.path.exists(path):
            return None
        with open(path, encoding="utf-8") as f:
            raw = json.load(f)
        sequences = raw.get("sequences", raw) if isinstance(raw, dict) else raw
    if not isinstance(sequences, list):
        return None

    by_window = {}
    for s in sequences:
        if isinstance(s, dict):
            by_window.setdefault(s.get("window"), []).append(s.get("team"))

    checked = alternating = 0
    for teams in by_window.values():
        teams = [t for t in teams if t is not None]
        if len(teams) < ALTERNATION_MIN_SEQS:
            continue
        checked += 1
        if all(teams[i] != teams[i + 1] for i in range(len(teams) - 1)):
            alternating += 1

    if checked < ALTERNATION_MIN_WINDOWS:
        return {"verdict": NO_DATA, "windows_checked": checked,
                "windows_alternating": alternating, "share": 0.0,
                "sequences": len(sequences),
                "reason": "too few windows carry %d+ attributed sequences to "
                          "judge the ordering" % ALTERNATION_MIN_SEQS}

    share   = alternating / checked
    strict  = share >= ALTERNATION_SHARE
    return {
        "verdict":            CONSTRUCTED if strict else MEASURED,
        "windows_checked":    checked,
        "windows_alternating": alternating,
        "share":              round(share, 3),
        "sequences":          len(sequences),
        "reason": ("team label alternates strictly in %d of %d windows (%.0f%%); "
                   "the possession split follows from that alternation, not "
                   "from the frames" % (alternating, checked, share * 100))
                  if strict else
                  ("team label alternates strictly in %d of %d windows (%.0f%%), "
                   "below the %.0f%% artefact threshold"
                   % (alternating, checked, share * 100, ALTERNATION_SHARE * 100)),
    }


def compute(match_dir: str, running_summary: dict = None,
            min_windows: int = MIN_WINDOWS,
            dominant_share: float = DOMINANT_SHARE,
            write: bool = True) -> dict:
    """Verdicts for every monitored field, written to field_variance.json."""
    if running_summary is None:
        path = os.path.join(match_dir, "running_summary.json")
        if not os.path.exists(path):
            raise FileNotFoundError(
                f"field_variance: no running_summary.json in {match_dir}")
        with open(path, encoding="utf-8") as f:
            running_summary = json.load(f)

    fields = {}
    for list_name, field, family in MONITORED:
        entries = running_summary.get(list_name) or []
        if not isinstance(entries, list):
            continue
        values = [e.get(field) if isinstance(e, dict) else None
                  for e in entries]
        rec = classify(values, min_windows, dominant_share)
        rec["family"] = family
        fields[f"{list_name}.{field}"] = rec

    # A field can pass the dominance test and still be returning a default,
    # if the default is one a sibling field is provably stuck on.
    anchored = mark_shared_defaults(fields)

    # Possession is not judged by distinct-value counting -- focus_seqs moves
    # across windows and would pass. It is judged by whether the team label it
    # is built from carries information at all.
    attribution = check_team_attribution(match_dir) if match_dir else None
    if attribution and attribution["verdict"] == CONSTRUCTED:
        entries = running_summary.get("possession_by_window") or []
        for f, family in (("focus_pct", "territory"),
                          ("focus_seqs", "territory"),
                          ("opp_seqs", "territory")):
            key = "possession_by_window.%s" % f
            rec = fields.get(key) or classify(
                [e.get(f) for e in entries if isinstance(e, dict)],
                min_windows, dominant_share)
            rec["verdict"] = CONSTRUCTED
            rec["family"]  = family
            rec["reason"]  = attribution["reason"]
            fields[key]    = rec

    report = {
        "match":         running_summary.get("match", ""),
        "min_windows":     min_windows,
        "dominant_share":  dominant_share,
        "fields":          fields,
        "team_attribution": attribution,
        "anchored": sorted(anchored),
        "not_measured":  sorted(k for k, v in fields.items()
                                if v["verdict"] in UNMEASURED),
        "no_data":       sorted(k for k, v in fields.items()
                                if v["verdict"] == NO_DATA),
        "schema_version": SCHEMA_VERSION,
    }
    if write:
        with open(os.path.join(match_dir, "field_variance.json"),
                  "w", encoding="utf-8") as f:
            json.dump(report, f, indent=2)
    return report


def unmeasured_families(report: dict) -> list:
    """Result families with at least one field that never varied.

    A downstream grader should not present these as observed patterns.
    """
    return sorted({v["family"] for v in report.get("fields", {}).values()
                   if v["verdict"] in UNMEASURED})


def redact(running_summary: dict, report: dict) -> dict:
    """A copy of the summary with never-measured values replaced by a marker.

    Prompt rules are advisory; absent data is dispositive. Telling a report
    writer to ignore a number you have handed it does not work -- the first
    version of this fix added exactly such a rule, and the agent went on to
    write "both teams operated in a 4-4-2 throughout the match, confirmed
    across all observed phases [A]" because canonical_formation still said
    4-4-2 and a separate FORMATION RULE still told it to use that label.

    So the value is removed rather than annotated. Redaction is per FIELD,
    not per list: away_height_pct varies across the match and survives even
    though home_height_pct, sitting beside it in the same records, does not.
    """
    out     = dict(running_summary)
    flagged = set(report.get("not_measured", []))
    if not flagged:
        return out

    # A derived field falls with any of its sources.
    for derived, sources in DERIVED_FIELDS.items():
        if any(src in flagged for src in sources):
            flagged.add(derived)

    by_list = {}
    for key in flagged:
        list_name, _, field = key.partition(".")
        by_list.setdefault(list_name, []).append(field)

    for list_name, fields in by_list.items():
        entries = out.get(list_name)
        if not isinstance(entries, list):
            continue
        out[list_name] = [
            {**e, **{f: NOT_MEASURED for f in fields if f in e}}
            if isinstance(e, dict) else e
            for e in entries
        ]

    for derived, sources in DERIVED_FROM.items():
        if derived in out and any(s in flagged for s in sources):
            out[derived] = NOT_MEASURED

    # The label can also sit in agent prose, which no per-field redaction
    # reaches. See withheld_prose_tokens for why this is narrow.
    return scrub_prose(out, withheld_prose_tokens(report))


# A withheld value can reappear inside prose the variance test cannot judge.
# On this match formation_history.home_formation was not_measured and
# correctly redacted, and the report still said "operating from a compact
# 4-4-2 mid-block" -- because two key_moments descriptions mention 4-4-2 and
# free text is out of scope for a distinct-value count.
#
# Scrubbing prose in general would be reckless: home_shape is stuck on "mid",
# and removing "mid" from descriptions would destroy them. So this is
# deliberately narrow. Only a value shaped like a formation is scrubbed --
# digits joined by dashes, which cannot be mistaken for an ordinary word.
FORMATION_TOKEN = re.compile(r"^\d(?:-\d){1,3}$")
PROSE_REPLACEMENT = "[shape not measured]"


def withheld_prose_tokens(report: dict) -> list:
    """Distinctive string values that a withheld field kept returning."""
    tokens = set()
    for key, rec in (report.get("fields") or {}).items():
        if rec.get("verdict") not in UNMEASURED:
            continue
        for value in (rec.get("values") or {}):
            text = str(value)
            if FORMATION_TOKEN.match(text):
                tokens.add(text)
    return sorted(tokens)


def scrub_prose(obj, tokens):
    """Replace withheld formation labels wherever they appear in free text."""
    if not tokens:
        return obj
    if isinstance(obj, dict):
        return {k: scrub_prose(v, tokens) for k, v in obj.items()}
    if isinstance(obj, list):
        return [scrub_prose(v, tokens) for v in obj]
    if isinstance(obj, str):
        for token in tokens:
            obj = re.sub(r"(?<![\d-])%s(?![\d-])" % re.escape(token),
                         PROSE_REPLACEMENT, obj)
        return obj
    return obj


def format_report(report: dict) -> str:
    lines = [f"  Field variance -- {report.get('match','?')} "
             f"(a field needs {report['min_windows']}+ windows to be judged)",
             ""]
    for name, rec in sorted(report["fields"].items()):
        mark = {NOT_MEASURED: "STUCK", NEAR_CONSTANT: "STUCK",
                CONSTRUCTED: "BUILT", ANCHORED: "ANCHR",
                MEASURED: "ok   ", NO_DATA: "none "}.get(rec["verdict"], "?????")
        vals = ", ".join(f"{k}x{v}" for k, v in rec["values"].items()) or "-"
        lines.append(f"  [{mark}] {name:42} {rec['distinct']:>2} distinct / "
                     f"{rec['windows_with_value']:>2} windows  "
                     f"top {rec['dominant_share']:.0%}  {vals[:46]}")
    if report["not_measured"]:
        lines += ["",
                  f"  {len(report['not_measured'])} field(s) barely varied across "
                  f"the match. Treat as not measured, not as a pattern:",
                  "    " + "\n    ".join(report["not_measured"])]
    return "\n".join(lines)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python field_variance.py [MATCH_DIR]")
        sys.exit(1)
    print(format_report(compute(sys.argv[1], write=False)))
