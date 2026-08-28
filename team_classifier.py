"""Assign each detected person to a team by kit colour.

WHY THIS IS HARD, MEASURED ON GORLESTON v TILBURY
-------------------------------------------------
A first attempt using RGB thresholds returned 2-7 "home" where ~11 should
have been visible. Every fix below was made against a specific, visible
failure in an annotated frame, not against a hunch:

  * A bounding box in a cluster contains the NEIGHBOUR's shirt. Uses the
    instance mask, not the box.
  * A torso crop is a mixture -- kit, skin, grass through the gaps -- so the
    mean hue lands between the modes. One green player scored hue 30, exactly
    the grass value, and was called green by coincidence. Counts pixels per
    kit band instead of summarising to one number.
  * `gk_orange` (hue 12) sits INSIDE the red kit's own band. Left unchecked
    it turned 3-5 outfield players per frame into goalkeepers.
  * Skin is hue 5-20 at saturation 60-110; a red kit is the same hue at
    saturation 155-220. Without a saturation floor an assistant referee in
    black scored as a red player on twenty pixels of forearm.
  * A yellow keeper collides with grass in HUE (27 vs 30) but not in VALUE
    (grass sits near 57). Gated on brightness rather than discarded.
  * Gorleston's shirts carry white stripes down the front, which dilute the
    shirt band. Shorts and socks are solid, so all three are sampled.
  * Substitutes sit in the dugout with shirts across their laps -- exactly
    the right red, always present, always one team's colours, always on the
    same side. Colour cannot exclude them; the perspective ground plane can,
    partially. See KNOWN LIMITS.

WHAT IT REFUSES TO DO
---------------------
If two outfield kits are within COLLIDE of each other in hue, the match is
not separable by colour and both anchors are disabled rather than guessed.
Every result carries the anchors that were disabled and why, and the share
of detections it could not label. A team-level count is only as good as its
coverage, and the caller is given both.

KNOWN LIMITS (do not build on these without reading)
----------------------------------------------------
1. THRESHOLDS ARE PROVISIONAL. They reproduce one hand-labelled frame
   (9 away / 6 home / 1 keeper, exactly). One frame is not a validation set,
   and adjusting any constant currently trades one frame's error for
   another's. Fit against a labelled set before trusting the numbers.
2. TOUCHLINE PERSONNEL ARE NOT EXCLUDED. People standing at the barrier sit
   at nearly the same image row as players just inside the touchline, so the
   ground plane cannot separate them -- the difference is a metre of depth,
   not of height. This needs the touchline detected. Until then, counts on
   frames showing a dugout are biased toward whichever team's bench is in
   view.
3. NON-PLAY FRAMES MUST BE EXCLUDED BY THE CALLER using match_boundaries.
   A half-time frame returns a confident, meaningless split.
"""
from dataclasses import dataclass, field

import cv2
import numpy as np

import pitch_lines

# ── tuning constants (provisional -- see KNOWN LIMITS 1) ─────────────────────
BAND        = 16.0   # half-width of a kit's hue band, OpenCV H units
COLLIDE     = 18.0   # anchors closer than this cannot be told apart
MIN_SHARE   = 0.12   # winner must own this share of usable kit pixels
MARGIN      = 1.6    # ...and beat the runner-up by this factor
MIN_BOX_H   = 24     # px; below this a torso is too few pixels to read
SKIN_HUE    = 12.0
SKIN_NEAR   = 20.0   # an anchor this close to skin hue needs a saturation floor
SKIN_S      = 130
GRASS_V_GAP = 45     # a hue-colliding kit must beat grass by this in value
SHORT_FRAC  = 0.70   # shorter than this fraction of the predicted height ⇒ off-field
MIN_ASPECT  = 1.55   # a standing player is taller than this, times wider
MIN_PLANE_PTS = 6    # fewer confident players than this ⇒ no ground-plane fit

# Kit sampling bands as fractions of box height.
#
# Shirt only, deliberately. Adding shorts and socks was sound reasoning --
# Gorleston's shirts carry white stripes that dilute the shirt band, and the
# solid garments should have helped. It did help while the pitch mask was
# broken, because extra evidence partly compensated for detections that were
# never players at all. With the field-of-play boundary working it over-fires:
# on the one hand-labelled frame, shirt-only returns exactly 9 away / 6 home /
# 1 keeper, while shirt+shorts+socks returns 9 / 8 / 1. Revisit against a
# larger labelled set -- one frame is not a validation set.
BANDS = ((0.15, 0.48),)
BANDS_ALL_GARMENTS = ((0.15, 0.48), (0.52, 0.68), (0.72, 0.92))

