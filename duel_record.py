"""Duel outcomes as counts, never as rates.

WHY NOT A PERCENTAGE
--------------------
A rate needs a denominator you know. This one is not knowable:

  * The per-duel field is `players_visible`, not `players_contesting`. A
    defender standing near a header is in the list. "Eleven duels" means
    eleven duels he was VISIBLE IN.
  * 73 duels were logged across 98 minutes of live play -- 0.74 per minute,
    against a competitive norm nearer 1.2-1.8. Roughly half the duels in the
    match were never observed, and the missing half is not random: it is the
    half away from the ball and the half falling between sampled frames.
  * The sample is biased in a direction that flatters. One centre-back's
    record here is nine won and none lost, which is what observation bias
    looks like -- the clearance is logged, the one where he was beaten and the
    ball sailed past is not.
  * One substitute striker appears in fifteen duels across roughly 35 minutes
    on the pitch, a fifth of the entire match's duels while playing a third of
    it. That is the ball-following camera parked on the team chasing the game.

The report published "82% win rate across 11 contested duels" for a player
whose actual record was 9 won, 0 lost, 2 contested, of which only 7 were
aerial. It was computing wins divided by times-visible, counting contested
duels as losses, and labelling a mixed aerial/ground figure as aerial.

Counts carry the same tactical meaning without the false precision. "Nine
duels won, none lost" tells a coach what "82%" pretends to.
"""
from collections import defaultdict

SCHEMA_VERSION = "1.0"

# Duels per minute in a competitive match, used only to state how much of the
# contest went unobserved. Not used to scale or correct any figure.
TYPICAL_PER_MIN = (1.2, 1.8)


def _side_of(token):
    """'#4 home_kit' -> 'home_kit'. Shirt number alone is not an identity:
    both teams have a #4."""
    return "home_kit" if "home_kit" in token else (
        "away_kit" if "away_kit" in token else None)


def build(summary, live_play_minutes=None):
    """Per-player duel record, plus what fraction of the match it covers."""
    duels = summary.get("duels") or []
    rec = defaultdict(lambda: {"observed": 0, "won": 0, "lost": 0,
                               "contested": 0, "aerial": 0, "ground": 0})
    for d in duels:
        winner = d.get("winner")
        kind = d.get("type")
        for token in d.get("players_visible") or []:
            side = _side_of(token)
            if side is None:
                continue
            r = rec[token]
            r["observed"] += 1
            r["aerial" if kind == "aerial" else "ground"] += 1
            if winner == "contested":
                r["contested"] += 1
            elif winner == side:
                r["won"] += 1
            else:
                r["lost"] += 1

    coverage = None
    if live_play_minutes:
        per_min = len(duels) / live_play_minutes
        lo, hi = TYPICAL_PER_MIN
        coverage = {
            "duels_logged": len(duels),
            "live_play_minutes": round(live_play_minutes, 1),
            "logged_per_minute": round(per_min, 2),
            "typical_per_minute": f"{lo}-{hi}",
            "estimated_share_observed": round(per_min / ((lo + hi) / 2), 2),
        }
    return {
        "players": {k: dict(v) for k, v in sorted(
            rec.items(), key=lambda kv: -kv[1]["observed"])},
        "coverage": coverage,
        # Stated in the data, not only in a prompt, so a reader who never sees
        # the prompt still gets the caveat with the numbers.
        "reporting_rule": (
            "Counts only. Do not compute or publish a win rate: the "
            "denominator is duels the player was VISIBLE in, not duels he "
            "contested, and roughly half the match's duels were never "
            "observed by this source."),
        "schema_version": SCHEMA_VERSION,
    }


def strip_outcomes(duels):
    """Per-duel records with the winner removed.

    The event-level detail is still worth having -- a header at 34:20 in the
    left channel is a real observation. The outcome is removed so a rate
    cannot be recomputed from the raw array: a prompt rule telling a writer to
    ignore a number it has been handed does not survive contact, which this
    project has now demonstrated three times.
    """
    out = []
    for d in duels:
        e = {k: v for k, v in d.items() if k != "winner"}
        e["outcome_in"] = "duel_record.players"
        out.append(e)
    return out
