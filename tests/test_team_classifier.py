"""Kit colour attribution, and the six ways it went wrong.

Every test here is a defect that shipped and was caught by annotating a frame
and looking at it. The classifier reproduced one hand-counted frame exactly --
9 away, 6 home, 1 keeper -- but three separate changes in a single session each
improved the average while breaking that frame. These pin the mechanisms so the
next change has to argue with something.
"""
import numpy as np
import pytest

from team_classifier import (
    BAND, COLLIDE, SKIN_HUE, SKIN_NEAR, SKIN_S,
    FrameResult, kit_hue, label_from_votes, resolve_anchors, theil_sen,
)

GREEN, RED, ORANGE, YELLOW = 50.0, 0.0, 12.0, 27.0
GRASS = 30


def _mc(home="green shirts", away="red shirts",
        home_gk="orange shirts", away_gk="yellow shirt"):
    return {"home_kit": home, "away_kit": away,
            "home_gk_kit": home_gk, "away_gk_kit": away_gk}


# ── kit names → hue ──────────────────────────────────────────────────────────

def test_kit_hue_reads_the_first_colour_word():
    assert kit_hue("green shirts, green shorts, green socks") == GREEN
    assert kit_hue("yellow shirt") == YELLOW


def test_an_unrecognised_kit_raises_rather_than_defaulting(): 
    """A kit with no colour word has no anchor. Guessing one would attribute
    every player on the pitch to a hue nobody chose."""
    with pytest.raises(ValueError):
        resolve_anchors(_mc(home="maroon and gold hoops"), GRASS)


# ── anchor collisions ────────────────────────────────────────────────────────

def test_orange_keeper_is_disabled_against_a_red_outfield_kit():
    """gk_orange sits at hue 12, inside the red kit's band of 0 +/- 16.

    Unchecked this turned three to five outfield players per frame into
    goalkeepers.
    """
    live, dead, _, _ = resolve_anchors(_mc(), GRASS)

    assert "home_gk" in dead
    assert "away" in live, "the outfield kit must survive the collision"


def test_an_outfield_kit_never_loses_to_a_keeper():
    """Precedence, not proximity. Ten players against one.

    The first version of this rule disabled the entire red TEAM because the
    orange keeper was close to it, which left one usable kit on the pitch.
    """
    live, dead, _, _ = resolve_anchors(_mc(), GRASS)

    assert "away" not in dead
    assert "home" not in dead


def test_a_dead_anchor_cannot_disable_a_live_one():
    """gk_yellow was disabled for colliding with gk_orange -- which had itself
    already been disabled for colliding with the red kit. Cascade."""
    live, dead, needs_value, _ = resolve_anchors(_mc(), GRASS)

    assert "away_gk" in live
    assert "away_gk" in needs_value, "kept, but gated on brightness"


def test_two_outfield_kits_that_collide_disable_both():
    """Then the match is not separable by colour and must say so, rather than
    assigning every player to whichever anchor won a coin toss."""
    live, dead, _, _ = resolve_anchors(_mc(home="red shirts"), GRASS)

    assert "home" in dead and "away" in dead
    assert "not separable" in dead["home"]


def test_disabling_a_keeper_states_the_consequence_not_just_the_cause():
    """The keeper does not vanish -- his pixels fall into the band that
    swallowed his colour, so that side runs one high in every frame he is in."""
    _, _, _, caveats = resolve_anchors(_mc(), GRASS)

    assert any("counted as a away outfield player" in c for c in caveats)


def test_a_kit_on_the_grass_hue_is_kept_and_gated_on_brightness():
    """Yellow at 27 against grass at 30 cannot be separated by hue. It can be
    separated by value -- turf sits near 57 -- so discarding the only keeper on
    the pitch would be throwing away a readable signal."""
    live, dead, needs_value, _ = resolve_anchors(_mc(home_gk="purple shirts"), GRASS)

    assert "away_gk" in live and "away_gk" in needs_value
    assert "away_gk (hue)" in dead and "brightness" in dead["away_gk (hue)"]


# ── vote arithmetic ──────────────────────────────────────────────────────────

def _votes(home, away, total, **extra):
    return {"home": home, "away": away, "_total": total, **extra}


def test_a_clear_winner_is_labelled():
    assert label_from_votes(_votes(400, 10, 1000), {"home": GREEN, "away": RED}) == "home"


