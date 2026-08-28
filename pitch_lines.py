"""Find the field-of-play boundary from pitch markings.

WHY A LINE AND NOT A COLOUR
---------------------------
The pitch mask used to be "the largest connected region of grass-coloured
pixels". On this ground that region covered 79% of the frame with its top edge
at y=95 -- up in the trees, because background vegetation shares turf hue and a
morphological close bridged it all together. It passed essentially every
detection as on-pitch, which is how 52 of 197 frames came to report more than
eleven players for one team.

Texture fixes the vegetation (turf runs at local sigma 0.7-2.2, trees at
4.8-9.6) but not the real problem: at this ground the turf continues past the
touchline to the running track, and the substitutes' bench sits on that strip.
The edge of the GRASS is not the edge of the FIELD OF PLAY. Only the painted
line is, so that is what this module looks for.

WHAT IT DOES NOT DO
-------------------
It does not identify which line is which, and it does not solve a homography.
It finds long straight markings, keeps the ones with every confident player on
a single side, and treats those as half-planes. That is enough to exclude a
linesman standing on the track; it is not enough to measure anything in metres.
Naming the lines and fitting a pitch template is the next piece of work, and it
is what would turn these same segments into real distances.
"""
import cv2
import numpy as np

WHITE_LOCAL_GAIN = 14    # a marking is this much brighter than the turf AROUND it
WHITE_MAX_SAT    = 110
TURF_SIGMA       = 4.0   # local std below this is turf, above it is vegetation
MIN_SEG_LEN      = 90
MERGE_ANGLE_DEG  = 4.0
MERGE_RHO_PX     = 26.0
MIN_LINE_LEN     = 240   # a boundary candidate must be at least this long
SIDE_PURITY      = 0.90  # ...with this share of confident players on one side
SIDE_MARGIN_PX   = 18    # a player may straddle the line by this much
MIN_PLAYERS_FIT  = 5

# The Veo watermark sits bottom-right and produces the same phantom horizontal
# segments in every frame -- 140px at y≈968-1005 in three separate frames here.
# A static false line would anchor a false boundary in every frame of a match.
WATERMARK_BOX = (0.86, 0.87, 1.00, 1.00)   # x1,y1,x2,y2 as fractions


def _local_std(gray, k=9):
    g = gray.astype(np.float32)
    mu = cv2.blur(g, (k, k))
    mu2 = cv2.blur(g * g, (k, k))
    return np.sqrt(np.maximum(mu2 - mu * mu, 0))


def marking_mask(img_bgr, hsv, grass_hue):
    """Pixels that look like paint on turf.

    Brightness is compared to the LOCAL background rather than a global
    threshold: grass value ranged 59 to 108 across five frames of this one
    match, so any fixed cut fails half of them -- worn lines in shadow at one
    end, blown-out turf in sun at the other.
    """
    h, s, v = hsv[:, :, 0], hsv[:, :, 1], hsv[:, :, 2]
    d = np.abs(h.astype(float) - grass_hue) % 180.0
    green = (np.minimum(d, 180.0 - d) <= 12) & (s > 40)
    sd = _local_std(cv2.cvtColor(img_bgr, cv2.COLOR_BGR2GRAY))
    turf = cv2.morphologyEx((green & (sd < TURF_SIGMA)).astype(np.uint8),
                            cv2.MORPH_CLOSE, np.ones((9, 9), np.uint8))
    n, lab, st, _ = cv2.connectedComponentsWithStats(turf, 8)
    if n < 2:
        return None
    big = 1 + int(st[1:, cv2.CC_STAT_AREA].argmax())
    near_turf = cv2.dilate((lab == big).astype(np.uint8),
                           np.ones((21, 21), np.uint8)) > 0

    bg = cv2.blur(v, (41, 41)).astype(np.int16)
    m = (((v.astype(np.int16) - bg) > WHITE_LOCAL_GAIN)
         & (s < WHITE_MAX_SAT) & near_turf).astype(np.uint8)

    H, W = m.shape
    x1, y1, x2, y2 = WATERMARK_BOX
    m[int(y1 * H):int(y2 * H), int(x1 * W):int(x2 * W)] = 0
    return cv2.morphologyEx(m, cv2.MORPH_CLOSE, np.ones((3, 3), np.uint8))


def detect_segments(img_bgr, hsv, grass_hue):
    m = marking_mask(img_bgr, hsv, grass_hue)
    if m is None:
        return []
    ls = cv2.HoughLinesP(m, 1, np.pi / 360, threshold=50,
                         minLineLength=MIN_SEG_LEN, maxLineGap=22)
    return [] if ls is None else [tuple(map(int, s)) for s in ls.reshape(-1, 4)]


def _normal_form(seg):
    x1, y1, x2, y2 = seg
    th = np.arctan2(y2 - y1, x2 - x1)
    nth = th + np.pi / 2
    return (np.degrees(nth) % 180.0), (x1 * np.cos(nth) + y1 * np.sin(nth))


def merge_collinear(segments):
    """Collapse the many Hough echoes of one painted line into one line.

    A single touchline returns as a dozen near-identical segments; left
    unmerged they would each vote as an independent boundary.
    """
    groups = []
    for s in segments:
        a, r = _normal_form(s)
        for g in groups:
            da = abs(a - g["angle"])
            da = min(da, 180 - da)
            if da < MERGE_ANGLE_DEG and abs(r - g["rho"]) < MERGE_RHO_PX:
                g["segs"].append(s)
                break
        else:
            groups.append({"angle": a, "rho": r, "segs": [s]})
    out = []
    for g in groups:
        pts = np.array([(s[0], s[1]) for s in g["segs"]]
                       + [(s[2], s[3]) for s in g["segs"]], float)
        mean = pts.mean(axis=0)
        u, sv, vt = np.linalg.svd(pts - mean)
        d = vt[0]
        t = (pts - mean) @ d
        p1, p2 = mean + d * t.min(), mean + d * t.max()
        out.append({"p1": tuple(p1), "p2": tuple(p2),
                    "length": float(np.hypot(*(p2 - p1))),
                    "n_segments": len(g["segs"])})
    return sorted(out, key=lambda l: -l["length"])


def signed_side(line, pts):
    (x1, y1), (x2, y2) = line["p1"], line["p2"]
    p = np.asarray(pts, float).reshape(-1, 2)
    return ((x2 - x1) * (p[:, 1] - y1) - (y2 - y1) * (p[:, 0] - x1)) \
        / max(1e-6, np.hypot(x2 - x1, y2 - y1))


def boundaries_from(lines, player_feet):
    """Lines with (almost) every confident player on one side.

    A halfway line or an 18-yard line has players on both sides and is
    rejected by construction -- no rule needed for it. What survives is the
    perimeter, which is exactly what we want to constrain against.
    """
    feet = np.asarray(player_feet, float).reshape(-1, 2)
    if len(feet) < MIN_PLAYERS_FIT:
        return []
    keep = []
    for ln in lines:
        if ln["length"] < MIN_LINE_LEN:
            continue
        d = signed_side(ln, feet)
        pos = float((d > 0).mean())
        purity = max(pos, 1 - pos)
        if purity >= SIDE_PURITY:
            keep.append({**ln, "inside_sign": 1.0 if pos >= 0.5 else -1.0,
                         "purity": purity})
    return keep


def outside_play(boundaries, point):
    """True if this point sits beyond any boundary, allowing a straddle."""
    for b in boundaries:
        d = float(signed_side(b, [point])[0]) * b["inside_sign"]
        if d < -SIDE_MARGIN_PX:
            return True
    return False
