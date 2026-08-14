"""Regression tests for the AUDIT-2026-08 fixes.

Each test names the finding it guards. They are written to fail loudly if the
original defect returns, so the fix cannot be silently undone by a later edit.

Scope note: these cover pure logic only. See tests/conftest.py — video, image
and API paths are stubbed, not exercised.
"""
import json
import os
import tempfile

import pytest


# ── A1: the readiness gate must actually gate ────────────────────────────────

def _gate(payload, override=False):
    from pipeline_runner_v2 import _report_gate_open
    d = tempfile.mkdtemp()
    if payload is not None:
        with open(os.path.join(d, "report_readiness.json"), "w") as f:
            f.write(payload)
    return _report_gate_open(d, override=override), d


def test_a1_gate_open_when_ready():
    ok, _ = _gate(json.dumps({"report_ready": True}))
    assert ok is True


def test_a1_gate_closed_when_not_ready():
    """The original defect: report_ready was computed and ignored."""
    ok, _ = _gate(json.dumps({"report_ready": False,
                              "blocking_issues": ["boundary confidence 0.4"]}))
    assert ok is False


def test_a1_gate_fails_closed_when_file_missing():
    """The gate not having run is not evidence the pipeline is healthy."""
    ok, _ = _gate(None)
    assert ok is False


def test_a1_gate_fails_closed_on_corrupt_json():
    ok, _ = _gate("{not json")
    assert ok is False


def test_a1_override_opens_gate_and_records_the_decision():
    ok, d = _gate(json.dumps({"report_ready": False, "blocking_issues": ["x"]}),
                  override=True)
    assert ok is True
    with open(os.path.join(d, "report_readiness.json")) as f:
        assert json.load(f)["readiness_overridden"] is True


def test_a1_report_ready_has_a_reader_outside_the_writer():
    """Guards the shape of the bug: the flag existed but nothing consumed it."""
    import pipeline_runner_v2 as p
    src = open(p.__file__, encoding="utf-8").read()
    assert "report_ready" in src, "the runner must consult report_ready"


# ── A3: player metrics must not be fabricated from a forbidden field ─────────

def test_a3_metrics_unavailable_when_no_ratings():
    """SKILL.md forbids agents emitting `rating`; the default fabricated a 3,
    making both metrics constants (1.00 / 0.60) for every player."""
    from deep_skill_metrics import calc_player_metrics
    summary = {"individual_observations": [
        {"player": "#10", "observation": "drops between lines"},
        {"player": "#10", "observation": "switches play"},
    ]}
    (pm,) = calc_player_metrics(summary, {"items": []})
    assert pm["player_role_consistency"] is None
    assert pm["player_positioning_stability"] is None
    assert pm["observations_count"] == 2, "must count observations, not ratings"
    assert pm["ratings_count"] == 0


def test_a3_metrics_still_compute_when_ratings_are_real():
    from deep_skill_metrics import calc_player_metrics
    summary = {"individual_observations": [
        {"player": "#7", "observation": "a", "rating": 4},
        {"player": "#7", "observation": "b", "rating": 2},
    ]}
    (pm,) = calc_player_metrics(summary, {"items": []})
    # mean 3.0, variance 1.0 -> 1 - 1/4 = 0.75 ; 3.0/5 = 0.6
    assert pm["player_role_consistency"] == 0.75
    assert pm["player_positioning_stability"] == 0.6


def test_a3_no_fabricated_rating_default_remains():
    """Checked via AST, not text search: the fix's own explanatory comment
    quotes the old expression, so a substring check would match the comment."""
    import ast
    import deep_skill_metrics as d
    tree = ast.parse(open(d.__file__, encoding="utf-8").read())
    for node in ast.walk(tree):
        if (isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "get"
                and len(node.args) == 2
                and isinstance(node.args[0], ast.Constant)
                and node.args[0].value == "rating"):
            pytest.fail(f"fabricated rating default is back at line {node.lineno}")


# ── A5/A6: published provenance must match the arithmetic ────────────────────

