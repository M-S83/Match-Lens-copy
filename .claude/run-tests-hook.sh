#!/usr/bin/env bash
# PostToolUse hook: run the test suite after a Python file is edited.
#
# Wired up in .claude/settings.json. Claude Code passes the tool-call JSON on
# stdin; we pull the edited path out of it and skip anything that is not Python,
# so editing markdown or JSON does not trigger a run.
#
# Exit codes are the contract with Claude Code:
#   0  -> silent success, nothing surfaced
#   2  -> stderr is fed back to Claude as feedback, so failures are seen
#         immediately rather than at the end of the task
#
# The suite runs in well under a second, which is what makes this practical on
# every edit. If it ever gets slow, narrow it with `-k` or move to a pre-commit
# hook instead.

set -uo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
payload="$(cat)"

# Extract file_path from the tool payload without assuming jq is installed.
edited="$(printf '%s' "$payload" | python3 -c '
import json, sys
try:
    d = json.load(sys.stdin)
except Exception:
    print(""); raise SystemExit
inp = d.get("tool_input") or {}
print(inp.get("file_path") or inp.get("notebook_path") or "")
' 2>/dev/null)"

case "$edited" in
  *.py) ;;
  *) exit 0 ;;                       # not Python — nothing to do
esac

command -v python3 >/dev/null 2>&1 || exit 0
python3 -c 'import pytest' 2>/dev/null || {
  echo "run-tests-hook: pytest not installed (pip install -r requirements-dev.txt)" >&2
  exit 0                             # missing tooling is not a test failure
}

# `timeout` from coreutils rather than pytest-timeout, so the hook needs no
# plugin beyond pytest itself. -x stops at the first failure to keep it quick.
output="$(cd "$REPO_ROOT" && timeout 120 python3 -m pytest tests/ -q --no-header -x 2>&1)" || {
  {
    echo "Tests failed after editing $(basename "$edited"):"
    echo
    printf '%s\n' "$output" | tail -40
  } >&2
  exit 2
}

exit 0