# Colour names as they appear in match_config, mapped to OpenCV hue.
HUE_OF = {"red": 0.0, "orange": 12.0, "yellow": 27.0, "green": 50.0,
          "blue": 110.0, "purple": 140.0, "pink": 165.0}


@dataclass
class FrameResult:
    labels: list                      # [(box, label, votes), ...]
    grass_hue: int
    disabled: dict = field(default_factory=dict)
    caveats: list = field(default_factory=list)
    plane: tuple = None
    boundaries: int = 0
    lines_found: int = 0

    @property
    def counts(self):
        c = {}
        for _, lab, _ in self.labels:
            c[lab] = c.get(lab, 0) + 1
        return c

    @property
    def coverage(self):
        """Share of on-pitch detections that got a team label.

        Reported alongside every count because a count without it is not
        interpretable: 6 home out of 8 readable detections and 6 out of 20
        are different claims."""
        readable = [l for _, l, _ in self.labels
                    if l not in ("too_small", "off_pitch", "off_field",
                                 "outside_play")]
        if not readable:
            return 0.0
        named = [l for l in readable if l in ("home", "away", "keeper")]
        return len(named) / len(readable)


def _cd(a, b):
    """Circular distance on the OpenCV hue wheel (0-179)."""
    d = np.abs(np.asarray(a, dtype=float) - b) % 180.0
    return np.minimum(d, 180.0 - d)


def kit_hue(description):
    """First recognised colour word in a match_config kit string, or None."""
    if not description:
        return None
    words = str(description).lower().replace(",", " ").split()
    for w in words:
        if w in HUE_OF:
            return HUE_OF[w]
    return None


def resolve_anchors(match_config, grass_hue):
    """Which kits can be told apart on this pitch, and why the others cannot.

    Precedence is deliberate: an outfield kit is worn by ten players and a
    keeper kit by one, so a keeper anchor never disqualifies an outfield kit
    -- it loses the collision itself. Only live anchors can disqualify
    others, so a dead anchor cannot take a live one down with it.
    """
    outfield = {}
    for side, key in (("home", "home_kit"), ("away", "away_kit")):
        h = kit_hue(match_config.get(key))
        if h is None:
            raise ValueError(
                f"resolve_anchors: {key} names no recognised colour "
                f"({match_config.get(key)!r}). Team assignment has no anchor; "
                f"add a colour word or mark this match unclassifiable.")
        outfield[side] = h
    keepers = {f"{s}_gk": kit_hue(match_config.get(f"{s}_gk_kit"))
               for s in ("home", "away")}
    keepers = {k: v for k, v in keepers.items() if v is not None}

    live, dead, needs_value, caveats = {}, {}, set(), []
    for n, a in outfield.items():
        clash = [m for m, b in outfield.items() if m != n and _cd(a, b) < COLLIDE]
        if clash:
            dead[n] = (f"outfield kit within {COLLIDE:.0f} of {clash[0]} -- "
                       f"the two teams are not separable by colour")
        elif _cd(a, grass_hue) <= COLLIDE / 2:
            dead[n] = f"within {_cd(a, grass_hue):.0f} of grass hue {grass_hue}"
        else:
            live[n] = a
    for n, a in keepers.items():
        clash = [m for m, b in live.items() if _cd(a, b) < COLLIDE]
        if clash:
            dead[n] = f"within {COLLIDE:.0f} of {clash[0]}"
            # Disabling an anchor is not neutral. The keeper does not vanish;
            # his pixels fall into whichever live band swallowed his colour,
            # so that side's count runs one high in every frame he appears
            # in. Gorleston keep in orange (hue 12), which sits inside
            # Tilbury's red band -- so every second-half frame showing the
            # Gorleston goal quietly adds a Tilbury player. State the
            # consequence, not just the cause; a caller that only reads
            # `dead` will not know its counts are biased.
            if clash[0] in ("home", "away"):
                caveats.append(
                    f"{n} is indistinguishable from the {clash[0]} outfield "
                    f"kit; that keeper will be counted as a {clash[0]} "
                    f"outfield player wherever he is in frame. Subtract one "
                    f"from {clash[0]} in frames containing his goal, or "
                    f"resolve keepers positionally once pitch landmarks "
                    f"are available.")
        elif _cd(a, grass_hue) <= COLLIDE / 2:
            live[n] = a
            needs_value.add(n)
            dead[n + " (hue)"] = (
                f"within {_cd(a, grass_hue):.0f} of grass hue {grass_hue} -- "
                f"kept, separated on brightness instead")
        else:
            live[n] = a
    return live, dead, needs_value, caveats