def test_a5_a6_calculation_basis_is_generated_from_the_constants():
    """The durable guard: basis strings are rendered from the same constants the
    computation uses, so they cannot drift apart again."""
    import deep_skill_metrics as d
    assert f"{d.COMPACTNESS_W_HEIGHT:.0%}" in d.COMPACTNESS_BASIS
    assert f"{d.COMPACTNESS_W_PRESSING:.0%}" in d.COMPACTNESS_BASIS
    assert str(d.ROUTE_DIVERSITY_CEILING) in d.ROUTE_DIVERSITY_BASIS


def test_a5_a6_weights_sum_to_one():
    # Plain float comparison rather than pytest.approx: conftest stubs numpy,
    # and approx introspects sys.modules["numpy"] when it is present.
    import deep_skill_metrics as d
    assert abs((d.COMPACTNESS_W_HEIGHT + d.COMPACTNESS_W_PRESSING) - 1.0) < 1e-9


def test_a5_a6_no_hardcoded_formula_strings_remain():
    import deep_skill_metrics as d
    src = open(d.__file__, encoding="utf-8").read()
    assert "Line height stability (60%)" not in src
    assert "pairs / 12" not in src


def test_a6_compactness_arithmetic_unchanged():
    """Provenance was corrected; the values were deliberately NOT changed."""
    from deep_skill_metrics import calc_compactness
    score, _, n, _, _ = calc_compactness({
        "line_height_by_window": [{"avg_pct": 40.0}, {"avg_pct": 50.0}],
        "pressing_by_window": [{"avg_score": 6.0}]})
    # height_score = 1 - 0.45 = 0.55 ; press = 0.6 ; .55*.8 + .6*.2 = 0.56
    assert score == 0.56
    assert n == 2


# ── A7: high-danger share must classify on the row vocabulary ────────────────

def test_a7_high_danger_uses_row_not_column():
    """`shot_zone` held origin_column (lateral) but was tested against row
    values, so the share was structurally always 0%."""
    from deep_skill_metrics import calc_chance_creation_profile
    shots = [{"timestamp": "10m00s", "origin_column": "central",
              "origin_row": "six_yard_box"},
             {"timestamp": "20m00s", "origin_column": "left_channel",
              "origin_row": "penalty_spot"},
             {"timestamp": "30m00s", "origin_column": "central",
              "origin_row": "outside_box"}]
    prof, _, _ = calc_chance_creation_profile({"shots_for": shots},
                                              {"sequences": []})
    assert prof["high_danger_chances"] == 2
    assert prof["low_danger_chances"] == 1
    assert prof["high_danger_pct"] == 67
    assert prof["chances_with_known_row"] == 3


def test_a7_unavailable_rather_than_zero_when_row_absent():
    from deep_skill_metrics import calc_chance_creation_profile
    prof, _, _ = calc_chance_creation_profile(
        {"shots_for": [{"timestamp": "10m00s", "origin_column": "central"}]},
        {"sequences": []})
    assert prof["high_danger_pct"] is None, "absent data must not read as 0%"
    assert prof["chances_with_known_row"] == 0


# ── A4: moment time must resolve either key ──────────────────────────────────

def test_a4_moment_time_prefers_canonical_minute():
    from pipeline_accessors import get_moment_time
    assert get_moment_time({"minute": "38:00"}) == "38:00"
    assert get_moment_time({"timestamp": "12m30s"}) == "12m30s"
    assert get_moment_time({"minute": "38:00", "timestamp": "99m99s"}) == "38:00"
    assert get_moment_time({}) == ""


def test_a4_ground_truth_matches_moments_carrying_minute():
    """The defect: ground_truth read `timestamp` only, so every known event
    scored as missed."""
    from ground_truth import find_event_in_moments
    moments = [{"minute": "38:00", "type": "goal"},
               {"timestamp": "12m30s", "type": "substitution"}]
    assert find_event_in_moments({"type": "goal", "minute": 38}, moments)
    assert find_event_in_moments({"type": "sub", "minute": 12}, moments)


def test_a4_unrelated_event_still_misses():
    """Guards against 'fixing' the match by making it match everything."""
    from ground_truth import find_event_in_moments
    moments = [{"minute": "38:00", "type": "goal"}]
    assert find_event_in_moments({"type": "goal", "minute": 80}, moments) is None


# ── A13: the dual-agent merge must not drop schema fields ────────────────────

DUAL_MERGE_DROPPED = ["timestamp_range", "half", "match_state", "score_home",
                      "score_away", "confidence", "source_limitations"]