def test_a_near_tie_is_not_labelled():
    """A green player beside a red one scored 60 red / 55 green. Calling that
    green would be a coin toss reported as a reading."""
    assert label_from_votes(_votes(55, 60, 700), {"home": GREEN, "away": RED}) == "other"


def test_a_thin_majority_of_a_large_torso_is_not_enough():
    """An assistant referee in black scored as a red player on twenty pixels of
    forearm. The winner must own a SHARE, not merely come first."""
    assert label_from_votes(_votes(2, 20, 900), {"home": GREEN, "away": RED}) == "other"


def test_no_live_anchors_means_no_label():
    assert label_from_votes(_votes(500, 0, 600), {}) == "other"


def test_skin_hue_is_close_enough_to_red_to_need_a_saturation_floor():
    """Not a threshold to taste: skin runs 60-110 and a red kit 155-220 on the
    same hue, so the floor has to sit between them."""
    assert abs(RED - SKIN_HUE) < SKIN_NEAR
    assert 110 < SKIN_S < 155


# ── ground plane ─────────────────────────────────────────────────────────────

def test_theil_sen_ignores_the_outliers_it_exists_to_expose():
    """Least squares would be dragged by the bench players it must reject."""
    x = np.arange(20, dtype=float)
    y = 2.0 * x + 5.0
    y[3] = 500.0
    y[11] = -400.0

    m, c = theil_sen(x, y)
    assert abs(m - 2.0) < 0.05
    assert abs(c - 5.0) < 1.0


def test_theil_sen_refuses_too_few_points():
    assert theil_sen([1.0], [2.0]) == (None, None)


# ── coverage ─────────────────────────────────────────────────────────────────

def _lbl(*labels):
    return FrameResult(labels=[((0, 0, 1, 1), l, None) for l in labels],
                       grass_hue=GRASS)


def test_coverage_is_named_over_readable_not_over_everything():
    """Six of eight readable and six of twenty are different claims, and a
    count published without this is not interpretable."""
    r = _lbl("home", "home", "away", "other")
    assert r.coverage == 0.75


def test_rejected_detections_are_outside_the_coverage_denominator():
    """A spectator excluded by the boundary is not a player we failed to read."""
    r = _lbl("home", "away", "off_pitch", "outside_play", "too_small")
    assert r.coverage == 1.0


def test_coverage_of_nothing_is_zero_not_an_error():
    assert _lbl().coverage == 0.0


# ── training bibs: the hazard the operator named ──────────────────────────
#
# Substitutes wear tracksuits and TRAINING BIBS, not match shirts. A bib is a
# large, saturated, single-colour surface -- the best target on the frame for
# a hue classifier -- worn by someone who is not playing. The warm-up bibs on
# this footage are orange and Gorleston's keeper is orange, so a substitute
# jogging the touchline is a perfect match for the home keeper anchor.
#
# Colour cannot separate them. What can is a bound: a side has one
# goalkeeper. Two home_gk in a frame means at least one is wrong.

def _gk_config():
    return {"home_kit": "green shirts", "away_kit": "red shirts",
            "home_gk_kit": "orange shirt", "away_gk_kit": "yellow shirt"}


def test_the_keeper_anchor_is_kept_for_validation():
    """collapse=False must name which keeper won, not just "keeper".

    Collapsing before the check throws the error away, because two keepers
    in one frame is legitimate when both goals are in shot.
    """
    live = {"home": GREEN, "away": RED, "home_gk": 12.0}
    votes = {"_total": 1000, "home": 5, "away": 10, "home_gk": 700}
    assert label_from_votes(votes, live) == "keeper"
    assert label_from_votes(votes, live, collapse=False) == "home_gk"


def test_an_outfield_label_is_unaffected_by_collapse():
    live = {"home": GREEN, "away": RED}
    votes = {"_total": 1000, "home": 700, "away": 10}
    assert label_from_votes(votes, live) == "home"
    assert label_from_votes(votes, live, collapse=False) == "home"


def test_keeper_counts_are_reported_per_side():
    from team_classifier import FrameResult
    def det(raw):
        return ((0, 0, 10, 40), "keeper", {"_total": 100, "_label": raw})
    fr = FrameResult(grass_hue=30.0, labels=[det("home_gk"), det("home_gk"), det("away_gk")])
    assert fr.keeper_counts == {"home_gk": 2, "away_gk": 1}
    assert fr.counts["keeper"] == 3, (
        "the collapsed count cannot distinguish two home keepers from one "
        "of each -- which is why keeper_counts exists")


