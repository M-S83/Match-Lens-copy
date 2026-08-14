# Runbook — running a match through the pipeline

Written 2026-08-14 for the first real end-to-end run. Everything before this was
static analysis: the audit, the fixes and the test suite were all produced
without executing the pipeline against footage. **Treat the first run as an
experiment that will surface things static analysis could not.**

The commands below are verified against the code, not copied from the old spec —
`SKILL.md`'s Step 5 command pointed at a hardcoded path in one developer's home
directory and had been dead for months.

---

## Prerequisites

**Python 3.10+** (3.11 verified). The code uses PEP 604 unions in annotations.

**ffmpeg / ffprobe on PATH** — `container_analyser.py` shells out to `ffprobe`.
Windows: `winget install Gyan.FFmpeg`, then **open a new terminal** and confirm:

```bat
ffprobe -version
```

The new terminal matters: winget's PATH update does not reach shells that are
already open, and that is the single most likely way step 1a fails. The pipeline
now returns a named error telling you to install ffmpeg — previously it raised
`[WinError 2] The system cannot find the file specified`, which mentions neither
ffprobe nor ffmpeg.

**An Anthropic API key.**

---

## Setup (once)

```bat
git clone https://github.com/M-S83/Match-Lens-copy.git
cd Match-Lens-copy
git checkout claude/repo-duplication-gi8ood

python -m venv .venv
.venv\Scripts\activate

pip install -r requirements.txt
```

Optional extras, only if you need them:

```bat
pip install -r requirements-ocr.txt      :: jersey-number OCR (pulls torch, ~2GB)
pip install -r requirements-reports.txt  :: branded PDFs (needs system libs)
pip install -r requirements-dev.txt      :: pytest
```

Create `.env` **in the repository root** (loaded by `pipeline_runner_v2.py:43`):

```
ANTHROPIC_API_KEY=sk-ant-...
```

Confirm the suite passes before running anything expensive:

```bat
python -m pytest tests\ -q
```

---

## Set up the match directory

One directory per match. **You do not have to move the video into it.**

`frame_extraction.py:52-88` resolves the source video in this order:

1. `match_config.video_path` — **absolute paths are accepted**. Preferred: no
   copying gigabytes around.
2. A single `*.mp4` in the match directory.
3. Several `*.mp4` in the match directory — it picks the **largest** and only
   warns.

Rule 3 is a trap on a folder that holds more than one video. `Desktop\Grays
Analysis` contains a 3.76 GB `DJI_20250413113449_0002_D.MP4` alongside the 1.84 GB
match file, and the glob is case-insensitive on Windows — so it would silently
select the drone clip and carry on. **Set `video_path` explicitly and the
ambiguity disappears.**

```
Grays Analysis\                 <- match_dir (video may live elsewhere)
  match_config.json
```

### match_config.json

Minimum viable content. `home_team` and `away_team` are the most-read keys in
the whole pipeline (18 and 13 call sites); everything else degrades gracefully.

```json
{
  "match": "Grays vs [Opponent]",
  "date": "2026-08-09",
  "home_team": "Grays Athletic",
  "away_team": "[Opponent]",
  "focus_team": "home",
  "video_path": "C:\\Users\\dbmux\\Desktop\\Grays Analysis\\69ca09036f6e8ccff1207418.mp4",
  "home_kit": "blue shirts, blue shorts",
  "away_kit": "white shirts, black shorts",
  "home_gk_kit": "green",
  "lineups": {
    "home": [{"number": 1, "name": "..."}],
    "away": [{"number": 1, "name": "..."}]
  },
  "goals": [],
  "substitutions": []
}
```

Notes that matter for output quality:

- **`lineups` drives player identification.** Without it, player naming falls
  back to shirt numbers and the player-ID confidence ceiling drops.
- **`goals`** is the operator's ground truth. `ground_truth.py` validates the
  pipeline's detections against it. With an empty list, event validation checks
  nothing — and currently still reports as passed (FABRICATION-AUDIT O2).
  Fill it in if you know the scoreline.