def test_a13_event_window_merge_preserves_all_schema_fields():
    import merge_utils as mu
    d = tempfile.mkdtemp()
    a = {"timestamp_range": "30:00-35:00", "half": "1H",
         "match_state": "away_winning", "score_home": 0, "score_away": 1,
         "confidence": 0.85, "source_limitations": "far side occluded",
         "formation": {"home": "4-2-3-1", "away": "4-4-2"},
         "defensive_line": {"avg_pct": 42}, "pressing": {"avg_score": 6},
         "key_moments": [{"minute": "32:00", "type": "goal"}],
         "pass_sequences": [], "set_pieces": []}
    b = {"event_agent": True, "events": [{"type": "goal"}]}
    ap = os.path.join(d, "agent_07_structural.json")
    bp = os.path.join(d, "agent_07_event.json")
    op = os.path.join(d, "agent_07_1H_30-00-35-00_merged.json")
    for path, obj in ((ap, a), (bp, b)):
        with open(path, "w") as f:
            json.dump(obj, f)

    mu.merge_dual_agents(ap, bp, op, "07", d)
    with open(op) as f:
        merged = json.load(f)

    missing = [k for k in DUAL_MERGE_DROPPED if k not in merged]
    assert not missing, f"dual merge dropped: {missing}"
    # match_state specifically: accumulator skips the window on a falsy value,
    # leaving holes at exactly the goal windows.
    assert merged["match_state"] == "away_winning"
    # computed keys must still win over the spread
    assert merged["merge_type"] == "dual_agent"


# ── A14: frames must order chronologically past minute 99 ────────────────────

def test_a14_frame_sort_key_orders_past_minute_99():
    from pipeline_paths import frame_sort_key
    names = ["frame_100m00s.jpg", "frame_97m30s.jpg",
             "frame_99m00s.jpg", "frame_102m00s.jpg"]
    assert [os.path.basename(p) for p in sorted(names, key=frame_sort_key)] == [
        "frame_97m30s.jpg", "frame_99m00s.jpg",
        "frame_100m00s.jpg", "frame_102m00s.jpg"]


def test_a14_unparseable_names_sort_deterministically_not_raise():
    from pipeline_paths import frame_sort_key
    got = sorted(["odd.jpg", "frame_01m00s.jpg", "another.png"],
                 key=frame_sort_key)
    assert got == ["another.png", "odd.jpg", "frame_01m00s.jpg"]


def test_a14_window_frames_are_chronological():
    from pipeline_paths import frame_sort_key
    from pipeline_runner_v2 import get_window_frames
    d = tempfile.mkdtemp()
    fr = os.path.join(d, "frames", "07")
    os.makedirs(fr)
    for m in (97, 98, 99, 100, 101, 102):
        open(os.path.join(fr, f"frame_{m:02d}m00s.jpg"), "w").close()
    got = get_window_frames(d, {"agent_id": "07"}, 6)
    assert got == sorted(got, key=frame_sort_key)
    assert os.path.basename(got[0]) == "frame_97m00s.jpg"


def test_a14_all_frame_sorts_use_the_canonical_key():
    """Four modules sort frame lists; all must use frame_sort_key."""
    for mod in ("pipeline_runner_v2", "jersey_ocr",
                "frame_extraction", "frame_preprocessor"):
        src = open(os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            f"{mod}.py"), encoding="utf-8").read()
        assert "frame_sort_key" in src, f"{mod} does not use the canonical key"


# ── NO FABRICATION: absent input must never become a plausible number ────────
#
# The system's credibility rests on every published figure tracing to a real
# observation. These tests assert that missing data yields None/unavailable
# rather than a neutral-looking value that reads as a measurement.

def test_nofab_compactness_unavailable_when_line_never_read():
    from deep_skill_metrics import calc_compactness
    score, avg_m, n, _, cat = calc_compactness(
        {"line_height_by_window": [], "pressing_by_window": []})
    assert score is None, "0.0 would publish 'maximally expansive' for unread data"
    assert avg_m is None and n == 0


