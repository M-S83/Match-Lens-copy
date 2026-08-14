# Fabrication Audit

**Requirement: the pipeline must never present unobserved data as observed.**

A substituted value is worse than a missing one, because the reader cannot tell
it apart from a measurement. This file tracks every known site where the code
produces a figure, category, or verdict that did not come from the footage.

Status is **OPEN** unless a fix is recorded. This document is deliberately a
liability list, not an achievement list — it exists to stop a partial fix from
reading as a complete one.

---

## The rule

When an input is absent, the output must be **`None` / `"unavailable"`**, never:

- a neutral-looking number (`0.5`, `0.3`)
- a legitimate-looking zero (`0.0`, `0%`, `[]`)
- a plausible category (`"unknown"` is acceptable; `"broadcast_fixed_wide"` is not)
- a value carried over from a different subject (one team's figure for another)

Where a metric has several inputs and only some are missing, **renormalise over
what was measured** rather than substituting for what was not — and record which
components contributed.

---

## FIXED

| # | Site | What was fabricated |
|---|---|---|
| F1 | `deep_skill_metrics.py` `calc_player_metrics` | `obs.get("rating", 3)` invented a rating for every observation, making `player_role_consistency` **1.00** and `player_positioning_stability` **0.60** constants for every player in every match. Now `None` + `value_type: "unavailable"`. |
| F2 | `deep_skill_metrics.py` `calc_chance_creation_profile` | High-danger share compared a *column* vocabulary against *row* values, so it published **"0% from high-danger zones"** on every match. Now classified on the row, over known-row chances only, `None` when none are known. |
| F3 | `deep_skill_metrics.py` `calc_compactness` | Substituted an **assumed 0.30** pressing value when none was recorded — ~20% of every published compactness score was invented. Now renormalises to line height alone. |
| F4 | `deep_skill_metrics.py` `calc_compactness` | Returned **0.0** when the defensive line was never read, publishing "maximally expansive". Now `None`. |
| F5 | `deep_skill_metrics.py` `calc_momentum_by_window` | Substituted **0.5** for absent press/line-height, contributing up to 55% of the momentum figure as invention. Now renormalises over measured components; each component reports `None` when unobserved. |
| F6 | `deep_skill_metrics.py` `calc_build_up_effectiveness` | Returned **0.0** rates with zero sequences, published as *"0% of sequences reached the final third"* — a verdict on play never watched. Now `None` + explicit unavailable summary. |
| F8 | `generate_flagged_moments.py` (deleted) | Defaulted `source_type` to the literal `"broadcast_fixed_wide"` and printed it as fact in the report footer, contradicting the runner's `"veo_ball_tracking"` default for the same field. **Resolved by removing the report entirely** — flagged moments are now folded into the tactical and opposition reports. |
| F9 | `cost_estimator.py` `print_estimate` | Priced a match against **zero windows** on a cold directory, because every per-window cost scales with `total_windows` from `window_plan.json`. Printed ~$0.73 against a real $8.75 for the same video — a 12x understatement that exited 0 and read as success, then persisted it to `cost_estimate.json`. Now refuses: `ESTIMATE UNAVAILABLE`, exit 2, `estimate_available: false`. **Found by a dry run on real footage, not by static analysis.** |
| F7 | `deep_skill_metrics.py` `calculation_basis` | Published formulas the code did not implement (`60/40` while computing `80/20`; `/12` while dividing by `4`). Basis strings are now generated from the same constants the arithmetic uses. |

Each is covered by a regression test in `tests/test_audit_fixes.py`, and each
test was mutation-checked — the defect was reintroduced and the suite confirmed
to fail.

---

## OPEN — verified, still fabricating

These were confirmed against the code during the audit and are **not yet fixed**.

| # | Site | What is fabricated | Reaches |
|---|---|---|---|
| O1 | `build_readiness_check.py:133` | `suppressed_families = []` is hardcoded with the comment "no suppressed families in this pipeline", while `source_profiler.py:165` computes real suppression state. | `report_readiness.json` **and** `confidence_reliability_report.json` — the artefact whose entire job is stating what could not be measured asserts nothing was suppressed. |
| O2 | `build_readiness_check.py:79-83` | With no operator event list the `known_events` loop never runs, giving `events_checked=0, missed=0`, which sets `event_validation_passed: true`. | Terminal prints "All events accounted for"; the readiness file records validation as passed when nothing was checked. |
| O4 | `validation/compare_counter1.py:134-144` | `claimed_count` is hardcoded `0` and the finding string hardcodes `"CARDS -- 5 real, 0 claimed"` regardless of input — a fixture-specific value emitted as a measurement. | `counter1_result.json` |
| O5 | `validation/compare_counter1.py:176` | `re.match` fails on the `W02_1H_05-10min` label form, so every window is scored against a fabricated `"level"` truth, and every window the pipeline labelled `level` counts as agreeing. | Prints "22/22 windows agree with true score timeline". |
| O6 | `accumulator.py:518` + `PITCH_LENGTH_M` | Pitch length is assumed **105 m**; `_pct_to_m(pct, pitch=105.0)` is never called with a real value, and `pitch_validation.py`'s venue table is empty, so a correctly recorded 100 m pitch still yields metre figures computed at 105 m. | Every line-height metre figure in the reports (~5% overstatement on a 100 m pitch). |
| O7 | `accumulator.py:550-553` | `derived_avg_pct = (home + away) / 2` — both teams' defensive lines averaged, then labelled `subject_team: "focus"`. | A focus team defending at 31.5 m is reported at **47.3 m** ("high line") when the opponent presses high. Not absent data — data attributed to the wrong subject. |
| O8 | `accumulator.py:760-779` | Vertical progressions and defensive-third turnovers pooled across **both** teams with no filter, though the possession block 40 lines above does split by team. | `progressive_rate` reported as the focus team's build-up effectiveness when it is the average of both. |
| O9 | `deep_skill_metrics.py` (zone keys) | Metrics read `zone_start`/`zone_end`; the structural prompt emits `start_zone`/`end_zone`. 120 real sequences yield `pattern_reliability = 0.0`, which `calc_predictability` turns into **`predictability_score = 0.4`, category "mixed"** — a prose claim derived from zero observations. | Tactical report build-up section. |
| O10 | `zone_helpers.py:244-249` | A missing `off_ball_coverage_score` defaults to `0`, tripping the `< 0.4` branch, and `between_lines` is then written as `None` **into every `*_merged.json` on disk**. `player_aggregator.py:853` defaults the same field to `1`. | Destroys source data; `between_lines_rate` then reads `0.00` for every player as a measured value. |
| O11 | `deep_skill_metrics.py:1112-1128` | Backward-shift rate divides by *all* windows including those with no line reading; `from_pct`/`to_pct` default to `0`, so a shift recording only `{"from_pct": 45}` counts as backward — missing data becomes a vulnerability event. | Line-security score and its window count. |
| O12 | `deep_skill_metrics.py:1651-1658` | Fitness trajectory compares thirds of the *observed* subset but reports the full window count as its sample: 9 readable windows of 20 yields a "first vs last third of match" claim with `sample_n = 20`. | Conditioning read in the report. |
| O13 | `player_aggregator.py:395-423` | Windows with zero observations are dropped before the early/late split, so a player who disappears after window 5 scores arc `"stable"` with `avg_obs_late_windows: 10.0`. | Player cards; `fading_late` can never fire for total disappearance. |
| O14 | `deep_skill_metrics.py:1242-1257` | Transition rates pool `transitions + flagged_moments + key_moments + resolved confirmations` un-deduplicated. One counter-attack logged three ways clears the `len < 3` gate and reports `attack_threat_rate = 1.00, sample_n = 3`. | Transition metrics. |
| O15 | `accumulator.py:1318-1319` | `windows_appeared += 1` sits inside the per-observation loop, so 4 observations in one window count as 4 windows. `synthesis_agent.py:990` gates the tendency table on `>= 3`. | A single-window burst published as a cross-match tendency. |
| O16 | `deep_skill_metrics.py:963` / `:948` | `SOURCE_GLOBAL_CAP.get(source_type, 0.5)` and `EVIDENCE_TIER_CAP.get(worst_tier, 0.4)` silently supply a confidence cap for source types and tiers not in the table — including `broadcast_fixed_wide`, which `source_profiler` rewrites to `unknown`. | Every metric's published confidence. |
| O17 | `build_readiness_check.py:121, 240` | `classification_confidence` and `avg_confidence` default to `0.0` when the source profile or metrics file is absent — indistinguishable from a genuine zero-confidence measurement, and published alongside `report_ready: true`. | `confidence_reliability_report.json` |

---

## Not fabrication (checked, recorded so they are not re-raised)

- `"unknown"` string defaults (`source_type`, `top_route`, `dominant_trigger`, …)
  are honest: they name the absence rather than inventing a value. They become a
  problem only when a *specific plausible* value is substituted instead — see O3.
- `frame_preprocessor.py:101` `num / den if den > 0 else 0.0` — internal ratio,
  not published.
- `calc_momentum_by_window` possession weighting was already safe: the weight
  dropped to `0.0` when possession was absent, so the `0.5` never contributed.

---

## Suggested order

O1, O2 and O17 first: they are the ones that make the *reliability report* —
the artefact whose whole purpose is disclosing limitations — assert that nothing
was limited. A tool that overstates its own reliability fails at exactly the
moment its output matters.

Then O7, O8, O9 and O10: these publish numbers attributed to the wrong subject
or derived from zero observations, which is the most damaging class in a
delivered tactical report.

O6 (pitch length) is a product decision as much as a fix: either read the real
dimensions through to `_pct_to_m`, or state on every metre figure that 105 m was
assumed.
