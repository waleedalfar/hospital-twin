#!/usr/bin/env bash
# Fails if unfinished-work markers are present (CLAUDE.md §2). Part of `make verify`.
# Scans every tracked or untracked-but-not-ignored text file, except the spec documents, the reference
# prototype, lockfiles (hashes can contain any letters) and this script.
set -euo pipefail
cd "$(dirname "$0")/.."

PATTERN='\bTODO\b|\bFIXME\b|\bXXX\b|NotImplementedError|pass[[:space:]]+#[[:space:]]*later|not[[:space:]]+implemented|coming[[:space:]]+soon|lorem[[:space:]]+ipsum|\bTBD\b'

matches=$(
  git ls-files -co --exclude-standard -z \
    | grep -zv -E '^(CLAUDE\.md|PROMPT\.md|reference/|scripts/check_placeholders\.sh$|frontend/package-lock\.json$|backend/uv\.lock$)' \
    | xargs -0 grep -I -n -i -E "$PATTERN" -- 2>/dev/null || true
)

if [[ -n "$matches" ]]; then
  echo "Placeholder check FAILED. Unfinished-work markers found:" >&2
  echo "$matches" >&2
  exit 1
fi
echo "Placeholder check passed: no unfinished-work markers."
