"""Guards for the two concepts that caused most of this project's defects.

"Which team is this" and "which clock is this time on" were each implemented
five and four times respectively across the codebase. The copies diverged, and
that divergence produced calc_match_state, the ground-truth 100% miss rate, the
cost estimator's event-window count, the never-set event_window flag, and the
team_side collapse that attributed 176 of 223 observations to the wrong team.

These tests exist to keep both concepts single-implementation. The two
enforcement tests at the bottom are the ones that matter long-term: without
them the duplicates simply grow back.
"""
import ast
import io
import json
import os
import tokenize

import pytest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

import pipeline_accessors as pa


# -- match_config shape as production actually writes it ----------------------
# NOTE: no "team_side" key. Nothing in the pipeline has ever written one.
MC = {
    "home_team": "Gorleston",
    "away_team": "Tilbury",
    "lineups": [
        {"team": {"name": "Gorleston"},
         "startXI": [{"player": {"name": "Adam Tann", "number": 6}}],
         "substitutes": []},
        {"team": {"name": "Tilbury"},
         "startXI": [{"player": {"name": "Jack Hayes", "number": 6}}],
         "substitutes": []},
    ],
}

KO = {"ko_1h": 350.0, "ht_whistle": 3245.0, "ko_2h": 4269.0, "ft_whistle": 7282.0}


# -- team side ----------------------------------------------------------------

def test_resolve_team_side_without_the_key_production_never_writes():
    """The exact failure: no team_side key, both lineups must still resolve."""
    sides = [pa.resolve_team_side(l, MC) for l in MC["lineups"]]
    assert sides == ["home", "away"]


def test_resolve_team_side_prefers_explicit_when_present():
    lineup = dict(MC["lineups"][1], team_side="home")
    assert pa.resolve_team_side(lineup, MC) == "home"


def test_resolve_team_side_raises_rather_than_defaulting():
    """A silent default here is what routed all 32 players into one roster."""
    with pytest.raises(ValueError):
        pa.resolve_team_side({"team": {"name": "Norwich"}}, MC)


def test_normalise_side_covers_the_kit_spellings_agents_emit():
    assert pa.normalise_side("home_kit") == "home"
    assert pa.normalise_side("AWAY_KIT") == "away"
    assert pa.normalise_side("banana") is None


# -- match clock vs video clock -----------------------------------------------

@pytest.mark.parametrize("minute,expected", [(6, 710.0), (45, 3050.0), (59, 5109.0)])
def test_match_minute_matches_the_values_the_pipeline_recorded(minute, expected):
    """These three are the exact expected_seconds from the real run."""
    assert pa.match_minute_to_video_s(minute, KO) == pytest.approx(expected)


@pytest.mark.parametrize("minute", [0, 6, 45, 59, 88, 90])
def test_match_minute_round_trips(minute):
    v = pa.match_minute_to_video_s(minute, KO)
    assert pa.video_s_to_match_minute(v, KO) == pytest.approx(minute, abs=0.02)


def test_match_minute_raises_without_kickoff():
    """Defaulting ko_1h to 0 puts every event in the pre-match footage."""
    with pytest.raises(ValueError):
        pa.match_minute_to_video_s(45, {})


def test_match_minute_rejects_non_numeric():
    with pytest.raises(TypeError):
        pa.match_minute_to_video_s("45", KO)


def test_get_kickoff_seconds_reads_all_three_shapes_we_write():
    nested = {"boundaries": {"ko_1h": {"seconds": 350}}}
    flat_a = {"ko_1h_seconds": 350}
    flat_b = {"ko_1h_s": 350}
    for src in (nested, flat_a, flat_b):
        assert pa.get_kickoff_seconds(src)["ko_1h"] == 350.0


# -- the regression that would have caught the original defect ----------------

def test_player_prompt_renders_two_non_empty_disjoint_rosters(tmp_path):
    """THE test. The 3b prompt previously contained 32 away players and zero
    home players, which is structurally valid and silently catastrophic."""
    import pipeline_runner_v2 as pr
    (tmp_path / "match_config.json").write_text(json.dumps(MC), encoding="utf-8")
    window = {"agent_id": "01", "label": "1H 00-00-05-00", "half": "1H",
              "start_s": 350, "end_s": 650,
              "start_frame": "frame_05m50s.jpg", "end_frame": "frame_10m49s.jpg"}
    prompt = pr.build_player_prompt(str(tmp_path), window, MC, {})

    assert "=== PLAYER IDENTIFICATION ===" in prompt
    roster = prompt.split("=== PLAYER IDENTIFICATION ===", 1)[1]
    assert "HOME TEAM" in roster and "AWAY TEAM" in roster
    home_block = roster.split("HOME TEAM", 1)[1].split("AWAY TEAM", 1)[0]
    away_block = roster.split("AWAY TEAM", 1)[1][:400]
    assert "Adam Tann" in home_block, "home roster is empty or misfiled"
    assert "Jack Hayes" in away_block, "away roster is empty or misfiled"
    assert "Adam Tann" not in away_block, "home player leaked into away roster"


# -- enforcement: without these, the duplicates grow back ---------------------

def _code_only(path):
    """Source with comments and docstrings stripped, so prose about a defect
    does not trip the guard that prevents the defect."""
    with open(path, "rb") as fh:
        src = fh.read().decode("utf-8")
    out = []
    for tok in tokenize.generate_tokens(io.StringIO(src).readline):
        if tok.type == tokenize.COMMENT:
            continue
        out.append(tok.string if tok.type != tokenize.STRING else '""')
    return " ".join(out)


def _py_files():
    for name in sorted(os.listdir(REPO)):
        if name.endswith(".py") and name != "pipeline_accessors.py":
            yield os.path.join(REPO, name)


def test_no_module_reads_team_side_directly():
    """team_side is read via the accessor or not at all. Four modules used to
    read it raw against a key nothing writes."""
    offenders = [os.path.basename(p) for p in _py_files()
                 if "team_side" in _code_only(p).replace("resolve_team_side", "")
                 and ". get ( 'team_side'" in _code_only(p).replace('"', "'")]
    assert offenders == [], f"raw team_side reads reappeared in: {offenders}"


def test_only_the_accessor_defines_a_minute_to_video_conversion():
    """One implementation of match-minute -> video-seconds, not four."""
    offenders = []
    for path in _py_files():
        with open(path, encoding="utf-8") as fh:
            tree = ast.parse(fh.read(), filename=path)
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and "video_s" in node.name \
                    and "minute" in node.name:
                # A thin delegating wrapper is fine; a reimplementation is not.
                body = ast.dump(node)
                if "match_minute_to_video_s" not in body:
                    offenders.append(f"{os.path.basename(path)}:{node.name}")
    assert offenders == [], f"reimplemented minute->video conversion: {offenders}"