def test_nofab_compactness_uses_height_alone_when_pressing_absent():
    """Pressing used to fall back to an assumed 0.30, inventing ~20% of the
    score. With pressing absent the score must be height alone, not a blend
    with a guess."""
    from deep_skill_metrics import calc_compactness
    score, _, _, _, _ = calc_compactness(
        {"line_height_by_window": [{"avg_pct": 40.0}], "pressing_by_window": []})
    assert score == 0.6                       # 1 - 0.40, full weight
    # the old behaviour blended in 0.30 -> 0.6*0.8 + 0.3*0.2 = 0.54
    assert score != 0.54


def test_nofab_no_assumed_pressing_constant_remains():
    import deep_skill_metrics as d
    assert not hasattr(d, "COMPACTNESS_PRESS_ABSENT")


def test_nofab_momentum_renormalises_over_measured_components():
    """A missing component must contribute nothing, not a neutral 0.5."""
    from deep_skill_metrics import calc_momentum_by_window
    got = calc_momentum_by_window({
        "pressing_by_window":    [{"window": "W01", "avg_score": 8.0}],
        "line_height_by_window": [],
        "possession_by_window":  [],
    })
    (row,) = got
    # press only: 0.8 renormalised over its own weight -> 0.8, not a 0.5 blend
    assert row["momentum"] == 0.8
    assert row["components"]["line_height"] is None
    assert row["components"]["possession"] is None


def test_nofab_build_up_rates_unavailable_with_no_sequences():
    """Used to return 0.0 rates, published as '0% reached the final third' --
    a verdict on build-up that was never observed."""
    from deep_skill_metrics import calc_build_up_effectiveness
    v, total, prog, threats, ft, prog_rate, ft_rate, conv_rate, _ = \
        calc_build_up_effectiveness({"sequences": []})
    assert v is None
    assert prog_rate is None and ft_rate is None and conv_rate is None
    assert total == 0


def test_nofab_build_up_rates_still_compute_with_real_sequences():
    from deep_skill_metrics import calc_build_up_effectiveness
    seqs = [{"progressive": True, "outcome": "shot",
             "zone_start": "middle", "zone_end": "attacking_third"},
            {"progressive": False, "outcome": "loss",
             "zone_start": "middle", "zone_end": "middle"}]
    v, total, prog, threats, ft, prog_rate, ft_rate, conv_rate, _ = \
        calc_build_up_effectiveness({"sequences": seqs})
    assert total == 2 and prog == 1 and threats == 1
    assert prog_rate == 0.5 and ft_rate == 0.5 and conv_rate == 0.5


# ── Removed deliverables: flagged_moments.md / pass_network.md ───────────────
#
# Folded into the tactical and opposition reports. These guard against the
# generators or their pipeline steps being reintroduced by a later merge.

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def test_removed_generators_are_gone():
    for name in ("generate_flagged_moments.py", "generate_pass_network.py"):
        assert not os.path.exists(os.path.join(REPO, name)), f"{name} is back"


def test_removed_pipeline_steps_are_unregistered():
    for mod in ("pipeline_state.py", "pipeline_runner_v2.py", "md_to_docx.py"):
        src = open(os.path.join(REPO, mod), encoding="utf-8").read()
        for token in ("4c_flagged_moments", "4d_pass_network"):
            assert token not in src, f"{token} still registered in {mod}"


def test_synthesis_takes_moments_from_running_summary_not_a_rendered_file():
    """3l_synthesis ran BEFORE the phase that wrote flagged_moments.md, so the
    old _load_text always returned "". Moments now come from structured data."""
    import synthesis_agent as sa
    src = open(sa.__file__, encoding="utf-8").read()
    assert '_load_text(os.path.join(match_dir, "flagged_moments.md"))' not in src
    assert '"flagged_moments.md"' not in src.split("OPTIONAL_FILES")[1][:400]


def test_synthesis_bundle_exposes_moments_from_the_summary(tmp_path):
    import synthesis_agent as sa
    for name, payload in (
        ("match_config.json", {"home_team": "A", "away_team": "B"}),
        ("running_summary.json", {"flagged_moments": [{"minute": "38:00"}],
                                  "key_moments": [{"minute": "12:00"}]}),
        ("pass_sequences.json", {"sequences": []}),
    ):
        (tmp_path / name).write_text(json.dumps(payload))
    bundle = sa.build_input_bundle(str(tmp_path))
    assert bundle["flagged_moments"] == [{"minute": "38:00"}]
    assert bundle["key_moments"] == [{"minute": "12:00"}]