def grass_stats(hsv):
    """Modal hue of the frame and the median value of pixels at that hue."""
    gh = int(np.bincount(hsv[:, :, 0].ravel(), minlength=180).argmax())
    m = (_cd(hsv[:, :, 0], gh) <= 10)
    gv = int(np.median(hsv[:, :, 2][m])) if m.any() else 0
    return gh, gv


def grass_edge(image_bgr, hsv, grass_hue):
    """Image row of the far edge of the turf, per column, or None.

    The previous pitch mask was "largest connected grass-coloured region,
    dilated". On this ground that covered 79% of the frame with its top edge at
    y=95 -- in the trees -- because background vegetation shares turf hue and a
    35x35 close bridged it all into one blob. It passed nearly every detection
    as on-pitch, which is how 52 frames of 197 came to report more than eleven
    players for a team. Eroding it did nothing: there was a townscape inside.

    Texture separates them cleanly -- turf runs at local sigma 0.7-2.2, trees
    and hedges at 4.8-9.6 -- but only as an EDGE FINDER. As a per-pixel mask it
    punches holes in distant turf, where mowing stripes raise the variance, and
    rejects real players.
    """
    H, W = image_bgr.shape[:2]
    green = ((_cd(hsv[:, :, 0], grass_hue) <= 12) & (hsv[:, :, 1] > 40))
    sd = pitch_lines._local_std(cv2.cvtColor(image_bgr, cv2.COLOR_BGR2GRAY))
    m = cv2.morphologyEx((green & (sd < pitch_lines.TURF_SIGMA)).astype(np.uint8),
                         cv2.MORPH_CLOSE, np.ones((9, 9), np.uint8))
    n, lab, st, _ = cv2.connectedComponentsWithStats(m, 8)
    if n < 2:
        return None
    turf = (lab == 1 + int(st[1:, cv2.CC_STAT_AREA].argmax()))
    xs, ys = [], []
    for x in range(0, W, 8):
        col = np.where(turf[:, x])[0]
        if len(col) > 30:
            xs.append(x)
            ys.append(col.min())
    if len(xs) < 20:
        return None
    xs, ys = np.array(xs, float), np.array(ys, float)
    keep = np.ones(len(xs), bool)
    # A panoramic lens bows the edge, so fit a quadratic; iterate rejecting
    # points ABOVE the fit, which are notches where a dark shirt breaks the run.
    for _ in range(3):
        c = np.polyfit(xs[keep], ys[keep], 2)
        r = ys - np.polyval(c, xs)
        keep = r < np.percentile(r, 85) + 8
        if keep.sum() < 10:
            break
    return np.polyval(np.polyfit(xs[keep], ys[keep], 2), np.arange(W))


def kit_votes(hsv, box, mask, grass_hue, grass_v, live, needs_value):
    """Pixels of each kit's colour on this person, across all three garments."""
    x1, y1, x2, y2 = box
    h = y2 - y1
    band = np.zeros_like(mask)
    for lo, hi in BANDS:
        a, b = max(0, y1 + int(lo * h)), min(mask.shape[0], y1 + int(hi * h))
        if b - a >= 2:
            band[a:b, :] |= mask[a:b, :]
    if band.sum() < 25:
        return {}
    H, S, V = hsv[:, :, 0][band], hsv[:, :, 1][band], hsv[:, :, 2][band]
    # White stripes and black shorts are kit too but carry no hue. Drop them
    # from the denominator rather than letting them dilute a team's share.
    ok = (S > 50) & (V > 30) & (V < 250)
    if ok.sum() < 25:
        return {}
    Hs, Ss, Vs = H[ok], S[ok], V[ok]
    out = {"_total": int(ok.sum())}
    for n, a in live.items():
        m = _cd(Hs, a) <= BAND
        if _cd(a, SKIN_HUE) < SKIN_NEAR:
            m &= Ss > SKIN_S
        if n in needs_value:
            m &= Vs > (grass_v + GRASS_V_GAP)
        elif _cd(a, grass_hue) < 25:
            m &= _cd(Hs, float(grass_hue)) > 9
        out[n] = int(m.sum())
    return out


