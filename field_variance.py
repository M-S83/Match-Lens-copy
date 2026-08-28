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

NOT_MEASURED  = "not_measured"
NEAR_CONSTANT = "near_constant"
MEASURED      = "measured"
NO_DATA       = "no_data"

# Verdicts that mean "do not report this as an observed pattern".
UNMEASURED = (NOT_MEASURED, NEAR_CONSTANT)


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

    report = {
        "match":         running_summary.get("match", ""),
        "min_windows":     min_windows,
        "dominant_share":  dominant_share,
        "fields":          fields,
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

    return out


def format_report(report: dict) -> str:
    lines = [f"  Field variance -- {report.get('match','?')} "
             f"(a field needs {report['min_windows']}+ windows to be judged)",
             ""]
    for name, rec in sorted(report["fields"].items()):
        mark = {NOT_MEASURED: "STUCK", NEAR_CONSTANT: "STUCK",
                MEASURED: "ok   ", NO_DATA: "none "}[rec["verdict"]]
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