# ── Deliverable set: tactical + one opposition report per team, nothing else ─

def test_deliverables_are_exactly_three_reports():
    """The pipeline emits tactical_report.md and one opposition report per
    team. The unreachable 'advanced' tier that would have produced three more
    is removed."""
    import synthesis_agent as sa
    src = open(sa.__file__, encoding="utf-8").read()
    for token in ("advanced_tactical_report", "advanced_opposition_report",
                  "synthesise_advanced", "ADVANCED_SYNTHESIS_ADDITIONS"):
        assert token not in src, f"advanced synthesis tier is back: {token}"


def test_docx_conversion_targets_only_the_three_reports():
    import md_to_docx
    assert md_to_docx.REPORT_FILES == ["tactical_report.md",
                                       "opposition_report_*.md"]


def test_spec_has_no_machine_specific_paths():
    """SKILL.md told operators to run a script from
    C:\\Users\\<name>\\.claude\\skills\\match-analysis\\scripts\\ -- a path that
    exists on no current machine. F6 was fixed in the code and survived in the
    spec, because nothing ties the two together."""
    spec = open(os.path.join(REPO, "SKILL.md"), encoding="utf-8").read()
    for bad in ("C:\\Users", "/Users/", "AppData\\Local"):
        assert bad not in spec, f"machine-specific path back in SKILL.md: {bad}"


# ── Project skills live in the repo, and the spec has one authoritative copy ──

SKILLS = os.path.join(REPO, ".claude", "skills")


def test_required_skills_are_present_in_the_repo():
    for name in ("match-analysis", "matchlens-tactical-report",
                 "matchlens-opposition-report"):
        assert os.path.isdir(os.path.join(SKILLS, name)), f"missing skill: {name}"


def test_skill_spec_matches_repo_spec():
    """SKILL.md at the repo root is authoritative. The copy under
    .claude/skills/match-analysis/ exists only because a skill directory must
    contain its own SKILL.md. They had already drifted by 38 lines when the two
    copies lived in separate stores; this makes that impossible to repeat.

    To fix a failure here, re-sync from the root file (see .claude/skills/README.md).
    """
    root = open(os.path.join(REPO, "SKILL.md"), encoding="utf-8").read()
    copy = open(os.path.join(SKILLS, "match-analysis", "SKILL.md"),
                encoding="utf-8").read()
    assert root == copy, (
        "SKILL.md and .claude/skills/match-analysis/SKILL.md have diverged; "
        "re-sync from the repo root copy")


def test_report_skills_keep_their_own_assets():
    """render.py resolves assets as <skill_dir>/assets, so each skill must keep
    its own copy. Deduplicating into a shared directory would break it."""
    for name in ("matchlens-tactical-report", "matchlens-opposition-report"):
        for sub in ("assets/brand.css", "assets/fonts", "scripts/render.py"):
            assert os.path.exists(os.path.join(SKILLS, name, sub)), \
                f"{name} is missing {sub}"


def test_no_compiled_artifacts_committed_under_skills():
    for root_dir, dirs, files in os.walk(SKILLS):
        assert "__pycache__" not in dirs, f"__pycache__ under {root_dir}"
        assert not [f for f in files if f.endswith(".pyc")], f".pyc under {root_dir}"


# ── Cost estimate must not price a match it cannot price ─────────────────────

def test_estimate_refuses_on_a_cold_match_directory(tmp_path, capsys):
    """Every per-window cost scales with total_windows, which comes from
    window_plan.json. Cold, that is zero, and the estimator printed a confident
    total ~12x under the real figure and exited 0."""
    from cost_estimator import load_match_data, calculate_cost, print_estimate
    (tmp_path / "match_config.json").write_text(json.dumps(
        {"match": "X vs Y", "goals": [], "substitutions": []}))
    md = load_match_data(str(tmp_path))
    assert md["total_windows"] == 0
    ok = print_estimate(md, [calculate_cost(md, "standard")])
    assert ok is False, "a zero-window estimate must not be presented as usable"
    out = capsys.readouterr().out
    assert "ESTIMATE UNAVAILABLE" in out
    assert "$" not in out.split("ESTIMATE UNAVAILABLE")[1], \
        "no dollar figures may follow the unavailable notice"


