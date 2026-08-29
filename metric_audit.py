"""Trace every published figure back to what it was counted over.

    python metric_audit.py MATCH_DIR

WHY
---
The tactical report's most concrete-looking numbers were its most wrong. It
published "82% win rate across 11 contested duels" for a player whose record
was 9 won, 0 lost, 2 contested -- dividing wins by times-VISIBLE, counting
contested duels as losses, over a sample that captured about half the match's
duels. Four defects, three of them invisible in the output.

Nothing was checking the arithmetic, because a number looks like a fact. Prose
gets hedged; figures get quoted. So figures need MORE scrutiny than sentences,
and that scrutiny has to be mechanical or it does not happen.

This does not read the report. It audits the DATA the report is written from,
and states for every figure: what it was counted over, how big that sample is,
whether the denominator is knowable, and what the source profile permits. A
figure that fails is not deleted -- it is labelled, so a human decides.

VERDICTS
--------
  publish       sample adequate, denominator meaningful, family allowed
  counts_only   the denominator is not knowable; publish counts, not a rate
  cap_at_B      the family is downgraded for this source
  withhold      too few observations, or the value is not measured at all
"""
import argparse
import json
import re
import os

# Observations below which a rate is arithmetic rather than evidence. At n=9
# a single event moves the figure eleven points, which is wider than most of
# the differences a report would draw from it.
MIN_N_FOR_RATE = 12

# Figures whose denominator counts something other than what its name implies.
# Each entry names what is actually being counted, so the label cannot drift
# back to the convenient reading.
UNKNOWABLE_DENOMINATOR = {
    "duel_effectiveness": (
        "players_visible is who was IN FRAME for a duel, not who contested "
        "it; and this source logs roughly half the duels in a match"),
    "aerial_dominance": (
        "counts duels the source happened to observe, not duels contested; "
        "contested outcomes fall into the denominator rather than being "
        "excluded"),
    "possession_balance": (
        "counts possession EXCHANGES, which alternate by construction, not "
        "time in possession"),
    "width_usage_score": (
        "denominator is sequences the agent classified, not sequences "
        "played; a ball-following crop under-samples the far touchline, "
        "which is where width lives"),
    # {n} is filled with THIS match's sample size. The first version wrote
    # "429 is the number of sequences the agent LOGGED" -- Gorleston's count,
    # hardcoded into a generic reason. Audited against Leverkusen, which
    # logged 445, the tool stated another match's number as a fact about the
    # one in front of it.
    "build_up_effectiveness_score": (
        "{n} is the number of sequences the agent LOGGED, not the number "
        "played. The camera samples the ball's neighbourhood, so the total "
        "is a sample of unknown size and a percentage of it describes the "
        "sample rather than the team. The duel section of the same report "
        "refuses rates for exactly this reason"),
    "pattern_reliability_score": (
        "same denominator as build-up effectiveness -- {n} sequences logged, "
        "not played -- and the route labels come from a three-zone encoding, "
        "so a dominant-route share measures the encoding as much as the play"),
}


def _fill(note, n):
    """Put this match's sample size into a reason that asks for it."""
    if "{n}" not in note:
        return note
    return note.replace("{n}", str(n) if n is not None else "the logged total")


def _has_rate(value) -> bool:
    """Is there a proportion anywhere in this value?"""
    if isinstance(value, dict):
        return any(_looks_like_a_rate(k, v) or _has_rate(v)
                   for k, v in value.items())
    if isinstance(value, list):
        return any(_has_rate(v) for v in value)
    return False


def _n_of(value):
    """Best-effort observation count behind a metric value."""
    if isinstance(value, dict):
        for k in ("total_sequences", "total", "sample", "n", "observations",
                  "overall_duels", "windows_with_data", "total_set_pieces"):
            if isinstance(value.get(k), int):
                return value[k]
        for v in value.values():
            if isinstance(v, dict):
                inner = _n_of(v)
                if inner is not None:
                    return inner
    if isinstance(value, list):
        return len(value)
    return None


def audit(match_dir):
    def load(name):
        p = os.path.join(match_dir, name)
        if not os.path.exists(p):
            return {}
        with open(p, encoding="utf-8") as f:
            return json.load(f)

    metrics = load("deep_skill_metrics.json").get("metrics") or []
    variance = load("field_variance.json")
    not_measured = set(variance.get("not_measured") or [])
    unmeasured_families = {
        v.get("family") for k, v in (variance.get("fields") or {}).items()
        if k in not_measured}

    rows = []
    for m in metrics:
        name = m.get("metric_name", "?")
        fam = (m.get("supporting_result_families") or ["?"])[0]
        status = m.get("result_family_status")
        n = _n_of(m.get("value"))
        note, verdict = "", "publish"

        if fam in unmeasured_families:
            verdict = "withhold"
            note = f"underlying field never varied ({fam})"
        elif name in UNKNOWABLE_DENOMINATOR:
            verdict = "counts_only"
            note = _fill(UNKNOWABLE_DENOMINATOR[name], n)
        elif n is not None and n < MIN_N_FOR_RATE:
            verdict = "withhold"
            note = f"n={n}: one event moves this by {100/max(n,1):.0f} points"
        elif n is None and _has_rate(m.get("value")):
            # between_lines_receiving_rate published a per-player rate over
            # samples of one to six receptions. It was marked publish because
            # _n_of cannot see inside a dict keyed by player, so the
            # MIN_N_FOR_RATE check never ran at all -- the metric was not
            # judged safe, it was simply not judged.
            #
            # A rate whose sample size cannot be stated is not publishable at
            # any n. The counts underneath it survive: "received between the
            # lines 0 times from 2 receptions" is honest; "0.0%" is not.
            verdict = "counts_only"
            note = ("carries a rate but no sample size this tool can find, so "
                    "the minimum-n rule never applied to it; publish the "
                    "counts underneath instead")
        elif status == "downgraded":
            verdict = "cap_at_B"
            note = f"{fam} downgraded for this source"

        rows.append({"metric": name, "family": fam, "n": n,
                     "confidence": m.get("confidence"), "verdict": verdict,
                     "note": note})

    order = {"withhold": 0, "counts_only": 1, "cap_at_B": 2, "publish": 3}
    rows.sort(key=lambda r: (order[r["verdict"]], r["metric"]))
    return {"match_dir": match_dir, "metrics_audited": len(rows),
            "rows": rows,
            "summary": {v: sum(1 for r in rows if r["verdict"] == v)
                        for v in order}}


