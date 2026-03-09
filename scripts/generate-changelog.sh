#!/usr/bin/env bash
# Generate a changelog from git log (conventional commits).
# Usage: ./scripts/generate-changelog.sh [since-tag]
#
# If no tag is given, generates from the last tag (or all commits).
set -euo pipefail

SINCE="${1:-$(git describe --tags --abbrev=0 2>/dev/null || echo '')}"

if [ -n "$SINCE" ]; then
    RANGE="${SINCE}..HEAD"
    echo "# Changelog (since ${SINCE})"
else
    RANGE=""
    echo "# Changelog"
fi
echo ""
echo "Generated: $(date -u +%Y-%m-%d)"
echo ""

# Group commits by type
for prefix in feat fix perf refactor deps docs chore test ci; do
    case "$prefix" in
        feat)     heading="Features" ;;
        fix)      heading="Bug Fixes" ;;
        perf)     heading="Performance" ;;
        refactor) heading="Refactoring" ;;
        deps)     heading="Dependencies" ;;
        docs)     heading="Documentation" ;;
        chore)    heading="Chores" ;;
        test)     heading="Tests" ;;
        ci)       heading="CI/CD" ;;
    esac

    commits=$(git log $RANGE --oneline --grep="^${prefix}" --format="- %s (%h)" 2>/dev/null || true)
    if [ -n "$commits" ]; then
        echo "## $heading"
        echo ""
        echo "$commits"
        echo ""
    fi
done

# Uncategorized commits
uncategorized=$(git log $RANGE --oneline --format="- %s (%h)" --invert-grep \
    --grep="^feat" --grep="^fix" --grep="^perf" --grep="^refactor" \
    --grep="^deps" --grep="^docs" --grep="^chore" --grep="^test" --grep="^ci" \
    2>/dev/null || true)
if [ -n "$uncategorized" ]; then
    echo "## Other"
    echo ""
    echo "$uncategorized"
    echo ""
fi