def test_estimate_works_once_a_window_plan_exists(tmp_path):
    from cost_estimator import load_match_data, calculate_cost, print_estimate
    (tmp_path / "match_config.json").write_text(json.dumps(
        {"match": "X vs Y", "goals": [], "substitutions": []}))
    (tmp_path / "window_plan.json").write_text(json.dumps(
        {"windows": [{"agent_id": f"{i:02d}", "start_s": i*300,
                      "end_s": (i+1)*300} for i in range(20)]}))
    md = load_match_data(str(tmp_path))
    assert md["total_windows"] == 20
    est = calculate_cost(md, "standard")
    assert est["total_cost_usd"] > 0
    assert print_estimate(md, [est]) is True


# ── Missing ffprobe must degrade with a useful message, not crash ────────────

def test_missing_ffprobe_returns_an_actionable_error(monkeypatch):
    """subprocess.run raises FileNotFoundError before returncode exists, so the
    `returncode != 0` handler never covered a missing binary -- it covers a bad
    video. Step 1a is the first thing the pipeline runs, and on Windows the
    uncaught error reads '[WinError 2]' with no mention of ffmpeg."""
    import shutil as _sh
    import container_analyser as ca
    monkeypatch.setattr(ca.shutil, "which", lambda name: None)
    monkeypatch.setattr(ca.subprocess, "run", lambda *a, **k: (_ for _ in ()).throw(
        AssertionError("must not invoke ffprobe when it is absent")))
    result = ca.analyse_container("whatever.mp4")
    assert "ffprobe not found" in result["error"]
    assert "ffmpeg" in result["error"].lower()
    assert result["seek_reliable"] is False
    assert result["boundaries"] == []


def test_ffprobe_invoked_with_error_verbosity_not_quiet():
    """-v quiet empties stderr, so 'ffprobe failed: {stderr}' carried no
    diagnostic on a genuinely unreadable video."""
    import container_analyser as ca
    src = open(ca.__file__, encoding="utf-8").read()
    assert '"-v", "quiet"' not in src
    assert '"-v", "error"' in src


def test_hsv_saturation_does_not_divide_by_zero(recwarn):
    """np.where evaluated diff / mx eagerly, warning once per call."""
    import frame_preprocessor as fp
    src = open(fp.__file__, encoding="utf-8").read()
    assert "np.where(mx > 0, diff / mx, 0)" not in src
    assert "np.divide(diff, mx" in src


# ── Setup helpers ────────────────────────────────────────────────────────────

