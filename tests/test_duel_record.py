"""Duel outcomes are counts. The denominator for a rate is not knowable.

The published report said Dion Frary had an "82% win rate across 11 contested
duels". His actual record was 9 won, 0 lost, 2 contested, of which 7 were
aerial. The 82% was wins divided by times-VISIBLE, counting contested duels as
losses and mixing ground duels into a figure labelled aerial.

Even corrected, a rate would mislead: 73 duels were logged across 98 minutes
(0.74/min against a competitive norm of 1.2-1.8), so roughly half the match's
duels were never observed -- and the missing half is the half away from the
ball, not a random half.
"""
import pytest

from duel_record import TYPICAL_PER_MIN, build, strip_outcomes


def _duel(kind, winner, *tokens, ts="10m00s"):
    return {"timestamp": ts, "type": kind, "winner": winner,
            "players_visible": list(tokens), "zone": {}, "window": "1H"}


def _summary(*duels):
    return {"duels": list(duels)}


# ── counting ─────────────────────────────────────────────────────────────────

def test_a_win_is_credited_to_the_side_that_won_it():
    r = build(_summary(_duel("aerial", "home_kit", "#4 home_kit", "#9 away_kit")))

    assert r["players"]["#4 home_kit"]["won"] == 1
    assert r["players"]["#9 away_kit"]["lost"] == 1


def test_contested_is_neither_won_nor_lost():
    """The report counted these as losses, which deflates every figure."""
    r = build(_summary(_duel("aerial", "contested", "#4 home_kit", "#9 away_kit")))

    for p in ("#4 home_kit", "#9 away_kit"):
        assert r["players"][p]["contested"] == 1
        assert r["players"][p]["won"] == 0
        assert r["players"][p]["lost"] == 0


def test_ground_duels_do_not_count_toward_the_aerial_tally():
    """A figure labelled aerial that includes ground duels is mislabelled."""
    r = build(_summary(
        _duel("aerial", "home_kit", "#4 home_kit"),
        _duel("ground", "home_kit", "#4 home_kit")))
    rec = r["players"]["#4 home_kit"]

    assert rec["aerial"] == 1 and rec["ground"] == 1 and rec["observed"] == 2


def test_shirt_number_alone_is_not_an_identity():
    """Both teams have a #4. Conflating them merges two players' records."""
    r = build(_summary(
        _duel("aerial", "home_kit", "#4 home_kit", "#4 away_kit")))

    assert r["players"]["#4 home_kit"]["won"] == 1
    assert r["players"]["#4 away_kit"]["lost"] == 1


def test_a_token_with_no_recognisable_side_is_ignored():
    r = build(_summary(_duel("aerial", "home_kit", "#4 home_kit", "unknown")))

    assert "unknown" not in r["players"]


# ── no rates anywhere ────────────────────────────────────────────────────────

def test_no_rate_or_percentage_is_ever_emitted():
    """Absent beats forbidden. A rule telling a writer to ignore a number it
    has been handed has failed three times in this project."""
    r = build(_summary(_duel("aerial", "home_kit", "#4 home_kit")), 90)
    blob = repr(r).lower()

    assert "win_rate" not in blob and "winrate" not in blob
    assert "pct" not in blob and "percent" not in blob
    for rec in r["players"].values():
        assert all(isinstance(v, int) for v in rec.values())


def test_the_record_carries_its_own_reporting_rule():
    """Stated in the data, not only in a prompt, so a reader who never sees
    the prompt still gets the caveat alongside the numbers."""
    r = build(_summary(_duel("aerial", "home_kit", "#4 home_kit")))

    assert "Counts only" in r["reporting_rule"]
    assert "VISIBLE" in r["reporting_rule"]


# ── coverage ─────────────────────────────────────────────────────────────────

def test_coverage_states_how_much_of_the_contest_was_missed():
    """73 duels in 98 minutes is about half a match's worth."""
    r = build(_summary(*[_duel("aerial", "home_kit", "#4 home_kit")] * 73), 98.0)
    c = r["coverage"]

    assert c["duels_logged"] == 73
    assert c["logged_per_minute"] == pytest.approx(0.74, abs=0.01)
    assert 0.45 < c["estimated_share_observed"] < 0.55


def test_coverage_is_absent_rather_than_guessed_without_a_duration():
    assert build(_summary(_duel("aerial", "home_kit", "#4 home_kit")))["coverage"] is None


