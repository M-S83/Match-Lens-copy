# Handoff — coordination between sessions

Two Claude sessions are working on this repo and **cannot talk to each other**.
Everything passes through this repository and through the user relaying messages.
This file is the shared state. Update it when you change something that the
other session would otherwise have to guess at.

Keep it short. A file that is actually maintained beats a process document.

Written state decays in two distinct ways, and they need different remedies.
Know which kind each row is before trusting it.

**Self-invalidating** — cannot be correct at rest. The first version pinned the
commit hash at the top; it was wrong the instant it was committed, because the
commit that updates the hash becomes the new hash. It also contradicted rule 3
below: a written state claim placed where it invites exactly the trust the
protocol forbids, so a session that read the table and skipped the command would
have *followed the file and broken the protocol*. **Remedy: replace the value
with the command.** Never write the value at all.

**Stale-prone** — can be true when written, and drifts. The test count went
42 → 45 across two commits in one session. Nothing about committing "45 passing"
makes it false, so no command is forced; it simply rots unless the commit that
changes the fact also updates this file. **Remedy: discipline, plus never
reading these as verification.** They are orientation — roughly where things
stand — and a command is given for anyone who needs the real answer.

---

## Current state

| | |
|---|---|
| **Repo** | `M-S83/Match-Lens-copy` — branch `claude/repo-duplication-gi8ood` |
| **Head** | `git ls-remote --heads https://github.com/M-S83/Match-Lens-copy.git` — **never trust a hash written here** (rule 3) |
| **Tests** | *orientation only:* 45 passing, each mutation-checked. To verify: `python -m pytest tests/ -q` |
| **Fabrications** | *orientation only:* 9 fixed (F1–F9), 16 open. `FABRICATION-AUDIT.md` is the record |
| **Blocking the run** | nothing |
| **Awaiting** | first real match run; the Grays video, ~20 windows, ~$8.75 at standard |

`M-S83/Match-Lens` is the **original** and is frozen at `b5cc6de`. It also carries
a stray `claude/repo-duplication-gi8ood` at `ce06ae2` — one commit, harmless,
deletable whenever. Do not push there.

---

## Division of labour

This split is based on what each session can actually do, not on preference.

**The Cowork session has the machine.** Real video, real dependencies, a Windows
environment, and the ability to execute. It owns **execution**: running the
pipeline, reproducing defects, verifying fixes by running them rather than
reading them, and finding what only contact with real input reveals.

**The cloud session has the history.** Full repo context, the audit trail, and
the reasoning behind every fix. It owns **changes**: writing fixes, adding
regression tests, updating the audits and runbook, and pushing.

The loop that has worked twice now:

```
Cowork runs something and finds a defect
  -> cloud session fixes it, adds a test, pushes
    -> Cowork pulls, verifies by execution, reports
```

Both rounds produced real findings that six sessions of reading had missed
(F9, and the ffprobe guard).

**Neither half was sufficient on its own, and that is the point.** In both
rounds the *finding* came from execution and the *diagnosis* came from reading.
Cowork could demonstrate that `--estimate-only` printed $0.73 but not why
`wp = {}` propagated into every per-window cost; static analysis had that code
in view for six sessions without noticing it mattered. So neither session should
treat the other as a reporting channel — the execution side is not a test
harness that emits tickets, and the reading side is not a fix service. The
finding and the explanation are different work, and both rounds needed both.

---

## Protocol

Each of these was learned the expensive way in this project.

1. **Verify the identity of what you inspected before claiming its contents.**
   A session concluded this work was lost after checking `Match-Lens` without
   ever searching for the `-copy` name. One `git ls-remote` would have settled
   it. "The repo" reads as a settled referent rather than something to verify,
   so the inference does not feel like an inference.

2. **Label how you know.** Claims from *executing* something have held
   consistently in this project; claims from *reasoning about state* have not.
   Say which you are giving, so the other session knows how hard to check it.

   But labelling is a service to the reader, not a safeguard for the writer.
   The session that concluded this work was lost labelled its claim correctly as
   inference and was still wrong. The failure was not mislabelling — it was not
   noticing that a one-command check existed. So: **before asserting anything
   about state, ask whether a single command would settle it.** If one would,
   run it. That question catches what careful labelling does not.

3. **Push by explicit URL.** `origin` was silently reset to the original repo
   five times in one session. Any "N unpushed commits" warning is unverified
   until local `HEAD` is compared against `git ls-remote` for the **copy**.

4. **Run the suite before pushing, and check its exit code.** One push went out
   with a failing test because pytest was piped to `tail`, which swallowed the
   exit status from the `&&` chain.

5. **Prove completeness before deleting anything.** Not "probably fine" —
   enumerate what would be lost and show it exists elsewhere.

6. **Absent input must never become a plausible number.** The governing rule of
   this codebase. See `FABRICATION-AUDIT.md`.

---

## Open work

Nothing blocks the run. In rough priority:

| Item | Notes |
|---|---|
| **Run the Grays match** | Highest value by a distance. Everything below is static reasoning until real output exists. |
| Readiness/metrics ordering | `3j_readiness` runs before `3k_metrics`, so a first run reports `avg_confidence: 0.0` on a file that does not exist yet. One-line reorder. |
| O1, O2, O17 | The reliability-report cluster: the artefact whose job is disclosing limitations currently asserts there were none. |
| O7, O8 | Numbers attributed to the wrong team — confidently wrong and invisible to the reader. |
| O9, O10 | Zone-key drift zeroes build-up metrics; `zone_helpers` writes `None` into merged files **on disk**. |
| ~30 REPORTED leads | Unverified. Two of fifteen CONFIRMED findings had scope errors, so assume a similar rate. Verify individually before fixing. |
| Three product decisions | A2 findings contract, A5/A6 metric values, A3 rating contract. Each needs the owner, not a guess. |

---

## Decisions already taken

So neither session reopens them.

- Deliverables are **three documents**: `tactical_report.md` and one
  `opposition_report_<team>.md` per team. Flagged-moments and pass-network
  reports were retired; moments fold into the surviving reports where relevant.
- Skills live in `.claude/skills/` in this repo, not in the account store.
  `SKILL.md` at the root is authoritative; the skill copy is generated and a
  test fails if they diverge.
- A5/A6 metric **values** were deliberately left as the code had them; only the
  false provenance strings were corrected. Changing the values is a product
  decision that has not been made.