# Field names that express a proportion. On a counts_only metric these are the
# part that cannot be justified: the counts survive, the ratio does not.
#
# Matched on word boundaries. The first version listed "_rate" as a
# substring, which does not match a field named plainly "rate" -- so
# between_lines_receiving_rate kept a per-player "rate" of 0.0 over two
# receptions straight through strip_rates, and the audit could not even see
# that the metric carried a proportion. A substring test also has the
# opposite failure: "rate" appears inside "accurate_passes", which is a count.
RATE_KEYS = ("rate", "pct", "share", "score", "percentage", "ratio")
_RATE_KEY_RE = re.compile(
    r"(?:^|_)(?:" + "|".join(RATE_KEYS) + r")(?:$|_)", re.I)


def _looks_like_a_rate(key, value):
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return False
    return bool(_RATE_KEY_RE.search(str(key)))


def strip_rates(value):
    """Remove proportions from a metric value, keeping the counts.

    "Nine duels won, none lost" survives; "82%" does not. Applied to the
    bundle rather than enforced by instruction, because a rule telling a
    writer to ignore a number it has been handed has failed three times in
    this project.
    """
    if isinstance(value, dict):
        out = {}
        for k, v in value.items():
            if _looks_like_a_rate(k, v):
                continue
            if isinstance(v, str) and "%" in v:
                continue          # prose summaries carry the rate as text
            out[k] = strip_rates(v) if isinstance(v, (dict, list)) else v
        return out
    if isinstance(value, list):
        return [strip_rates(v) for v in value]
    return value


# Text fields that describe HOW a metric is computed rather than what this
# match did. "Pattern reliability (60%) + inverse route diversity (40%)" is a
# formula, not a reading, and removing it would cost traceability for no gain.
METHOD_FIELDS = ("calculation_basis", "value_type", "sample_status")

_PCT_IN_PROSE = re.compile(r"\d+(?:\.\d+)?\s*%")


def _strip_rate_prose(metric: dict) -> dict:
    """Remove match rates that survive as sentences beside the value.

    strip_rates cleans `value`. It does not touch prose_interpretation, which
    on this match still read "37.0% of sequences used the dominant route" and
    "31.5% of 429 sequences reached the final third" -- the audit removing a
    figure from one key and handing the writer the same figure, in words, one
    key to the right. The report duly published 37%.

    This is the third time a suppression mechanism has leaked through a
    neighbouring field: pressing peak beside a redacted avg_score, a bare
    "rate" key that RATE_KEYS could not see, and now this. Removing the
    number is the only thing that works -- a rule telling the writer to
    ignore a figure it has been handed has never once held.
    """
    out = dict(metric)
    for key, value in metric.items():
        if key in METHOD_FIELDS or not isinstance(value, str):
            continue
        if _PCT_IN_PROSE.search(value):
            out.pop(key, None)
    return out


def apply(metrics, match_dir):
    """Metrics as the report writer should receive them.

    withhold    -> removed entirely
    counts_only -> proportions stripped, counts kept
    otherwise   -> unchanged, with the verdict attached so the grader can see it
    """
    verdicts = {r["metric"]: r for r in audit(match_dir)["rows"]}
    out = []
    for m in metrics or []:
        row = verdicts.get(m.get("metric_name"))
        if row is None:
            out.append(m)
            continue
        if row["verdict"] == "withhold":
            continue
        m = dict(m, audit=row)
        if row["verdict"] == "counts_only":
            m["value"] = strip_rates(m.get("value"))
            m = _strip_rate_prose(m)
        out.append(m)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("match_dir")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()
    r = audit(a.match_dir)
    if a.json:
        print(json.dumps(r, indent=2))
        return
    print(f"\n  {r['metrics_audited']} figures audited\n")
    print(f"  {'verdict':12} {'metric':34} {'n':>5}  why")
    for row in r["rows"]:
        print(f"  {row['verdict']:12} {row['metric']:34} "
              f"{str(row['n'] if row['n'] is not None else '-'):>5}  {row['note'][:74]}")
    s = r["summary"]
    print(f"\n  withhold {s['withhold']}   counts_only {s['counts_only']}   "
          f"cap_at_B {s['cap_at_B']}   publish {s['publish']}")
    print("\n  This audits the DATA, not the prose. A figure marked withhold or")
    print("  counts_only appearing as a percentage in the report is a defect.")


if __name__ == "__main__":
    main()