def test_both_goals_in_shot_is_not_an_error():
    """One keeper per side is fine even though two keepers are in frame."""
    from team_classifier import FrameResult
    from team_detect import MAX_KEEPERS_PER_SIDE
    fr = FrameResult(grass_hue=30.0, labels=[
        ((0, 0, 10, 40), "keeper", {"_total": 100, "_label": "home_gk"}),
        ((0, 0, 10, 40), "keeper", {"_total": 100, "_label": "away_gk"})])
    assert all(n <= MAX_KEEPERS_PER_SIDE for n in fr.keeper_counts.values())


def test_a_bib_wearing_substitute_makes_the_frame_invalid():
    """The failure this bound exists for, as a count rather than a pixel test."""
    from team_classifier import FrameResult
    from team_detect import MAX_KEEPERS_PER_SIDE
    fr = FrameResult(grass_hue=30.0, labels=[
        ((0, 0, 10, 40), "keeper", {"_total": 100, "_label": "home_gk"}),
        ((0, 0, 10, 40), "keeper", {"_total": 100, "_label": "home_gk"})])
    assert fr.keeper_counts == {"home_gk": 2}
    assert not all(n <= MAX_KEEPERS_PER_SIDE
                   for n in fr.keeper_counts.values())


def test_officials_and_staff_land_in_other_not_in_a_team():
    """Black is worn by the referee, both assistants and much of the
    management team, so it identifies nobody. All of them must refuse a
    team label rather than being split between the two."""
    live = {"home": GREEN, "away": RED}
    assert label_from_votes({}, live) == "other"
    assert label_from_votes({"_total": 1000, "home": 3, "away": 4},
                            live) == "other"


# ── shorts and socks: wearing the colour vs wearing the kit ───────────────
#
# The team vote deliberately samples the shirt alone. That is right for
# deciding WHICH team, and it is exactly why a training bib defeats it: a bib
# is a torso, and a substitute jogging the touchline in an orange bib is, on
# the shirt band, a perfect Gorleston keeper.
#
# The lower body answers a different question -- is this person wearing the
# kit, or only the colour -- so it is sampled separately rather than folded
# back into the vote.

import cv2
from team_classifier import (
    LOWER_MIN_SHARE, classify_frame, garment_hues, lower_body_probe,
)


def test_garment_hues_reads_each_garment_the_kit_names():
    assert garment_hues("orange shirt, orange shorts, orange socks") == {
        "shirt": ORANGE, "shorts": ORANGE, "socks": ORANGE}


def test_a_shirt_only_kit_string_claims_nothing_about_the_legs():
    """away_gk_kit on this match is "yellow shirt" and nothing more.

    Assuming yellow shorts would let the bib test fire on a keeper who wears
    black ones. The honest answer is that he cannot be tested.
    """
    assert garment_hues("yellow shirt") == {"shirt": YELLOW}
    assert lower_body_probe("yellow shirt") == (None, ())


def test_a_bare_colour_claims_nothing():
    assert lower_body_probe("red") == (None, ())


def test_white_shorts_are_dropped_and_the_socks_carry_the_test():
    """Including a large white surface in the denominator would make a real
    player look like a bib."""
    hue, bands = lower_body_probe("red shirt, white shorts, red socks")
    assert hue == RED
    assert len(bands) == 1 and bands[0] == (0.72, 0.92)


# -- end to end on synthetic frames ----------------------------------------

def _person(img, mask, x, y, w, h, torso_hsv, legs_hsv):
    """A rectangle of torso over a rectangle of legs, in HSV."""
    torso = (y + int(0.10 * h), y + int(0.50 * h))
    legs  = (y + int(0.50 * h), y + h)
    for (a, b), colour in ((torso, torso_hsv), (legs, legs_hsv)):
        patch = np.full((b - a, w, 3), colour, np.uint8)
        img[a:b, x:x + w] = cv2.cvtColor(patch, cv2.COLOR_HSV2BGR)
    mask[y:y + h, x:x + w] = True
    return (x, y, x + w, y + h)


