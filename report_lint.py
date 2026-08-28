"""Does the report claim more than the run can support?

WHY THIS EXISTS
---------------
Two mechanisms already decide what a report may say. result_family_gates.json
downgrades eighteen families on a ball-following source, because a camera that
follows the ball cannot see far-side structure. field_variance.json names the
fields that returned the same value all match and are therefore not readings.

Neither mechanism can tell whether the report obeyed them. They shape the
bundle the writer is given; the writer then produces prose, and prose is where
the discipline is actually lost. On the Gorleston report:

  * seven [A] grades survived, six of them justified by the word "consistent"
    -- the exact reasoning the two-axis grading rule was written to kill.
    They went uncounted because the report writes "[A - reason]" and the
    check that reported "zero [A] grades" searched for the literal "[A]".

  * "Rest defence security was measured as very secure - minimal backward
    line shifts were registered across both teams [B - downgraded family]",
    twelve lines above a limitations note saying rest-defence structure is
    precisely what this source cannot show. Nothing was measured. Shifts were
    not registered because they were not visible, and the absence was read as
    security.

A report is the last artefact and the only one anybody reads. It needs a check
of its own, run against the same two files the writer was handed.
"""
import json
import os
import re
import sys

SCHEMA_VERSION = "1.0"

# Report vocabulary -> result family. Only families whose gate can be
# downgraded need an entry; a term that maps to nothing is not checked.
FAMILY_TERMS = {
    "rest_defence":       r"rest.?defen[cs]e",
    "pressing":           r"press(?:ing|ure)\b|counter.?press",
    "shape":              r"\bformation\b|\bshape\b|back four|midfield (?:two|three|four)",
    "territory":          r"line height|defensive line|possession|territor|field position",
    "set_pieces":         r"set.?piece|corner|free.?kick|throw.?in",
    "player_positioning": r"positioning|position(?:al)? tendenc",
    "player_role":        r"\brole\b",
    "build_up":           r"build.?up",
    "transitions":        r"transition",
    "opposition_structure": r"opposition structure",
}

# Language that asserts a reading was taken.
MEASURED_LANGUAGE = (
    r"was measured|were measured|measured as|registered across|"
    r"recorded across|the pipeline measure|confirmed across|"
    r"data shows|figures show")

# Language that turns nothing-seen into something-known.
# The span has to cover a real noun phrase. "minimal backward line shifts
# from possession changes were registered" puts 44 characters between the
# quantifier and the verb; a 30-character window missed the sentence this
# check was written for.
ABSENCE_AS_EVIDENCE = (
    r"(?:minimal|no|few|little|nothing) [a-z ,]{0,70}"
    r"(?:were|was) (?:registered|recorded|observed|detected|seen)")

# "[A - because it was consistent]" is the defect the two-axis rule replaced:
# consistency is evidence that a field did not move, not that it was seen.
CONSISTENCY_AS_GRADE = r"consistent|consistency|stable across|throughout"


def _sentences(text: str):
    """(line number, sentence). Bullets and table cells count as sentences."""
    out = []
    for n, line in enumerate(text.splitlines(), 1):
        stripped = line.strip(" -*|>#\t")
        if not stripped:
            continue
        for part in re.split(r"(?<=[.!?])\s+(?=[A-Z(\[*])", stripped):
            if part.strip():
                out.append((n, part.strip()))
    return out


def grades_in(text: str):
    """Every evidence grade and its stated reason.

    Matches "[A]", "[A - reason]" and "[A — reason]". The em dash form is
    what the report actually writes, and searching for the bare "[A]" is how
    seven of them were reported as zero.
    """
    out = []
    for m in re.finditer(r"\[([A-I])(?:\s*[—–-]\s*([^\]]{0,120}))?\]", text):
        out.append({"grade": m.group(1),
                    "reason": (m.group(2) or "").strip(),
                    "pos": m.start()})
    return out


def families_in(fragment: str):
    return sorted(fam for fam, pat in FAMILY_TERMS.items()
                  if re.search(pat, fragment, re.I))


