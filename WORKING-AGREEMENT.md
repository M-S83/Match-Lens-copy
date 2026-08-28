# Working agreement

Written 25 Aug 2026, after a session that produced good work and too many
corrections. Every rule below is here because of a specific incident, and the
incident is named so the rule can be argued with rather than obeyed.

The pattern being fixed: **checks that compared code against my reasoning
passed; checks that compared output against reality found things.** Four of
that day's corrections came from the operator in one line each — "9 red to 6
green", "the bench sits inside the track", "we have a lot of reference
points", "the frames don't cover all the duels". Each redirected the work
faster than any amount of re-reading would have.

---

## 1. Measure the distribution before choosing the constant

`ACHROM_S = 70` was set before anyone had measured what saturation a
Gorleston shirt actually has. It was rejecting green players as colourless —
the kit is dark green with white stripes and runs S 58–133. The same happened
with `MIN_SHARE`, `SKIN_S`, and a Hough filter set to ±14° when the touchline
in that camera runs at 139°.

Every threshold picked from intuition that day was later corrected by
rendering a frame and looking at it. Every threshold picked *after* printing
the distribution was right first time.

**Practice:** print the two things the constant is meant to separate before
choosing the number. If that isn't possible, the constant is a guess — write
that in the code, so the next person knows it is load-bearing and unverified.

## 2. The test ships with the code, and its expectation is a literal

`test_a_player_straddling_the_line` asserted using `SIDE_MARGIN_PX`, the
constant under test. Setting it to zero made the test agree with the bug. An
hour later the same shape recurred: a test grepping the source for
`"opposition"` passed as soon as a comment explaining the old bug contained
the word.

`team_classifier.py` shipped in the afternoon and was tested at midnight. The
tests found a real defect in minutes — `prepare` had come to hard-depend on
ultralytics, so a machine without YOLO got no labelling frames at all.

**Practice:** write the expected value out. `assert outside_play(b, (900, 388))
is False` — never `400 - SIDE_MARGIN_PX + 4`. Write the test in the same
sitting as the code. Mutate one constant and confirm the test fails; a test
that survives its own mutation is measuring nothing.

## 3. After a fix, re-read the whole function

`calc_aerial_dominance` held two bugs in six lines: a denominator counting a
value the data never contained, and a rate asked for by club name where the
data holds a kit token. Fixing only the first turned "always 100%" into
"always 0%" and looked like progress.

**Practice:** bugs cluster. A function that had one has others. Re-read it
whole after changing it, not the line that changed.

## 4. Render the artefact and look at it

Every genuine fix to the team classifier came from drawing boxes on a frame
and reading the image: the neighbour's shirt bleeding into a bounding box, a
green player scored at grass hue by a circular mean over a bimodal set, an
assistant referee in black scored as a red player on twenty pixels of forearm.
Reasoning found none of them.

**Practice:** before saying it works, produce the thing a human would inspect,
and inspect it.

---

## Failure modes this codebase keeps producing

Watch for these specifically. Each has occurred more than once.

**A rule added, the contradicting instruction left standing.** Three times in
one session. `accumulator "consistent" → always [A]` versus the family gate;
`FORMATION RULE: use canonical_formation` versus the not-measured list; worked
examples ending in a literal `[A]` versus the two-axis rule. Each time the
contradiction won. **Absent beats forbidden** — remove the value rather than
instructing the reader to ignore it.

**A second implementation added beside a broken one.** `line_height_by_window`
reads `avg_pct`, which the schema never emits, so it is null on every window
of every match; the fix was to add `line_height_m_by_window` alongside and
leave the broken one shipping. Team-side resolution reached five
implementations the same way, time-base conversion four.

**A confident number over an unknowable denominator.** Duel "win rates" were
wins ÷ times-*visible*, over a sample capturing half the match's duels.
Formation was a constant reported as a confirmed finding. Defensive line
height was 45.0 in nineteen windows of twenty. If the denominator cannot be
stated, publish counts, or publish nothing.

---

## What worked, and is worth repeating

- **Annotate and look.** Six classifier defects in an afternoon.
- **Mutation testing.** Caught both vacuous tests. Nothing else would have.
- **A negative experiment.** Sweeping the grass mask from +25px to −31px and
  seeing *no change* proved the pitch boundary is a line, not a colour, and
  ended an hour of pointless tuning.
- **An accidental control.** Eighteen agent runs against identical frames
  showed formation, line height and pressing intensity were constants. That
  single observation was worth more than the whole report it came from.
- **Withholding.** Above a 10% invalid rate the local CV publishes no
  match-level figure at all. A number printed beside a warning gets quoted
  without the warning.
