"""Guards for the zone vocabulary mismatch.

The agent prompts teach one set of zone codes and zone_helpers validated
against a different set. Neither side was wrong on its own; they were simply
never reconciled. The first run where zone normalisation actually executed
stamped _zone_invalid on all 253 observations, nulled between_lines on every
one of them, and resolved all 421 pass sequences to vertical_progression
"unknown".

These tests pin the vocabularies together, using the exact strings the agents
emitted on Gorleston v Tilbury.
"""
import pytest

import zone_helpers as zh


# What the agents actually emitted, with counts from the real run.
EMITTED_LANES  = ["central_channel", "left", "right"]          # 224, 15, 14
EMITTED_THIRDS = ["middle", "defensive", "attacking", "defending"]  # 119, 69, 59, 6
EMITTED_SEQ_ZONES = ["middle_third", "defending_third", "attacking_third"]  # 201, 139, 52


@pytest.mark.parametrize("lane", EMITTED_LANES)
def test_every_lane_the_agents_emit_canonicalises(lane):
    assert zh.canonical_lateral_lane(lane) in zh.VALID_LATERAL_LANES


@pytest.mark.parametrize("third", EMITTED_THIRDS)
def test_every_third_the_agents_emit_canonicalises(third):
    assert zh.canonical_vertical_third(third) in zh.VALID_VERTICAL_THIRDS


@pytest.mark.parametrize("zone", EMITTED_SEQ_ZONES)
def test_every_sequence_zone_the_agents_emit_canonicalises(zone):
    assert zh.canonical_vertical_third(zone) in zh.VALID_VERTICAL_THIRDS


def test_unknown_spellings_still_rejected():
    """Normalising aliases must not turn the validator into a rubber stamp."""
    assert zh.canonical_lateral_lane("banana") is None
    assert zh.canonical_vertical_third("banana") is None
    assert zh.canonical_lateral_lane(None) is None


def test_a_real_observation_zone_is_no_longer_invalidated():
    """The exact zone dict from the run, which used to come back _zone_invalid."""
    out = zh.normalise_zone({
        "vertical_third": "defensive",
        "lateral_lane":   "central_channel",
        "named_zone":     None,
        "between_lines":  None,
    })
    assert "_zone_invalid" not in out
    assert out["vertical_third"] == "defending"
    assert out["lateral_lane"] == "central"


def test_between_lines_survives_normalisation():
    """between_lines was nulled on all 253 observations because the whole zone
    was invalidated before this field was ever considered."""
    out = zh.normalise_zone({
        "vertical_third": "middle",
        "lateral_lane":   "central_channel",
        "named_zone":     None,
        "between_lines":  "between_mid_fwd",
    })
    assert out["between_lines"] == "between_mid_fwd"
    assert "_zone_invalid" not in out


@pytest.mark.parametrize("start,end,expected", [
    ("defending_third", "middle_third",    "defending_to_middle"),
    ("middle_third",    "attacking_third", "middle_to_attacking"),
    ("defending_third", "attacking_third", "defending_to_attacking"),
    ("attacking_third", "attacking_third", "same_third"),
    ("attacking_third", "defending_third", "regression_attacking_to_defending"),
])
def test_progression_derives_from_plain_string_zones(start, end, expected):
    """pass_sequences carry start_zone/end_zone as STRINGS. The dict-only
    version returned "unknown" for all 421 sequences in the real run."""
    assert zh.derive_vertical_progression(start, end) == expected


def test_progression_still_accepts_zone_dicts():
    assert zh.derive_vertical_progression(
        {"vertical_third": "defending"}, {"vertical_third": "middle"}
    ) == "defending_to_middle"


def test_progression_is_unknown_only_when_it_genuinely_cannot_tell():
    assert zh.derive_vertical_progression(None, None) == "unknown"
    assert zh.derive_vertical_progression("banana", "middle_third") == "unknown"


def test_boolean_between_lines_is_kept_not_discarded():
    """The prompt asks for "between_lines (or null)" without naming a
    vocabulary, so agents answer True. The validator wanted one of three band
    codes and nulled everything else -- between_lines_events went 27 -> 0 the
    moment normalisation first ran."""
    out = zh.normalise_zone({
        "vertical_third": "middle", "lateral_lane": "central_channel",
        "named_zone": None, "between_lines": True,
    })
    assert out["between_lines"] == "between_lines_unspecified"


def test_named_band_codes_still_pass_through():
    out = zh.normalise_zone({
        "vertical_third": "middle", "lateral_lane": "central",
        "named_zone": None, "between_lines": "between_mid_fwd",
    })
    assert out["between_lines"] == "between_mid_fwd"


def test_nonsense_between_lines_is_still_dropped():
    out = zh.normalise_zone({
        "vertical_third": "middle", "lateral_lane": "central",
        "named_zone": None, "between_lines": "somewhere_about_there",
    })
    assert out["between_lines"] is None