def test_the_typical_rate_is_a_range_not_a_point():
    lo, hi = TYPICAL_PER_MIN
    assert lo < hi


# ── the raw array ────────────────────────────────────────────────────────────

def test_the_winner_is_removed_from_the_per_event_records():
    """The event detail is worth keeping -- a header at 34:20 in the left
    channel is a real observation. The outcome is removed so no rate can be
    recomputed from the array."""
    out = strip_outcomes([_duel("aerial", "home_kit", "#4 home_kit")])

    assert "winner" not in out[0]
    assert out[0]["timestamp"] == "10m00s" and out[0]["type"] == "aerial"
    assert out[0]["outcome_in"] == "duel_record.players"


def test_stripping_does_not_mutate_the_input():
    src = [_duel("aerial", "home_kit", "#4 home_kit")]
    strip_outcomes(src)

    assert src[0]["winner"] == "home_kit"


# ── the team-level metric that was always 100% ───────────────────────────────

def test_the_team_aerial_rate_reflects_both_sides():
    """Two bugs sat in six lines. The denominator counted wins by this team or
    by "opposition" -- a value the data has never held -- so total equalled won
    and every team scored 100%. And the rate was asked for by club name
    ("Gorleston") where the data holds a kit token, so wins were always zero.
    Checked by behaviour: asserting on the source text passes as soon as a
    comment mentions the old value, which is how the first version of this
    test broke.
    """
    from deep_skill_metrics import calc_aerial_dominance

    r = calc_aerial_dominance({
        "home_team": "Gorleston",
        "duels": [_duel("aerial", "home_kit", "#4 home_kit"),
                  _duel("aerial", "home_kit", "#5 home_kit"),
                  _duel("aerial", "away_kit", "#9 away_kit"),
                  _duel("aerial", "contested", "#6 home_kit")]})

    assert r["aerial_win_rate"] == 0.67, "2 of 3 decided, contested excluded"
    assert r["aerial_duels_total"] == 4


# ── one implementation ───────────────────────────────────────────────────────

def test_post_duel_outcomes_are_counted_on_the_win():
    """Winning a header and conceding the second ball is a different event
    from winning it and keeping the ball."""
    r = build(_summary(
        {**_duel("aerial", "home_kit", "#4 home_kit"),
         "post_duel_outcome": "retained_possession"},
        {**_duel("aerial", "home_kit", "#4 home_kit"),
         "post_duel_outcome": "lost_to_second_ball"}))
    rec = r["players"]["#4 home_kit"]

    assert rec["won"] == 2 and rec["retained"] == 1 and rec["lost_to_second"] == 1


def test_an_outcome_after_a_loss_is_not_credited():
    r = build(_summary(
        {**_duel("aerial", "away_kit", "#4 home_kit"),
         "post_duel_outcome": "retained_possession"}))

    assert r["players"]["#4 home_kit"]["retained"] == 0


def test_deep_skill_metrics_delegates_rather_than_counting_again():
    """It used to count duels itself, with `total` meaning times-visible and a
    contested duel indistinguishable from a loss. Two implementations of one
    count is how team-side resolution reached five."""
    import inspect

    import deep_skill_metrics as dsm

    src = inspect.getsource(dsm._metric_duel_effectiveness)
    assert "duel_record.build" in src
    assert "players_visible" not in src, "counting its own again"
    assert "win_rate" not in src and "retention_rate" not in src


def test_the_metric_publishes_counts_and_no_rate():
    import deep_skill_metrics as dsm

    m = dsm._metric_duel_effectiveness(
        _summary(_duel("aerial", "home_kit", "#4 home_kit", "#9 away_kit")),
        "veo_ball_tracking")
    rec = m["value"]["#4 home_kit"]

    assert rec["observed"] == 1 and rec["won"] == 1
    assert not [k for k in rec if "rate" in k]
    assert "not knowable" in m["calculation_basis"]


def test_the_metric_carries_the_reporting_rule_as_its_limitation_note():
    """The caveat travels with the numbers, not only in the prompt."""
    import deep_skill_metrics as dsm

    m = dsm._metric_duel_effectiveness(
        _summary(_duel("aerial", "home_kit", "#4 home_kit")), "veo_ball_tracking")

    assert "VISIBLE" in (m["limitation_note"] or "")
