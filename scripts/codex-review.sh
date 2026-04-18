#!/usr/bin/env bash
# Usage: codex-review.sh [BASE_SHA] [FILE...] [-- extra codex flags]
#
# Pipes `git diff BASE..HEAD -- FILES` + an explicit review prompt directly
# into `codex exec review -m gpt-5.4 -` so GPT-5.4 sees the diff inline
# and does NOT need to explore the codebase (avoids __pycache__ context blowout).
#
# Examples:
#   ./scripts/codex-review.sh b747156 handlers/terrain_semantics.py
#   ./scripts/codex-review.sh HEAD~3 handlers/terrain_pipeline.py handlers/terrain_semantics.py

set -euo pipefail

BASE_SHA="${1:-HEAD~1}"
shift 2>/dev/null || true

# Remaining args before '--' are file paths; after '--' are extra codex flags
FILES=()
EXTRA_FLAGS=()
in_files=true
for arg in "$@"; do
    if [[ "$arg" == "--" ]]; then
        in_files=false
        continue
    fi
    if $in_files; then
        FILES+=("$arg")
    else
        EXTRA_FLAGS+=("$arg")
    fi
done

# Build git diff command
if [[ ${#FILES[@]} -gt 0 ]]; then
    DIFF=$(git diff "${BASE_SHA}..HEAD" -- "${FILES[@]}" 2>/dev/null || git diff "${BASE_SHA}" -- "${FILES[@]}")
else
    DIFF=$(git diff "${BASE_SHA}..HEAD" 2>/dev/null || git diff "${BASE_SHA}")
fi

if [[ -z "$DIFF" ]]; then
    echo "[codex-review] No diff found vs ${BASE_SHA}. Nothing to review." >&2
    exit 0
fi

PROMPT="You are a senior Python engineer performing a focused code review.

REVIEW ONLY the changes shown in the diff below. Do NOT explore other files or directories.

For each finding, state:
  - Severity: P1 (correctness/data-loss) | P2 (logic error) | P3 (style)
  - File and line number
  - Concise description of the issue and recommended fix

If there are no findings, respond with: \"No issues found.\"

=== DIFF ===
${DIFF}
"

echo "[codex-review] Reviewing diff vs ${BASE_SHA} (${#DIFF} bytes)" >&2
echo "$PROMPT" | codex exec review -m "gpt-5.4" "${EXTRA_FLAGS[@]}" -
