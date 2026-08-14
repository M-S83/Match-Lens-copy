# Project skills

These skills live in the repository so they version with the pipeline they
describe, rather than being synced from a separate account-level store.

## Why they are here

`SKILL.md` previously existed in two places — this repo and the account-synced
`match-analysis` skill — with nothing linking them. They had already drifted:
the synced copy was missing the entire **Pipeline Invariants** section (38
lines), and both carried a Step 5 command pointing at a hardcoded path in one
developer's home directory that exists on no current machine. Every spec fix
made in the repo never reached the copy that actually ran.

Keeping the skills in the repo makes that class of drift structurally
impossible: one commit changes the spec, the code, and the tests together.

## Contents

| Skill | Purpose |
|---|---|
| `match-analysis/` | The pipeline spec. **Do not edit here** — see below. |
| `matchlens-tactical-report/` | Branded PDF of `tactical_report.md` |
| `matchlens-opposition-report/` | Branded PDF of `opposition_report_<team>.md` |

## match-analysis/SKILL.md is a generated copy

The authoritative spec is `SKILL.md` at the repository root. The copy here
exists only because a skill directory must contain its own `SKILL.md`.

Edit the root file, then re-sync:

    python -c "import shutil; shutil.copyfile('SKILL.md', '.claude/skills/match-analysis/SKILL.md')"

`tests/test_audit_fixes.py::test_skill_spec_matches_repo_spec` fails if the two
diverge, so this cannot rot silently.

## PDF rendering

`render.py` resolves assets as `<skill_dir>/assets`, so each skill keeps its own
`assets/` and `scripts/`. `brand.css`, both renderers and all seven fonts are
byte-identical between the two skills — deduplicating them into a shared
directory would break that path resolution, so it was deliberately not done.

Rendering needs WeasyPrint: `pip install -r requirements-reports.txt`, plus its
system libraries. It is imported lazily, so everything else works without it.