def lint(report_text: str, gates: dict = None,
         variance: dict = None) -> list:
    """Findings, most serious first. Empty list means nothing to answer for."""
    gates    = (gates or {}).get("gates", gates or {})
    variance = variance or {}
    findings = []
    downgraded = {f for f, v in gates.items() if v == "downgraded"}

    # 1. An A grade on a family this source cannot see.
    for g in grades_in(report_text):
        if g["grade"] != "A":
            continue
        fams = [f for f in families_in(g["reason"]) if f in downgraded]
        line = report_text[:g["pos"]].count("\n") + 1
        if fams:
            findings.append({
                "check": "a_grade_on_downgraded_family", "severity": "high",
                "line": line, "quote": g["reason"][:100],
                "detail": "graded [A] citing %s, which this source downgrades"
                          % ", ".join(fams)})
        elif re.search(CONSISTENCY_AS_GRADE, g["reason"], re.I):
            findings.append({
                "check": "a_grade_justified_by_consistency", "severity": "high",
                "line": line, "quote": g["reason"][:100],
                "detail": "graded [A] because a value was consistent. "
                          "Consistency shows a field did not move, not that "
                          "it was observed -- see the two-axis rule"})

    # 2. Measurement language about a family that was downgraded.
    for line_no, sentence in _sentences(report_text):
        fams = [f for f in families_in(sentence) if f in downgraded]
        if not fams:
            continue
        if re.search(MEASURED_LANGUAGE, sentence, re.I):
            findings.append({
                "check": "measurement_language_on_downgraded_family",
                "severity": "high", "line": line_no, "quote": sentence[:120],
                "detail": "asserts a reading was taken of %s, which is "
                          "downgraded on this source" % ", ".join(fams)})
        if re.search(ABSENCE_AS_EVIDENCE, sentence, re.I):
            findings.append({
                "check": "absence_read_as_evidence", "severity": "high",
                "line": line_no, "quote": sentence[:120],
                "detail": "treats nothing-recorded about %s as a positive "
                          "finding. On a downgraded family the absence is "
                          "the camera, not the match" % ", ".join(fams)})

    # 3. A value the variance report says was never a reading.
    for field, rec in (variance.get("fields") or {}).items():
        if rec.get("verdict") not in ("not_measured", "near_constant",
                                      "constructed"):
            continue
        for value, seen in (rec.get("values") or {}).items():
            # json.load returns object keys as strings, so the in-memory
            # dict and the one read back from field_variance.json do not
            # have the same key type. Checking isinstance(value, float)
            # silently skipped every field once the report was linted from
            # disk -- which is the only way it is ever run.
            try:
                number = float(value)
            except (TypeError, ValueError):
                continue
            pat = r"(?<![\d.])%s\s*%%" % re.escape(
                str(int(number) if number.is_integer() else number))
            for m in re.finditer(pat, report_text):
                findings.append({
                    "check": "value_from_unmeasured_field",
                    "severity": "medium",
                    "line": report_text[:m.start()].count("\n") + 1,
                    "quote": report_text[max(0, m.start() - 70):
                                         m.start() + 20].replace("\n", " "),
                    "detail": "%s is %s; %s was its value in %s of %s windows"
                              % (field, rec["verdict"], m.group(0), seen,
                                 rec.get("windows_with_value", 0))})

    order = {"high": 0, "medium": 1, "low": 2}
    findings.sort(key=lambda f: (order.get(f["severity"], 9), f["line"]))
    return findings


def lint_match(match_dir: str, report_name: str = "tactical_report.md") -> list:
    def _load(name):
        path = os.path.join(match_dir, name)
        if not os.path.exists(path):
            return {}
        with open(path, encoding="utf-8") as f:
            return json.load(f)

    path = os.path.join(match_dir, report_name)
    if not os.path.exists(path):
        raise FileNotFoundError("report_lint: no %s in %s"
                                % (report_name, match_dir))
    with open(path, encoding="utf-8") as f:
        text = f.read()
    return lint(text, _load("result_family_gates.json"),
                _load("field_variance.json"))


def format_findings(findings: list, report_name: str = "") -> str:
    if not findings:
        return "  report_lint %s: nothing to answer for." % report_name
    lines = ["  report_lint %s: %d finding(s)" % (report_name, len(findings)), ""]
    for f in findings:
        lines.append("  [%s] line %-4s %s" % (f["severity"].upper(),
                                              f["line"], f["check"]))
        lines.append("        %s" % f["detail"])
        lines.append('        "%s"' % f["quote"].strip())
        lines.append("")
    return "\n".join(lines)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python report_lint.py MATCH_DIR [report.md]")
        sys.exit(1)
    name = sys.argv[2] if len(sys.argv) > 2 else "tactical_report.md"
    out  = lint_match(sys.argv[1], name)
    print(format_findings(out, name))
    sys.exit(1 if out else 0)