def test_new_match_writes_absolute_video_path(tmp_path):
    """video_path must be absolute so the video can live outside the match dir
    and the largest-file glob is never consulted."""
    import subprocess, sys as _s
    vid = tmp_path / "match.mp4"; vid.write_bytes(b"x" * 1024)
    mdir = tmp_path / "Match Dir"
    r = subprocess.run([_s.executable, os.path.join(REPO, "new_match.py"),
                        "--video", str(vid), "--home", "H", "--away", "A",
                        "--dir", str(mdir)], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    cfg = json.loads((mdir / "match_config.json").read_text())
    assert os.path.isabs(cfg["video_path"])
    assert cfg["home_team"] == "H" and cfg["away_team"] == "A"


def test_new_match_refuses_to_clobber_and_rejects_missing_video(tmp_path):
    import subprocess, sys as _s
    vid = tmp_path / "match.mp4"; vid.write_bytes(b"x" * 1024)
    mdir = tmp_path / "d"
    args = [_s.executable, os.path.join(REPO, "new_match.py"), "--home", "H",
            "--away", "A", "--dir", str(mdir)]
    assert subprocess.run(args + ["--video", str(vid)],
                          capture_output=True).returncode == 0
    # second run without --force must refuse
    assert subprocess.run(args + ["--video", str(vid)],
                          capture_output=True).returncode == 1
    # missing video must refuse
    assert subprocess.run(args + ["--video", str(tmp_path / "nope.mp4"), "--force"],
                          capture_output=True).returncode == 1


def test_new_match_sibling_check_is_case_insensitive(tmp_path):
    """The decoy is DJI_..._D.MP4. A check for a case-sensitivity trap must not
    itself be case-sensitive, or it misses the case it exists to catch."""
    src = open(os.path.join(REPO, "new_match.py"), encoding="utf-8").read()
    assert 'glob("*.mp4")' not in src
    assert 'suffix.lower() == ".mp4"' in src


def test_check_setup_mirrors_the_runners_env_search_order():
    """If preflight looks somewhere the runner does not, a green check can
    precede a keyless run."""
    setup_src = open(os.path.join(REPO, "check_setup.py"), encoding="utf-8").read()
    runner_src = open(os.path.join(REPO, "pipeline_runner_v2.py"), encoding="utf-8").read()
    for token in ('REPO / ".env"', 'REPO.parent / ".env"', 'Path.home() / ".env"'):
        assert token in setup_src, f"preflight missing search path: {token}"
    assert "Path.home()/'.env'" in runner_src or 'Path.home()/".env"' in runner_src


def test_check_setup_deduplicates_env_search_paths(tmp_path, monkeypatch, capsys):
    """On Windows with the repo at C:\\Users\\<name>\\Match-Lens-copy,
    REPO.parent and Path.home() are the same path and the list printed it
    twice."""
    import check_setup
    monkeypatch.setattr(check_setup, "REPO", tmp_path / "home" / "repo")
    monkeypatch.setattr(check_setup.Path, "home",
                        staticmethod(lambda: tmp_path / "home"))
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    check_setup.check_api_key()
    listed = [l for l in capsys.readouterr().out.splitlines()
              if l.strip().endswith(".env")]
    assert len(listed) == len(set(l.strip() for l in listed)), \
        f"duplicate paths printed: {listed}"


def test_no_deprecated_utcnow_remains():
    """utcnow() is deprecated from Python 3.12 and returns a NAIVE datetime that
    the old code labelled 'Z'. The machine running this is on 3.13."""
    import ast, pathlib
    for path in pathlib.Path(REPO).rglob("*.py"):
        if ".venv" in path.parts or "tests" in path.parts:
            continue
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if (isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Attribute)
                    and node.func.attr == "utcnow"):
                pytest.fail(f"datetime.utcnow() at {path.name}:{node.lineno}")


# ── .env encoding: the two ways a Windows .env silently fails ────────────────

def _preflight_env(tmp_path, monkeypatch, data: bytes):
    import check_setup
    (tmp_path / ".env").write_bytes(data)
    monkeypatch.setattr(check_setup, "REPO", tmp_path)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    return check_setup.check_api_key()


def test_preflight_diagnoses_utf16_env(tmp_path, monkeypatch, capsys):
    """PowerShell's `>` writes UTF-16. python-dotenv raises UnicodeDecodeError,
    and the preflight used to die with a raw traceback."""
    ok = _preflight_env(tmp_path, monkeypatch,
                        "ANTHROPIC_API_KEY=sk-ant-ABCD\n".encode("utf-16"))
    out = capsys.readouterr().out
    assert ok is False
    assert "UTF-16" in out and "WriteAllText" in out


def test_preflight_diagnoses_utf8_bom_env(tmp_path, monkeypatch, capsys):
    """The quiet one: PS 5.1 `-Encoding utf8` writes a BOM that becomes part of
    the first key name, so the lookup returns None with no error at all."""
    ok = _preflight_env(tmp_path, monkeypatch,
                        b"\xef\xbb\xbf" + b"ANTHROPIC_API_KEY=sk-ant-ABCD\n")
    out = capsys.readouterr().out
    assert ok is False
    assert "BOM" in out


def test_preflight_accepts_clean_utf8_env(tmp_path, monkeypatch, capsys):
    ok = _preflight_env(tmp_path, monkeypatch, b"ANTHROPIC_API_KEY=sk-ant-ABCD\n")
    assert ok is True
    assert "ABCD" in capsys.readouterr().out


def test_runner_reads_env_as_utf_8_sig():
    """utf-8-sig strips a BOM if present, so a BOM'd .env still works at runtime
    even though the preflight asks for it to be fixed."""
    for mod in ("pipeline_runner_v2.py", "synthesis_agent.py"):
        src = open(os.path.join(REPO, mod), encoding="utf-8").read()
        assert 'encoding="utf-8-sig"' in src, f"{mod} load_dotenv is not BOM-tolerant"