def _scene(legs_hsv, torso_hue=ORANGE):
    """One person on grass. Torso and legs vary by test."""
    H, W = 400, 400
    img  = cv2.cvtColor(np.full((H, W, 3), (GRASS, 120, 57), np.uint8),
                        cv2.COLOR_HSV2BGR)
    mask = np.zeros((H, W), bool)
    box  = _person(img, mask, 150, 150, 40, 180,
                   torso_hsv=(int(torso_hue), 200, 200), legs_hsv=legs_hsv)
    return img, [(np.array(box, float), mask)]


def _label(legs_hsv, torso_hue=ORANGE, **cfg):
    img, dets = _scene(legs_hsv, torso_hue)
    res = classify_frame(img, dets, _mc(**cfg))
    return [l for _, l, _ in res.labels][0], res


TRACKSUIT = (110, 180, 60)      # dark navy bottoms
FULL_KIT_ORANGE = (int(ORANGE), 200, 200)
FULL_KIT_YELLOW = (int(YELLOW), 200, 200)

REAL = dict(home="green shirts, green shorts, green socks",
            away="red shirts, red shorts, red socks",
            home_gk="orange shirt, orange shorts, orange socks",
            away_gk="yellow shirt")


def test_a_red_bib_is_a_false_TILBURY_PLAYER_not_a_false_keeper():
    """The failure as it actually occurs, and why the keeper bound misses it.

    home_gk is orange, which sits 12 from red -- inside COLLIDE -- so the
    keeper anchor is disabled on this match and orange pixels fall into
    Tilbury's band. No detection is ever labelled "keeper", so a per-side
    keeper bound cannot fire. A bib in an outfield colour is counted as an
    outfield PLAYER, and only the legs give it away.
    """
    lab, _ = _label(TRACKSUIT, RED, **REAL)
    assert lab == "bib", (
        f"a red training bib over tracksuit bottoms was labelled {lab!r}; "
        f"on the shirt band alone it is a Tilbury player")


def test_an_orange_bib_is_ambiguous_on_this_config_rather_than_wrong():
    """Worth pinning because it is luck, not design.

    Orange sits 12 from red and 15 from yellow, both inside BAND, so an
    orange surface votes equally for the Tilbury kit and the Tilbury keeper
    and the margin rule refuses it. That refusal is the only thing standing
    between an orange bib and a false Tilbury player, and it would vanish if
    either kit colour moved. It is not a substitute for the lower-body test.
    """
    lab, _ = _label(TRACKSUIT, ORANGE, **REAL)
    assert lab in ("other", "bib")


def test_a_tilbury_player_in_full_red_survives():
    """The other direction: full kit below the waist must not be discarded."""
    lab, _ = _label((int(RED), 200, 200), RED, **REAL)
    assert lab == "away"


def test_a_green_bib_would_be_caught_the_same_way():
    lab, _ = _label(TRACKSUIT, GREEN, **REAL)
    assert lab == "bib"


def test_a_gorleston_player_in_full_green_survives():
    lab, _ = _label((int(GREEN), 200, 200), GREEN, **REAL)
    assert lab == "home"


def test_a_separable_keeper_still_reads_as_a_keeper():
    """With a keeper colour far enough from both outfield kits, the anchor is
    live -- and full kit below the waist keeps him a keeper."""
    cfg = dict(REAL, away_gk="yellow shirt, yellow shorts, yellow socks")
    lab, _ = _label(FULL_KIT_YELLOW, YELLOW, **cfg)
    assert lab == "keeper"


def test_a_yellow_bib_over_tracksuit_is_not_a_keeper():
    cfg = dict(REAL, away_gk="yellow shirt, yellow shorts, yellow socks")
    lab, _ = _label(TRACKSUIT, YELLOW, **cfg)
    assert lab == "bib"


def test_a_bib_does_not_count_against_coverage():
    """A positive identification of a non-player, like off_pitch -- not
    someone the classifier failed to read."""
    _, res = _label(TRACKSUIT, RED, **REAL)
    assert res.counts.get("bib") == 1
    assert res.coverage == 0.0


def test_an_unprobed_anchor_is_declared_rather_than_silently_skipped():
    """away_gk names only a shirt, so the caller must be told the bib test
    cannot protect that anchor -- not left assuming it ran."""
    _, res = _label((int(RED), 200, 200), RED, **REAL)
    assert any("no lower-body check" in c and "away_gk" in c
               for c in res.caveats), res.caveats