- **`ko_1h_s` / `ko_2h_s`** (kickoff offsets in video seconds) are optional;
  Step 1b detects boundaries automatically and writes `match_boundaries.json`.

---

## Cost estimate first

Do this before any paid run:

```bat
python pipeline_runner_v2.py "<match_dir>" --estimate-only
```

**The estimate is meaningless until a window plan exists.** Every per-window
cost scales with `total_windows`, which comes from `window_plan.json`. On a cold
match directory that file is absent, so the figure is computed from zero
windows: about $0.73 against a real $8.75 for the same 96-minute video, a 12x
understatement that used to exit 0 and read as success.

It now refuses instead — prints `ESTIMATE UNAVAILABLE` and exits 2 rather than
standing behind a number it cannot compute. Run through Step 1c first, then
estimate.

Note which command you use: **`pipeline_runner_v2.py --estimate-only` never
writes `cost_estimate.json`** — only the `cost_estimator.py` CLI does. Via the
runner you get the printed estimate and the exit code but no file on disk. If
you want the artefact, including the `estimate_available: false` record:

```bat
python cost_estimator.py "<match_dir>"
```

---

## Run

```bat
python pipeline_runner_v2.py "C:\Users\dbmux\Desktop\Grays Analysis" --quality standard
```

Quality profiles (`pipeline_runner_v2.py:142`), frames per window:

| Profile | Frames | Notes |
|---|---|---|
| `economy` | 10 | cheapest |
| `standard` | 30 | sensible default |
| `full` | 60 | |
| `high_density` | 90 | downscaled to 512×288 |
| `full_1fps` | 90 | downscaled to 512×288 |

Interrupted? `--resume` picks up from `pipeline_state.json`.

---

## Output

Three documents, in the match directory:

- `tactical_report.md`
- `opposition_report_<home_team>.md`
- `opposition_report_<away_team>.md`

Then, optionally, Word versions:

```bat
python md_to_docx.py "C:\Users\dbmux\Desktop\Grays Analysis"
```

---

## The report gate

If `report_ready` is `false`, **no reports are generated** — this is now
enforced (AUDIT-2026-08 A1; before this it was computed and ignored). The run
prints `REPORT GATE: report_ready=FALSE` and lists the blocking issues.

That is working as intended. Fix the blockers and re-run rather than reaching
for the override. If you do need reports from a run that failed the gate:

```bat
python pipeline_runner_v2.py "<match_dir>" --override-readiness
```

It says so loudly and records `readiness_overridden: true` in
`report_readiness.json`, so the artefacts stay traceable to a deliberate
decision. Reports produced this way are not supported by the pipeline's own
checks.

---

## What to watch on the first run

Known-live issues that will affect this run. Full detail in
`FABRICATION-AUDIT.md`.

| Watch for | Why |
|---|---|
| `confidence_reliability_report.json` showing `total_metrics: 0`, `avg_confidence: 0.0` | The readiness step runs **before** the metrics step, so on a first run it reports on a file that does not exist yet. Expected, not a real zero. |
| `suppressed_families: []` | Hardcoded (O1). Not evidence that nothing was suppressed. |
| `event_validation_passed: true` with an empty `goals` list | Nothing was checked (O2). |
| Line-height metres | Assume a 105 m pitch (O6). Roughly 5% high on a 100 m pitch. |
| Defensive line attributed to the focus team | Currently the **average of both teams** (O7). A deep block can read as a high line. |
| Build-up predictability = 0.4, "mixed" | Zone key drift (O9) can produce this from zero observations. |

**Keep the whole match directory after the run.** The intermediate JSON
(`running_summary.json`, `agent_*_merged.json`, `deep_skill_metrics.json`) is
what makes it possible to tell a real finding from a pipeline artefact, and it
is the first real corpus this project has had to test against.