def label_from_votes(v, live):
    if not v:
        return "other"
    total = max(1, v["_total"])
    scores = {n: v.get(n, 0) for n in live}
    if not scores:
        return "other"
    best = max(scores, key=scores.get)
    rest = max([x for n, x in scores.items() if n != best] or [0])
    if scores[best] / total >= MIN_SHARE and scores[best] >= MARGIN * max(1, rest):
        return "keeper" if best.endswith("_gk") else best
    return "other"


def theil_sen(x, y):
    """Median of pairwise slopes. Robust to the outliers that are the point:
    least squares would be dragged by the bench players it must expose."""
    x, y = np.asarray(x, float), np.asarray(y, float)
    slopes = []
    for i in range(len(x)):
        dx = x[i + 1:] - x[i]
        ok = np.abs(dx) > 1e-6
        if ok.any():
            slopes.extend(((y[i + 1:] - y[i])[ok] / dx[ok]).tolist())
    if len(slopes) < 3:
        return None, None
    m = float(np.median(slopes))
    return m, float(np.median(y - m * x))


def apply_ground_plane(labelled):
    """Reject people too short to be standing on the pitch at their image row.

    Players form a perspective ground plane: box height is near-linear in
    where the feet sit. Someone in the dugout is behind the touchline, so at
    that row they are further away and measure short; someone seated measures
    shorter again. Fitted on confidently-labelled detections, which are
    outfield players by construction, then applied to all.

    Partial by design -- see KNOWN LIMITS 2.
    """
    conf = [(b, l) for b, l, v in labelled
            if l in ("home", "away") and v
            and max(v.get("home", 0), v.get("away", 0)) / max(1, v["_total"]) >= 0.25]
    if len(conf) < MIN_PLANE_PTS:
        return labelled, None
    m, c = theil_sen([b[3] for b, _ in conf], [b[3] - b[1] for b, _ in conf])
    if m is None or m <= 0:
        return labelled, None
    out = []
    for b, l, v in labelled:
        x1, y1, x2, y2 = b
        h, w = y2 - y1, max(1, x2 - x1)
        pred = m * y2 + c
        off = l in ("home", "away", "keeper") and (
            (pred > 0 and h < SHORT_FRAC * pred) or h / w < MIN_ASPECT)
        out.append((b, "off_field" if off else l, v))
    return out, (m, c)


def classify_frame(image_bgr, detections, match_config):
    """Label every detection in one frame.

    detections: iterable of (box, instance_mask) where box is (x1,y1,x2,y2)
    in image pixels and instance_mask is a full-frame boolean array. Boxes
    alone are not enough -- in a cluster a box contains the neighbour's kit.
    """
    hsv = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2HSV)
    gh, gv = grass_stats(hsv)
    live, dead, needs_value, caveats = resolve_anchors(match_config, gh)
    edge = grass_edge(image_bgr, hsv, gh)
    H0, W0 = image_bgr.shape[:2]

    labelled = []
    for box, mask in detections:
        x1, y1, x2, y2 = map(int, box)
        if (y2 - y1) < MIN_BOX_H:
            labelled.append(((x1, y1, x2, y2), "too_small", None))
            continue
        fx, fy = min(W0 - 1, (x1 + x2) // 2), y2
        if edge is not None and fy < edge[fx]:
            labelled.append(((x1, y1, x2, y2), "off_pitch", None))
            continue
        v = kit_votes(hsv, (x1, y1, x2, y2), mask, gh, gv, live, needs_value)
        labelled.append(((x1, y1, x2, y2), label_from_votes(v, live), v))

    labelled, plane = apply_ground_plane(labelled)

    # The turf runs past the touchline to the track, and the bench sits on that
    # strip, so the grass edge alone still admits people who are not playing.
    # Painted lines mark the field of play; a line with every confident player
    # on one side is a perimeter, and one through the middle of the pitch is
    # rejected by that test without needing a rule of its own.
    feet = [((b[0] + b[2]) // 2, b[3]) for b, l, _ in labelled
            if l in ("home", "away")]
    lines = pitch_lines.merge_collinear(
        pitch_lines.detect_segments(image_bgr, hsv, gh))
    bounds = pitch_lines.boundaries_from(lines, feet)
    if bounds:
        labelled = [
            (b, "outside_play", v)
            if l in ("home", "away", "keeper")
            and pitch_lines.outside_play(bounds, ((b[0] + b[2]) // 2, b[3]))
            else (b, l, v)
            for b, l, v in labelled]

    return FrameResult(labels=labelled, grass_hue=gh, disabled=dead,
                       caveats=caveats, plane=plane,
                       boundaries=len(bounds), lines_found=len(lines))
