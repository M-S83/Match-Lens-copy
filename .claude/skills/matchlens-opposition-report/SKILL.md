---
name: matchlens-opposition-report
description: Create a branded Match Lens opposition scouting report as a PDF for ONE team: that team's formation board, a shot map, player grade cards, and evidence-graded scouting notes. Trigger when the user asks for an opposition report, scouting report, or opponent analysis in Match Lens style.
---

# Match Lens — Opposition Report

Generates an opposition scouting report for one team (formation board, shot map, player grade cards, scouting notes) as a branded **Match Lens** PDF — a dark "ink" header band with the gold Match Lens identity, a category-coloured spine and accent edges, evidence-grade chips (A/B/C), and the focus team's formation board, a shot map (that team's shots), player grade cards parsed from the profiles, and stat tiles.

## Inputs you need
1. **The written analysis** as a markdown file (headings `##`, paragraphs, tables). Inline evidence grades written as `[A]`, `[B]`, `[C]` are rendered as colour-coded chips automatically.
2. **A `match_data.json`** describing the teams, events, shots and stat tiles (schema below). `report_type` must be `"opposition"`.

## How to produce the report
1. Gather or write the analysis markdown. If the user supplies raw notes, structure them into sections first.
2. Build `match_data.json` to the schema below (set `report_type` to `"opposition"`, and `focus_team` to the team the report is about).
3. Run:
   ```bash
   python scripts/render.py <analysis.md> <match_data.json> "<output>.pdf"
   ```
4. Save the resulting PDF to the user's output folder and share it.

A complete worked example is in `example/` — run it to see the exact output:
```bash
python scripts/render.py example/report.md example/match_data.json example/output.pdf
```

## match_data.json schema
```json
{
  "report_type": "opposition",            // fixed for this skill
  "title": "Home Team vs Away Team",   // optional; falls back to the markdown H1
  "meta":  "Competition · date · venue · result",   // optional sub-title line
  "focus_team": "home",                // OPPOSITION ONLY: which team the report is about
  "category_color": "#2BD58C",         // optional override of the report-type accent
  "teams": {
    "home": {
      "name": "Bayern Munich", "short": "BAY", "color": "#D7263D", "formation": "4-2-3-1",
      "lines": [
        ["GK",  [[1,"Neuer"]]],
        ["DEF", [[27,"Laimer"],[4,"Tah"],[2,"Upamecano"],[24,"Stanišić"]]],
        ["DM",  [[35,"Pavlović"],[6,"Kimmich"]]],
        ["ATT", [[23,"Díaz"],[42,"Musiala"],[25,"Olise"]]],
        ["ST",  [[9,"Kane"]]]
      ],
      "subs": [[22,"Nicolas Jackson"],[15,"Alphonso Davies"]]
    },
    "away": { "...": "same shape" }
  },
  "events": [
    {"t":3,"mm":"3'","type":"goal","team":"away","who":"Dembélé","desc":"Opener from the right channel"},
    {"t":52,"mm":"52'","type":"card","team":"away","who":"Kvaratskhelia","desc":"Booked"},
    {"t":68,"mm":"68'","type":"sub","team":"away","who":"Barcola","desc":"Barcola on for Dembélé"}
  ],
  "shots": [
    {"x":214,"y":64,"o":"goal","team":"away"},
    {"x":182,"y":30,"o":"on","team":"home"}
  ],
  "stats": [["BAYERN LINE","51.3m",true],["PSG LINE","43.5m",false]]
}
```

**Field notes**
- `lines` are ordered GK → ST, each row left → right from the team's own perspective (left-back on the left).
- `events.team` and `shots.team` are `"home"` or `"away"`; the engine resolves club colours from `teams`.
- `events.type` is `goal` | `card` | `sub`. `shots.o` (outcome) is `goal` | `on` | `off` | `blocked`.
- shot `x`/`y` are positions on a goal-box graphic (x 40–320, y 2–150, goal at top); placement is indicative.
- `stats` is up to four `[label, value, accent?]` tiles; `accent:true` colours the value in the report accent.
- Text is auto-converted to UK English. Player names, numbers and clubs are never altered.

## Requirements
- Python 3 with **weasyprint** installed (`pip install weasyprint`), and **pandoc** on the PATH.
- Fonts are bundled in `assets/fonts/` and referenced by `assets/brand.css`; no system fonts needed.
- The engine is in `scripts/` (`render.py`, `viz.py`); styling and fonts are in `assets/`.

## Notes
- Reports are descriptive only — they state what was observed and what repeated; they do not give instructions or judgements.
- Evidence grades: **A** directly observed, **B** pattern across phases, **C** single/limited sighting.
